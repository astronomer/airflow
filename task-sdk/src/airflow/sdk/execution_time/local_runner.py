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
"""Execute one Python task from a local Dag file without Airflow services."""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import structlog
from uuid6 import uuid7

from airflow.sdk.api.datamodels._generated import BundleInfo
from airflow.sdk.bases.xcom import BaseXCom
from airflow.sdk.configuration import clear_secrets_backends_cache, conf
from airflow.sdk.execution_time.local_client import LOCAL_TASK_RUN_ENV, LocalClient, LocalRunStore

if TYPE_CHECKING:
    from collections.abc import Iterator

    from structlog.typing import FilteringBoundLogger

    from airflow.sdk.api.client import Client


@dataclass(frozen=True)
class LocalTaskResult:
    """Outcome and published values from a local execution attempt."""

    run_id: str
    task_instance_id: str
    try_number: int
    state: str
    exit_code: int
    process_exit_code: int
    diagnostic: str | None
    rendered_fields: dict[str, Any]
    xcoms: dict[str, Any]
    asset_outputs: dict[str, Any]
    skipped_downstream_tasks: list[str]
    """IDs of tasks a branch or short-circuit task would skip; downstream tasks never run locally."""
    diagnostics: list[str]


def _load_secret_environment(path: str | os.PathLike[str] | None, *, connections: bool) -> dict[str, str]:
    if path is None:
        return {}
    values = json.loads(Path(path).expanduser().read_text())
    if not isinstance(values, dict):
        raise ValueError(f"Secret file {path} must contain a JSON object")
    prefix = "AIRFLOW_CONN_" if connections else "AIRFLOW_VAR_"
    result = {}
    for key, value in values.items():
        if not key or "=" in key or "\x00" in key:
            raise ValueError(f"Invalid secret name in {path}")
        if connections and not isinstance(value, (str, dict)):
            raise ValueError(f"Connection {key!r} must be a URI string or JSON object")
        env_key = prefix + key.upper()
        if env_key in result:
            raise ValueError(f"Secret names in {path} must be unique ignoring case")
        result[env_key] = value if isinstance(value, str) else json.dumps(value)
    return result


@contextmanager
def _configure_local_xcom_backend() -> Iterator[None]:
    # Resolve before execution so an invalid caller backend cannot fail during restoration.
    from airflow.sdk.execution_time.xcom import XCom as original_backend

    # Runtime modules bind XCom at import time; the core model modules cache lazy exports.
    module_names = (
        "airflow.sdk.execution_time.xcom",
        "airflow.sdk.execution_time.task_runner",
        "airflow.sdk.execution_time.loop",
        "airflow.models",
        "airflow.models.xcom",
    )
    previous_aliases = {
        name: module.__dict__["XCom"]
        for name in module_names
        if (module := sys.modules.get(name)) is not None and "XCom" in module.__dict__
    }
    env_key = "AIRFLOW__CORE__XCOM_BACKEND"
    previous_config = os.environ.get(env_key)
    try:
        os.environ[env_key] = "airflow.sdk.bases.xcom.BaseXCom"
        for name in previous_aliases:
            sys.modules[name].__dict__["XCom"] = BaseXCom
        yield
    finally:
        if previous_config is None:
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = previous_config

        for name in module_names:
            if (module := sys.modules.get(name)) is None or "XCom" not in module.__dict__:
                continue
            if name in previous_aliases:
                module.__dict__["XCom"] = previous_aliases[name]
            elif name in {"airflow.models", "airflow.models.xcom"}:
                del module.__dict__["XCom"]
            else:
                # A first local run can import these modules in the parent before forking.
                module.__dict__["XCom"] = original_backend


@contextmanager
def _configure_local_execution(
    root: Path,
    connections: str | os.PathLike[str] | None,
    variables: str | os.PathLike[str] | None,
) -> Iterator[None]:
    with _configure_local_xcom_backend(), _configure_local_environment(root, connections, variables):
        yield


@contextmanager
def _configure_local_environment(
    root: Path,
    connections: str | os.PathLike[str] | None,
    variables: str | os.PathLike[str] | None,
) -> Iterator[None]:
    from airflow.dag_processing.bundles.manager import _load_bundle_config_snapshot  # noqa: SDK002
    from airflow.sdk.execution_time.cache import SecretCache
    from airflow.sdk.execution_time.context import _get_worker_state_store_backend
    from airflow.sdk.execution_time.coordinator import reset_coordinator_manager
    from airflow.sdk.log import _ActiveLoggingConfig, logging_processors

    environment = {
        "_AIRFLOW_PROCESS_CONTEXT": "client",
        LOCAL_TASK_RUN_ENV: "1",
        "AIRFLOW__CORE__DAG_RUN_CONF_OVERRIDES_PARAMS": "true",
        "AIRFLOW__CORE__LOAD_EXAMPLES": "false",
        "AIRFLOW__WORKERS__MISSING_DAG_RETRIES": "0",
        "AIRFLOW__WORKERS__STATE_STORE_BACKEND": "",
        "AIRFLOW__LOGGING__REMOTE_LOGGING": "false",
        "AIRFLOW__SDK__COORDINATORS": "{}",
        "AIRFLOW__SDK__QUEUE_TO_COORDINATOR": "{}",
        "AIRFLOW__DAG_PROCESSOR__DAG_BUNDLE_CONFIG_LIST": json.dumps(
            [
                {
                    "name": "local_task",
                    "classpath": "airflow.dag_processing.bundles.local.LocalDagBundle",
                    "kwargs": {"path": str(root)},
                }
            ]
        ),
    }
    secrets = _load_secret_environment(connections, connections=True)
    secrets.update(_load_secret_environment(variables, connections=False))
    # Files supply the environment tier without replacing an enterprise secrets backend.
    environment.update({key: value for key, value in secrets.items() if key not in os.environ})
    previous = {key: os.environ.get(key) for key in environment}
    previous_secret_cache = SecretCache._cache
    previous_logging = (
        _ActiveLoggingConfig.logging_config_loaded,
        _ActiveLoggingConfig.remote_task_log,
        _ActiveLoggingConfig.default_remote_conn_id,
    )
    try:
        os.environ.update(environment)
        # A fork must not inherit cached deployment credentials ahead of local secret inputs.
        SecretCache._cache = None
        _get_worker_state_store_backend.cache_clear()
        # Cached handlers and processors may predate the temporary remote_logging setting.
        _ActiveLoggingConfig.set(None, None)
        logging_processors.cache_clear()
        clear_secrets_backends_cache()
        _load_bundle_config_snapshot.cache_clear()
        reset_coordinator_manager()
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        SecretCache._cache = previous_secret_cache
        _get_worker_state_store_backend.cache_clear()
        (
            _ActiveLoggingConfig.logging_config_loaded,
            _ActiveLoggingConfig.remote_task_log,
            _ActiveLoggingConfig.default_remote_conn_id,
        ) = previous_logging
        logging_processors.cache_clear()
        clear_secrets_backends_cache()
        _load_bundle_config_snapshot.cache_clear()
        reset_coordinator_manager()


def _create_local_task_logger() -> FilteringBoundLogger:
    from airflow.sdk.log import logging_processors

    colors = bool(os.environ.get("FORCE_COLOR")) or (
        conf.getboolean("logging", "colored_console_log", fallback=True) and sys.stdout.isatty()
    )
    return structlog.wrap_logger(
        structlog.WriteLogger(file=sys.stdout),
        processors=logging_processors(json_output=False, colors=colors and not os.environ.get("NO_COLOR")),
        wrapper_class=structlog.make_filtering_bound_logger(logging.NOTSET),
        logger_name="task",
    ).bind()


def run_task_local(
    dag_file: str | os.PathLike[str],
    task_id: str,
    *,
    dag_id: str,
    run_id: str | None = None,
    bundle_root: str | os.PathLike[str] | None = None,
    state_dir: str | os.PathLike[str] | None = None,
    connections: str | os.PathLike[str] | None = None,
    variables: str | os.PathLike[str] | None = None,
    params: dict[str, Any] | None = None,
    upstream_xcoms: dict[str, dict[str, Any]] | None = None,
    cancellation_grace_seconds: float = 5.0,
) -> LocalTaskResult:
    """
    Run a task through the normal Python worker startup, parsing and execution path.

    Run metadata and task state survive same-run reruns; XComs are attempt-local.
    This entry point changes environment and signal handlers while running and must
    be called on the main thread, without concurrent task execution in this process.
    """
    path = Path(dag_file).expanduser().resolve(strict=True)
    root = Path(bundle_root).expanduser().resolve(strict=True) if bundle_root else path.parent
    if not path.is_file() or path.suffix != ".py":
        raise ValueError("run-local requires a Python Dag file")
    if not root.is_dir() or not path.is_relative_to(root):
        raise ValueError(f"Dag file {path} must lie beneath bundle root {root}")
    if not dag_id or not task_id:
        raise ValueError("Dag ID and task ID are required")
    if params is not None and not isinstance(params, dict):
        raise ValueError("Task params must be a JSON object")
    if upstream_xcoms is not None and (
        not isinstance(upstream_xcoms, dict)
        or any(not isinstance(value, dict) for value in upstream_xcoms.values())
    ):
        raise ValueError("Upstream XComs must map task IDs to objects containing XCom keys and values")
    if cancellation_grace_seconds < 0:
        raise ValueError("Cancellation grace period must not be negative")

    if state_dir is None:
        state_dir = Path(os.environ.get("AIRFLOW_HOME", "~/airflow")).expanduser() / "local-task-state"
    run_id = run_id or f"local__{uuid7()}"
    with _configure_local_execution(root, connections, variables):
        from airflow.sdk.execution_time.supervisor import supervise_task

        store = LocalRunStore(Path(state_dir).expanduser())
        dag_run = store.prepare_run(dag_id, run_id, params=params)
        attempt = store.begin_attempt(dag_run, task_id)
        client = LocalClient(store=store, dag_run=dag_run, attempt=attempt, upstream_xcoms=upstream_xcoms)
        process_exit_code = supervise_task(
            ti=attempt.ti,
            bundle_info=BundleInfo(name="local_task"),
            dag_rel_path=path.relative_to(root),
            token="",
            client=cast("Client", client),
            task_logger=_create_local_task_logger(),
            subprocess_logs_to_stdout=False,
            reset_secrets=False,
            cancel_on_signal=True,
            cancellation_grace_seconds=cancellation_grace_seconds,
        )
        outcome = client.outcome
        state = outcome.state if outcome else "failed"
        diagnostic = outcome.diagnostic if outcome else "Task process exited without reporting an outcome"
        success = state == "success" and process_exit_code == 0
        if process_exit_code in (-signal.SIGINT, -signal.SIGTERM):
            state = "cancelled"
            diagnostic = (
                f"Task was cancelled by {signal.Signals(-process_exit_code).name}; "
                f"saved task state was kept for a rerun with run ID {run_id!r}."
            )
        elif process_exit_code != 0:
            state = "failed"
            diagnostic = f"Task process exited with code {process_exit_code}. {diagnostic or ''}".rstrip()
        elif not success and diagnostic is None:
            diagnostic = f"Task finished with state {state!r}; local execution did not succeed"
        xcoms = {
            key: value
            for (value_dag_id, value_run_id, value_task_id, key), value in client.xcom_values.items()
            if (value_dag_id, value_run_id, value_task_id) == (dag_id, run_id, task_id)
        }
        return LocalTaskResult(
            run_id=run_id,
            task_instance_id=str(attempt.ti.id),
            try_number=attempt.ti.try_number,
            state=state,
            exit_code=0 if success else 1,
            process_exit_code=process_exit_code,
            diagnostic=diagnostic,
            rendered_fields=client.rendered_fields,
            xcoms=xcoms,
            asset_outputs={
                "outlets": outcome.task_outlets,
                "events": outcome.outlet_events,
            }
            if outcome
            else {},
            skipped_downstream_tasks=client.skipped_downstream_tasks,
            diagnostics=client.diagnostics,
        )
