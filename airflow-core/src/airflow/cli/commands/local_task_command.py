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
"""CLI for running one local task without a metadata database."""

from __future__ import annotations

import json
import sys
from typing import Any

from pydantic import TypeAdapter

from airflow.sdk._shared.secrets_masker import redact  # noqa: SDK001
from airflow.sdk.execution_time.local_runner import run_task_local  # noqa: SDK001

_output_adapter = TypeAdapter(Any)


def _format_output(value: Any) -> str:
    return json.dumps(redact(_output_adapter.dump_python(value, mode="json", fallback=str)))


def _parse_json_object(value: str | None, option: str) -> dict | None:
    if value is None:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{option} must be a JSON object")
    return parsed


def task_run_local(args) -> None:
    """Execute a local task and report its published outputs and outcome."""
    try:
        result = run_task_local(
            args.dag_file,
            args.task_id,
            dag_id=args.dag_id,
            run_id=args.run_id,
            bundle_root=args.bundle_root,
            state_dir=args.state_dir,
            connections=args.connections,
            variables=args.variables,
            params=_parse_json_object(args.params, "--params"),
            upstream_xcoms=_parse_json_object(args.upstream_xcoms, "--upstream-xcoms"),
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Local task failed: {redact(str(error))}", file=sys.stderr)
        raise SystemExit(1) from error

    print(f"Run ID: {result.run_id}")
    print(f"Task instance: {result.task_instance_id} (attempt {result.try_number})")
    print(f"Rendered fields: {_format_output(result.rendered_fields)}")
    print(f"XComs: {_format_output(result.xcoms)}")
    if "return_value" in result.xcoms:
        print(f"Return value: {_format_output(result.xcoms['return_value'])}")
    else:
        print("no return value published")
    if any(result.asset_outputs.values()):
        print(f"Asset outputs (not recorded locally): {_format_output(result.asset_outputs)}")
    if result.skipped_downstream_tasks:
        print(f"Downstream tasks that would be skipped: {_format_output(result.skipped_downstream_tasks)}")
    for diagnostic in result.diagnostics:
        print(redact(diagnostic), file=sys.stderr)
    if result.diagnostic:
        print(redact(result.diagnostic), file=sys.stderr)
    print(f"Final state: {result.state}")
    print(f"Exit code: {result.exit_code}")
    raise SystemExit(result.exit_code)
