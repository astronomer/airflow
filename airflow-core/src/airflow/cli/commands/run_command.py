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
"""Run a Dag from a Python file in its project's local Airflow environment."""

from __future__ import annotations

import json
import re
import reprlib
import sys

from airflow.sdk.definitions.local_run import DagRunResult, run_dag_file
from airflow.sdk.exceptions import DagExecutionError, LocalRunError

MAX_PRINTED_OUTPUTS = 10
# How the run labels one map index of a task, e.g. double[1].
TASK_MARKER = re.compile(r"(?P<task_id>.+)\[(?P<map_index>\d+)\]")

_output_repr = reprlib.Repr()
_output_repr.maxstring = 80
_output_repr.maxother = 80
_output_repr.maxlist = 10
_output_repr.maxdict = 10


def run(args) -> None:
    """
    Run one Dag from ``args.file`` and print its outputs; the run itself reports progress and outcome.

    Not wrapped in ``action_cli``: that would log the command to the ambient database, not the project's.
    """
    try:
        run_conf = json.loads(args.conf) if args.conf else None
    except json.JSONDecodeError as e:
        raise SystemExit(f"--conf is not valid JSON: {e.msg}")
    if run_conf is not None and not isinstance(run_conf, dict):
        raise SystemExit("--conf must be a JSON object")
    selected = bool(args.task_ids or args.task_group_ids)
    if not selected and (args.include_upstream or args.include_downstream or args.run_id):
        raise SystemExit(
            "--upstream, --downstream and --run-id apply to the tasks chosen with --task or --group"
        )
    if args.run_id and not args.keep_history:
        raise SystemExit("--run-id names a run in the project's history, which --no-history does not use")
    try:
        result = run_dag_file(
            args.file,
            dag_id=args.dag_id,
            run_conf=run_conf,
            connections_file=args.connections_file,
            variables_file=args.variables_file,
            task_ids=parse_task_ids(args.task_ids),
            task_group_ids=args.task_group_ids,
            include_upstream=args.include_upstream,
            include_downstream=args.include_downstream,
            run_id=args.run_id,
            triggered_by="cli",
            debug=args.debug,
            keep_history=args.keep_history,
        )
    except DagExecutionError as e:
        print_outputs(e.result, only_ran=selected)
        raise SystemExit(1)
    except (LocalRunError, OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(2)
    except KeyboardInterrupt:
        raise SystemExit(130)
    print_outputs(result, only_ran=selected)


def parse_task_ids(values: list[str] | None) -> list[str | tuple[str, int]] | None:
    """Read ``--task`` values; ``TASK_ID[i]`` selects one map index."""
    if not values:
        return None
    return [
        (match["task_id"], int(match["map_index"])) if (match := TASK_MARKER.fullmatch(value)) else value
        for value in values
    ]


def print_outputs(result: DagRunResult, *, only_ran: bool = False) -> None:
    """Print the run's outputs; with ``only_ran``, those of the task instances this command ran."""
    keys = sorted(
        key
        for key in {*result.outputs, *result.output_errors}
        if not only_ran or (key[0], key[1]) in result.ran
    )
    if keys:
        print("Outputs:")
    for task_id, map_index, key in keys[:MAX_PRINTED_OUTPUTS]:
        label = task_id if map_index < 0 else f"{task_id}[{map_index}]"
        if key != "return_value":
            label += f" {key}"
        if (error := result.output_errors.get((task_id, map_index, key))) is not None:
            print(f"  {label}: not loaded ({error})")
        else:
            print(f"  {label} = {_output_repr.repr(result.outputs[task_id, map_index, key])}")
    if len(keys) > MAX_PRINTED_OUTPUTS:
        print(f"  ... {len(keys) - MAX_PRINTED_OUTPUTS} more outputs")
