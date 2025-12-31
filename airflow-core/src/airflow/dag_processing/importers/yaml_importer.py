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
"""YAML DAG importer - imports DAGs from YAML files."""

from __future__ import annotations

import importlib
import logging
import os
import re
from difflib import get_close_matches
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError

from airflow import settings
from airflow._shared.timezones import timezone
from airflow.dag_processing.importers.base import (
    AbstractDagImporter,
    DagImportError,
    DagImportResult,
    DagImportWarning,
)
from airflow.dag_processing.importers.yaml_schema import (
    YamlDagDefinition,
    YamlDagFile,
    YamlTaskDefinition,
    YamlTaskGroupDefinition,
)

if TYPE_CHECKING:
    from airflow.sdk import DAG

log = logging.getLogger(__name__)


# Registry of known operators for suggestions
KNOWN_OPERATORS: list[str] = [
    "airflow.operators.bash.BashOperator",
    "airflow.operators.python.PythonOperator",
    "airflow.operators.empty.EmptyOperator",
    "airflow.operators.trigger_dagrun.TriggerDagRunOperator",
    "airflow.operators.email.EmailOperator",
    "airflow.providers.http.operators.http.HttpOperator",
    "airflow.providers.postgres.operators.postgres.PostgresOperator",
    "airflow.providers.mysql.operators.mysql.MySqlOperator",
    "airflow.providers.amazon.aws.operators.s3.S3CreateBucketOperator",
    "airflow.providers.google.cloud.operators.bigquery.BigQueryInsertJobOperator",
]


def _get_operator_suggestion(classpath: str) -> str | None:
    """Get a suggestion for a mistyped operator classpath."""
    # Extract just the class name
    class_name = classpath.split(".")[-1] if "." in classpath else classpath

    # Check known operators for close matches
    known_class_names = [op.split(".")[-1] for op in KNOWN_OPERATORS]
    matches = get_close_matches(class_name, known_class_names, n=1, cutoff=0.6)

    if matches:
        # Find the full classpath for the match
        for op in KNOWN_OPERATORS:
            if op.endswith(matches[0]):
                return op

    return None


def _format_yaml_error_context(content: str, line: int, context_lines: int = 2) -> str:
    """Format YAML content around the error line for display."""
    lines = content.splitlines()
    start = max(0, line - context_lines - 1)
    end = min(len(lines), line + context_lines)

    result = []
    for i in range(start, end):
        line_num = i + 1
        prefix = "  " if line_num != line else "> "
        result.append(f"{prefix}{line_num:4} | {lines[i]}")

    return "\n".join(result)


def _get_line_for_key(content: str, key: str) -> int | None:
    """Find the line number for a key in YAML content."""
    lines = content.splitlines()
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:")
    for i, line in enumerate(lines):
        if pattern.match(line):
            return i + 1
    return None


class YamlDagImporter(AbstractDagImporter):
    """
    Importer for YAML DAG files.

    This importer handles .yaml and .yml files, parsing them according to
    the YAML DAG schema and creating DAG objects.

    **File Detection:**
    To avoid processing non-DAG YAML files (like config files, metadata),
    the importer uses content-based detection requiring:
    - Single-DAG format: `dag:` key with nested `tasks:` key
    - Multi-DAG format: `tasks:` key under each DAG ID key

    Files matching common config patterns are automatically skipped:
    - pyproject.toml, setup.cfg, requirements.txt, etc.
    - Files in directories named: .git, __pycache__, node_modules, etc.
    - Files with names like: cosmos.yml, dbt_project.yml, profiles.yml

    Features:
    - Full operator classpath support
    - Importable function references for PythonOperator
    - Inline code support for PythonOperator (with security considerations)
    - Detailed error messages with line numbers
    - Operator classpath suggestions for typos
    """

    # Known non-DAG YAML file patterns (case-insensitive)
    IGNORED_FILENAMES: set[str] = {
        "cosmos.yml",
        "cosmos.yaml",
        "dbt_project.yml",
        "dbt_project.yaml",
        "profiles.yml",
        "profiles.yaml",
        "schema.yml",
        "schema.yaml",
        "sources.yml",
        "sources.yaml",
        ".pre-commit-config.yaml",
        "docker-compose.yml",
        "docker-compose.yaml",
        "mkdocs.yml",
        "mkdocs.yaml",
        "codecov.yml",
        "codecov.yaml",
        ".readthedocs.yml",
        ".readthedocs.yaml",
    }

    # Directories to ignore
    IGNORED_DIRECTORIES: set[str] = {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "dbt_packages",
        "target",  # dbt target directory
    }

    @classmethod
    def supported_extensions(cls) -> list[str]:
        """Return supported file extensions."""
        return [".yaml", ".yml"]

    def _should_skip_file(self, filepath: str) -> bool:
        """
        Check if a file should be skipped based on its name or location.

        This helps avoid processing known non-DAG YAML files like:
        - dbt project files (dbt_project.yml, profiles.yml)
        - CI/CD configs (docker-compose.yml, .pre-commit-config.yaml)
        - Documentation configs (mkdocs.yml, .readthedocs.yaml)
        """
        path = Path(filepath)

        # Check filename against known non-DAG patterns
        if path.name.lower() in self.IGNORED_FILENAMES:
            log.debug("Skipping known non-DAG file: %s", filepath)
            return True

        # Check if file is in an ignored directory
        for part in path.parts:
            if part.lower() in self.IGNORED_DIRECTORIES:
                log.debug("Skipping file in ignored directory: %s", filepath)
                return True

        return False

    def import_file(
        self,
        file_path: str | Path,
        *,
        bundle_path: Path | None = None,
        bundle_name: str | None = None,
        safe_mode: bool = True,
    ) -> DagImportResult:
        """
        Import DAGs from a YAML file.

        :param file_path: Path to the YAML file to import.
        :param bundle_path: Path to the bundle root.
        :param bundle_name: Name of the bundle.
        :param safe_mode: If True, check if file might contain DAG (for YAML, checks for 'dag:' key).
        :return: DagImportResult with imported DAGs and any errors.
        """
        filepath = str(file_path)
        relative_path = self.get_relative_path(filepath, bundle_path)
        result = DagImportResult(file_path=relative_path)

        # Skip known non-DAG files before doing any processing
        if self._should_skip_file(filepath):
            return result

        if not os.path.isfile(filepath):
            result.errors.append(
                DagImportError(
                    file_path=relative_path,
                    message=f"File not found: {filepath}",
                    error_type="file_not_found",
                )
            )
            return result

        # Read file content
        try:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            result.errors.append(
                DagImportError(
                    file_path=relative_path,
                    message=f"Failed to read file: {e}",
                    error_type="io",
                )
            )
            return result

        # Safe mode: check if file appears to contain DAG definitions
        # For single-DAG format, look for 'dag:' key
        # For multi-DAG format, look for 'tasks:' key (every DAG must have tasks)
        if safe_mode and "dag:" not in content and "tasks:" not in content:
            log.debug("File %s does not appear to contain a DAG definition. Skipping.", filepath)
            return result

        # Parse YAML
        try:
            yaml_content = yaml.safe_load(content)
        except yaml.YAMLError as e:
            line = getattr(e, "problem_mark", None)
            line_num = line.line + 1 if line else None
            col_num = line.column + 1 if line else None

            context = _format_yaml_error_context(content, line_num) if line_num else None

            result.errors.append(
                DagImportError(
                    file_path=relative_path,
                    message=f"YAML syntax error: {e}",
                    error_type="syntax",
                    line_number=line_num,
                    column_number=col_num,
                    context=context,
                )
            )
            return result

        if yaml_content is None:
            result.warnings.append(
                DagImportWarning(
                    file_path=relative_path,
                    message="File is empty",
                    warning_type="empty_file",
                )
            )
            return result

        # Validate against schema
        try:
            yaml_dag_file = YamlDagFile.from_yaml_content(yaml_content)
        except ValidationError as e:
            for error in e.errors():
                loc = ".".join(str(x) for x in error["loc"])
                msg = error["msg"]
                line_num = _get_line_for_key(content, str(error["loc"][-1])) if error["loc"] else None

                result.errors.append(
                    DagImportError(
                        file_path=relative_path,
                        message=f"Schema validation error at '{loc}': {msg}",
                        error_type="schema",
                        line_number=line_num,
                        context=_format_yaml_error_context(content, line_num) if line_num else None,
                    )
                )
            return result
        except ValueError as e:
            result.errors.append(
                DagImportError(
                    file_path=relative_path,
                    message=str(e),
                    error_type="schema",
                )
            )
            return result

        # Build DAG objects (supports multiple DAGs per file)
        for dag_def in yaml_dag_file.dags:
            try:
                dag = self._build_dag(dag_def, filepath, bundle_path, content, result)
                if dag and not result.errors:
                    result.dags.append(dag)
            except Exception as e:
                log.exception("Failed to build DAG '%s' from %s", dag_def.dag_id, filepath)
                result.errors.append(
                    DagImportError(
                        file_path=relative_path,
                        message=f"Failed to build DAG '{dag_def.dag_id}': {e}",
                        error_type="build",
                    )
                )

        return result

    def _build_dag(
        self,
        dag_def: YamlDagDefinition,
        filepath: str,
        bundle_path: Path | None,
        content: str,
        result: DagImportResult,
    ) -> DAG | None:
        """Build a DAG object from a validated YAML definition."""
        from airflow.sdk import DAG, TaskGroup

        # Convert default_args to dict
        default_args = dag_def.default_args.to_dict() if hasattr(dag_def.default_args, "to_dict") else {}

        # Create DAG - only pass non-None optional parameters
        dag_kwargs: dict[str, Any] = {
            "dag_id": dag_def.dag_id,
            "catchup": dag_def.catchup,
            "tags": dag_def.tags,
            "max_active_tasks": dag_def.max_active_tasks,
            "max_active_runs": dag_def.max_active_runs,
            "default_args": default_args,
            "owner_links": dag_def.owner_links,
            "render_template_as_native_obj": dag_def.render_template_as_native_obj,
        }
        if dag_def.description is not None:
            dag_kwargs["description"] = dag_def.description
        if dag_def.schedule is not None:
            dag_kwargs["schedule"] = dag_def.schedule
        if dag_def.start_date is not None:
            dag_kwargs["start_date"] = dag_def.start_date
        if dag_def.end_date is not None:
            dag_kwargs["end_date"] = dag_def.end_date
        if dag_def.dag_display_name is not None:
            dag_kwargs["dag_display_name"] = dag_def.dag_display_name
        if dag_def.template_searchpath is not None:
            dag_kwargs["template_searchpath"] = dag_def.template_searchpath

        # DAG-level callbacks
        if dag_def.on_success_callback:
            callback = self._import_callback(dag_def.on_success_callback, content, result)
            if callback:
                dag_kwargs["on_success_callback"] = callback
        if dag_def.on_failure_callback:
            callback = self._import_callback(dag_def.on_failure_callback, content, result)
            if callback:
                dag_kwargs["on_failure_callback"] = callback

        dag = DAG(**dag_kwargs)

        dag.fileloc = filepath
        dag.relative_fileloc = self.get_relative_path(filepath, bundle_path)
        dag.last_loaded = timezone.utcnow()

        # Create task groups
        task_groups: dict[str, TaskGroup] = {}
        with dag:
            task_groups = self._create_task_groups(dag_def.task_groups, content, result)

        # Create tasks
        tasks: dict[str, Any] = {}
        with dag:
            for task_def in dag_def.tasks:
                # Get the task group if specified
                tg = task_groups.get(task_def.task_group) if task_def.task_group else None

                # Create task within the appropriate context
                if tg:
                    with tg:
                        task = self._create_task(task_def, dag, content, result)
                else:
                    task = self._create_task(task_def, dag, content, result)

                if task:
                    tasks[task_def.task_id] = task

        # If we had errors creating tasks, return None
        if result.errors:
            return None

        # Set up dependencies
        for task_def in dag_def.tasks:
            if task_def.task_id in tasks:
                task = tasks[task_def.task_id]
                for dep_id in task_def.depends_on:
                    if dep_id in tasks:
                        tasks[dep_id] >> task

        # Validate and finalize DAG
        try:
            dag.validate()
            dag.check_cycle()
            dag.resolve_template_files()

            settings.dag_policy(dag)
            for task in dag.tasks:
                settings.task_policy(task)

        except Exception as e:
            result.errors.append(
                DagImportError(
                    file_path=result.file_path,
                    message=f"DAG validation failed: {e}",
                    error_type="validation",
                )
            )
            return None

        return dag

    def _create_task_groups(
        self,
        group_defs: list[YamlTaskGroupDefinition],
        content: str,
        result: DagImportResult,
    ) -> dict[str, Any]:
        """Create task groups from definitions, supporting arbitrary nesting depth."""
        from contextlib import nullcontext

        from airflow.sdk import TaskGroup

        groups: dict[str, TaskGroup] = {}

        # Build groups iteratively - each pass creates groups whose parents already exist
        # This handles arbitrary nesting depth (A -> B -> C -> ...)
        pending = list(group_defs)
        max_iterations = len(pending) + 1  # Prevent infinite loops on circular refs

        for _ in range(max_iterations):
            if not pending:
                break

            remaining = []
            for group_def in pending:
                # Can we create this group now?
                can_create = group_def.parent_group is None or group_def.parent_group in groups

                if can_create:
                    tg_kwargs: dict[str, Any] = {
                        "group_id": group_def.group_id,
                        "prefix_group_id": group_def.prefix_group_id,
                    }
                    if group_def.tooltip:
                        tg_kwargs["tooltip"] = group_def.tooltip
                    if group_def.ui_color:
                        tg_kwargs["ui_color"] = group_def.ui_color
                    if group_def.ui_fgcolor:
                        tg_kwargs["ui_fgcolor"] = group_def.ui_fgcolor

                    # Create within parent context if nested
                    parent = groups.get(group_def.parent_group) if group_def.parent_group else None
                    ctx = parent if parent else nullcontext()
                    with ctx:
                        groups[group_def.group_id] = TaskGroup(**tg_kwargs)
                else:
                    remaining.append(group_def)

            # If no progress was made, we have an unresolvable dependency
            if len(remaining) == len(pending):
                for group_def in remaining:
                    result.warnings.append(
                        DagImportWarning(
                            file_path=result.file_path,
                            message=f"Task group '{group_def.group_id}' has unresolved parent '{group_def.parent_group}'",
                            warning_type="task_group",
                        )
                    )
                break

            pending = remaining

        return groups

    def _import_callback(
        self,
        callback_ref: str,
        content: str,
        result: DagImportResult,
    ) -> Any | None:
        """Import a callback function from a module.function reference."""
        try:
            module_path, func_name = callback_ref.rsplit(".", 1)
            module = importlib.import_module(module_path)
            return getattr(module, func_name)
        except (ValueError, ModuleNotFoundError, AttributeError) as e:
            line_num = _get_line_for_key(content, "callback")
            result.warnings.append(
                DagImportWarning(
                    file_path=result.file_path,
                    message=f"Failed to import callback '{callback_ref}': {e}",
                    warning_type="callback_import",
                    line_number=line_num,
                )
            )
            return None

    def _create_task(
        self,
        task_def: YamlTaskDefinition,
        dag: DAG,
        content: str,
        result: DagImportResult,
    ) -> Any | None:
        """Create a task instance from a task definition."""
        # Import the operator class
        operator_class = self._import_operator(task_def.operator, content, result)
        if operator_class is None:
            return None

        # Prepare parameters
        params = dict(task_def.params)

        # Handle special cases for PythonOperator
        if task_def.operator.endswith("PythonOperator"):
            prepared_params = self._prepare_python_operator_params(params, content, result)
            if prepared_params is None:
                return None
            params = prepared_params

        # Handle trigger_rule
        if task_def.trigger_rule != "all_success":
            params["trigger_rule"] = task_def.trigger_rule

        # Handle task-level callbacks
        if task_def.on_success_callback:
            callback = self._import_callback(task_def.on_success_callback, content, result)
            if callback:
                params["on_success_callback"] = callback
        if task_def.on_failure_callback:
            callback = self._import_callback(task_def.on_failure_callback, content, result)
            if callback:
                params["on_failure_callback"] = callback
        if task_def.on_retry_callback:
            callback = self._import_callback(task_def.on_retry_callback, content, result)
            if callback:
                params["on_retry_callback"] = callback
        if task_def.on_execute_callback:
            callback = self._import_callback(task_def.on_execute_callback, content, result)
            if callback:
                params["on_execute_callback"] = callback

        # Create the task
        try:
            task = operator_class(
                task_id=task_def.task_id,
                dag=dag,
                **params,
            )

            # Handle dynamic task mapping (expand)
            if task_def.expand:
                # expand: {param_name: [list of values]}
                task = task.expand(**task_def.expand)
            elif task_def.expand_kwargs:
                # expand_kwargs: [{param1: val1, param2: val2}, ...]
                task = task.expand_kwargs(task_def.expand_kwargs)

            return task
        except Exception as e:
            line_num = _get_line_for_key(content, task_def.task_id)
            result.errors.append(
                DagImportError(
                    file_path=result.file_path,
                    message=f"Failed to create task '{task_def.task_id}': {e}",
                    error_type="task_creation",
                    line_number=line_num,
                    context=_format_yaml_error_context(content, line_num) if line_num else None,
                )
            )
            return None

    def _import_operator(
        self,
        classpath: str,
        content: str,
        result: DagImportResult,
    ) -> type | None:
        """Import an operator class from its classpath."""
        try:
            module_path, class_name = classpath.rsplit(".", 1)
            module = importlib.import_module(module_path)
            operator_class = getattr(module, class_name)
            return operator_class
        except ModuleNotFoundError as e:
            suggestion = _get_operator_suggestion(classpath)
            line_num = _get_line_for_key(content, "operator")

            result.errors.append(
                DagImportError(
                    file_path=result.file_path,
                    message=f"Module not found for operator '{classpath}': {e}",
                    error_type="reference",
                    line_number=line_num,
                    suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
                    context=_format_yaml_error_context(content, line_num) if line_num else None,
                )
            )
            return None
        except AttributeError:
            suggestion = _get_operator_suggestion(classpath)
            line_num = _get_line_for_key(content, "operator")

            result.errors.append(
                DagImportError(
                    file_path=result.file_path,
                    message=f"Class not found in module for operator '{classpath}'",
                    error_type="reference",
                    line_number=line_num,
                    suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
                    context=_format_yaml_error_context(content, line_num) if line_num else None,
                )
            )
            return None

    def _prepare_python_operator_params(
        self,
        params: dict[str, Any],
        content: str,
        result: DagImportResult,
    ) -> dict[str, Any] | None:
        """Prepare parameters for PythonOperator, handling callable references."""
        if "python_callable" not in params:
            result.errors.append(
                DagImportError(
                    file_path=result.file_path,
                    message="PythonOperator requires 'python_callable' parameter",
                    error_type="schema",
                )
            )
            return None

        callable_ref = params["python_callable"]

        # Check if it's inline code (starts with 'lambda' or 'def')
        if isinstance(callable_ref, str):
            if callable_ref.strip().startswith(("lambda", "def ")):
                # Inline code - compile and execute
                try:
                    # For lambda expressions
                    if callable_ref.strip().startswith("lambda"):
                        params["python_callable"] = eval(callable_ref)
                    else:
                        # For def statements, compile and extract function
                        local_ns: dict[str, Any] = {}
                        exec(callable_ref, {}, local_ns)
                        # Get the first function defined
                        for obj in local_ns.values():
                            if callable(obj):
                                params["python_callable"] = obj
                                break
                        else:
                            raise ValueError("No callable found in inline code")
                except Exception as e:
                    result.errors.append(
                        DagImportError(
                            file_path=result.file_path,
                            message=f"Failed to compile inline python_callable: {e}",
                            error_type="syntax",
                        )
                    )
                    return None
            else:
                # It's a module.function reference
                try:
                    module_path, func_name = callable_ref.rsplit(".", 1)
                    module = importlib.import_module(module_path)
                    func = getattr(module, func_name)
                    params["python_callable"] = func
                except (ValueError, ModuleNotFoundError, AttributeError) as e:
                    line_num = _get_line_for_key(content, "python_callable")
                    result.errors.append(
                        DagImportError(
                            file_path=result.file_path,
                            message=f"Failed to import python_callable '{callable_ref}': {e}",
                            error_type="reference",
                            line_number=line_num,
                            suggestion="Use format 'module.submodule.function_name'",
                        )
                    )
                    return None

        return params
