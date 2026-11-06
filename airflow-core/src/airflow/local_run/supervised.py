# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""
Run a local Dag run's task tries as a worker does: each in a process of its own, under the task supervisor.

The supervisor talks to the run's in-process Execution API and writes the attempt's log itself. Module state
therefore starts fresh for every try, a crash ends only its own try, and the log is the one a worker writes.
"""

from __future__ import annotations

import os
import signal
import threading
import warnings
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psutil

from airflow._shared.module_loading import import_string
from airflow.configuration import conf
from airflow.executors.workloads import ExecuteTask
from airflow.local_run.logs import capture_task_log
from airflow.models.trigger import Trigger
from airflow.sdk._shared.secrets_masker import reset_secrets_masker
from airflow.sdk.definitions.dag import FINISHED_STATES, _run_inline_trigger
from airflow.sdk.execution_time.supervisor import (
    ActivitySubprocess,
    InProcessTestSupervisor,
    _configure_logging,
)
from airflow.utils.state import TaskInstanceState

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

    from airflow.models.taskinstance import TaskInstance
    from airflow.sdk.types import Operator

# How long a stopped try gets to clean up after SIGTERM, e.g. in its operator's on_kill, before it is interrupted.
INTERRUPT_DELAY = 1.0
# How long a stopped try's processes get to exit before they are killed, as in the supervisor's own kill.
KILL_DELAY = 5.0


class SupervisedTries:
    """Run task tries one at a time, each in a process of its own, using the run loop's session."""

    def __init__(self, *, session: Session) -> None:
        self._session = session
        self._running: ActivitySubprocess | None = None
        self._left_behind: list[psutil.Process] = []

    def run(self, ti: TaskInstance, task: Operator) -> tuple[str, Path]:
        """
        Run a try of ``ti`` and return the state its supervisor reported, and the try's log file.

        A try that defers waits here for its trigger, then resumes in a new process, as it would once the
        triggerer fired.
        """
        try:
            while True:
                ti.set_state(TaskInstanceState.QUEUED, session=self._session)
                self._session.commit()
                workload = ExecuteTask.make(ti)
                if TYPE_CHECKING:
                    assert workload.log_path is not None
                state = self._supervise(workload, workload.log_path, task)
                # The Execution API updated the row through a session of its own.
                self._session.refresh(ti)
                log_path = Path(conf.get("logging", "base_log_folder"), workload.log_path)
                if state != TaskInstanceState.DEFERRED:
                    return state, log_path
                self._resume_after_trigger(ti, workload, log_path)
        except Exception:
            # Otherwise the run loop would wait forever for a task left queued.
            self._session.rollback()
            self._session.refresh(ti)
            if ti.state not in FINISHED_STATES:
                ti.set_state(TaskInstanceState.FAILED, session=self._session)
                self._session.commit()
            raise

    def stop(self) -> bool:
        """
        Interrupt the running try, if any, and return whether there was one.

        The try runs in a process group of its own, so the terminal's Ctrl-C does not reach it. It gets
        SIGTERM here, so that its operator stops what it started, as on a worker (``on_kill``), such as a
        ``BashOperator``'s command in a session of its own. If it is still running after ``INTERRUPT_DELAY`` it
        gets the terminal's interrupt, which stops plain Python code, and after ``KILL_DELAY`` it is killed,
        with whatever it started outside its group.
        """
        if (process := self._running) is None:
            return False
        self._left_behind = find_descendants(process.pid)
        _signal_group(process.pid, signal.SIGTERM)
        # SIGINT sent with SIGTERM would be handled first, and end the task before its operator cleans up.
        _call_later(INTERRUPT_DELAY, self._interrupt_if_running, process)
        _call_later(KILL_DELAY, self._kill_if_running, process)
        return True

    def _interrupt_if_running(self, process: ActivitySubprocess) -> None:
        if self._running is process:
            _signal_group(process.pid, signal.SIGINT)

    def _kill_if_running(self, process: ActivitySubprocess) -> None:
        if self._running is process:
            _signal_group(process.pid, signal.SIGKILL)
            # They can hold the try's sockets, which the supervisor waits on.
            for left_behind in self._left_behind:
                with suppress(psutil.NoSuchProcess):
                    left_behind.kill()

    def _supervise(self, workload: ExecuteTask, relative_log_path: str, task: Operator) -> str:
        """Run the workload as ``supervise_task`` does, but keep this process's Ctrl-C handler installed."""
        client = InProcessTestSupervisor._api_client(task.dag, workload.ti.id)
        logger, log_file = _configure_logging(relative_log_path, client)
        try:
            reset_secrets_masker()
            with warnings.catch_warnings():
                # The Execution API's thread is idle while this thread forks, as in the Dag processor, which
                # forks the same way.
                warnings.filterwarnings("ignore", message=r".* is multi-threaded, use of fork\(\)")
                process = ActivitySubprocess.start(
                    what=workload.ti,  # type: ignore[arg-type]  # duck-types as the SDK's TaskInstance
                    dag_rel_path=workload.dag_rel_path,
                    bundle_info=workload.bundle_info,
                    client=client,
                    logger=logger.bind(ti_id=str(workload.ti.id)),
                    subprocess_logs_to_stdout=True,
                )
            self._running = process
            try:
                process.wait()
            finally:
                self._running = None
                stop_processes(self._left_behind)
                self._left_behind = []
            return process.final_state
        finally:
            log_file.close()

    def _resume_after_trigger(self, ti: TaskInstance, workload: ExecuteTask, log_path: Path) -> None:
        """Run the deferred try's trigger here, then schedule the task to resume, as the triggerer would."""
        trigger_row = self._session.get_one(Trigger, ti.trigger_id)
        trigger = import_string(trigger_row.classpath)(**trigger_row.kwargs)
        with capture_task_log(log_path):
            event = _run_inline_trigger(trigger, workload.ti)
        if event is None:
            ti.state = TaskInstanceState.SCHEDULED
            ti.trigger_id = None
        else:
            Trigger.submit_event(trigger_row.id, event, session=self._session)
        self._session.commit()
        self._session.refresh(ti)


def _call_later(delay: float, func: Callable[..., None], *args: Any) -> None:
    timer = threading.Timer(delay, func, args=args)
    timer.daemon = True
    timer.start()


def _signal_group(pid: int, signum: signal.Signals) -> None:
    # The supervisor starts each try as the leader of its own process group.
    with suppress(ProcessLookupError):
        os.killpg(pid, signum)


def find_descendants(pid: int) -> list[psutil.Process]:
    try:
        return psutil.Process(pid).children(recursive=True)
    except psutil.NoSuchProcess:
        return []


def stop_processes(processes: list[psutil.Process]) -> None:
    """Terminate ``processes`` that are still running, and kill any still running after ``KILL_DELAY``."""
    for process in processes:
        with suppress(psutil.NoSuchProcess):
            process.terminate()
    _, still_running = psutil.wait_procs(processes, timeout=KILL_DELAY)
    for process in still_running:
        with suppress(psutil.NoSuchProcess):
            process.kill()
