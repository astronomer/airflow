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
"""Local Execution API resources for running one task without Airflow services."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog

from airflow.sdk._shared.state import TaskScope
from airflow.sdk.api.datamodels._generated import (
    DagRun,
    DagRunState,
    DagRunType,
    InactiveAssetsResponse,
    TaskInstance,
    TaskStateStorePutBody,
    TaskStateStoreResponse,
    TIRunContext,
    XComResponse,
    XComSequenceIndexResponse,
    XComSequenceSliceResponse,
)
from airflow.sdk.exceptions import ErrorType
from airflow.sdk.execution_time.comms import ErrorResponse, OKResponse, XComCountResponse

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic import JsonValue

    from airflow.sdk.execution_time.comms import SkipDownstreamTasks

log = structlog.get_logger(__name__)

LOCAL_TASK_RUN_ENV = "_AIRFLOW_LOCAL_TASK_RUN"
"""Set to ``"1"`` in a task process started by the local runner."""


class LocalUnsupportedOperationError(NotImplementedError):
    """An operation needs an Airflow service unavailable to the local runner."""


@dataclass(frozen=True)
class LocalAttempt:
    """Identity and start time of a single local execution attempt."""

    ti: TaskInstance
    start_date: datetime


@dataclass(frozen=True)
class LocalTaskOutcome:
    """The worker's reported outcome, independent of its process exit status."""

    state: str
    diagnostic: str | None = None
    task_outlets: list[Any] = field(default_factory=list)
    outlet_events: list[Any] = field(default_factory=list)


def _compute_storage_key(*parts: str | int) -> str:
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


@contextmanager
def _lock_directory(directory: Path) -> Iterator[None]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(directory / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError(f"Cannot read local recovery state {path}: {error}") from error


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(mode="w", dir=path.parent, prefix=".state-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class LocalRunStore:
    """Preserve run metadata and task-scoped recovery values across local attempts."""

    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)

    def _get_run_directory(self, dag_id: str, run_id: str) -> Path:
        return self.state_dir / "runs" / _compute_storage_key(dag_id, run_id)

    def _get_scope_directory(self, scope: TaskScope) -> Path:
        return (
            self._get_run_directory(scope.dag_id, scope.run_id)
            / "tasks"
            / _compute_storage_key(scope.task_id, str(scope.region_id), scope.region_index)
        )

    def prepare_run(self, dag_id: str, run_id: str, params: dict[str, Any] | None = None) -> DagRun:
        """Create a manual run, or reuse its initial dates and configuration."""
        directory = self._get_run_directory(dag_id, run_id)
        with _lock_directory(directory):
            path = directory / "run.json"
            saved = _read_json(path)
            if saved:
                run = DagRun.model_validate(saved["dag_run"])
                if params is not None and json.dumps(params, sort_keys=True, allow_nan=False) != json.dumps(
                    run.conf, sort_keys=True, allow_nan=False
                ):
                    raise ValueError(
                        f"Run {run_id!r} already has different params; choose a new run ID to change params."
                    )
                return run
            now = datetime.now(UTC)
            run = DagRun(
                dag_id=dag_id,
                run_id=run_id,
                logical_date=now,
                data_interval_start=now,
                data_interval_end=now,
                run_after=now,
                start_date=now,
                end_date=None,
                run_type=DagRunType.MANUAL,
                state=DagRunState.RUNNING,
                conf=params or {},
                consumed_asset_events=[],
                partition_key=None,
            )
            _write_json(path, {"dag_run": run.model_dump(mode="json"), "attempts": {}})
            return run

    def begin_attempt(self, dag_run: DagRun, task_id: str) -> LocalAttempt:
        """Allocate a fresh task-instance identity and monotonically increasing try number."""
        directory = self._get_run_directory(dag_run.dag_id, dag_run.run_id)
        with _lock_directory(directory):
            path = directory / "run.json"
            saved = _read_json(path)
            if not saved:
                raise ValueError("Prepare the local run before beginning an attempt")
            attempts = saved["attempts"]
            try_number = attempts.get(task_id, 0) + 1
            attempts[task_id] = try_number
            attempt = LocalAttempt(
                ti=TaskInstance(
                    id=uuid4(),
                    task_id=task_id,
                    dag_id=dag_run.dag_id,
                    run_id=dag_run.run_id,
                    try_number=try_number,
                    dag_version_id=uuid4(),
                ),
                start_date=datetime.now(UTC),
            )
            _write_json(path, saved)
            return attempt

    def get_task_state(self, scope: TaskScope, key: str) -> TaskStateStoreResponse | ErrorResponse:
        directory = self._get_scope_directory(scope)
        with _lock_directory(directory):
            path = directory / "state.json"
            values = _read_json(path)
            if key in values:
                entry = TaskStateStorePutBody.model_validate(values[key])
                if entry.expires_at is None or entry.expires_at > datetime.now(UTC):
                    return TaskStateStoreResponse(value=entry.value)
                del values[key]
                _write_json(path, values)
            return ErrorResponse(error=ErrorType.TASK_STORE_NOT_FOUND, detail={"key": key})

    def set_task_state(
        self, scope: TaskScope, key: str, value: JsonValue, expires_at: datetime | None = None
    ) -> None:
        entry = TaskStateStorePutBody(value=value, expires_at=expires_at)
        directory = self._get_scope_directory(scope)
        with _lock_directory(directory):
            path = directory / "state.json"
            values = _read_json(path)
            values[key] = entry.model_dump(mode="json")
            _write_json(path, values)

    def delete_task_state(self, scope: TaskScope, key: str) -> None:
        directory = self._get_scope_directory(scope)
        with _lock_directory(directory):
            path = directory / "state.json"
            values = _read_json(path)
            values.pop(key, None)
            _write_json(path, values)

    def clear_task_state(self, scope: TaskScope) -> None:
        directory = self._get_scope_directory(scope)
        with _lock_directory(directory):
            _write_json(directory / "state.json", {})


class _UnsupportedResource:
    def __init__(self, client: LocalClient, resource: str):
        self.client = client
        self.resource = resource

    def __getattr__(self, operation: str):
        def fail(*args, **kwargs):
            diagnostic = f"Local task execution does not support {self.resource}.{operation}."
            self.client.diagnostics.append(diagnostic)
            raise LocalUnsupportedOperationError(diagnostic)

        return fail


class _TaskInstances(_UnsupportedResource):
    def start(self, id: UUID, pid: int, when: datetime) -> TIRunContext:
        return TIRunContext(
            dag_run=self.client.dag_run,
            max_tries=0,
            should_retry=False,
            start_date=self.client.attempt.start_date,
        )

    def heartbeat(self, id: UUID, pid: int) -> None:
        pass

    def finish(self, id: UUID, state, when: datetime, rendered_map_index=None, retry_reason=None, **kwargs):
        state = str(getattr(state, "value", state))
        diagnostic = retry_reason
        if state == "up_for_retry":
            diagnostic = "Automatic retries are unsupported locally; rerun with the same run ID to recover."
        elif not diagnostic and state != "success":
            diagnostic = f"Local task finished in state {state!r}."
        self.client.outcome = LocalTaskOutcome(state=state, diagnostic=diagnostic)

    def succeed(
        self,
        id: UUID,
        when: datetime,
        task_outlets,
        outlet_events,
        rendered_map_index=None,
        **kwargs,
    ) -> None:
        self.client.outcome = LocalTaskOutcome(
            state="success", task_outlets=task_outlets or [], outlet_events=outlet_events or []
        )

    def retry(self, id: UUID, end_date: datetime, rendered_map_index=None, **kwargs) -> None:
        self.finish(id, "up_for_retry", end_date, rendered_map_index)

    def defer(self, id: UUID, msg) -> None:
        self.client.outcome = LocalTaskOutcome(
            state="deferred", diagnostic="Deferral and triggers are unsupported during local task execution."
        )

    def reschedule(self, id: UUID, msg) -> None:
        self.client.outcome = LocalTaskOutcome(
            state="up_for_reschedule", diagnostic="Rescheduling is unsupported during local task execution."
        )

    def await_input(self, id: UUID, msg) -> None:
        self.client.outcome = LocalTaskOutcome(
            state="awaiting_input",
            diagnostic="Human-in-the-loop approval is unsupported during local task execution.",
        )

    def skip_downstream_tasks(self, id: UUID, msg: SkipDownstreamTasks) -> None:
        # Only unmapped tasks request skips, so a (task_id, map_index) entry always has map index -1.
        self.client.skipped_downstream_tasks.extend(
            task if isinstance(task, str) else task[0] for task in msg.tasks
        )

    def set_rtif(self, id: UUID, body: dict[str, str]) -> OKResponse:
        self.client.rendered_fields = body.copy()
        return OKResponse(ok=True)

    def validate_inlets_and_outlets(self, id: UUID) -> InactiveAssetsResponse:
        diagnostic = "Asset registry validation is skipped locally; asset outputs are not recorded locally."
        if diagnostic not in self.client.diagnostics:
            self.client.diagnostics.append(diagnostic)
            log.warning(diagnostic)
        return InactiveAssetsResponse(inactive_assets=[])


class _Connections(_UnsupportedResource):
    def get(self, conn_id: str) -> ErrorResponse:
        diagnostic = (
            f"Connection {conn_id!r} was not found in the configured secrets backend, local connection files "
            "or AIRFLOW_CONN_* environment variables. Deployment metadata-database connections are "
            "unavailable locally."
        )
        self.client.diagnostics.append(diagnostic)
        return ErrorResponse(
            error=ErrorType.CONNECTION_NOT_FOUND, detail={"conn_id": conn_id, "message": diagnostic}
        )


class _Variables(_UnsupportedResource):
    def get(self, key: str) -> ErrorResponse:
        diagnostic = (
            f"Variable {key!r} was not found in the configured secrets backend, local Variable files "
            "or AIRFLOW_VAR_* environment variables."
        )
        self.client.diagnostics.append(diagnostic)
        return ErrorResponse(error=ErrorType.VARIABLE_NOT_FOUND, detail={"key": key, "message": diagnostic})


class _XComs(_UnsupportedResource):
    def _check_scope(
        self,
        dag_id: str,
        run_id: str,
        map_index: int | None = None,
        include_prior_dates: bool = False,
        previous_iteration: bool = False,
    ) -> None:
        if map_index not in (None, -1):
            raise LocalUnsupportedOperationError("Mapped XComs are unsupported during local task execution.")
        if (
            dag_id != self.client.dag_run.dag_id
            or run_id != self.client.dag_run.run_id
            or include_prior_dates
            or previous_iteration
        ):
            raise LocalUnsupportedOperationError("XCom run-history queries are unsupported locally.")

    def _has_value(self, dag_id: str, run_id: str, task_id: str, key: str) -> bool:
        """Return whether the XCom exists, recording a diagnostic for an unsupplied upstream value."""
        if (dag_id, run_id, task_id, key) in self.client.xcom_values:
            return True
        if task_id != self.client.attempt.ti.task_id:
            diagnostic = (
                f"Task read unsupplied upstream XCom for task {task_id!r}, key {key!r}, and received no "
                "value. Supply upstream XCom values explicitly; upstream tasks are not executed locally."
            )
            if diagnostic not in self.client.diagnostics:
                self.client.diagnostics.append(diagnostic)
                log.warning(diagnostic)
        return False

    def get(
        self,
        dag_id: str,
        run_id: str,
        task_id: str,
        key: str,
        map_index: int | None = None,
        include_prior_dates: bool = False,
        *,
        previous_iteration: bool = False,
    ) -> XComResponse:
        self._check_scope(dag_id, run_id, map_index, include_prior_dates, previous_iteration)
        if not self._has_value(dag_id, run_id, task_id, key):
            return XComResponse(key=key, value=None)
        return XComResponse(key=key, value=self.client.xcom_values[dag_id, run_id, task_id, key])

    def set(
        self,
        dag_id: str,
        run_id: str,
        task_id: str,
        key: str,
        value: JsonValue,
        map_index: int | None = None,
        *,
        dag_result: bool = False,
        mapped_length: int | None = None,
    ) -> OKResponse:
        self._check_scope(dag_id, run_id, map_index)
        self.client.xcom_values[dag_id, run_id, task_id, key] = value
        return OKResponse(ok=True)

    def delete(
        self, dag_id: str, run_id: str, task_id: str, key: str, map_index: int | None = None
    ) -> OKResponse:
        self._check_scope(dag_id, run_id, map_index)
        self.client.xcom_values.pop((dag_id, run_id, task_id, key), None)
        return OKResponse(ok=True)

    def head(
        self, dag_id: str, run_id: str, task_id: str, key: str, *, previous_iteration: bool = False
    ) -> XComCountResponse:
        self._check_scope(dag_id, run_id, previous_iteration=previous_iteration)
        return XComCountResponse(len=int(self._has_value(dag_id, run_id, task_id, key)))

    def get_sequence_item(
        self,
        dag_id: str,
        run_id: str,
        task_id: str,
        key: str,
        offset: int,
        *,
        previous_iteration: bool = False,
    ) -> XComSequenceIndexResponse | ErrorResponse:
        self._check_scope(dag_id, run_id, previous_iteration=previous_iteration)
        if not self._has_value(dag_id, run_id, task_id, key) or offset not in (0, -1):
            return ErrorResponse(
                error=ErrorType.XCOM_NOT_FOUND,
                detail={"dag_id": dag_id, "run_id": run_id, "task_id": task_id, "key": key, "offset": offset},
            )
        return XComSequenceIndexResponse(root=self.client.xcom_values[dag_id, run_id, task_id, key])

    def get_sequence_slice(
        self,
        dag_id: str,
        run_id: str,
        task_id: str,
        key: str,
        start: int | None,
        stop: int | None,
        step: int | None,
        include_prior_dates: bool = False,
        *,
        previous_iteration: bool = False,
    ) -> XComSequenceSliceResponse:
        self._check_scope(
            dag_id, run_id, include_prior_dates=include_prior_dates, previous_iteration=previous_iteration
        )
        # xcom_pull() uses this route even for one unmapped producer. The sequence
        # contains at most one XCom row, which may itself hold a list or None.
        values = (
            [self.client.xcom_values[dag_id, run_id, task_id, key]]
            if self._has_value(dag_id, run_id, task_id, key)
            else []
        )
        return XComSequenceSliceResponse(root=values[slice(start, stop, step)])


class _TaskStateStore(_UnsupportedResource):
    def _get_scope(self, ti_id: UUID) -> TaskScope:
        ti = self.client.attempt.ti
        if ti_id != ti.id:
            raise ValueError(f"Unknown local task instance {ti_id}")
        return TaskScope(
            dag_id=ti.dag_id,
            run_id=ti.run_id,
            task_id=ti.task_id,
            region_id=ti.region_id or UUID(int=0),
            region_index=ti.region_index if ti.region_index is not None else -1,
        )

    def get(self, ti_id: UUID, key: str) -> TaskStateStoreResponse | ErrorResponse:
        return self.client.store.get_task_state(self._get_scope(ti_id), key)

    def set(self, ti_id: UUID, key: str, value: JsonValue, expires_at: datetime | None = None) -> OKResponse:
        self.client.store.set_task_state(self._get_scope(ti_id), key, value, expires_at)
        return OKResponse(ok=True)

    def delete(self, ti_id: UUID, key: str) -> OKResponse:
        self.client.store.delete_task_state(self._get_scope(ti_id), key)
        return OKResponse(ok=True)

    def clear(self, ti_id: UUID) -> OKResponse:
        self.client.store.clear_task_state(self._get_scope(ti_id))
        return OKResponse(ok=True)


class LocalClient:
    """Execution API resources backed by local run metadata, task state and memory."""

    def __init__(
        self,
        *,
        store: LocalRunStore,
        dag_run: DagRun,
        attempt: LocalAttempt,
        upstream_xcoms: dict[str, dict[str, JsonValue]] | None = None,
    ):
        if attempt.ti.task_id in (upstream_xcoms or {}):
            raise ValueError(
                f"Upstream XComs cannot include selected task {attempt.ti.task_id!r}; "
                "supply values only for other tasks."
            )
        self.store = store
        self.dag_run = dag_run
        self.attempt = attempt
        self.outcome: LocalTaskOutcome | None = None
        self.rendered_fields: dict[str, str] = {}
        self.xcom_values: dict[tuple[str, str, str, str], JsonValue] = {
            (dag_run.dag_id, dag_run.run_id, task_id, key): value
            for task_id, values in (upstream_xcoms or {}).items()
            for key, value in values.items()
        }
        self.diagnostics: list[str] = []
        self.skipped_downstream_tasks: list[str] = []
        self.task_instances = _TaskInstances(self, "task_instances")
        self.connections = _Connections(self, "connections")
        self.variables = _Variables(self, "variables")
        self.xcoms = _XComs(self, "xcoms")
        self.task_state_store = _TaskStateStore(self, "task_state_store")
        self.assets = _UnsupportedResource(self, "assets")
        self.asset_events = _UnsupportedResource(self, "asset_events")
        self.asset_state_store = _UnsupportedResource(self, "asset_state_store")
        self.dag_runs = _UnsupportedResource(self, "dag_runs")
        self.dags = _UnsupportedResource(self, "dags")
        self.hitl = _UnsupportedResource(self, "hitl")
