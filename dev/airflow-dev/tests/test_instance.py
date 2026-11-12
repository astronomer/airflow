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
import socket
from unittest import mock

import pytest

from airflow_dev import instance as instances
from airflow_dev.db import MySQL
from airflow_dev.discovery import Installation
from airflow_dev.instance import Instance, is_healthy, is_port_free, stop
from airflow_dev.repo import DevError

HEALTHY = {name: {"status": "healthy"} for name in instances.HEALTH_COMPONENTS}


@pytest.fixture
def mysql_instance(fake_repo, tmp_path):
    server = MySQL(fake_repo, Installation("mysql", "8.4.13", tmp_path, tmp_path))
    server.directory.mkdir(parents=True)
    server.write_state(port=3307)
    return Instance(fake_repo, "mysql", server)


@pytest.mark.parametrize(
    ("health", "expected"),
    [
        (HEALTHY, True),
        ({**HEALTHY, "triggerer": {"status": "unhealthy"}}, False),
        ({**HEALTHY, "dag_processor": None}, False),
        (None, False),
    ],
)
def test_is_healthy(health, expected):
    assert is_healthy(health) is expected


@mock.patch.dict(os.environ, {"AIRFLOW__CORE__EXECUTOR": "CeleryExecutor"})
def test_build_env_points_at_the_instance_database(mysql_instance, tmp_path):
    env = mysql_instance.build_env(port=8081, dags_folder=tmp_path, examples=False)

    assert "AIRFLOW__CORE__EXECUTOR" not in env
    assert env["AIRFLOW_HOME"] == str(mysql_instance.home)
    assert env["AIRFLOW__API__PORT"] == "8081"
    assert env["AIRFLOW__CORE__LOAD_EXAMPLES"] == "False"
    assert env["AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS"] == "True"
    assert env["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"].startswith(
        "mysql+pymysql://root@127.0.0.1:3307/airflow_instance?"
    )


def test_build_command_runs_standalone_with_drivers(mysql_instance):
    assert mysql_instance.build_command() == [
        "uv",
        "run",
        "--project",
        "providers/standard",
        "--with",
        "pymysql==1.1.3",
        "--with",
        "aiomysql==0.3.2",
        "airflow",
        "standalone",
    ]


def test_sqlite_instance_keeps_the_default_database(fake_repo, tmp_path):
    instance = Instance(fake_repo, "sqlite", None)

    env = instance.build_env(port=8080, dags_folder=tmp_path, examples=True)

    assert instance.name == "sqlite"
    assert "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN" not in env
    assert instance.build_command()[-2:] == ["airflow", "standalone"]


def test_stop_forgets_an_instance_whose_process_is_gone(mysql_instance):
    mysql_instance.home.mkdir(parents=True)
    mysql_instance.state_file.write_text(json.dumps({"pid": 999_999_999, "pgid": 999_999_999}))

    assert stop(mysql_instance) is False
    assert not mysql_instance.state_file.exists()


def test_start_refuses_a_busy_port(mysql_instance):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        assert is_port_free(port) is False

        with pytest.raises(DevError, match=f"Port {port} is in use"):
            instances.start(
                mysql_instance, port=port, dags_folder=None, examples=False, background=True, timeout=1
            )
