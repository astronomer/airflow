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

"""Launch one isolated local task, with no metadata database configuration."""

from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from airflow.sdk.definitions.local_run import (
    PROTOCOL_VERSION,
    DagRunResult,
    build_child_environment,
    build_result,
    find_project_root,
    resolve_resource_file,
    serialize_inputs,
    wait_for_child,
)
from airflow.sdk.exceptions import LocalRunConfigError, LocalRunUsageError

CHILD_MODULE = "airflow.sdk.local_runtime.runner"


def run_task_file(
    source: str | os.PathLike[str],
    *,
    dag_id: str | None,
    run_conf: dict[str, Any] | None,
    connections_file: str | os.PathLike[str] | None,
    variables_file: str | os.PathLike[str] | None,
    task_ids: Sequence[str | tuple[str, int]] | None,
    task_group_ids: Sequence[str] | None,
    include_upstream: bool,
    include_downstream: bool,
    run_id: str | None,
    inputs: Mapping[str, Any] | None,
    keep_task_state: bool,
    state_file: str | os.PathLike[str] | None,
    debug: bool,
) -> DagRunResult:
    if sys.platform == "win32":
        raise LocalRunConfigError("Running a task locally needs Linux or macOS; on Windows, use WSL2")
    if not task_ids or len(task_ids) != 1 or not isinstance(task_ids[0], str):
        raise LocalRunUsageError("--no-db requires exactly one unmapped --task")
    for flag, enabled in (
        ("--group", task_group_ids),
        ("--upstream", include_upstream),
        ("--downstream", include_downstream),
        ("--run-id", run_id),
        ("--debug", debug),
    ):
        if enabled:
            raise LocalRunUsageError(f"--no-db does not support {flag}")
    if keep_task_state and state_file is None:
        raise LocalRunUsageError("--no-db --keep-task-state requires an explicit --state-file")
    source_path = Path(source).resolve()
    if source_path.suffix != ".py" or not source_path.is_file():
        raise LocalRunUsageError(f"A local run needs a Python Dag file; {source_path} is not one")
    if run_conf is not None and not isinstance(run_conf, dict):
        raise LocalRunUsageError("--conf must be a JSON object")
    root = find_project_root(source_path)
    connections_path = resolve_resource_file(connections_file, "connections")
    variables_path = resolve_resource_file(variables_file, "variables")
    started_at = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="airflow-no-db-") as directory:
        home = Path(directory)
        env = build_child_environment(
            os.environ,
            home=home,
            root=root,
            connections_file=connections_path,
            variables_file=variables_path,
            no_db=True,
        )
        request_path = home / "request.json"
        result_path = home / "result.pickle"
        request_path.write_text(
            json.dumps(
                {
                    "version": PROTOCOL_VERSION,
                    "source": str(source_path),
                    "root": str(root),
                    "dag_id": dag_id,
                    "task_id": task_ids[0],
                    "run_conf": run_conf,
                    "inputs": serialize_inputs(inputs) if inputs is not None else {},
                    "keep_task_state": keep_task_state,
                    "state_file": str(Path(state_file).resolve()) if state_file is not None else None,
                    "result_path": str(result_path),
                    "started_at": started_at,
                }
            )
        )
        process = subprocess.Popen([sys.executable, "-m", CHILD_MODULE, str(request_path)], env=env)
        return_code = wait_for_child(process)
        payload = pickle.loads(result_path.read_bytes()) if result_path.exists() else None
    return build_result(payload, return_code, None, source_path)
