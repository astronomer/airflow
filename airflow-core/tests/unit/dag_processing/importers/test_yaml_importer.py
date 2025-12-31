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
"""Tests for the YAML DAG importer."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from airflow.dag_processing.importers import YamlDagImporter
from airflow.dag_processing.importers.yaml_schema import YamlDagDefinition, YamlDagFile, YamlTaskDefinition


class TestYamlDagImporter:
    """Tests for YamlDagImporter."""

    def test_supported_extensions(self):
        """Test that YAML extensions are supported."""
        extensions = YamlDagImporter.supported_extensions()
        assert ".yaml" in extensions
        assert ".yml" in extensions
        assert ".py" not in extensions

    def test_can_handle_yaml_file(self):
        """Test that can_handle correctly identifies YAML files."""
        importer = YamlDagImporter()
        assert importer.can_handle("test.yaml")
        assert importer.can_handle("test.yml")
        assert importer.can_handle(Path("dir/test.yaml"))
        assert not importer.can_handle("test.py")
        assert not importer.can_handle("test.json")

    def test_import_valid_yaml_dag(self, tmp_path):
        """Test importing a valid YAML DAG file."""
        yaml_content = dedent(
            """
            dag:
              dag_id: test_yaml_dag
              description: Test DAG
              schedule: "@daily"
              start_date: "2024-01-01"
              catchup: false
              tags: [test]

              tasks:
                - task_id: task1
                  operator: airflow.providers.standard.operators.bash.BashOperator
                  params:
                    bash_command: "echo hello"

                - task_id: task2
                  operator: airflow.providers.standard.operators.empty.EmptyOperator
                  depends_on: [task1]
            """
        )

        yaml_file = tmp_path / "test_dag.yaml"
        yaml_file.write_text(yaml_content)

        importer = YamlDagImporter()
        result = importer.import_file(yaml_file, safe_mode=False)

        assert result.success
        assert len(result.dags) == 1
        assert result.dags[0].dag_id == "test_yaml_dag"
        assert len(result.dags[0].tasks) == 2
        assert result.dags[0].description == "Test DAG"
        assert "test" in result.dags[0].tags

    def test_import_yaml_with_syntax_error(self, tmp_path):
        """Test that YAML syntax errors are caught."""
        yaml_content = "dag:\n  dag_id: test\n  tasks:\n    - bad yaml here:\n      nested: [unclosed"

        yaml_file = tmp_path / "bad_syntax.yaml"
        yaml_file.write_text(yaml_content)

        importer = YamlDagImporter()
        result = importer.import_file(yaml_file, safe_mode=False)

        assert not result.success
        assert len(result.errors) > 0
        assert result.errors[0].error_type == "syntax"

    def test_import_yaml_with_invalid_dependency(self, tmp_path):
        """Test that invalid task dependencies are caught."""
        yaml_content = dedent(
            """
            dag:
              dag_id: test_invalid_dep
              tasks:
                - task_id: task1
                  operator: airflow.providers.standard.operators.empty.EmptyOperator
                  depends_on: [nonexistent_task]
            """
        )

        yaml_file = tmp_path / "invalid_dep.yaml"
        yaml_file.write_text(yaml_content)

        importer = YamlDagImporter()
        result = importer.import_file(yaml_file, safe_mode=False)

        assert not result.success
        assert len(result.errors) > 0
        assert "nonexistent_task" in result.errors[0].message

    def test_import_yaml_with_invalid_operator(self, tmp_path):
        """Test that invalid operator classpaths are caught."""
        yaml_content = dedent(
            """
            dag:
              dag_id: test_invalid_op
              tasks:
                - task_id: task1
                  operator: airflow.nonexistent.FakeOperator
                  params:
                    some_param: value
            """
        )

        yaml_file = tmp_path / "invalid_op.yaml"
        yaml_file.write_text(yaml_content)

        importer = YamlDagImporter()
        result = importer.import_file(yaml_file, safe_mode=False)

        assert not result.success
        assert len(result.errors) > 0
        assert result.errors[0].error_type == "reference"

    def test_import_missing_file(self, tmp_path):
        """Test importing a file that doesn't exist."""
        importer = YamlDagImporter()
        result = importer.import_file(tmp_path / "nonexistent.yaml")

        assert not result.success
        assert len(result.errors) == 1
        assert result.errors[0].error_type == "file_not_found"

    def test_safe_mode_skips_non_dag_files(self, tmp_path):
        """Test that safe_mode skips files without 'dag:' key."""
        yaml_content = "config:\n  key: value\n"

        yaml_file = tmp_path / "not_a_dag.yaml"
        yaml_file.write_text(yaml_content)

        importer = YamlDagImporter()
        result = importer.import_file(yaml_file, safe_mode=True)

        assert result.success
        assert len(result.dags) == 0
        assert len(result.errors) == 0


class TestYamlSchema:
    """Tests for YAML schema validation."""

    def test_valid_dag_definition(self):
        """Test that a valid DAG definition passes validation."""
        content = {
            "dag": {
                "dag_id": "test_dag",
                "tasks": [
                    {
                        "task_id": "task1",
                        "operator": "airflow.operators.bash.BashOperator",
                        "params": {"bash_command": "echo hello"},
                    }
                ],
            }
        }

        dag_file = YamlDagFile.from_yaml_content(content)
        assert len(dag_file.dags) == 1
        assert dag_file.dags[0].dag_id == "test_dag"
        assert len(dag_file.dags[0].tasks) == 1

    def test_missing_tasks_key(self):
        """Test that missing 'tasks' key in multi-DAG format raises ValueError."""
        content = {"my_dag": {"description": "no tasks"}}

        with pytest.raises(ValueError, match="must have a 'tasks' key"):
            YamlDagFile.from_yaml_content(content)

    def test_invalid_dag_id(self):
        """Test that invalid dag_id format is rejected."""
        with pytest.raises(ValueError, match="contains invalid characters"):
            YamlDagDefinition(
                dag_id="invalid dag id with spaces",
                tasks=[
                    YamlTaskDefinition(
                        task_id="task1",
                        operator="airflow.operators.empty.EmptyOperator",
                    )
                ],
            )

    def test_duplicate_task_ids(self):
        """Test that duplicate task_ids are detected."""
        with pytest.raises(ValueError, match="Duplicate task_ids"):
            YamlDagDefinition(
                dag_id="test_dag",
                tasks=[
                    YamlTaskDefinition(
                        task_id="task1",
                        operator="airflow.operators.empty.EmptyOperator",
                    ),
                    YamlTaskDefinition(
                        task_id="task1",
                        operator="airflow.operators.empty.EmptyOperator",
                    ),
                ],
            )

    def test_invalid_dependency_reference(self):
        """Test that invalid dependency references are detected."""
        with pytest.raises(ValueError, match="depends on non-existent task"):
            YamlDagDefinition(
                dag_id="test_dag",
                tasks=[
                    YamlTaskDefinition(
                        task_id="task1",
                        operator="airflow.operators.empty.EmptyOperator",
                        depends_on=["nonexistent"],
                    )
                ],
            )

    def test_invalid_operator_format(self):
        """Test that operator without dots is rejected."""
        with pytest.raises(ValueError, match="must be a full classpath"):
            YamlTaskDefinition(
                task_id="task1",
                operator="JustAClassName",
            )
