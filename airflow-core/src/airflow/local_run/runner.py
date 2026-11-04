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
import fcntl
import getpass
import json
import logging
import math
import os
import pickle
import signal
import sys
import threading
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import structlog
from alembic.util import CommandError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError

from airflow import settings
from airflow._shared.timezones import timezone
from airflow.api.common.mark_tasks import set_dag_run_state_to_failed
from airflow.configuration import conf
from airflow.dag_processing.bundles.manager import DagBundlesManager
from airflow.dag_processing.dagbag import BundleDagBag, sync_bag_to_db
from airflow.local_run.logs import capture_task_log, configure_local_run_logging, record_startup_events
from airflow.models.dag import DagModel
from airflow.models.dagrun import DagRun
from airflow.models.taskinstance import TaskInstance
from airflow.models.xcom import XComModel
from airflow.sdk import DAG
from airflow.sdk.definitions.dag import _run_dag_run_to_completion
from airflow.sdk.definitions.local_run import PROTOCOL_VERSION, find_loaded_module
from airflow.sdk.execution_time.xcom import XCom
from airflow.sdk.serde import allow_class
from airflow.serialization.encoders import coerce_to_core_timetable
from airflow.serialization.serialized_objects import DagSerialization
from airflow.utils.db import _get_current_revision, _get_script_object, initdb, upgradedb
from airflow.utils.log.task_log_address import prepare_task_log_contexts, render_task_log_filename
from airflow.utils.retries import run_with_db_retries
from airflow.utils.session import create_session
from airflow.utils.state import DagRunState, TaskInstanceState
from airflow.utils.types import DagRunTriggeredByType, DagRunType

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from airflow.serialization.definitions.dag import SerializedDAG

# The default bundle configuration maps this bundle to ``[core] dags_folder``, the project root.
BUNDLE_NAME = "dags-folder"
RUN_CREATION_ATTEMPTS = 5


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
    configure_local_run_logging()
    try:
        return run_requested_dag(request)
    finally:
        # Otherwise dispose_orm() at exit closes the async engine's aiosqlite connections outside an
        # event loop, and SQLAlchemy reports each one as a MissingGreenlet error.
        asyncio.run(settings.dispose_async_engine())


def run_requested_dag(request: dict[str, Any]) -> dict[str, Any]:
    source = Path(request["source"])
    root = Path(settings.DAGS_FOLDER)
    home = Path(os.environ["AIRFLOW_HOME"])
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
    try:
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
        interrupted = threading.Event()

        def handle_interrupt(signum, frame):
            interrupted.set()
            # Further Ctrl-C presses would interrupt recording the cancellation.
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            raise KeyboardInterrupt

        @contextmanager
        def run_task(ti: TaskInstance) -> Iterator[None]:
            with capture_task_log(get_task_log_path(ti, session=session)) as attempt:
                yield
            retry_in = (
                get_retry_delay(ti, session=session) if ti.state == TaskInstanceState.UP_FOR_RETRY else None
            )
            report_task(ti, attempt.failure, cancelled=interrupted.is_set(), retry_in=retry_in)

        signal.signal(signal.SIGINT, handle_interrupt)
        report(f"Running Dag {dag.dag_id!r} from {source.name} (run {dag_run.run_id})")
        started = time.monotonic()
        cancelled = False
        try:
            _run_dag_run_to_completion(
                dag,
                dag_run,
                session=session,
                should_stop=interrupted.is_set,
                task_context=run_task,
            )
        except KeyboardInterrupt:
            session.rollback()
            set_dag_run_state_to_failed(
                dag=scheduler_dag, run_id=dag_run.run_id, commit=True, session=session
            )
            session.commit()
            cancelled = True
        payload = collect_result(
            dag_run.dag_id, dag_run.run_id, source=source, cancelled=cancelled, session=session
        )
        report(summarize_run(payload, time.monotonic() - started, home))
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
    only a new transaction gets past it.
    """
    if TYPE_CHECKING:
        assert settings.Session is not None
    session = settings.Session()
    for attempt in run_with_db_retries():
        with attempt, project_lock(home):
            try:
                register_dags(bag, source, root, bundles, session=session)
                session.commit()
                created = create_dag_run(dag, run_conf, triggered_by, session=session)
                session.commit()
            except DBAPIError:
                session.rollback()
                raise
    return created


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
    ti: TaskInstance, failure: BaseException | None, *, cancelled: bool, retry_in: timedelta | None = None
) -> None:
    """Report a finished attempt; ``failure`` is the exception it failed with, held back from the terminal."""
    label = _task_label(ti.task_id, ti.map_index)
    state = _state_name(ti.state)
    if state == "success":
        report(f"  ✓ {label}")
    elif state == "up_for_retry":
        when = f" in {_describe_delay(retry_in)}" if retry_in else ""
        reason = f": {_describe(failure)}" if failure is not None else ""
        report(f"  ↻ {label} failed attempt {ti.try_number} of {ti.max_tries + 1}, retrying{when}{reason}")
    elif state == "failed" and cancelled:
        report(f"  ✗ {label} cancelled")
    elif state == "failed":
        report(f"  ✗ {label} failed")
        if failure is not None:
            traceback.print_exception(failure, file=sys.stderr)
    else:
        report(f"  · {label} {state}")


def summarize_run(payload: dict[str, Any], elapsed: float, home: Path) -> str:
    if payload["cancelled"]:
        outcome = f"Cancelled after {elapsed:.1f}s"
    elif payload["state"] == DagRunState.SUCCESS:
        outcome = f"Succeeded in {elapsed:.1f}s"
    else:
        failed = sorted(
            _task_label(task_id, map_index)
            for (task_id, map_index), state in payload["task_states"].items()
            if state == "failed"
        )
        outcome = f"Failed in {elapsed:.1f}s" + (f": {', '.join(failed)}" if failed else "")
    return f"{outcome}. History: {home}"


@contextmanager
def project_lock(home: Path) -> Iterator[None]:
    with open(home / ".lock", "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield


def ensure_database(home: Path) -> None:
    """Create the project database, or migrate it to this Airflow version; refuse a newer schema."""
    with project_lock(home):
        with create_session() as session:
            current = _get_current_revision(session)
        if current is None:
            report(f"Creating the project database in {home} (first run only)")
            initdb()
            return
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


def import_dag_file(source: Path, root: Path) -> BundleDagBag:
    """Import ``source`` the way Airflow discovers Dags; its ``__main__`` block does not run."""
    # Modules next to the file import as they do under ``python file.py``. Appended after Airflow is
    # imported, so a user module named like a standard-library one cannot shadow Airflow's own imports.
    if str(source.parent) not in sys.path:
        sys.path.append(str(source.parent))
    started = time.monotonic()
    bag = BundleDagBag(dag_folder=source, bundle_path=root, bundle_name=BUNDLE_NAME, collect_dags=False)
    bag.collect_dags(dag_folder=source, only_if_updated=False, safe_mode=False)
    if bag.import_errors:
        details = "\n".join(error.rstrip() for error in bag.import_errors.values())
        raise LocalRunSetupError(f"Importing {source} failed:\n{details}")
    structlog.get_logger(logger_name="task").info(
        "Local run startup parse complete",
        bundle_name=BUNDLE_NAME,
        bundle_version=None,
        dag_file=source.relative_to(root).as_posix(),
        dag_file_parse_ms=int((time.monotonic() - started) * 1000),
        parsed_at=timezone.utcnow().isoformat(),
    )
    return bag


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


def create_dag_run(
    dag: DAG, run_conf: dict | None, triggered_by: DagRunTriggeredByType, *, session: Session
) -> tuple[SerializedDAG, DagRun]:
    """
    Create a new run with its own logical date.

    ``get_or_create_dagrun`` (used by ``dag.test()``) deletes a run sharing the logical date, which a
    concurrent local run of the same Dag could hit; here a collision retries with a fresh timestamp.
    """
    dag.validate()
    scheduler_dag = DagSerialization.deserialize_dag(DagSerialization.serialize_dag(dag))
    # Serialization drops callbacks; the run loop finds them on the scheduler Dag, as in dag.test().
    scheduler_dag.on_success_callback = dag.on_success_callback  # type: ignore[attr-defined]
    scheduler_dag.on_failure_callback = dag.on_failure_callback  # type: ignore[attr-defined]
    timetable = coerce_to_core_timetable(dag.timetable)
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
                    session=session,
                )
        except IntegrityError:
            continue
        return scheduler_dag, dag_run
    raise LocalRunSetupError(f"Could not create a unique run for Dag {dag.dag_id!r}; run it again")


def collect_result(
    dag_id: str, run_id: str, *, source: Path, cancelled: bool, session: Session
) -> dict[str, Any]:
    """
    Read the run's outcome; each output is pickled on its own, so one the caller cannot load spares the rest.

    Outputs are read the way a downstream task reads them.
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


def _describe(error: BaseException) -> str:
    return "".join(traceback.format_exception_only(error)).strip()


def _describe_delay(delay: timedelta) -> str:
    minutes, seconds = divmod(math.ceil(delay.total_seconds()), 60)
    hours, minutes = divmod(minutes, 60)
    return " ".join(
        f"{value}{unit}" for value, unit in ((hours, "h"), (minutes, "m"), (seconds, "s")) if value
    )
