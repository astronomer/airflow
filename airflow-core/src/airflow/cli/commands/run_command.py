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

from airflow.local_run.exit_codes import (
    EXIT_CONFIG,
    EXIT_DAG_FILE,
    EXIT_FAILED,
    EXIT_INTERRUPTED,
    EXIT_USAGE,
    exit_with_error,
)
from airflow.sdk.definitions._internal.local_run_args import (  # noqa: SDK001
    check_run_options,
    options_from_args,
)
from airflow.sdk.definitions.local_run import DagRunResult, run_dag_file
from airflow.sdk.exceptions import (
    DagExecutionError,
    LocalRunConfigError,
    LocalRunDagFileError,
    LocalRunError,
    LocalRunUsageError,
)

MAX_PRINTED_OUTPUTS = 10


def run(args) -> None:
    """
    Run one Dag from ``args.file`` and print its outputs; the run itself reports progress and outcome.

    Not wrapped in ``action_cli``: that would log the command to the ambient database, not the project's.
    """
    try:
        options = options_from_args(args)
        check_run_options(options)
    except LocalRunUsageError as e:
        exit_with_error(str(e), EXIT_USAGE)
    selected = bool(options["task_ids"] or options["task_group_ids"])
    try:
        result = run_dag_file(args.file, dag_id=args.dag_id, triggered_by="cli", **options)
    except DagExecutionError as e:
        print_outputs(e.result, only_ran=selected)
        raise SystemExit(EXIT_FAILED)
    except KeyboardInterrupt:
        raise SystemExit(EXIT_INTERRUPTED)
    # LocalRunUsageError is a ValueError too.
    except ValueError as e:
        exit_with_error(str(e), EXIT_USAGE)
    except LocalRunDagFileError as e:
        exit_with_error(str(e), EXIT_DAG_FILE)
    except (LocalRunConfigError, OSError) as e:
        exit_with_error(str(e), EXIT_CONFIG)
    # Nothing the user can fix: the run's process ended without reporting how the run went, or could not create
    # a unique run.
    except LocalRunError as e:
        exit_with_error(str(e), EXIT_FAILED)
    print_outputs(result, only_ran=selected)


def print_outputs(result: DagRunResult, *, only_ran: bool = False) -> None:
    """
    Print what the run's tasks returned; with ``only_ran``, what the task instances this command ran returned.

    The other XComs that tasks push, such as an agent's usage, stay in the result. Each output is shown as the
    run's process showed it: this process has not imported the Dag file, so it cannot load the file's classes.
    """
    keys = sorted(
        (task_id, map_index)
        for task_id, map_index, key in {*result.output_reprs, *result.output_errors}
        if key == "return_value" and (not only_ran or (task_id, map_index) in result.ran)
    )
    if keys:
        print("Outputs:")
    for task_id, map_index in keys[:MAX_PRINTED_OUTPUTS]:
        label = task_id if map_index < 0 else f"{task_id}[{map_index}]"
        output = (task_id, map_index, "return_value")
        if output in result.output_reprs:
            print(f"  {label} = {result.output_reprs[output]}")
        else:
            print(f"  {label}: not loaded ({result.output_errors[output]})")
    if len(keys) > MAX_PRINTED_OUTPUTS:
        print(f"  ... {len(keys) - MAX_PRINTED_OUTPUTS} more outputs")
