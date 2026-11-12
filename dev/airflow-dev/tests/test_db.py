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
from pathlib import Path
from unittest import mock

import pytest

from airflow_dev import db
from airflow_dev.db import MySQL, Postgres, build_client_env, load_known_servers
from airflow_dev.discovery import Installation
from airflow_dev.repo import DevError


def make_server(server_class, repo, tmp_path, version):
    engine = server_class.engine
    server = server_class(repo, Installation(engine, version, tmp_path, tmp_path))
    server.directory.mkdir(parents=True)
    server.write_state(port=4321)
    return server


def test_urls_use_the_locked_drivers_and_loopback(fake_repo, tmp_path):
    postgres = make_server(Postgres, fake_repo, tmp_path, "14.17")
    mysql = make_server(MySQL, fake_repo, tmp_path, "8.4.13")

    assert postgres.get_url("d") == "postgresql+psycopg://postgres@127.0.0.1:4321/d"
    assert mysql.get_url("d") == "mysql+pymysql://root@127.0.0.1:4321/d?charset=utf8mb4&client_flag=65536"
    assert postgres.get_driver_requirements() == ["psycopg==3.3.8", "psycopg-binary==3.3.8"]
    assert mysql.get_driver_requirements() == ["pymysql==1.1.3", "aiomysql==0.3.2"]


def test_servers_are_kept_per_release_line(fake_repo, tmp_path):
    server = make_server(MySQL, fake_repo, tmp_path, "8.4.13")

    assert server.name == "mysql-8.4"
    assert server.directory == fake_repo / ".build" / "airflow-dev" / "db" / "mysql-8.4"


def test_mysql_socket_moves_to_tmp_when_the_path_is_too_long(fake_repo, tmp_path):
    server = make_server(MySQL, fake_repo, tmp_path, "8.4.13")
    with mock.patch.object(db, "MAX_SOCKET_PATH", 10):
        assert server.socket_path.parent == Path("/tmp")


@mock.patch.dict(os.environ, {"PGHOST": "prod", "MYSQL_PWD": "x", "HOME": "/home/me"})
def test_client_env_drops_connection_settings():
    env = build_client_env()

    assert "PGHOST" not in env
    assert "MYSQL_PWD" not in env
    assert env["HOME"] == "/home/me"


def test_ensure_running_refuses_a_half_initialized_data_dir(fake_repo, tmp_path):
    server = Postgres(fake_repo, Installation("postgres", "14.17", tmp_path, tmp_path))
    server.data_dir.mkdir(parents=True)

    with pytest.raises(DevError, match="never fully initialized"):
        server.ensure_running()


def test_load_known_servers_uses_the_recorded_binaries(fake_repo, tmp_path):
    server = make_server(Postgres, fake_repo, tmp_path, "14.17")
    server.write_state(version="14.17", bin_dir=str(tmp_path), client_dir=str(tmp_path), initialized=True)
    make_server(MySQL, fake_repo, tmp_path, "8.4.13")  # never initialized

    (loaded,) = load_known_servers(fake_repo)

    assert loaded.name == "postgres-14"
    assert loaded.installation.bin_dir == tmp_path
