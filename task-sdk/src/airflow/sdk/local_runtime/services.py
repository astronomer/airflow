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

"""Local implementations of the task-to-supervisor service messages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from airflow.sdk._shared.secrets_masker import mask_secret
from airflow.sdk.configuration import conf
from airflow.sdk.definitions.connection import Connection
from airflow.sdk.exceptions import AirflowSecretsBackendAccessDenied, ErrorType, LocalRunConfigError
from airflow.sdk.execution_time import comms
from airflow.secrets.environment_variables import EnvironmentVariablesBackend  # noqa: SDK002

if TYPE_CHECKING:
    from airflow.sdk.local_runtime.state import LocalStateStore


class UnsupportedLocalOperation(ValueError):
    """A task requested a service outside the single-task local contract."""


class MissingLocalInput(ValueError):
    """An upstream value was neither supplied nor produced by this execution."""


class LocalTaskServices:
    def __init__(self, *, startup: comms.StartupDetails, state: LocalStateStore, inputs: dict) -> None:
        self.startup = startup
        self.state = state
        self.xcoms: dict[tuple[str, str], Any] = dict(inputs)
        self.outputs: dict[str, Any] = {}
        self.backends = []
        try:
            backend = conf.getimport("secrets", "backend", fallback=None)
            if backend:
                if backend.__name__ in {"MetastoreBackend", "ExecutionAPISecretsBackend"}:
                    raise LocalRunConfigError(
                        "--no-db needs a secrets backend independent of Airflow services"
                    )
                self.backends.append(backend(**conf.getjson("secrets", "backend_kwargs", fallback={})))
        except (ImportError, TypeError, ValueError) as error:
            raise LocalRunConfigError(f"Cannot configure the local secrets backend: {error}") from error
        self.backends.append(EnvironmentVariablesBackend())
        for instance in self.backends:
            instance._set_connection_class(Connection)

    def handle(self, msg):
        match msg:
            case comms.MaskSecret():
                mask_secret(msg.value, msg.name)
                return None
            case comms.GetConnection():
                connection = self._resolve_secret("get_connection", conn_id=msg.conn_id)
                if connection is None:
                    return comms.ErrorResponse(
                        error=ErrorType.CONNECTION_NOT_FOUND,
                        detail={"message": f"Connection {msg.conn_id!r} is not configured locally"},
                    )
                mask_secret(connection.password)
                mask_secret(connection.extra_dejson)
                return comms.ConnectionResult(
                    conn_id=msg.conn_id,
                    conn_type=connection.conn_type,
                    host=connection.host,
                    schema=connection.schema,
                    login=connection.login,
                    password=connection.password,
                    port=connection.port,
                    extra=connection.extra,
                )
            case comms.GetVariable():
                value = self._resolve_secret("get_variable", key=msg.key)
                if value is None:
                    return comms.ErrorResponse(
                        error=ErrorType.VARIABLE_NOT_FOUND,
                        detail={"message": f"Variable {msg.key!r} is not configured locally"},
                    )
                mask_secret(value, msg.key)
                return comms.VariableResult(key=msg.key, value=value)
            case comms.GetXCom() | comms.SetXCom() | comms.DeleteXCom():
                return self._handle_xcom(msg)
            case comms.GetXComCount() | comms.GetXComSequenceItem() | comms.GetXComSequenceSlice():
                value = self._handle_xcom(
                    comms.GetXCom(
                        dag_id=msg.dag_id,
                        run_id=msg.run_id,
                        task_id=msg.task_id,
                        key=msg.key,
                        previous_iteration=msg.previous_iteration,
                        include_prior_dates=getattr(msg, "include_prior_dates", False),
                    )
                ).value
                if isinstance(msg, comms.GetXComCount):
                    return comms.XComCountResponse(len=1)
                if isinstance(msg, comms.GetXComSequenceSlice):
                    return comms.XComSequenceSliceResult(root=[value][slice(msg.start, msg.stop, msg.step)])
                if msg.offset not in (0, -1):
                    raise UnsupportedLocalOperation("--no-db only has one unmapped XCom per task and key")
                return comms.XComSequenceIndexResult(root=value)
            case (
                comms.GetTaskStateStore()
                | comms.SetTaskStateStore()
                | comms.DeleteTaskStateStore()
                | comms.ClearTaskStateStore()
            ):
                return self._handle_state(msg)
            case comms.SetRenderedFields() | comms.SetRenderedMapIndex():
                return None
            case comms.ValidateInletsAndOutlets():
                return comms.InactiveAssetsResult(inactive_assets=[])
            case comms.GetDagRun():
                if msg.dag_id != self.startup.ti.dag_id or msg.run_id != self.startup.ti.run_id:
                    raise UnsupportedLocalOperation("--no-db has no other Dag run or execution history")
                return comms.DagRunResult(**self.startup.ti_context.dag_run.model_dump())
            case _:
                raise UnsupportedLocalOperation(
                    f"{type(msg).__name__} is not supported by airflow run --no-db; "
                    "this mode executes one task without an Airflow control plane"
                )

    def _resolve_secret(self, method: str, **kwargs):
        for backend in self.backends:
            try:
                value = getattr(backend, method)(**kwargs)
            except AirflowSecretsBackendAccessDenied:
                raise
            if value is not None:
                return value
        return None

    def _handle_xcom(self, msg):
        ti = self.startup.ti
        if msg.dag_id != ti.dag_id or msg.run_id != ti.run_id:
            raise UnsupportedLocalOperation("--no-db cannot read or write another Dag or run's XComs")
        if msg.map_index not in (None, -1):
            raise UnsupportedLocalOperation("--no-db does not support mapped XComs")
        key = (msg.task_id, msg.key)
        if isinstance(msg, comms.GetXCom):
            if msg.include_prior_dates or msg.previous_iteration:
                raise UnsupportedLocalOperation("--no-db cannot resolve historical or loop XComs")
            if key not in self.xcoms:
                raise MissingLocalInput(
                    f"No input for {msg.task_id!r}, key {msg.key!r}. "
                    f"Supply --input {msg.task_id}=JSON; upstream tasks are not executed with --no-db"
                )
            return comms.XComResult(key=msg.key, value=self.xcoms[key])
        if msg.task_id != ti.task_id:
            raise UnsupportedLocalOperation("--no-db only writes outputs of the selected task")
        if isinstance(msg, comms.SetXCom):
            if msg.dag_result:
                raise UnsupportedLocalOperation("--no-db does not support Dag results")
            self.xcoms[key] = msg.value
            self.outputs[msg.key] = msg.value
        else:
            self.xcoms.pop(key, None)
            self.outputs.pop(msg.key, None)
        return None

    def _handle_state(self, msg):
        if msg.ti_id != self.startup.ti.id:
            raise UnsupportedLocalOperation("--no-db only provides the selected task's state")
        match msg:
            case comms.GetTaskStateStore():
                entry = self.state.get(msg.key)
                if entry is None:
                    return comms.ErrorResponse(error=ErrorType.TASK_STORE_NOT_FOUND)
                return comms.TaskStateStoreResult(value=entry["value"])
            case comms.SetTaskStateStore():
                self.state.set(msg.key, msg.value, msg.expires_at)
            case comms.DeleteTaskStateStore():
                self.state.delete(msg.key)
            case comms.ClearTaskStateStore():
                self.state.clear()
        return comms.OKResponse(ok=True)
