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
Run one Dag from a file in a process whose environment already selects the project's home.

Started as ``python -m airflow.local_run REQUEST_FILE`` by :func:`airflow.sdk.definitions.local_run.run_dag_file`,
which set ``AIRFLOW_HOME`` and the database before this interpreter imported Airflow.
"""

from __future__ import annotations

import asyncio
import difflib
import fcntl
import getpass
import json
import logging
import math
import os
import pickle
import re
import signal
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, TextIO

import structlog
from packaging.version import Version
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from airflow import settings
from airflow._shared.timezones import timezone
from airflow.api.common.mark_tasks import set_dag_run_state_to_failed
from airflow.configuration import conf
from airflow.dag_processing.bundles.manager import DagBundlesManager
from airflow.dag_processing.dagbag import BundleDagBag, sync_bag_to_db
from airflow.jobs.job import Job, JobState
from airflow.local_run.fork_server import ForkServer
from airflow.local_run.logs import (
    TaskFailure,
    capture_task_log,
    configure_local_run_logging,
    read_attempt_failure,
    record_startup_events,
)
from airflow.local_run.ownership import LOCAL_RUN_JOB_TYPE, assign_local_trigger_queue
from airflow.local_run.supervised import SupervisedTries, find_descendants, stop_processes
from airflow.local_run.ui import build_run_url, read_live_ui_url
from airflow.models.dag import DagModel
from airflow.models.dag_version import DagVersion
from airflow.models.dagbag import DBDagBag
from airflow.models.dagrun import DagRun
from airflow.models.taskinstance import TaskInstance, find_task_markers_to_clear
from airflow.models.trigger import Trigger
from airflow.models.xcom import XComModel
from airflow.sdk import DAG
from airflow.sdk.definitions.dag import _run_dag_run_to_completion
from airflow.sdk.definitions.local_run import PROTOCOL_VERSION, find_loaded_module, refuse_breakpoint
from airflow.sdk.execution_time.xcom import XCom
from airflow.sdk.serde import allow_class
from airflow.serialization.encoders import coerce_to_core_timetable
from airflow.serialization.serialized_objects import DagSerialization
from airflow.utils.db import _REVISION_HEADS_MAP, _get_script_object, initdb, upgradedb
from airflow.utils.log.task_log_address import prepare_task_log_contexts, render_task_log_filename
from airflow.utils.retries import run_with_db_retries
from airflow.utils.session import create_session
from airflow.utils.state import DagRunState, State, TaskInstanceState
from airflow.utils.types import DagRunTriggeredByType, DagRunType

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from airflow.sdk.types import Operator
    from airflow.serialization.definitions.dag import SerializedDAG

# The default bundle configuration maps this bundle to ``[core] dags_folder``, the project root.
BUNDLE_NAME = "dags-folder"
RUN_CREATION_ATTEMPTS = 5

# The locks this process holds on the runs it executes; the operating system releases them however it ends.
_run_locks: list[TextIO] = []


class LocalRunSetupError(Exception):
    """The run could not start; the message is shown to the user as is."""


def main(argv: list[str]) -> int:
    request = json.loads(Path(argv[0]).read_text())
    result_path = Path(request["result_path"])
    try:
        if request.get("version") != PROTOCOL_VERSION:
            raise LocalRunSetupError(f"Unsupported local run request version {request.get('version')!r}")
        payload = execute(request)
    except LocalRunSetupError as e:
        payload = {"version": PROTOCOL_VERSION, "error": str(e)}
    except KeyboardInterrupt:
        payload = {"version": PROTOCOL_VERSION, "cancelled": True}
    write_result(result_path, payload)
    if payload.get("cancelled"):
        return 130
    if payload.get("error"):
        return 2
    return 0 if payload["state"] == DagRunState.SUCCESS else 1


def execute(request: dict[str, Any]) -> dict[str, Any]:
    # Debug runs each task try in this process, so breakpoint() and debuggers work.
    fork_server = None if request.get("debug") else prepare_supervised_tries()
    configure_local_run_logging()
    try:
        return run_requested_dag(request, fork_server=fork_server)
    finally:
        if fork_server is not None:
            fork_server.close()
        # Otherwise dispose_orm() at exit closes the async engine's aiosqlite connections outside an
        # event loop, and SQLAlchemy reports each one as a MissingGreenlet error.
        asyncio.run(settings.dispose_async_engine())


def prepare_supervised_tries() -> ForkServer | None:
    """
    Set up the environment each try's process inherits, and fork the server that starts those processes.

    Called first: a try's process gets this process's state as of now, before logging is routed, the database
    opened or the Dag file imported. A deployment that asked for a new interpreter for each task gets that.
    """
    # The hook explains the debug mode instead of failing to read input.
    os.environ.setdefault(
        "PYTHONBREAKPOINT", f"{refuse_breakpoint.__module__}.{refuse_breakpoint.__qualname__}"
    )
    if conf.getboolean("core", "execute_tasks_new_python_interpreter", fallback=False):
        return None
    return ForkServer.start()


def run_requested_dag(request: dict[str, Any], *, fork_server: ForkServer | None = None) -> dict[str, Any]:
    source = Path(request["source"])
    root = Path(settings.DAGS_FOLDER)
    home = Path(os.environ["AIRFLOW_HOME"])
    debug = bool(request.get("debug"))
    ensure_database(home)
    with record_startup_events():
        bundles = DagBundlesManager()
        bag = import_dag_file(source, root)
    dag = select_dag(bag, request.get("dag_id"), source)
    triggered_by = DagRunTriggeredByType(request["triggered_by"])

    # The thread-local scoped session, as in dag.test(): helpers inside the run loop open
    # ``create_session()`` and must get this same session, or SQLite's write lock deadlocks the thread.
    if settings.Session is None:
        raise RuntimeError("Session not configured. Call configure_orm() first.")
    session = settings.Session()
    selection = read_task_selection(request)
    try:
        if selection is None:
            scheduler_dag, dag_run = start_run(
                bag,
                dag,
                source=source,
                root=root,
                home=home,
                bundles=bundles,
                run_conf=request.get("run_conf"),
                triggered_by=triggered_by,
            )
            heading = f"Running Dag {dag.dag_id!r} from {source.name} (run {dag_run.run_id})"
        else:
            scheduler_dag, dag_run, heading = start_selected_run(
                bag,
                dag,
                selection,
                source=source,
                root=root,
                home=home,
                bundles=bundles,
                run_conf=request.get("run_conf"),
                triggered_by=triggered_by,
            )
        # From here on every trigger this process creates is for one of its tries; those created while storing
        # the Dags, for asset watchers, are the project triggerer's.
        event.listen(Trigger, "before_insert", assign_local_trigger_queue)
        interrupted = threading.Event()
        tries = SupervisedTries(session=session, fork_server=fork_server)

        def handle_interrupt(signum, frame):
            interrupted.set()
            # Further Ctrl-C presses would interrupt recording the cancellation.
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            # A try in a process of its own is interrupted instead; once it ended, the run loop stops.
            if not tries.stop():
                raise KeyboardInterrupt

        # Why each task that failed for good failed, for the caller.
        failures: dict[tuple[str, int], str] = {}
        ran: set[tuple[str, int]] = set()

        def report_attempt(ti: TaskInstance, state: str, log_path: Path) -> None:
            ran.add((ti.task_id, ti.map_index))
            failure = None
            if state in (TaskInstanceState.FAILED, TaskInstanceState.UP_FOR_RETRY):
                failure = read_attempt_failure(log_path)
            retry_in = (
                get_retry_delay(ti, session=session) if state == TaskInstanceState.UP_FOR_RETRY else None
            )
            report_task(ti, state, failure, cancelled=interrupted.is_set(), retry_in=retry_in)
            if state == TaskInstanceState.FAILED and failure is not None:
                failures[ti.task_id, ti.map_index] = failure.summary

        @contextmanager
        def run_task_in_process(ti: TaskInstance) -> Iterator[None]:
            log_path = get_task_log_path(ti, session=session)
            with capture_task_log(log_path):
                yield
            report_attempt(ti, _state_name(ti.state), log_path)

        def run_supervised_try(ti: TaskInstance, task: Operator) -> None:
            outcome, log_path = tries.run(ti, task)
            report_attempt(ti, _state_name(outcome), log_path)

        signal.signal(signal.SIGINT, handle_interrupt)
        report(heading)
        started = time.monotonic()
        cancelled = False
        try:
            _run_dag_run_to_completion(
                dag,
                dag_run,
                session=session,
                should_stop=interrupted.is_set,
                task_context=run_task_in_process if debug else None,
                execute_try=None if debug else run_supervised_try,
            )
        except KeyboardInterrupt:
            # A task interrupted in this process, in debug mode, leaves what it started running, such as a
            # BashOperator's command in a session of its own.
            stop_processes(find_descendants(os.getpid()))
            session.rollback()
            set_dag_run_state_to_failed(
                dag=scheduler_dag, run_id=dag_run.run_id, commit=True, session=session
            )
            session.commit()
            cancelled = True
        # Once the job has ended, the scheduler treats the run as any other, e.g. runs tries cleared in the UI.
        job = session.get_one(Job, dag_run.creating_job_id)
        job.state = JobState.SUCCESS
        job.complete_execution(session=session)
        # The outcome is recorded, so no later run needs to tell whether this process still runs it. Under the
        # project lock, a start checking for abandoned runs sees either the lock held or the outcome recorded.
        with project_lock(home):
            get_run_lock_path(home, dag_run.id).unlink(missing_ok=True)
        payload = collect_result(
            dag_run.dag_id,
            dag_run.run_id,
            source=source,
            failures=failures,
            ran=ran,
            cancelled=cancelled,
            session=session,
        )
        ui_url = read_live_ui_url(home)
        run_url = build_run_url(ui_url, dag_run.dag_id, dag_run.run_id) if ui_url else None
        total = time.monotonic() - request["started_at"]
        report(summarize_run(payload, time.monotonic() - started, total, home, run_url=run_url))
        return payload
    finally:
        session.close()


def start_run(
    bag: BundleDagBag,
    dag: DAG,
    *,
    source: Path,
    root: Path,
    home: Path,
    bundles: DagBundlesManager,
    run_conf: dict | None,
    triggered_by: DagRunTriggeredByType,
) -> tuple[SerializedDAG, DagRun]:
    """
    Store the file's Dags and create the run, committed in the thread's session, which the run loop uses.

    Starts in one project take turns. A run that is already executing can still commit between this step's
    reads and its writes, which SQLite in WAL mode reports at once as a locked database instead of waiting;
    only a new transaction gets past it. The new run's lock is taken before the project lock is released, so
    a later start never mistakes this run for an abandoned one.
    """
    if TYPE_CHECKING:
        assert settings.Session is not None
    session = settings.Session()
    for attempt in run_with_db_retries():
        with attempt, project_lock(home):
            try:
                abandoned = fail_abandoned_runs(home, session=session)
                register_dags(bag, source, root, bundles, session=session)
                session.commit()
                scheduler_dag, dag_run = create_dag_run(dag, run_conf, triggered_by, session=session)
                session.commit()
            except DBAPIError:
                session.rollback()
                raise
            lock_run(home, dag_run)
    report_abandoned_runs(home, abandoned)
    return scheduler_dag, dag_run


@dataclass(frozen=True)
class TaskSelection:
    """The tasks a request reruns in an earlier run, and how the run to rerun them in is chosen."""

    task_ids: tuple[str | tuple[str, int], ...]
    task_group_ids: tuple[str, ...]
    include_upstream: bool
    include_downstream: bool
    run_id: str | None


def read_task_selection(request: dict[str, Any]) -> TaskSelection | None:
    if not request.get("task_ids") and not request.get("task_group_ids"):
        return None
    return TaskSelection(
        # JSON has no tuples; a map index arrives as a [task_id, map_index] list.
        task_ids=tuple(
            marker if isinstance(marker, str) else (marker[0], marker[1])
            for marker in request.get("task_ids") or ()
        ),
        task_group_ids=tuple(request.get("task_group_ids") or ()),
        include_upstream=bool(request.get("include_upstream")),
        include_downstream=bool(request.get("include_downstream")),
        run_id=request.get("run_id"),
    )


def start_selected_run(
    bag: BundleDagBag,
    dag: DAG,
    selection: TaskSelection,
    *,
    source: Path,
    root: Path,
    home: Path,
    bundles: DagBundlesManager,
    run_conf: dict | None,
    triggered_by: DagRunTriggeredByType,
) -> tuple[SerializedDAG, DagRun, str]:
    """
    Set up the run of the selected tasks, committed in the thread's session; return it and how it was chosen.

    The selected tasks rerun in the run that has their inputs, as Clear does, unless a new conf is given or
    no earlier run has those inputs: a new run then runs them and the tasks they need. Takes turns with other
    starts in the project, as :func:`start_run` does.
    """
    if TYPE_CHECKING:
        assert settings.Session is not None
    session = settings.Session()
    for attempt in run_with_db_retries():
        with attempt, project_lock(home):
            try:
                abandoned = fail_abandoned_runs(home, session=session)
                register_dags(bag, source, root, bundles, session=session)
                session.commit()
                scheduler_dag = build_scheduler_dag(dag)
                markers = expand_task_selection(scheduler_dag, selection)
                selected = {get_task_id(marker) for marker in markers}
                reused = find_reused_upstream(
                    scheduler_dag, selected, include_upstream=selection.include_upstream
                )
                # A rerun keeps its run's conf, and a new conf can change what the upstream tasks produce.
                earlier = (
                    find_rerun_target(scheduler_dag, selection, selected, reused, session=session)
                    if run_conf is None
                    else None
                )
                if earlier is not None:
                    dag_run = earlier
                    rerun_selection(scheduler_dag, dag_run, markers, selection, session=session)
                    heading = describe_rerun(selection, dag_run.run_id, sorted(reused))
                else:
                    scheduler_dag, dag_run, first = start_run_for_selection(
                        dag, markers, selected, selection, run_conf, triggered_by, session=session
                    )
                    heading = describe_new_run(
                        selection, dag_run.run_id, first, new_conf=run_conf is not None
                    )
                session.commit()
            except Exception:
                session.rollback()
                raise
            lock_run(home, dag_run)
    report_abandoned_runs(home, abandoned)
    # Clearing gives a run the latest Dag version from the database, which lacks the callbacks.
    dag_run.dag = scheduler_dag
    return scheduler_dag, dag_run, heading


def rerun_selection(
    dag: SerializedDAG,
    dag_run: DagRun,
    markers: list[str | tuple[str, int]],
    selection: TaskSelection,
    *,
    session: Session,
) -> None:
    """
    Clear the selected tasks in ``dag_run`` and take the run over.

    The cleared tries run the file as it is now, and move the run to the file's Dag version when that is
    newer. The run is taken over by pointing its ``creating_job_id`` at this process's job in the
    transaction that clears the tasks: the history server's scheduler leaves alone the runs whose creating
    job is a running local run's, so it never runs the cleared tries itself.
    """
    check_map_indexes(markers, dag_run, session=session)
    dag_run.creating_job_id = start_local_run_job(session=session).id
    dag.clear(
        task_ids=find_task_markers_to_clear(
            markers,
            dag=dag,
            run_id=dag_run.run_id,
            include_upstream=selection.include_upstream,
            include_downstream=selection.include_downstream,
            session=session,
        ),
        run_id=dag_run.run_id,
        dag_run_state=DagRunState.RUNNING,
        run_on_latest_version=has_newer_dag_version(dag_run, session=session),
        session=session,
    )


def start_run_for_selection(
    dag: DAG,
    markers: list[str | tuple[str, int]],
    selected: set[str],
    selection: TaskSelection,
    run_conf: dict | None,
    triggered_by: DagRunTriggeredByType,
    *,
    session: Session,
) -> tuple[SerializedDAG, DagRun, list[str]]:
    """
    Create a run of the selected tasks and the tasks they need, and record the others as skipped, with a note.

    Returns the run and the upstream tasks that run before the selected ones.
    """
    if mapped := next((marker for marker in markers if isinstance(marker, tuple)), None):
        raise LocalRunSetupError(
            f"{_task_label(*mapped)} can be rerun only in a run where {mapped[0]} has expanded; select "
            f"{mapped[0]} to run all of its map indexes"
        )
    scheduler_dag, dag_run = create_dag_run(dag, run_conf, triggered_by, session=session)
    wanted = set(selected)
    if selection.include_downstream:
        wanted.update(
            scheduler_dag.partial_subset(
                task_ids=selected, include_upstream=False, include_downstream=True
            ).task_dict
        )
    # The upstream tasks come with the teardowns of their setups.
    needed = set(
        scheduler_dag.partial_subset(
            task_ids=wanted, include_upstream=True, include_downstream=False
        ).task_dict
    )
    labels = describe_selection(selection)
    dag_run.note = f"Selected: {labels}"
    for ti in dag_run.get_task_instances(session=session):
        if ti.task_id not in needed:
            # Not set_state(), which gives the task a start date: a skip without one tells a later rerun
            # that the task was left out, not skipped by the Dag, so it has no outputs to reuse.
            ti.state = TaskInstanceState.SKIPPED
            ti.note = f"Not selected: {labels} did not need it"
    session.flush()
    first = (task_id for task_id in needed - wanted if not scheduler_dag.task_dict[task_id].is_teardown)
    return scheduler_dag, dag_run, sorted(first)


def has_newer_dag_version(dag_run: DagRun, *, session: Session) -> bool:
    """
    Tell whether the file's Dag is a newer version than the run's, which the cleared tries then move to.

    Only then: moving a run to the latest version re-verifies its task instances while it is cleared. A
    mapped task cleared with the task that feeds it then has its expansion recorded as removed before that
    task reruns, and it is never expanded again, so its downstream tasks run without its outputs. An edit
    to a task's code alone keeps the Dag's version, so most reruns stay clear of that.
    """
    latest = DagVersion.get_latest_version(dag_run.dag_id, session=session)
    return latest is not None and latest.id != dag_run.created_dag_version_id


def expand_task_selection(dag: SerializedDAG, selection: TaskSelection) -> list[str | tuple[str, int]]:
    """Return the selected tasks, with every task of each selected task group; an unknown ID is refused."""
    markers: list[str | tuple[str, int]] = []
    for marker in selection.task_ids:
        task_id = get_task_id(marker)
        if not dag.has_task(task_id):
            raise LocalRunSetupError(
                f"Dag {dag.dag_id!r} has no task {task_id!r}.{suggest_ids(task_id, dag.task_ids)}"
            )
        markers.append(marker)
    group_ids = [group_id for group_id in dag.task_group_dict if group_id]
    for group_id in selection.task_group_ids:
        if group_id not in group_ids:
            raise LocalRunSetupError(
                f"Dag {dag.dag_id!r} has no task group {group_id!r}.{suggest_ids(group_id, group_ids)}"
            )
        markers.extend(task.task_id for task in dag.task_group_dict[group_id].iter_tasks())
    return list(dict.fromkeys(markers))


def get_task_id(marker: str | tuple[str, int]) -> str:
    return marker[0] if isinstance(marker, tuple) else marker


def suggest_ids(given: str, known: list[str]) -> str:
    close = difflib.get_close_matches(given, known, n=3)
    return f" Did you mean {' or '.join(repr(match) for match in close)}?" if close else ""


def find_reused_upstream(dag: SerializedDAG, selected: set[str], *, include_upstream: bool) -> set[str]:
    """Return the tasks upstream of the selected ones whose outputs the rerun reads from its run."""
    if include_upstream:
        return set()
    return set(
        dag.partial_subset(
            task_ids=selected, include_upstream=True, include_downstream=False, exclude_original=True
        ).task_dict
    )


def find_rerun_target(
    dag: SerializedDAG,
    selection: TaskSelection,
    selected: set[str],
    reused: set[str],
    *,
    session: Session,
) -> DagRun | None:
    """
    Return the run to rerun the selection in: the one asked for, else the latest finished run that has its inputs.

    A run has the inputs when every task whose outputs the rerun reads succeeded or was skipped by the Dag,
    and every selected task has an instance in it. Returns None when no earlier run has them.
    """
    if selection.run_id is not None:
        dag_run = session.scalar(
            select(DagRun).where(DagRun.dag_id == dag.dag_id, DagRun.run_id == selection.run_id)
        )
        if dag_run is None:
            raise LocalRunSetupError(f"Dag {dag.dag_id!r} has no run {selection.run_id!r} in this project")
        if dag_run.state not in State.finished_dr_states:
            raise LocalRunSetupError(
                f"Run {dag_run.run_id} is still {dag_run.state}; rerun its tasks once it has finished"
            )
        if missing := find_missing_tasks(dag_run, selected, session=session):
            raise LocalRunSetupError(
                f"Run {dag_run.run_id} has no {', '.join(missing)}: the Dag gained "
                f"{'it' if len(missing) == 1 else 'them'} after that run. Run the whole Dag instead."
            )
        if lacking := find_missing_inputs(dag_run, reused, session=session):
            raise LocalRunSetupError(
                f"Run {dag_run.run_id} lacks the outputs {describe_selection(selection)} needs: "
                f"{', '.join(lacking)} did not succeed"
            )
        return dag_run
    finished = session.scalars(
        select(DagRun)
        .where(DagRun.dag_id == dag.dag_id, DagRun.state.in_(State.finished_dr_states))
        .order_by(DagRun.run_after.desc(), DagRun.id.desc())
    )
    for dag_run in finished:
        if not find_missing_tasks(dag_run, selected, session=session) and not find_missing_inputs(
            dag_run, reused, session=session
        ):
            return dag_run
    return None


def find_missing_tasks(dag_run: DagRun, task_ids: set[str], *, session: Session) -> list[str]:
    """Return the tasks among ``task_ids`` that have no instance in ``dag_run``, e.g. added to the Dag since."""
    present = set(
        session.scalars(
            select(TaskInstance.task_id).where(
                TaskInstance.dag_id == dag_run.dag_id,
                TaskInstance.run_id == dag_run.run_id,
                TaskInstance.task_id.in_(task_ids),
                TaskInstance.working_set.is_(True),
            )
        )
    )
    return sorted(task_ids - present)


def find_missing_inputs(dag_run: DagRun, task_ids: set[str], *, session: Session) -> list[str]:
    """
    Return the tasks among ``task_ids`` that did not succeed in ``dag_run``, nor were skipped by the Dag.

    Tasks the Dag skips get a start date: trigger-rule skips through ``TaskInstance.set_state``, and branch
    and short-circuit skips through the Execution API's skip route. A run of selected tasks skips the ones
    they do not need without one, and those have no outputs to reuse.
    """
    done: dict[str, bool] = {}
    for task_id, state, start_date in session.execute(
        select(TaskInstance.task_id, TaskInstance.state, TaskInstance.start_date).where(
            TaskInstance.dag_id == dag_run.dag_id,
            TaskInstance.run_id == dag_run.run_id,
            TaskInstance.task_id.in_(task_ids),
            TaskInstance.working_set.is_(True),
        )
    ):
        # Every map index of a mapped task has to have finished.
        done[task_id] = done.get(task_id, True) and (
            state == TaskInstanceState.SUCCESS
            or (state == TaskInstanceState.SKIPPED and start_date is not None)
        )
    return sorted(task_id for task_id in task_ids if not done.get(task_id, False))


def check_map_indexes(markers: list[str | tuple[str, int]], dag_run: DagRun, *, session: Session) -> None:
    for task_id, map_index in (marker for marker in markers if isinstance(marker, tuple)):
        indexes = sorted(
            session.scalars(
                select(TaskInstance.map_index).where(
                    TaskInstance.dag_id == dag_run.dag_id,
                    TaskInstance.run_id == dag_run.run_id,
                    TaskInstance.task_id == task_id,
                    TaskInstance.working_set.is_(True),
                )
            )
        )
        if map_index in indexes:
            continue
        if indexes == [-1]:
            raise LocalRunSetupError(f"Task {task_id!r} is not mapped; select it as {task_id}")
        raise LocalRunSetupError(
            f"Task {task_id!r} has no map index {map_index} in run {dag_run.run_id}; "
            f"it has {', '.join(map(str, indexes))}"
        )


def describe_selection(selection: TaskSelection) -> str:
    labels = [_task_label(*marker) if isinstance(marker, tuple) else marker for marker in selection.task_ids]
    labels += [f"task group {group_id}" for group_id in selection.task_group_ids]
    return ", ".join(labels)


def describe_rerun(selection: TaskSelection, run_id: str, reused: list[str]) -> str:
    message = f"Rerunning {describe_selection(selection)} in run {run_id}"
    return message + (f", with the outputs of {', '.join(reused)}" if reused else "")


def describe_new_run(selection: TaskSelection, run_id: str, first: list[str], *, new_conf: bool) -> str:
    labels = describe_selection(selection)
    if new_conf:
        reason = "A new conf needs a new run"
    elif first:
        reason = f"No earlier run has the outputs {labels} needs"
    else:
        reason = f"No earlier run to rerun {labels} in"
    if first:
        return f"{reason}; running {', '.join(first)} first, in run {run_id}"
    return f"{reason}; running {labels} in run {run_id}"


def get_run_lock_path(home: Path, dag_run_id: int) -> Path:
    return home / "runs" / f"{dag_run_id}.lock"


def lock_run(home: Path, dag_run: DagRun) -> None:
    """Hold ``dag_run``'s lock until this process ends, however it ends."""
    path = get_run_lock_path(home, dag_run.id)
    path.parent.mkdir(exist_ok=True)
    lock_file = path.open("w")
    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    _run_locks.append(lock_file)


def is_run_lock_held(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open("a") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def fail_abandoned_runs(home: Path, *, session: Session) -> list[DagRun]:
    """
    Record as failed, and return, each local run still running whose process has ended; fail that process's job.

    A run's process holds the run's lock until it ends. It can end before recording the run's outcome when it
    is killed, or in debug mode when a task ends it, e.g. with ``os._exit``. It can also end after recording
    the outcome but before ending its job, which would keep the scheduler away from the run for good; that job
    is failed too. Call under the project lock.
    """
    candidates: list[tuple[Job | None, DagRun]] = [
        (job, dag_run)
        for job, dag_run in session.execute(
            select(Job, DagRun)
            .join(DagRun, DagRun.creating_job_id == Job.id)
            .where(Job.job_type == LOCAL_RUN_JOB_TYPE, Job.state == JobState.RUNNING)
        )
    ]
    # Runs created before local runs recorded a job have none. Only a local run's process leaves a lock file
    # behind, so a run started any other way, e.g. with ``airflow dags trigger``, is left alone.
    candidates.extend(
        (None, dag_run)
        for dag_run in session.scalars(
            select(DagRun).where(DagRun.state == DagRunState.RUNNING, DagRun.creating_job_id.is_(None))
        )
        if get_run_lock_path(home, dag_run.id).exists()
    )
    abandoned = []
    dag_bag = DBDagBag()
    for job, dag_run in candidates:
        lock_path = get_run_lock_path(home, dag_run.id)
        if is_run_lock_held(lock_path):
            continue
        if dag_run.state == DagRunState.RUNNING:
            if (scheduler_dag := dag_bag.get_dag_for_run(dag_run, session=session)) is not None:
                set_dag_run_state_to_failed(
                    dag=scheduler_dag, run_id=dag_run.run_id, commit=True, session=session
                )
            else:
                dag_run.set_state(DagRunState.FAILED)
            abandoned.append(dag_run)
        else:
            # The caller removes the lock files of the runs returned; this run's job alone tells that its
            # process ended.
            lock_path.unlink(missing_ok=True)
        if job is not None:
            job.state = JobState.FAILED
            job.end_date = timezone.utcnow()
    return abandoned


def report_abandoned_runs(home: Path, dag_runs: list[DagRun]) -> None:
    """Say which runs ``fail_abandoned_runs`` recorded as failed, once that is committed, and drop their locks."""
    for dag_run in dag_runs:
        report(
            f"Recorded run {dag_run.run_id} of Dag {dag_run.dag_id!r} as failed: its process ended before "
            "the run finished"
        )
        get_run_lock_path(home, dag_run.id).unlink(missing_ok=True)


def get_task_log_path(ti: TaskInstance, *, session: Session) -> Path:
    """Return the file the UI reads for this attempt: its run's log template under ``base_log_folder``."""
    context = prepare_task_log_contexts([ti], session=session)[ti.id]
    relative = render_task_log_filename(ti, ti.try_number, context=context)
    return Path(conf.get("logging", "base_log_folder")) / relative


def get_retry_delay(ti: TaskInstance, *, session: Session) -> timedelta | None:
    """Return how long the retry of ``ti``'s failed attempt waits, as the run loop will work it out."""
    # The failed attempt's row is archived; its successor waits for the retry.
    next_try = DagRun.fetch_task_instance(
        dag_id=ti.dag_id, dag_run_id=ti.run_id, task_id=ti.task_id, map_index=ti.map_index, session=session
    )
    if next_try is None or next_try.state != TaskInstanceState.UP_FOR_RETRY:
        return None
    # Rows read from the database have no task, which the delay is computed from.
    next_try.task = ti.task
    return max(next_try.next_retry_datetime(session=session) - timezone.utcnow(), timedelta(0))


def report(message: str) -> None:
    """Show progress on stderr, keeping the user's stdout for their own output."""
    print(message, file=sys.stderr, flush=True)


def report_task(
    ti: TaskInstance,
    state: str,
    failure: TaskFailure | None,
    *,
    cancelled: bool,
    retry_in: timedelta | None = None,
) -> None:
    """Report a finished attempt in ``state``; ``failure`` is why it failed, held back from the terminal."""
    label = _task_label(ti.task_id, ti.map_index)
    if ti.try_number > 1 and state != "up_for_retry":
        # A rerun's try, or one after retries; the retry line already numbers its attempt.
        label += f" (try {ti.try_number})"
    if state == "success":
        report(f"  ✓ {label}")
    elif cancelled and state in ("failed", "up_for_retry"):
        report(f"  ✗ {label} cancelled")
    elif state == "up_for_retry":
        when = f" in {_describe_delay(retry_in)}" if retry_in else ""
        reason = f": {failure.summary}" if failure is not None else ""
        report(f"  ↻ {label} failed attempt {ti.try_number} of {ti.max_tries + 1}, retrying{when}{reason}")
    elif state == "failed":
        report(f"  ✗ {label} failed")
        if failure is not None:
            report(failure.details)
    else:
        report(f"  · {label} {state}")


def summarize_run(
    payload: dict[str, Any], elapsed: float, total: float, home: Path, *, run_url: str | None = None
) -> str:
    """
    Say how the run ended, and where to look at it: its page in the project's UI while one runs.

    ``elapsed`` is the time its tasks took, and ``total`` that of the whole run, from the call that started it.
    """
    times = f"{elapsed:.1f}s ({total:.1f}s total)"
    if payload["cancelled"]:
        outcome = f"Cancelled after {times}"
    elif payload["state"] == DagRunState.SUCCESS:
        outcome = f"Succeeded in {times}"
    else:
        failed = sorted(
            _task_label(task_id, map_index)
            for (task_id, map_index), state in payload["task_states"].items()
            if state == "failed"
        )
        outcome = f"Failed in {times}" + (f": {', '.join(failed)}" if failed else "")
    where = f"View it at {run_url}" if run_url else f"History: {home}"
    return f"{outcome}. {where}"


@contextmanager
def project_lock(home: Path) -> Iterator[None]:
    with open(home / ".lock", "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield


def ensure_database(home: Path) -> None:
    """Create the project database, or migrate it to this Airflow version; refuse a newer schema."""
    with project_lock(home):
        with create_session() as session:
            current = read_schema_revision(session)
        if current is None:
            report(f"Creating the project database in {home} (first run only)")
            initdb()
            return
        if current == get_newest_revision():
            return
        # Imported only when the schema may need migrating: importing Alembic is a noticeable part of a rerun.
        from alembic.util import CommandError

        script = _get_script_object()
        if current in script.get_heads():
            return
        try:
            script.get_revision(current)
        except CommandError:
            raise LocalRunSetupError(
                f"The project database in {home} was created by a newer Airflow version (schema {current}). "
                f"Upgrade Airflow, or delete {home} to start a new history."
            ) from None
        report(f"Upgrading the project database in {home} to this Airflow version")
        upgradedb()


def read_schema_revision(session: Session) -> str | None:
    """Return the schema revision Alembic recorded in the database, None for a new database."""
    if not inspect(session.connection()).has_table("alembic_version"):
        return None
    return session.scalar(text("SELECT version_num FROM alembic_version"))


def get_newest_revision() -> str:
    """Return the newest migration's revision, which a prek hook keeps in ``_REVISION_HEADS_MAP``."""
    return _REVISION_HEADS_MAP[max(_REVISION_HEADS_MAP, key=Version)]


def import_dag_file(source: Path, root: Path) -> BundleDagBag:
    """
    Import ``source`` the way Airflow discovers Dags; its ``__main__`` block does not run.

    Imports in the file resolve from the project root, as they do in each task's process and when deployed,
    not from the file's own directory as under ``python file.py``.
    """
    started = time.monotonic()
    bag = BundleDagBag(dag_folder=source, bundle_path=root, bundle_name=BUNDLE_NAME, collect_dags=False)
    bag.collect_dags(dag_folder=source, only_if_updated=False, safe_mode=False)
    if bag.import_errors:
        details = "\n".join(error.rstrip() for error in bag.import_errors.values())
        hint = suggest_project_root_import(details, source, root)
        raise LocalRunSetupError(f"Importing {source} failed:\n{details}" + (f"\n{hint}" if hint else ""))
    structlog.get_logger(logger_name="task").info(
        "Local run startup parse complete",
        bundle_name=BUNDLE_NAME,
        bundle_version=None,
        dag_file=source.relative_to(root).as_posix(),
        dag_file_parse_ms=int((time.monotonic() - started) * 1000),
        parsed_at=timezone.utcnow().isoformat(),
    )
    return bag


def suggest_project_root_import(import_error: str, source: Path, root: Path) -> str | None:
    """Name the import that works for a missing module that is next to a Dag file below the project root."""
    if source.parent == root or not (match := re.search(r"No module named '([^'.]+)", import_error)):
        return None
    name = match.group(1)
    if not ((source.parent / f"{name}.py").is_file() or (source.parent / name).is_dir()):
        return None
    package = ".".join(source.parent.relative_to(root).parts)
    # ``python sub/pipeline.py`` puts sub/, not the project root, on the path of the caller's own process.
    return (
        f"{name!r} is next to {source.name}, but Dag files import from the project root, as when deployed: "
        f"import it as {package}.{name}, and run the file as `python -m {package}.{source.stem}` from the "
        f"project root, or with `airflow run`."
    )


def select_dag(bag: BundleDagBag, dag_id: str | None, source: Path) -> DAG:
    # A bag can also hold serialized Dags from other language importers; only SDK Dags run in-process.
    dags = {found_id: found for found_id, found in bag.dags.items() if isinstance(found, DAG)}
    if dag_id is None:
        if len(dags) == 1:
            return next(iter(dags.values()))
        if not dags:
            raise LocalRunSetupError(
                f"No Dags found in {source}. Create the Dag at module level, for example `workflow = example()`."
            )
        raise LocalRunSetupError(
            f"{source} defines several Dags ({', '.join(sorted(dags))}); choose one with --dag-id."
        )
    if dag_id not in dags:
        defined = f" It defines: {', '.join(sorted(dags))}." if dags else ""
        raise LocalRunSetupError(
            f"{source} does not define Dag {dag_id!r} at module level.{defined} A local run imports the file "
            "the way Airflow discovers Dags, so the Dag must be created at module level."
        )
    return dags[dag_id]


def register_dags(
    bag: BundleDagBag, source: Path, root: Path, bundles: DagBundlesManager, *, session: Session
) -> None:
    """Store the file's Dags; a Dag ID still defined by another existing file in the project is refused."""
    bundles.sync_bundles_to_db(session=session)
    # The Dag rows reference the bundle row; without a flush SQLAlchemy may insert them first.
    session.flush()
    relative = source.relative_to(root).as_posix()
    for dag_model in session.scalars(select(DagModel).where(DagModel.dag_id.in_(list(bag.dags)))):
        other = dag_model.relative_fileloc
        if other and other != relative and (root / other).exists():
            raise LocalRunSetupError(
                f"Dag ID {dag_model.dag_id!r} is already used by {other} in this project; "
                "rename one of the Dags so their histories stay separate."
            )
    sync_bag_to_db(bag, BUNDLE_NAME, None, session=session)


def build_scheduler_dag(dag: DAG) -> SerializedDAG:
    dag.validate()
    scheduler_dag = DagSerialization.deserialize_dag(DagSerialization.serialize_dag(dag))
    # Serialization drops callbacks; the run loop finds them on the scheduler Dag, as in dag.test().
    scheduler_dag.on_success_callback = dag.on_success_callback  # type: ignore[attr-defined]
    scheduler_dag.on_failure_callback = dag.on_failure_callback  # type: ignore[attr-defined]
    return scheduler_dag


def start_local_run_job(*, session: Session) -> Job:
    """Add the running job of this process, which the run it drives names as its ``creating_job_id``."""
    job = Job(job_type=LOCAL_RUN_JOB_TYPE, state=JobState.RUNNING)
    session.add(job)
    session.flush()
    return job


def create_dag_run(
    dag: DAG, run_conf: dict | None, triggered_by: DagRunTriggeredByType, *, session: Session
) -> tuple[SerializedDAG, DagRun]:
    """
    Create a new run with its own logical date.

    ``get_or_create_dagrun`` (used by ``dag.test()``) deletes a run sharing the logical date, which a
    concurrent local run of the same Dag could hit; here a collision retries with a fresh timestamp.
    """
    scheduler_dag = build_scheduler_dag(dag)
    timetable = coerce_to_core_timetable(dag.timetable)
    # Committed with the run, so a scheduler never sees the run without the job driving it.
    job = start_local_run_job(session=session)
    for _ in range(RUN_CREATION_ATTEMPTS):
        now = timezone.coerce_datetime(timezone.utcnow())
        try:
            with session.begin_nested():
                dag_run = scheduler_dag.create_dagrun(
                    run_id=DagRun.generate_run_id(
                        run_type=DagRunType.MANUAL, logical_date=now, run_after=now
                    ),
                    logical_date=now,
                    data_interval=timetable.infer_manual_data_interval(run_after=now),
                    run_after=now,
                    conf=run_conf,
                    run_type=DagRunType.MANUAL,
                    state=DagRunState.RUNNING,
                    triggered_by=triggered_by,
                    triggering_user_name=getpass.getuser(),
                    start_date=now,
                    creating_job_id=job.id,
                    session=session,
                )
        except IntegrityError:
            continue
        return scheduler_dag, dag_run
    raise LocalRunSetupError(f"Could not create a unique run for Dag {dag.dag_id!r}; run it again")


def collect_result(
    dag_id: str,
    run_id: str,
    *,
    source: Path,
    failures: dict[tuple[str, int], str],
    ran: set[tuple[str, int]],
    cancelled: bool,
    session: Session,
) -> dict[str, Any]:
    """
    Read the run's outcome; each output is pickled on its own, so one the caller cannot load spares the rest.

    Outputs are read the way a downstream task reads them. ``ran`` holds the task instances this process ran.
    """
    session.expire_all()
    dag_run = session.scalars(select(DagRun).where(DagRun.dag_id == dag_id, DagRun.run_id == run_id)).one()
    task_instances = session.scalars(
        select(TaskInstance).where(TaskInstance.dag_id == dag_id, TaskInstance.run_id == run_id)
    )
    task_states = {(ti.task_id, ti.map_index): _state_name(ti.state) for ti in task_instances}
    dag_module = find_loaded_module(source)
    if dag_module is not None:
        allow_classes_defined_in(dag_module)
    outputs: dict[tuple[str, int, str], bytes] = {}
    output_errors: dict[tuple[str, int, str], str] = {}
    for row in session.scalars(XComModel.get_many(run_id=run_id, dag_ids=dag_id)):
        key = (row.task_id, row.map_index, row.key)
        try:
            outputs[key] = pickle.dumps(XCom.deserialize_value(row))
        except Exception as e:
            output_errors[key] = f"{type(e).__name__}: {e}"
    return {
        "version": PROTOCOL_VERSION,
        "dag_id": dag_id,
        "run_id": run_id,
        "state": _state_name(dag_run.state),
        "task_states": task_states,
        "outputs": outputs,
        "output_errors": output_errors,
        "dag_module": dag_module,
        "failures": failures,
        "ran": frozenset(ran),
        "cancelled": cancelled,
    }


def allow_classes_defined_in(module_name: str) -> None:
    """
    Let outputs load as instances of the classes the Dag file defines.

    A deployed task reads such an output only if ``allowed_deserialization_classes`` lists its class. The
    run is over, so this changes only what the caller gets back, not how the tasks ran.
    """
    for value in vars(sys.modules[module_name]).values():
        if isinstance(value, type) and value.__module__ == module_name:
            with suppress(ValueError):
                allow_class(value)


def exit_without_teardown(code: int) -> NoReturn:
    """
    End the process once the result is written, without the interpreter's teardown.

    Tearing down Airflow's import graph takes about half a second, which every run would pay. The run is
    committed and the result file and task logs are closed by now; what remains is closing the database
    connections and flushing output.
    """
    settings.dispose_orm()
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def write_result(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps(payload))
    os.replace(tmp, path)


def _state_name(state: Any) -> str:
    return "none" if state is None else str(getattr(state, "value", state))


def _task_label(task_id: str, map_index: int) -> str:
    return task_id if map_index < 0 else f"{task_id}[{map_index}]"


def _describe_delay(delay: timedelta) -> str:
    minutes, seconds = divmod(math.ceil(delay.total_seconds()), 60)
    hours, minutes = divmod(minutes, 60)
    return " ".join(
        f"{value}{unit}" for value, unit in ((hours, "h"), (minutes, "m"), (seconds, "s")) if value
    )
