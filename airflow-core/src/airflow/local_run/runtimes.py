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
The runtimes other than Python that a local run uses, such as Node for TypeScript.

The project configures them in ``[tool.airflow.sdk]``. A native Dag file, such as a packed TypeScript
bundle, is parsed by its runtime, as the Dag processor has it parse the files of a Dag bundle. Both a run
with a database and one without go through here, so the checks raise the errors the caller of either
reports to the user.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from typing import TYPE_CHECKING, Any, cast

import structlog

from airflow._shared.module_loading import import_string
from airflow.configuration import conf
from airflow.dag_processing.lang_sdk_processor import LangSDKDagFileProcessorProcess
from airflow.local_run import BUNDLE_NAME
from airflow.sdk.coordinators._dag_importer import (  # noqa: SDK001
    COORDINATOR_DAG_IMPORTERS,
    CoordinatorDagImporter,
    find_claiming_importer,
)
from airflow.sdk.exceptions import (  # noqa: SDK001
    LocalRunConfigError,
    LocalRunDagFileError,
    LocalRunUsageError,
)
from airflow.sdk.execution_time.coordinator import get_coordinator_manager  # noqa: SDK001
from airflow.sdk.importers import FilesystemDagDefinition  # noqa: SDK001

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from airflow.dag_processing.processor import DagFileParsingResult
    from airflow.serialization.definitions.baseoperator import SerializedBaseOperator
    from airflow.serialization.definitions.dag import SerializedDAG

# How many task IDs a refusal names for each queue it lists.
_TASKS_NAMED = 3


def check_project_coordinators() -> None:
    """Build the coordinators ``[tool.airflow.sdk]`` configures now, so a mistake in them stops the run."""
    try:
        manager = get_coordinator_manager()
        # get_coordinator_manager has read this setting as a table.
        for key in cast("dict[str, Any]", conf.getjson("sdk", "coordinators", fallback={})):
            manager.get_coordinator(key)
    except ValueError as e:
        # A coordinator that cannot be built says why only in the error it was raised from.
        reason = f"{e}: {e.__context__}" if e.__context__ else str(e)
        raise LocalRunConfigError(f"[tool.airflow.sdk] in pyproject.toml cannot be used: {reason}") from None


def find_native_dag_importer(source: Path, root: Path) -> CoordinatorDagImporter | None:
    """
    Return the coordinator Dag importer that claims ``source``, or ``None`` for a Python Dag file.

    :raises LocalRunConfigError: when the file needs a runtime that the project does not configure.
    :raises LocalRunUsageError: when the file is neither a Python Dag file nor one a runtime parses.
    """
    if source.suffix == ".py":
        return None
    if (importer := find_claiming_importer(source.relative_to(root), BUNDLE_NAME)) is not None:
        return importer
    if (unconfigured := find_unconfigured_importer(source)) is None:
        raise LocalRunUsageError(
            "A local run needs a Python Dag file or a native Dag file, such as a TypeScript bundle packed "
            f"by airflow-ts-pack; {source} is neither"
        )
    if (root / "pyproject.toml").is_file():
        fix = "[tool.airflow.sdk] in pyproject.toml configures none. Add one to its coordinators table"
    else:
        fix = (
            "no pyproject.toml configures one. Create a pyproject.toml at the project's root, and add one to "
            "the coordinators table of its [tool.airflow.sdk]"
        )
    raise LocalRunConfigError(
        f"{source} is a native Dag file that a {get_runtime_name(unconfigured)} runs, and {fix}, with "
        f"classpath = {unconfigured.coordinator_classpath!r}; then route the Dag's queue to it in "
        "queue_to_coordinator."
    )


def find_unconfigured_importer(source: Path) -> CoordinatorDagImporter | None:
    """Return the coordinator Dag importer that would claim ``source`` if its coordinator were configured."""
    definition = FilesystemDagDefinition(path=source)
    for classpath in COORDINATOR_DAG_IMPORTERS:
        importer = import_string(classpath)(bundle_name=BUNDLE_NAME)
        if importer.can_handle(source) and importer.might_contain_dag(definition, safe_mode=True):
            return importer
    return None


def warn_if_built_before_its_sources(source: Path, root: Path, importer: CoordinatorDagImporter) -> None:
    """Warn when ``source`` is older than a file it was built from, whose changes the run would miss."""
    try:
        paths = importer.get_source_paths(FilesystemDagDefinition(path=source))
    except (OSError, ValueError):
        # Parsing the file then says why it cannot be read.
        return
    built = source.stat().st_mtime
    # Relative to where the file was built, which is the project root when built as the docs show.
    changed = [path for path in paths if (root / path).is_file() and (root / path).stat().st_mtime > built]
    if changed:
        print(
            f"Warning: {source.relative_to(root)} is older than {', '.join(changed)}, which it was built "
            "from, so the run does not have the latest changes. Build it again to run them.",
            file=sys.stderr,
            flush=True,
        )


def get_runtime_name(importer: CoordinatorDagImporter) -> str:
    """Return the class name of the coordinator that runs the tasks of ``importer``'s files."""
    return importer.coordinator_classpath.rsplit(".", 1)[-1]


def parse_native_dag_file(source: Path, root: Path) -> DagFileParsingResult:
    """
    Parse ``source`` with its runtime, as the Dag processor does, and return the Dags it declares.

    The parse has no API client, so a request the runtime makes while parsing, such as for a Variable,
    gets an error.

    :raises LocalRunDagFileError: when the file does not parse, or declares no Dags.
    """
    result = LangSDKDagFileProcessorProcess.run(
        path=os.fspath(source),
        bundle_path=root,
        bundle_name=BUNDLE_NAME,
        dag_file_rel_path=source.relative_to(root).as_posix(),
        logger=structlog.get_logger(logger_name=__name__),
    )
    if result.import_errors:
        details = "\n".join(error.rstrip() for error in result.import_errors.values())
        raise LocalRunDagFileError(f"Parsing {source} failed:\n{details}")
    if not result.serialized_dags:
        raise LocalRunDagFileError(
            f"No Dags found in {source}. A bundle that only implements stub tasks runs through the Python "
            "Dag file that declares them."
        )
    return result


def check_native_task_routes(dag: SerializedDAG, importer: CoordinatorDagImporter) -> None:
    """
    Refuse a Dag with a task whose queue does not route to the runtime that parsed it.

    A deployment fails such a task when it starts; a local run says so before any task runs.

    :raises LocalRunConfigError: naming each such queue and some of its tasks.
    """
    runtime = import_string(importer.coordinator_classpath)
    manager = get_coordinator_manager()
    misrouted: dict[str, list[str]] = defaultdict(list)
    # check_project_coordinators built every coordinator a queue can route to.
    for task in dag.tasks:
        if not isinstance(manager.for_queue(task.queue), runtime):
            misrouted[task.queue].append(task.task_id)
    if not misrouted:
        return
    queues = "; ".join(
        f"queue {queue!r} of {', '.join(repr(task_id) for task_id in task_ids[:_TASKS_NAMED])}"
        + (f" and {len(task_ids) - _TASKS_NAMED} more" if len(task_ids) > _TASKS_NAMED else "")
        for queue, task_ids in sorted(misrouted.items())
    )
    raise LocalRunConfigError(
        f"Dag {dag.dag_id!r} runs on a {runtime.__name__}, but these tasks' queues route elsewhere: "
        f"{queues}. Map each queue to your {runtime.__name__} in queue_to_coordinator of [tool.airflow.sdk] "
        "in pyproject.toml."
    )


def iter_bound_outputs(task: SerializedBaseOperator) -> Iterator[str]:
    """Yield the ID of each task whose return value ``task``, of a native Dag, takes as an argument."""
    for binding in task.arg_bindings or ():
        if binding["kind"] == "xcom":
            yield binding["task_id"]
