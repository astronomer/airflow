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

import os
from unittest import mock

import pytest

from airflow_cli import is_no_db_run, main, prepare_module_execution


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["run", "agent.py", "--no-db", "--task", "agent"], True),
        (["run", "--no-db", "agent.py"], True),
        (["run", "agent.py", "--no-d"], True),
        (["run", "agent.py", "--no"], False),
        (["run", "agent.py", "--no-debug"], False),
        (["run", "agent.py"], False),
        (["run", "--", "--no-db"], False),
        (["version", "--no-db"], False),
        ([], False),
    ],
)
def test_selects_only_explicit_no_db_run(arguments, expected):
    assert is_no_db_run(arguments) is expected


@mock.patch("airflow.__main__.main", autospec=True)
def test_default_entrypoint_keeps_configuration(airflow_main, monkeypatch):
    monkeypatch.setattr("sys.argv", ["airflow", "version"])
    monkeypatch.setenv("AIRFLOW__DATABASE__SQL_ALCHEMY_CONN", "existing-settings")
    before = os.environ.copy()
    main()
    airflow_main.assert_called_once_with()
    assert dict(os.environ) == before


@pytest.mark.parametrize("module", ["airflow", "airflow.__main__"])
@mock.patch("airflow_cli.atexit.register", autospec=True)
def test_module_entrypoint_isolates_before_package_initialization(register, monkeypatch, module):
    monkeypatch.setattr("sys.argv", ["-m", "run", "agent.py", "--no-d", "--task", "agent"])
    monkeypatch.setattr("sys.orig_argv", ["python", "-m", module, "run", "agent.py", "--no-d"])
    monkeypatch.setenv("AIRFLOW__DATABASE__SQL_ALCHEMY_CONN", "production")
    before = os.environ.copy()

    prepare_module_execution()
    register.assert_called_once()
    try:
        assert os.environ["_AIRFLOW__LOCAL_NO_DB"] == "1"
        assert "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN" not in os.environ
        assert os.environ["AIRFLOW_HOME"] != before.get("AIRFLOW_HOME")
    finally:
        register.call_args.args[0]()
    assert dict(os.environ) == before


@pytest.mark.parametrize(
    ("argv", "original"),
    [
        (["-m", "run", "agent.py"], ["python", "-m", "airflow", "run", "agent.py"]),
        (["-m", "version"], ["python", "-m", "airflow", "version"]),
        (["-m", "run", "--no-db"], ["python", "-m", "other", "run", "--no-db"]),
        (["script.py", "run", "--no-db"], ["python", "script.py", "run", "--no-db"]),
    ],
)
@mock.patch("airflow_cli.atexit.register", autospec=True)
def test_module_bootstrap_leaves_other_invocations_unchanged(register, monkeypatch, argv, original):
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr("sys.orig_argv", original)
    before = os.environ.copy()
    prepare_module_execution()
    register.assert_not_called()
    assert dict(os.environ) == before


@mock.patch("airflow.__main__.main", autospec=True)
def test_no_db_entrypoint_isolates_configuration(airflow_main, monkeypatch):
    monkeypatch.setattr("sys.argv", ["airflow", "run", "agent.py", "--task", "agent", "--no-db"])
    monkeypatch.setenv("AIRFLOW__DATABASE__SQL_ALCHEMY_CONN", "production")
    monkeypatch.setenv("AIRFLOW_CONFIG", "/existing/airflow.cfg")
    monkeypatch.setenv("AIRFLOW_CONN_DEMO", "connection")
    monkeypatch.setenv("AIRFLOW_VAR_REGION", "region")
    before = os.environ.copy()
    observed = {}
    airflow_main.side_effect = lambda: observed.update(os.environ)

    main()

    assert observed["_AIRFLOW__LOCAL_NO_DB"] == "1"
    assert "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN" not in observed
    assert "AIRFLOW_CONFIG" not in observed
    assert observed["AIRFLOW_CONN_DEMO"] == "connection"
    assert observed["AIRFLOW_VAR_REGION"] == "region"
    assert observed["AIRFLOW_HOME"] != before.get("AIRFLOW_HOME")
    assert dict(os.environ) == before
