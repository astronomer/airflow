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
YAML DAG Schema Definition.

This module defines the Pydantic models for validating YAML DAG files.
The schema supports defining DAGs declaratively without Python code.

Unlike dag-factory, this is native to Airflow - no Python loader file required!
Just drop a YAML file in your dags folder and it will be parsed automatically.

Features over dag-factory:
- No Python loader file required
- Native to Airflow (part of the dag-processor)
- Better error messages with line numbers and suggestions
- Integrated with the importer abstraction for extensibility

Example YAML DAG file - Single DAG:
-----------------------------------

.. code-block:: yaml

    dag:
      dag_id: my_etl_pipeline
      description: Daily ETL pipeline
      schedule: "0 5 * * *"
      start_date: "2024-01-01"
      catchup: false
      tags: [etl, daily]

      default_args:
        owner: data-team
        retries: 2
        retry_delay: 300

      tasks:
        - task_id: extract
          operator: airflow.providers.postgres.operators.postgres.PostgresOperator
          params:
            postgres_conn_id: source_db
            sql: "SELECT * FROM source_table"

        - task_id: transform
          operator: airflow.providers.standard.operators.python.PythonOperator
          params:
            python_callable: my_module.transform_func
          depends_on: [extract]

        - task_id: load
          operator: airflow.providers.postgres.operators.postgres.PostgresOperator
          params:
            postgres_conn_id: dest_db
            sql: "INSERT INTO dest_table SELECT * FROM staging"
          depends_on: [transform]

Example YAML DAG file - Multiple DAGs:
--------------------------------------

.. code-block:: yaml

    # Optional defaults applied to all DAGs in this file
    default:
      default_args:
        owner: data-team
        retries: 2

    # First DAG
    my_first_dag:
      description: First pipeline
      schedule: "@daily"
      tasks:
        - task_id: task_1
          operator: airflow.providers.standard.operators.bash.BashOperator
          bash_command: "echo Hello"

    # Second DAG
    my_second_dag:
      description: Second pipeline
      schedule: "@hourly"
      tasks:
        - task_id: task_1
          operator: airflow.providers.standard.operators.bash.BashOperator
          bash_command: "echo World"

Example with Task Groups:
-------------------------

.. code-block:: yaml

    dag:
      dag_id: pipeline_with_groups
      task_groups:
        - group_id: extract_group
          tooltip: "Data extraction tasks"
        - group_id: transform_group
          tooltip: "Data transformation tasks"
          parent_group: extract_group  # Nested groups supported

      tasks:
        - task_id: extract_users
          operator: airflow.providers.standard.operators.bash.BashOperator
          bash_command: "echo extract users"
          task_group: extract_group

Example with Dynamic Task Mapping:
----------------------------------

.. code-block:: yaml

    dag:
      dag_id: dynamic_pipeline
      tasks:
        - task_id: process_files
          operator: airflow.providers.standard.operators.bash.BashOperator
          bash_command: "process {{ params.file }}"
          expand:
            params:
              - file: file1.csv
              - file: file2.csv
              - file: file3.csv

Example with Callbacks:
-----------------------

.. code-block:: yaml

    dag:
      dag_id: pipeline_with_callbacks
      on_success_callback: my_module.notify_success
      on_failure_callback: my_module.notify_failure

      tasks:
        - task_id: important_task
          operator: airflow.providers.standard.operators.bash.BashOperator
          bash_command: "echo important"
          on_success_callback: my_module.task_success
          on_failure_callback: my_module.task_failure
          on_retry_callback: my_module.task_retry
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class YamlTaskGroupDefinition(BaseModel):
    """
    Definition of a task group in a YAML DAG.

    Task groups provide visual grouping and organization of tasks in the UI.
    """

    group_id: str = Field(..., description="Unique identifier for the task group")
    tooltip: str | None = Field(default=None, description="Tooltip shown in the UI")
    prefix_group_id: bool = Field(default=True, description="Whether to prefix task IDs with group ID")
    parent_group: str | None = Field(default=None, description="Parent task group for nesting")
    ui_color: str | None = Field(default=None, description="Background color in the UI")
    ui_fgcolor: str | None = Field(default=None, description="Foreground color in the UI")


class YamlTaskDefinition(BaseModel):
    """
    Definition of a task in a YAML DAG.

    Attributes:
        task_id: Unique identifier for the task within the DAG.
        operator: Full classpath of the operator to use.
        params: Parameters to pass to the operator constructor.
        depends_on: List of task_ids this task depends on.
        trigger_rule: When to trigger this task (default: all_success).
        task_group: Task group this task belongs to.
        expand: Dynamic task mapping configuration.
        on_success_callback: Callback on task success.
        on_failure_callback: Callback on task failure.
        on_retry_callback: Callback on task retry.
    """

    task_id: str = Field(..., description="Unique identifier for the task")
    operator: str = Field(..., description="Full classpath of the operator class")
    params: dict[str, Any] = Field(default_factory=dict, description="Operator constructor parameters")
    depends_on: list[str] = Field(default_factory=list, description="List of upstream task_ids")
    trigger_rule: str = Field(default="all_success", description="Trigger rule for task execution")
    task_group: str | None = Field(default=None, description="Task group this task belongs to")

    # Dynamic task mapping (expand)
    expand: dict[str, list[Any]] | None = Field(
        default=None, description="Dynamic task mapping - expands task for each item"
    )
    expand_kwargs: list[dict[str, Any]] | None = Field(
        default=None, description="Dynamic task mapping with kwargs - each dict is a set of kwargs"
    )

    # Callbacks (can be module.function string or inline code)
    on_success_callback: str | None = Field(default=None, description="Callback on task success")
    on_failure_callback: str | None = Field(default=None, description="Callback on task failure")
    on_retry_callback: str | None = Field(default=None, description="Callback on task retry")
    on_execute_callback: str | None = Field(default=None, description="Callback before task execution")

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, v: str) -> str:
        """Validate task_id format."""
        if not v or not v.strip():
            raise ValueError("task_id cannot be empty")
        # Allow alphanumeric, underscores, hyphens, and dots
        import re

        if not re.match(r"^[a-zA-Z0-9_.\-]+$", v):
            raise ValueError(
                f"task_id '{v}' contains invalid characters. "
                "Only alphanumeric, underscores, hyphens, and dots are allowed."
            )
        return v

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        """Validate operator classpath format."""
        if not v or not v.strip():
            raise ValueError("operator cannot be empty")
        # Basic classpath validation
        if "." not in v:
            raise ValueError(
                f"operator '{v}' must be a full classpath (e.g., 'airflow.operators.bash.BashOperator')"
            )
        return v


class YamlDefaultArgs(BaseModel):
    """
    Default arguments applied to all tasks in a DAG.

    These correspond to common operator parameters that can be set at the DAG level.
    """

    owner: str | None = Field(default=None, description="Owner of the DAG/tasks")
    retries: int | None = Field(default=None, ge=0, description="Number of retries on failure")
    retry_delay: int | float | None = Field(default=None, description="Delay between retries in seconds")
    email: str | list[str] | None = Field(default=None, description="Email(s) for notifications")
    email_on_failure: bool | None = Field(default=None, description="Send email on task failure")
    email_on_retry: bool | None = Field(default=None, description="Send email on task retry")
    depends_on_past: bool | None = Field(default=None, description="Task depends on previous run")
    pool: str | None = Field(default=None, description="Pool to use for task execution")
    priority_weight: int | None = Field(default=None, description="Priority weight for scheduling")
    queue: str | None = Field(default=None, description="Queue for task execution")
    execution_timeout: int | None = Field(default=None, description="Max execution time in seconds")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for passing to operators."""
        result = {}
        # Use model_dump to get only actual fields, not pydantic internals
        for field_name, value in self.model_dump(exclude_none=True).items():
            if field_name == "retry_delay":
                result[field_name] = timedelta(seconds=value)
            elif field_name == "execution_timeout":
                result[field_name] = timedelta(seconds=value)
            else:
                result[field_name] = value
        return result


class YamlDagDefinition(BaseModel):
    """
    Complete DAG definition from a YAML file.

    This is the root model for parsing YAML DAG files.
    """

    dag_id: str = Field(..., description="Unique identifier for the DAG")
    description: str | None = Field(default=None, description="Human-readable description")
    schedule: str | None = Field(default=None, description="Cron expression or preset (@daily, @hourly)")
    start_date: str | datetime | None = Field(default=None, description="Start date for the DAG")
    end_date: str | datetime | None = Field(default=None, description="End date for the DAG")
    catchup: bool = Field(default=False, description="Whether to catch up on missed runs")
    tags: list[str] = Field(default_factory=list, description="Tags for filtering in the UI")
    max_active_tasks: int = Field(default=16, ge=1, description="Max concurrent task instances")
    max_active_runs: int = Field(default=16, ge=1, description="Max concurrent DAG runs")
    dag_display_name: str | None = Field(default=None, description="Display name in the UI")
    default_args: YamlDefaultArgs | dict[str, Any] = Field(
        default_factory=dict, description="Default arguments for tasks"
    )
    tasks: list[YamlTaskDefinition] = Field(..., description="List of tasks in the DAG")
    owner_links: dict[str, str] = Field(default_factory=dict, description="Owner links for the UI")

    # Task groups
    task_groups: list[YamlTaskGroupDefinition] = Field(
        default_factory=list, description="Task groups for visual organization"
    )

    # DAG-level callbacks
    on_success_callback: str | None = Field(default=None, description="Callback when all tasks succeed")
    on_failure_callback: str | None = Field(default=None, description="Callback when any task fails")

    # Render settings
    render_template_as_native_obj: bool = Field(
        default=False, description="Render templates as native Python objects"
    )
    template_searchpath: str | list[str] | None = Field(
        default=None, description="Paths to search for templates"
    )

    @field_validator("dag_id")
    @classmethod
    def validate_dag_id(cls, v: str) -> str:
        """Validate dag_id format."""
        if not v or not v.strip():
            raise ValueError("dag_id cannot be empty")
        import re

        if not re.match(r"^[a-zA-Z0-9_.\-]+$", v):
            raise ValueError(
                f"dag_id '{v}' contains invalid characters. "
                "Only alphanumeric, underscores, hyphens, and dots are allowed."
            )
        return v

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def parse_date(cls, v: str | datetime | None) -> datetime | None:
        """Parse date strings into datetime objects."""
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            from dateutil.parser import parse

            try:
                return parse(v)
            except Exception as e:
                raise ValueError(f"Invalid date format: {v}. Error: {e}")
        return v

    @field_validator("default_args", mode="before")
    @classmethod
    def parse_default_args(cls, v: dict[str, Any] | YamlDefaultArgs) -> YamlDefaultArgs:
        """Parse default_args dict into YamlDefaultArgs model."""
        if isinstance(v, YamlDefaultArgs):
            return v
        if isinstance(v, dict):
            return YamlDefaultArgs(**v)
        return YamlDefaultArgs()

    @model_validator(mode="after")
    def validate_task_dependencies(self) -> YamlDagDefinition:
        """Validate that all task dependencies and group references are valid."""
        task_ids = {task.task_id for task in self.tasks}
        group_ids = {group.group_id for group in self.task_groups}

        # Check for duplicate task_ids
        if len(task_ids) != len(self.tasks):
            seen: set[str] = set()
            duplicates: list[str] = []
            for task in self.tasks:
                if task.task_id in seen:
                    duplicates.append(task.task_id)
                seen.add(task.task_id)
            raise ValueError(f"Duplicate task_ids found: {duplicates}")

        # Check that all dependencies exist
        for task in self.tasks:
            for dep in task.depends_on:
                if dep not in task_ids:
                    raise ValueError(
                        f"Task '{task.task_id}' depends on non-existent task '{dep}'. "
                        f"Available tasks: {sorted(task_ids)}"
                    )

        # Check that all task_group references exist
        for task in self.tasks:
            if task.task_group and task.task_group not in group_ids:
                raise ValueError(
                    f"Task '{task.task_id}' references non-existent task_group '{task.task_group}'. "
                    f"Available groups: {sorted(group_ids)}"
                )

        # Check that parent_group references exist
        for group in self.task_groups:
            if group.parent_group and group.parent_group not in group_ids:
                raise ValueError(
                    f"Task group '{group.group_id}' references non-existent parent_group '{group.parent_group}'. "
                    f"Available groups: {sorted(group_ids)}"
                )

        return self


class YamlDagFile(BaseModel):
    """
    Root model for a YAML DAG file.

    Supports two formats:

    1. Single DAG format (with 'dag' key):
       dag:
         dag_id: my_dag
         tasks: [...]

    2. Multi-DAG format (dag_id as key):
       default:  # Optional defaults
         default_args:
           owner: team

       my_first_dag:
         tasks: [...]

       my_second_dag:
         tasks: [...]
    """

    dags: list[YamlDagDefinition] = Field(..., description="List of DAG definitions")
    defaults: dict[str, Any] = Field(default_factory=dict, description="Default config for all DAGs")

    @classmethod
    def from_yaml_content(cls, content: dict[str, Any]) -> YamlDagFile:
        """
        Parse YAML content into a YamlDagFile.

        Supports both single-DAG and multi-DAG formats.

        :param content: Parsed YAML content as a dictionary.
        :return: Validated YamlDagFile instance.
        :raises ValueError: If the content is invalid.
        """
        dags: list[YamlDagDefinition] = []
        defaults: dict[str, Any] = {}

        # Single-DAG format: { "dag": { ... } }
        if "dag" in content:
            dag_def = content["dag"]
            dags.append(YamlDagDefinition.model_validate(dag_def))

        # Multi-DAG format: { "dag_id_1": { ... }, "dag_id_2": { ... } }
        else:
            # Extract defaults if present (don't mutate input)
            if "default" in content:
                defaults = content["default"]

            # Each remaining key is a DAG ID
            for dag_id, dag_config in content.items():
                if dag_id == "default":
                    continue  # Skip the defaults key
                if not isinstance(dag_config, dict):
                    continue

                # Merge defaults with DAG config
                merged_config = cls._merge_configs(defaults, dag_config)
                merged_config["dag_id"] = dag_id

                # Validate tasks exist
                if "tasks" not in merged_config:
                    raise ValueError(f"DAG '{dag_id}' must have a 'tasks' key")

                dags.append(YamlDagDefinition.model_validate(merged_config))

        if not dags:
            raise ValueError(
                "YAML file must have either a top-level 'dag' key (single DAG) "
                "or DAG IDs as top-level keys (multi-DAG)"
            )

        return cls(dags=dags, defaults=defaults)

    @staticmethod
    def _merge_configs(defaults: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Merge default config with DAG-specific config (DAG config wins)."""
        merged = dict(defaults)
        for key, value in config.items():
            if key == "default_args" and "default_args" in merged:
                # Merge default_args dictionaries
                merged["default_args"] = {**merged["default_args"], **value}
            else:
                merged[key] = value
        return merged
