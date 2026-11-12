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

import json
import os
from unittest import mock

import pytest

from airflow_dev import testing
from airflow_dev.db import Postgres
from airflow_dev.discovery import Installation
from airflow_dev.repo import DevError
from airflow_dev.testing import PytestRun, prune, resolve_targets, run_tests


@pytest.fixture
def server(fake_repo, tmp_path):
    server = Postgres(fake_repo, Installation("postgres", "14.17", tmp_path, tmp_path))
    server.directory.mkdir(parents=True)
    server.write_state(port=5555)
    return server


def test_resolve_targets_keeps_node_ids_relative_to_the_repo(fake_repo):
    member, targets = resolve_targets(
        fake_repo, fake_repo / "airflow-core", ["tests/unit/models/test_x.py::TestX::test_a[1]"]
    )

    assert member == "airflow-core"
    assert targets == ["airflow-core/tests/unit/models/test_x.py::TestX::test_a[1]"]


def test_resolve_targets_rejects_targets_from_two_members(fake_repo):
    with pytest.raises(DevError, match="span airflow-core, task-sdk"):
        resolve_targets(fake_repo, fake_repo, ["airflow-core/tests/unit", "task-sdk/tests"])


def test_resolve_targets_rejects_missing_paths(fake_repo):
    with pytest.raises(DevError, match="does not exist"):
        resolve_targets(fake_repo, fake_repo, ["airflow-core/tests/nope.py"])


@mock.patch.dict(
    os.environ,
    {"AIRFLOW_HOME": "/elsewhere", "AIRFLOW__CORE__EXECUTOR": "CeleryExecutor", "PYTEST_ADDOPTS": "-x"},
)
def test_build_env_clears_inherited_airflow_settings(fake_repo, server):
    run = PytestRun(fake_repo, "airflow-core", ["t.py"], "postgres", 2, [], server)

    env = run.build_env()

    assert not {"AIRFLOW_HOME", "AIRFLOW__CORE__EXECUTOR", "PYTEST_ADDOPTS"} & env.keys()
    assert env["BACKEND"] == "postgres"
    assert env["AIRFLOW_DEV_HOME_TEMPLATE"] == str(run.home_root / "{worker}")
    assert env["AIRFLOW_DEV_DB_URL_TEMPLATE"] == (
        f"postgresql+psycopg://postgres@127.0.0.1:5555/{run.run_id}_{{worker}}"
    )
    assert run.database_names == [f"{run.run_id}_{worker}" for worker in ("main", "gw0", "gw1")]


def test_build_command_for_parallel_postgres(fake_repo, server):
    run = PytestRun(fake_repo, "airflow-core", ["t.py"], "postgres", 4, ["-x"], server)

    assert run.build_command() == [
        "uv",
        "run",
        "--project",
        "airflow-core",
        "--with",
        "psycopg==3.3.8",
        "--with",
        "psycopg-binary==3.3.8",
        "pytest",
        "t.py",
        "-n",
        "4",
        "--junitxml",
        str(run.results_dir / "junit.xml"),
        "-x",
    ]


def test_build_command_without_database(fake_repo):
    run = PytestRun(fake_repo, "task-sdk", ["t.py"], "none", 1, [])

    command = run.build_command()

    assert command[:6] == ["uv", "run", "--project", "task-sdk", "--with", "rfc3339-validator==0.1.4"]
    assert "--skip-db-tests" in command
    assert "-n" not in command
    assert "BACKEND" not in run.build_env()


def test_run_tests_drops_databases_even_when_pytest_fails(fake_repo, server):
    with (
        mock.patch.object(testing, "get_server", return_value=server),
        mock.patch.object(server, "ensure_running"),
        mock.patch.object(server, "create_database") as create,
        mock.patch.object(server, "drop_database") as drop,
        mock.patch.object(testing, "stream", side_effect=KeyboardInterrupt),
        pytest.raises(KeyboardInterrupt),
    ):
        run_tests(
            fake_repo,
            fake_repo,
            ["airflow-core/tests/unit"],
            backend="postgres",
            db_version=None,
            workers=1,
            keep_db=False,
            pytest_args=[],
            as_json=True,
        )

    assert create.call_args_list == drop.call_args_list
    assert not list((fake_repo / ".build" / "airflow-dev" / "runs").iterdir())


def test_run_tests_refuses_a_database_for_task_sdk(fake_repo):
    with pytest.raises(DevError, match="never use the metadata database"):
        run_tests(
            fake_repo,
            fake_repo,
            ["task-sdk/tests"],
            backend="sqlite",
            db_version=None,
            workers=1,
            keep_db=False,
            pytest_args=[],
            as_json=False,
        )


def test_prune_removes_runs_whose_owner_is_gone(fake_repo, server):
    runs = fake_repo / ".build" / "airflow-dev" / "runs"
    for run_id, pid in (("airflow_test_dead", 999_999_999), ("airflow_test_live", os.getpid())):
        (runs / run_id).mkdir(parents=True)
        (runs / run_id / "owner.json").write_text(json.dumps({"pid": pid}))
    databases = ["airflow_test_dead_main", "airflow_test_live_main", "airflow_test_lost_gw0"]
    with (
        mock.patch.object(testing, "load_known_servers", return_value=[server]),
        mock.patch.object(server, "is_running", return_value=True),
        mock.patch.object(server, "list_databases", return_value=databases),
        mock.patch.object(server, "drop_database") as drop,
    ):
        removed = prune(fake_repo)

    assert [call.args[0] for call in drop.call_args_list] == [
        "airflow_test_dead_main",
        "airflow_test_lost_gw0",
    ]
    assert str(runs / "airflow_test_dead") in removed
    assert (runs / "airflow_test_live").exists()
