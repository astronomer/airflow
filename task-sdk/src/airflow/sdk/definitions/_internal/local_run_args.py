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
"""The options of a local Dag run, as ``airflow run`` and a Dag file run as a script take them."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from airflow.sdk.exceptions import LocalRunUsageError

# How the run labels one map index of a task, e.g. double[1].
TASK_MARKER = re.compile(r"(?P<task_id>.+)\[(?P<map_index>\d+)\]")

# The options airflow run takes after the file, but --dag-id. airflow-core defines its own copies, so that
# every CLI command does not import the Task SDK; a test there keeps them the same as these.
CONF_ARGUMENT: tuple[tuple[str, ...], dict[str, Any]] = (
    ("-c", "--conf"),
    {"help": "JSON string that gets pickled into the DagRun's conf attribute"},
)

# Each as (flags, argparse keyword arguments).
RUN_ARGUMENTS: tuple[tuple[tuple[str, ...], dict[str, Any]], ...] = (
    (("--connections-file",), {"help": "Connections file (JSON, YAML or env) available to the run"}),
    (("--variables-file",), {"help": "Variables file (JSON, YAML or env) available to the run"}),
    (
        ("--task",),
        {
            "dest": "task_ids",
            "action": "append",
            "metavar": "TASK_ID",
            "help": (
                "Rerun this task, as Clear does in the UI, in the latest run that has the outputs of its "
                "upstream tasks; with --conf, or when no run has them, run it and the tasks it needs in a new "
                "run. TASK_ID[i] reruns one map index. Repeatable"
            ),
        },
    ),
    (
        ("--group",),
        {
            "dest": "task_group_ids",
            "action": "append",
            "metavar": "GROUP_ID",
            "help": "Rerun every task in this task group. Repeatable",
        },
    ),
    (
        ("--upstream",),
        {
            "dest": "include_upstream",
            "action": "store_true",
            "help": "Also rerun the upstream tasks of the selected ones",
        },
    ),
    (
        ("--downstream",),
        {
            "dest": "include_downstream",
            "action": "store_true",
            "help": "Also rerun the downstream tasks of the selected ones",
        },
    ),
    (
        ("--run-id",),
        {"help": "Rerun the selected tasks in this run instead of the latest one that has their inputs"},
    ),
    (
        ("--input",),
        {
            "dest": "inputs",
            "action": "append",
            "metavar": "TASK_ID=JSON",
            "help": (
                "Run the selected tasks alone in a new run, with JSON as what TASK_ID returned, a task directly "
                "upstream of them that then does not run; for a mapped task, the list of what each map index "
                "returned. Needed for each task whose output they read. Repeatable"
            ),
        },
    ),
    (
        ("--keep-task-state",),
        {
            "action": "store_true",
            "help": (
                "Keep what the rerun tasks stored in their task state in the earlier run, so they resume from "
                "it, as Clear's 'Keep task state and resume' does; otherwise they start with none"
            ),
        },
    ),
    (
        ("--debug",),
        {
            "action": "store_true",
            "help": (
                "Run every task try inside the run's process instead of a process of its own, so that a "
                "terminal debugger such as pdb reads the terminal at breakpoint(); an IDE's debugger needs no "
                "flag"
            ),
        },
    ),
    (
        ("--no-history",),
        {
            "dest": "keep_history",
            "action": "store_false",
            "help": (
                "Run against a database of the run's own, deleted when it ends, instead of the project's "
                "history; selected tasks run in a new run with the tasks they need"
            ),
        },
    ),
    (
        ("--no-retries",),
        {
            "dest": "retries",
            "action": "store_false",
            "help": "Give each task one attempt, whatever its retries say",
        },
    ),
    (
        ("--no-db",),
        {
            "action": "store_true",
            "help": (
                "Run exactly one --task once without a metadata database; supply upstream outputs with --input"
            ),
        },
    ),
    (
        ("--state-file",),
        {"help": "With --no-db, save task state to this JSON file; --keep-task-state explicitly reuses it"},
    ),
)

# The options as run_dag_file() takes them, with its defaults: an option at its default is not given.
RUN_OPTION_DEFAULTS: dict[str, Any] = {
    "run_conf": None,
    "connections_file": None,
    "variables_file": None,
    "task_ids": None,
    "task_group_ids": None,
    "include_upstream": False,
    "include_downstream": False,
    "run_id": None,
    "inputs": None,
    "keep_task_state": False,
    "debug": False,
    "keep_history": True,
    "retries": True,
    "no_db": False,
    "state_file": None,
}

# How the command line names each option, and how DAG.run() does where its keyword differs from run_dag_file()'s.
RUN_OPTION_FLAGS = {
    "run_conf": "--conf",
    "connections_file": "--connections-file",
    "variables_file": "--variables-file",
    "task_ids": "--task",
    "task_group_ids": "--group",
    "include_upstream": "--upstream",
    "include_downstream": "--downstream",
    "run_id": "--run-id",
    "inputs": "--input",
    "keep_task_state": "--keep-task-state",
    "debug": "--debug",
    "keep_history": "--no-history",
    "retries": "--no-retries",
    "no_db": "--no-db",
    "state_file": "--state-file",
}
RUN_KEYWORDS = {"connections_file": "conn_file_path", "variables_file": "variable_file_path"}

_PATH_OPTIONS = ("connections_file", "variables_file", "state_file")


def build_run_parser(prog: str) -> argparse.ArgumentParser:
    """Return a parser for the options of a Dag file run as a script: those ``airflow run`` takes after the file."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Run this file's Dag in the project's local Airflow environment. The options are those of airflow "
            "run, and of the Dag's run() call."
        ),
    )
    for flags, kwargs in (CONF_ARGUMENT, *RUN_ARGUMENTS):
        parser.add_argument(*flags, **kwargs)
    return parser


def options_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Return the run_dag_file() options that parsed command-line arguments give, refusing malformed values."""
    return {
        "run_conf": parse_conf(args.conf),
        "connections_file": args.connections_file,
        "variables_file": args.variables_file,
        "task_ids": parse_task_ids(args.task_ids),
        "task_group_ids": args.task_group_ids,
        "include_upstream": args.include_upstream,
        "include_downstream": args.include_downstream,
        "run_id": args.run_id,
        "inputs": parse_inputs(args.inputs),
        "keep_task_state": args.keep_task_state,
        "debug": args.debug,
        "keep_history": args.keep_history,
        "retries": args.retries,
        "no_db": args.no_db,
        "state_file": args.state_file,
    }


def check_run_options(options: Mapping[str, Any]) -> None:
    """Refuse options that do not go together, naming them as the command line does."""
    selected = bool(options["task_ids"] or options["task_group_ids"])
    if not selected and (
        options["include_upstream"]
        or options["include_downstream"]
        or options["run_id"]
        or options["inputs"]
        or options["keep_task_state"]
    ):
        raise LocalRunUsageError(
            "--upstream, --downstream, --run-id, --input and --keep-task-state apply to the tasks chosen with "
            "--task or --group"
        )
    if options["run_id"] and not options["keep_history"]:
        raise LocalRunUsageError(
            "--run-id names a run in the project's history, which --no-history does not use"
        )
    if options["inputs"] and options["run_id"]:
        raise LocalRunUsageError("--input runs the selected tasks in a new run, so it does not take --run-id")
    if options["inputs"] and options["include_upstream"]:
        raise LocalRunUsageError(
            "--input stands in for the upstream tasks' outputs, so it does not take --upstream"
        )
    for flag, new_run in (
        ("--no-history", not options["keep_history"]),
        ("--conf", options["run_conf"] is not None),
        ("--input", options["inputs"]),
    ):
        if options["keep_task_state"] and new_run and not options["no_db"]:
            raise LocalRunUsageError(
                f"{flag} runs the selected tasks in a new run, which has no task state to keep, so it does not "
                "take --keep-task-state"
            )


def parse_conf(value: str | None) -> dict[str, Any] | None:
    """Read ``--conf``, a JSON object."""
    if not value:
        return None
    try:
        conf = json.loads(value)
    except json.JSONDecodeError as e:
        raise LocalRunUsageError(f"--conf is not valid JSON: {e.msg}") from None
    if not isinstance(conf, dict):
        raise LocalRunUsageError("--conf must be a JSON object")
    return conf


def parse_task_ids(values: list[str] | None) -> list[str | tuple[str, int]] | None:
    """Read ``--task`` values; ``TASK_ID[i]`` selects one map index."""
    if not values:
        return None
    return [
        (match["task_id"], int(match["map_index"])) if (match := TASK_MARKER.fullmatch(value)) else value
        for value in values
    ]


def parse_inputs(values: list[str] | None) -> dict[str, Any] | None:
    """Read ``--input`` values, each ``TASK_ID=JSON``."""
    if not values:
        return None
    inputs: dict[str, Any] = {}
    for value in values:
        task_id, separator, data = value.partition("=")
        if not separator or not task_id:
            raise LocalRunUsageError(f"--input takes TASK_ID=JSON, not {value!r}")
        if task_id in inputs:
            raise LocalRunUsageError(f"--input gives {task_id} more than once")
        try:
            inputs[task_id] = json.loads(data)
        except json.JSONDecodeError as e:
            raise LocalRunUsageError(f"--input {task_id} is not valid JSON: {e.msg}") from None
    return inputs


def read_script_options(dag_file: str) -> dict[str, Any]:
    """
    Return the options given on the command line when ``dag_file`` is the script being run, and none otherwise.

    So a test, an import or a notebook that calls the Dag's run() is not affected by its own process's arguments.
    """
    if not sys.argv or Path(sys.argv[0]).resolve() != Path(dag_file).resolve():
        return {}
    args = build_run_parser(prog=Path(sys.argv[0]).name).parse_args(sys.argv[1:])
    return {
        name: value for name, value in options_from_args(args).items() if value != RUN_OPTION_DEFAULTS[name]
    }


def merge_run_options(given: Mapping[str, Any], command_line: Mapping[str, Any]) -> dict[str, Any]:
    """
    Return the run_dag_file() options from DAG.run()'s keyword arguments and the script's command line.

    Each option may come from either; one given both ways must have the same value. ``given`` holds the keyword
    arguments that differ from their defaults.
    """
    conflicts = [
        f"{RUN_OPTION_FLAGS[name]} on the command line gives {command_line[name]!r}, but run() gives "
        f"{RUN_KEYWORDS.get(name, name)}={given[name]!r}"
        for name in RUN_OPTION_DEFAULTS
        if name in given
        and name in command_line
        and _normalize(name, given[name]) != _normalize(name, command_line[name])
    ]
    if conflicts:
        raise LocalRunUsageError("; ".join(conflicts) + ". Give each in one place.")
    options = {**RUN_OPTION_DEFAULTS, **given, **command_line}
    if command_line:
        check_run_options(options)
    return options


def _normalize(name: str, value: Any) -> Any:
    if name in _PATH_OPTIONS:
        return Path(value).resolve()
    if name in ("task_ids", "task_group_ids"):
        return [tuple(item) if isinstance(item, list) else item for item in value]
    return value
