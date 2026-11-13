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

"""Execute a selected task with no metadata records or Execution API client."""

from __future__ import annotations

import json
import os
import pickle
import reprlib
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from airflow.local_run.logs import render_for_terminal  # noqa: SDK002
from airflow.sdk._shared.secrets_masker import redact
from airflow.sdk.api.datamodels._generated import (
    BundleInfo,
    DagRun,
    DagRunState,
    DagRunType,
    TaskInstance,
    TIRunContext,
)
from airflow.sdk.definitions._internal.loop import get_enclosing_loop
from airflow.sdk.definitions.dag import DAG
from airflow.sdk.definitions.local_run import PROTOCOL_VERSION, allow_classes_defined_in, find_loaded_module
from airflow.sdk.definitions.mappedoperator import MappedOperator
from airflow.sdk.definitions.param import process_params
from airflow.sdk.definitions.xcom_arg import XComArg
from airflow.sdk.exceptions import (
    LocalRunConfigError,
    LocalRunDagFileError,
    LocalRunUsageError,
    ParamValidationError,
)
from airflow.sdk.execution_time.comms import StartupDetails
from airflow.sdk.execution_time.supervisor import block_orm_access, task_process_uses_exec
from airflow.sdk.local_runtime.services import LocalTaskServices
from airflow.sdk.local_runtime.state import LocalStateStore
from airflow.sdk.local_runtime.supervisor import LocalTaskSupervisor
from airflow.sdk.log import configure_logging
from airflow.sdk.serde import CLASSNAME, deserialize


def load_task(source: Path, root: Path, dag_id: str | None, task_id: str):
    from airflow.dag_processing.dagbag import BundleDagBag  # noqa: SDK002

    bag = BundleDagBag(
        dag_folder=source,
        bundle_path=root,
        bundle_name="dags-folder",
        collect_dags=False,
        load_op_links=False,
    )
    bag.collect_dags(dag_folder=source, only_if_updated=False, safe_mode=False)
    if bag.import_errors:
        raise LocalRunDagFileError(f"Importing {source} failed:\n" + "\n".join(bag.import_errors.values()))
    dags = {key: dag for key, dag in bag.dags.items() if isinstance(dag, DAG)}
    if not dags:
        raise LocalRunDagFileError(
            f"No Dags found in {source}. Create the Dag at module level, for example `workflow = example()`."
        )
    if dag_id is None:
        if len(dags) != 1:
            raise LocalRunUsageError(f"Choose one Dag with --dag-id; found: {', '.join(dags) or 'none'}")
        dag_id = next(iter(dags))
    if dag_id not in dags:
        raise LocalRunUsageError(f"Dag {dag_id!r} was not found in {source}")
    dag = dags[dag_id]
    if task_id not in dag.task_dict:
        raise LocalRunUsageError(f"Dag {dag_id!r} has no task {task_id!r}")
    task = dag.task_dict[task_id]
    if isinstance(task, MappedOperator) or task.get_closest_mapped_task_group() or get_enclosing_loop(task):
        raise LocalRunUsageError("--no-db does not support mapped tasks or loops")
    if task.inlets or task.outlets:
        raise LocalRunUsageError("--no-db does not support asset services or inlet/outlet events")
    if getattr(task, "run_as_user", None):
        raise LocalRunUsageError("--no-db does not support run_as_user")
    if getattr(task, "is_stub", False):
        raise LocalRunUsageError("--no-db currently supports Python task implementations")
    return dag, task


def build_inputs(task, inputs: dict[str, Any]) -> dict[tuple[str, str], Any]:
    values = {}
    for task_id, value in inputs.items():
        if task_id not in task.upstream_task_ids:
            raise LocalRunUsageError(f"{task_id!r} is not directly upstream of {task.task_id!r}")
        upstream = task.dag.task_dict[task_id]
        if (
            isinstance(upstream, MappedOperator)
            or upstream.get_closest_mapped_task_group()
            or get_enclosing_loop(upstream)
        ):
            raise LocalRunUsageError("--no-db inputs cannot represent mapped tasks or loops")
        values[task_id, "return_value"] = value
        if upstream.multiple_outputs:
            if not isinstance(value, dict) or CLASSNAME in value:
                raise LocalRunUsageError(f"{task_id!r} has multiple_outputs; its input must be a JSON object")
            values.update(((task_id, key), item) for key, item in value.items())
    for upstream, key in XComArg.iter_xcom_references(task):
        if (upstream.task_id, key) not in values:
            raise LocalRunUsageError(
                f"No input for {upstream.task_id!r}, key {key!r}; supply --input {upstream.task_id}=JSON"
            )
    return values


def build_startup(dag, task, source: Path, root: Path, run_conf: dict | None) -> StartupDetails:
    now = datetime.now(tz=UTC)
    run_id = f"local__{uuid4()}"
    ti = TaskInstance(
        id=uuid4(),
        task_id=task.task_id,
        dag_id=dag.dag_id,
        run_id=run_id,
        try_number=1,
        dag_version_id=uuid4(),
        map_index=-1,
        queue=task.queue,
    )
    dag_run = DagRun(
        dag_id=dag.dag_id,
        run_id=run_id,
        logical_date=now,
        data_interval_start=now,
        data_interval_end=now,
        run_after=now,
        start_date=now,
        end_date=None,
        run_type=DagRunType.MANUAL,
        state=DagRunState.RUNNING,
        conf=run_conf or {},
        consumed_asset_events=[],
        partition_key=None,
    )
    return StartupDetails(
        ti=ti,
        dag_rel_path=source.relative_to(root).as_posix(),
        bundle_info=BundleInfo(name="dags-folder", version=None),
        start_date=now,
        ti_context=TIRunContext(dag_run=dag_run, max_tries=0, should_retry=False),
        sentry_integration="",
    )


def execute(request: dict[str, Any]) -> dict[str, Any]:
    configure_logging(output=sys.stderr)
    structlog.get_config()["processors"][-1] = render_for_terminal
    block_orm_access()
    source, root = Path(request["source"]), Path(request["root"])
    dag, task = load_task(source, root, request.get("dag_id"), request["task_id"])
    try:
        process_params(dag, task, request.get("run_conf"), suppress_exception=False)
    except ParamValidationError as error:
        raise LocalRunUsageError(str(error)) from error
    inputs = build_inputs(task, request["inputs"])
    startup = build_startup(dag, task, source, root, request.get("run_conf"))
    identity = {"source": str(source), "dag_id": dag.dag_id, "task_id": task.task_id}
    with LocalStateStore(
        identity=identity,
        run_id=startup.ti.run_id,
        path=Path(request["state_file"]) if request.get("state_file") else None,
        resume=request.get("keep_task_state", False),
    ) as state:
        services = LocalTaskServices(startup=startup, state=state, inputs=inputs)
        print(
            f"Running task {task.task_id!r} of Dag {dag.dag_id!r} without a database ({startup.ti.run_id})",
            flush=True,
        )
        process = LocalTaskSupervisor.start(
            id=startup.ti.id,
            services=services,
            use_exec=task_process_uses_exec(),
            new_process_group=True,
            logger=structlog.get_logger("airflow.sdk.local_runtime").bind(task_id=task.task_id),
        )
        cancelled = False
        try:
            process.send_msg(startup, request_id=0)
            process.wait()
        except KeyboardInterrupt:
            cancelled = True
        finally:
            if process._exit_code is None:
                process.kill(signal.SIGTERM, escalation_delay=1, force=True)
                process.cleanup_sockets_after_kill()
                process.selector.close()
        task_state = "failed" if cancelled else process.final_state
        payload = collect_result(startup, services, task_state, source)
        payload["cancelled"] = cancelled
        if process.failure and task_state == "failed":
            payload["failures"] = {(task.task_id, -1): redact(process.failure)}
        print(
            f"{'Succeeded' if payload['state'] == 'success' else 'Failed'} in {time.monotonic() - request['started_at']:.1f}s.",
            flush=True,
        )
        return payload


def collect_result(startup: StartupDetails, services: LocalTaskServices, state: str, source: Path) -> dict:
    dag_module = find_loaded_module(source)
    if dag_module is not None:
        allow_classes_defined_in(dag_module)
    outputs, output_reprs, output_errors = {}, {}, {}
    for key, stored in services.outputs.items():
        coordinate = (startup.ti.task_id, -1, key)
        try:
            value = deserialize(stored)
            output_reprs[coordinate] = redact(reprlib.repr(value))
            outputs[coordinate] = pickle.dumps(value)
        except Exception as error:
            output_errors[coordinate] = redact(f"{type(error).__name__}: {error}")
    return {
        "version": PROTOCOL_VERSION,
        "dag_id": startup.ti.dag_id,
        "run_id": startup.ti.run_id,
        "state": "success" if state in {"success", "skipped"} else "failed",
        "task_states": {(startup.ti.task_id, -1): state},
        "outputs": outputs,
        "output_reprs": output_reprs,
        "output_errors": output_errors,
        "dag_module": dag_module,
        "ran": frozenset({(startup.ti.task_id, -1)}),
    }


def interrupt(signum, frame) -> None:
    # A terminal Ctrl-C reaches both processes; the CLI also forwards SIGINT while we clean up.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise KeyboardInterrupt


def main() -> int:
    request = json.loads(Path(sys.argv[1]).read_text())
    try:
        if os.environ.get("_AIRFLOW__LOCAL_NO_DB") != "1":
            raise LocalRunConfigError("The database-free runner must be started by airflow run --no-db")
        if request.get("version") != PROTOCOL_VERSION:
            raise LocalRunConfigError("Unsupported local run protocol version")
        signal.signal(signal.SIGINT, interrupt)
        signal.signal(signal.SIGTERM, interrupt)
        payload = execute(request)
    except KeyboardInterrupt:
        payload = {"version": PROTOCOL_VERSION, "cancelled": True}
    except (LocalRunUsageError, LocalRunDagFileError, LocalRunConfigError, OSError) as error:
        kind = (
            "usage"
            if isinstance(error, LocalRunUsageError)
            else "dag_file"
            if isinstance(error, LocalRunDagFileError)
            else "config"
        )
        payload = {"version": PROTOCOL_VERSION, "error": redact(str(error)), "error_kind": kind}
    except Exception as error:
        structlog.get_logger().exception("Local task execution failed")
        payload = {"version": PROTOCOL_VERSION, "error": redact(str(error)), "error_kind": None}
    Path(request["result_path"]).write_bytes(pickle.dumps(payload))
    if payload.get("cancelled"):
        return 130
    return 0 if payload.get("state") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
