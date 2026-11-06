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
from __future__ import annotations

import sys
import tomllib
from importlib import metadata

import pytest

from airflow import __version__ as airflow_version
from airflow.cli import cli_parser
from airflow.cli.commands import bootstrap_command


@pytest.fixture(scope="module")
def parser():
    return cli_parser.get_parser()


@pytest.mark.parametrize("exists", [False, True], ids=["new", "empty"])
def test_new_folder_gets_a_project_with_the_example_dag(parser, tmp_path, monkeypatch, capsys, exists):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "demo"
    if exists:
        project.mkdir()

    bootstrap_command.bootstrap(parser.parse_args(["bootstrap", "demo"]))

    assert tomllib.loads((project / "pyproject.toml").read_text())["project"] == {
        "name": "demo",
        "version": "0.1.0",
        "requires-python": metadata.metadata("apache-airflow-core")["Requires-Python"],
        "dependencies": [f"apache-airflow>={airflow_version}"],
    }
    assert (project / ".python-version").read_text() == f"{sys.version_info.major}.{sys.version_info.minor}\n"
    example = (project / "pipeline.py").read_text()
    # What the guide shows: no license header, and none of the markers around it.
    assert example.startswith("from airflow.sdk import dag, task\n")
    assert example.endswith('    print("total:", result.output("total"))\n')
    assert capsys.readouterr().out.splitlines()[1:] == ["  cd demo", "  uv run pipeline.py"]


def test_folder_with_files_keeps_them_and_gets_no_example(parser, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "etl.py").write_text("")
    (tmp_path / ".python-version").write_text("3.11\n")

    bootstrap_command.bootstrap(parser.parse_args(["bootstrap"]))

    assert sorted(path.name for path in tmp_path.iterdir()) == [".python-version", "etl.py", "pyproject.toml"]
    assert (tmp_path / ".python-version").read_text() == "3.11\n"
    assert capsys.readouterr().out.splitlines()[1:] == ["  uv run airflow run your_dag.py"]


def test_folder_with_a_project_is_left_alone(parser, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n")

    with pytest.raises(SystemExit, match="already has a pyproject.toml$"):
        bootstrap_command.bootstrap(parser.parse_args(["bootstrap", str(tmp_path)]))

    assert sorted(path.name for path in tmp_path.iterdir()) == ["pyproject.toml"]
    assert (tmp_path / "pyproject.toml").read_text() == "[project]\n"


def test_folder_that_cannot_be_created_is_reported(parser, tmp_path):
    (tmp_path / "taken").write_text("")

    with pytest.raises(SystemExit, match="^Error: "):
        bootstrap_command.bootstrap(parser.parse_args(["bootstrap", str(tmp_path / "taken")]))


@pytest.mark.parametrize(("folder", "name"), [("My_Dags.v2", "my-dags-v2"), ("проект", "dags")])
def test_project_name_comes_from_the_folder(folder, name):
    assert bootstrap_command.build_project_name(folder) == name
