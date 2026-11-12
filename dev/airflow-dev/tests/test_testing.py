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

import io
import json
import os
import sys
from unittest import mock

import pytest

from airflow_dev import testing
from airflow_dev.db import Postgres
from airflow_dev.discovery import Installation
from airflow_dev.repo import DevError
from airflow_dev.testing import (
    PytestRun,
    format_summary,
    prune,
    resolve_targets,
    run_tests,
    stream,
    use_color,
)


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
    {
        "AIRFLOW_HOME": "/elsewhere",
        "AIRFLOW__CORE__EXECUTOR": "CeleryExecutor",
        "PYTEST_ADDOPTS": "-x",
        "VIRTUAL_ENV": "dev/airflow-dev/.venv",
    },
)
def test_build_env_clears_inherited_airflow_settings(fake_repo, server):
    run = PytestRun(fake_repo, "airflow-core", ["t.py"], "postgres", 2, [], server)

    env = run.build_env()

    assert not {"AIRFLOW_HOME", "AIRFLOW__CORE__EXECUTOR", "PYTEST_ADDOPTS", "VIRTUAL_ENV"} & env.keys()
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


def test_build_command_forces_color_before_user_arguments(fake_repo):
    run = PytestRun(fake_repo, "airflow-core", ["t.py"], "sqlite", 1, ["--color=no"], color=True)

    command = run.build_command()

    assert command.index("--color=yes") < command.index("--color=no")


def test_stream_shows_colors_but_logs_plain_text(tmp_path):
    output = io.StringIO()
    log_path = tmp_path / "pytest.log"
    command = [sys.executable, "-c", r"print('\x1b[32m1 passed\x1b[0m')"]

    exit_code = stream(command, cwd=tmp_path, env=dict(os.environ), log_path=log_path, output=output)

    assert exit_code == 0
    assert output.getvalue() == "\x1b[32m1 passed\x1b[0m\n"
    assert log_path.read_text() == "1 passed\n"


SUMMARY = {"member": "airflow-core", "backend": "postgres", "db_version": "14.17", "junit": "j.xml"}


@pytest.mark.parametrize(("exit_code", "color_code"), [(0, "\x1b[32m"), (1, "\x1b[31m")])
def test_format_summary_colors_the_result(exit_code, color_code):
    line = format_summary({**SUMMARY, "exit_code": exit_code}, color=True)

    assert f"{color_code}exited {exit_code}\x1b[0m" in line
    assert line.startswith("\nairflow-dev: airflow-core on postgres 14.17 ")


def test_format_summary_without_color():
    line = format_summary({**SUMMARY, "exit_code": 0}, color=False)

    assert line == "\nairflow-dev: airflow-core on postgres 14.17 exited 0; JUnit j.xml"


@pytest.mark.parametrize(
    ("no_color", "isatty", "expected"), [(False, True, True), (True, True, False), (False, False, False)]
)
def test_use_color(monkeypatch, no_color, isatty, expected):
    if no_color:
        monkeypatch.setenv("NO_COLOR", "1")
    else:
        monkeypatch.delenv("NO_COLOR", raising=False)
    output = mock.Mock(spec=io.StringIO, **{"isatty.return_value": isatty})

    assert use_color(output) is expected
