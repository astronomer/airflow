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
"""Supervised tries' edge cases; ``test_runner`` runs them end to end."""

from __future__ import annotations

import signal
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import psutil
import pytest
from sqlalchemy.orm import Session

from airflow.local_run import supervised
from airflow.local_run.fork_server import ForkServer, ForkServerError
from airflow.local_run.supervised import SupervisedTries
from airflow.models.taskinstance import TaskInstance
from airflow.models.trigger import Trigger
from airflow.sdk.execution_time.supervisor import ActivitySubprocess
from airflow.utils.state import TaskInstanceState


@pytest.fixture
def session():
    return mock.create_autospec(Session, instance=True)


@pytest.fixture
def ti():
    return mock.create_autospec(TaskInstance, instance=True)


def test_stop_without_a_running_try_reports_none(session):
    assert SupervisedTries(session=session).stop() is False


@pytest.mark.parametrize(("still_running", "escalated"), [(True, True), (False, False)])
@mock.patch.object(supervised, "find_descendants", autospec=True)
@mock.patch.object(supervised.threading, "Timer", autospec=True)
@mock.patch.object(supervised.os, "killpg", autospec=True)
def test_stop_lets_the_try_clean_up_then_interrupts_and_kills_it_if_it_keeps_running(
    killpg, timer, find_descendants, session, still_running, escalated
):
    tries = SupervisedTries(session=session)
    process = mock.create_autospec(ActivitySubprocess, instance=True)
    process.pid = 123
    tries._running = process
    left_behind = mock.create_autospec(psutil.Process, instance=True)
    find_descendants.return_value = [left_behind]

    assert tries.stop() is True

    killpg.assert_called_once_with(123, signal.SIGTERM)
    assert timer.call_args_list == [
        mock.call(supervised.INTERRUPT_DELAY, tries._interrupt_if_running, args=(process,)),
        mock.call(supervised.KILL_DELAY, tries._kill_if_running, args=(process,)),
    ]
    if not still_running:
        tries._running = None
    tries._interrupt_if_running(process)
    tries._kill_if_running(process)
    escalation = [mock.call(123, signal.SIGINT), mock.call(123, signal.SIGKILL)]
    assert killpg.call_args_list[1:] == (escalation if escalated else [])
    assert left_behind.kill.called is escalated


@mock.patch.object(supervised, "KILL_DELAY", 2.0)
def test_stop_processes_kills_one_that_ignores_sigterm():
    stops = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    ignores = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print(flush=True); time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
    )
    assert ignores.stdout is not None
    # Once it ignores SIGTERM.
    ignores.stdout.readline()

    supervised.stop_processes([psutil.Process(stops.pid), psutil.Process(ignores.pid)])

    # Under pytest a child's SIGTERM handler can exit 0, so this checks only that SIGTERM was enough.
    assert stops.wait(timeout=10) != -signal.SIGKILL
    assert ignores.wait(timeout=10) == -signal.SIGKILL


@mock.patch.object(supervised, "reset_secrets_masker", autospec=True)
@mock.patch.object(supervised, "_configure_logging", autospec=True, return_value=(mock.Mock(), mock.Mock()))
@mock.patch.object(supervised.InProcessTestSupervisor, "_api_client", autospec=True)
@mock.patch.object(supervised.ActivitySubprocess, "start", autospec=True)
def test_tries_start_without_the_fork_server_once_it_is_gone(start, *_):
    process = mock.create_autospec(ActivitySubprocess, instance=True)
    start.side_effect = [ForkServerError("gone"), process, process]
    fork_server = mock.create_autospec(ForkServer, instance=True)
    tries = SupervisedTries(session=mock.create_autospec(Session, instance=True), fork_server=fork_server)
    # The workload's fields are pydantic fields, which autospec does not see.
    workload = mock.NonCallableMock(spec=["ti", "dag_rel_path", "bundle_info"])
    task = mock.NonCallableMock(spec=["dag"])

    assert tries._supervise(workload, "attempt=1.log", task) is process.final_state
    tries._supervise(workload, "attempt=2.log", task)

    assert [call.kwargs.get("launcher") for call in start.call_args_list] == [fork_server, None, None]
    process.wait.assert_called_with()


@pytest.mark.parametrize(
    ("state_after_error", "marked_failed"),
    [(TaskInstanceState.QUEUED, True), (TaskInstanceState.SUCCESS, False)],
)
@mock.patch.object(supervised.ExecuteTask, "make", autospec=True, side_effect=RuntimeError("no workload"))
def test_try_that_cannot_run_does_not_leave_its_task_waiting(
    _, session, ti, state_after_error, marked_failed
):
    ti.state = state_after_error

    with pytest.raises(RuntimeError, match="no workload"):
        SupervisedTries(session=session).run(ti, mock.sentinel.task)

    session.rollback.assert_called_once_with()
    assert (mock.call(TaskInstanceState.FAILED, session=session) in ti.set_state.mock_calls) is marked_failed


@mock.patch.object(
    supervised.InProcessTestSupervisor, "run_trigger_in_process", autospec=True, return_value=None
)
@mock.patch.object(supervised, "import_string", autospec=True)
@mock.patch.object(supervised, "capture_task_log", autospec=True)
@pytest.mark.parametrize(("seconds_left", "timeout"), [(None, None), (-1, 0), (30, 30)])
def test_trigger_without_an_event_lets_the_task_resume(
    _, import_string, run_trigger, session, ti, tmp_path, time_machine, seconds_left, timeout
):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    time_machine.move_to(now, tick=False)
    session.get_one.return_value = mock.Mock(spec=Trigger, classpath="pkg.Trigger", kwargs={"n": 1})
    ti.trigger_timeout = now + timedelta(seconds=seconds_left) if seconds_left is not None else None
    # The workload's fields are pydantic fields, which autospec does not see.
    workload = mock.NonCallableMock(spec=["ti"], ti=mock.sentinel.ti)

    SupervisedTries(session=session)._resume_after_trigger(ti, workload, Path(tmp_path, "attempt=1.log"))

    import_string.return_value.assert_called_once_with(n=1)
    run_trigger.assert_called_once_with(
        trigger=import_string.return_value.return_value, ti=workload.ti, timeout=timeout
    )
    assert ti.state == TaskInstanceState.SCHEDULED
    assert ti.trigger_id is None
    session.commit.assert_called_once_with()
