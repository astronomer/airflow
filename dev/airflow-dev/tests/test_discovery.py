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
from conftest import write_executable

from airflow_dev import discovery
from airflow_dev.discovery import (
    EXTRA_DIRS_VARIABLE,
    find_frontend_tools,
    find_installations,
    select_installation,
)
from airflow_dev.repo import DevError


def make_postgres(directory, version):
    write_executable(directory / "postgres", f"postgres (PostgreSQL) {version} (Homebrew)")
    for name in ("initdb", "pg_ctl", "psql"):
        write_executable(directory / name, "")
    return directory


def make_mysql(server_dir, client_dir, version):
    write_executable(server_dir / "mysqld", f"/x/mysqld  Ver {version} for macos15 on arm64 (MySQL)")
    for name in ("mysql", "mysqladmin"):
        write_executable(client_dir / name, "")


@pytest.fixture
def only_tool_dirs(monkeypatch):
    """Search only the directories a test names, never the machine's real installations."""

    def use(*directories):
        monkeypatch.setenv(EXTRA_DIRS_VARIABLE, os.pathsep.join(map(str, directories)))
        monkeypatch.setenv("PATH", "/nonexistent")
        monkeypatch.setattr(discovery, "ENGINE_DIR_PATTERNS", {"postgres": [], "mysql": []})

    return use


def test_find_installations_reads_versions(tmp_path, only_tool_dirs):
    only_tool_dirs(make_postgres(tmp_path / "pg14", "14.17"), make_postgres(tmp_path / "pg16", "16.4"))

    found = {(i.version, i.major) for i in find_installations("postgres")}

    assert found == {("14.17", "14"), ("16.4", "16")}


def test_find_installations_finds_mysql_clients_in_sibling_bin(tmp_path, only_tool_dirs):
    make_mysql(tmp_path / "usr" / "sbin", tmp_path / "usr" / "bin", "8.0.40")
    only_tool_dirs(tmp_path / "usr" / "sbin")

    (installation,) = find_installations("mysql")

    assert installation.major == "8.0"
    assert installation.get_executable("mysqld") == tmp_path / "usr" / "sbin" / "mysqld"
    assert installation.get_executable("mysql") == tmp_path / "usr" / "bin" / "mysql"


def test_find_installations_skips_servers_without_clients(tmp_path, only_tool_dirs):
    write_executable(tmp_path / "bin" / "postgres", "postgres (PostgreSQL) 14.17")
    only_tool_dirs(tmp_path / "bin")

    assert find_installations("postgres") == []


def test_select_installation_prefers_breeze_order_and_skips_unsupported(fake_repo, tmp_path, only_tool_dirs):
    make_mysql(tmp_path / "m92", tmp_path / "m92", "9.2.0")
    make_mysql(tmp_path / "m84", tmp_path / "m84", "8.4.13")
    only_tool_dirs(tmp_path / "m92", tmp_path / "m84")

    assert select_installation(fake_repo, "mysql", None).version == "8.4.13"


def test_select_installation_explains_how_to_install(fake_repo, tmp_path, only_tool_dirs):
    only_tool_dirs(make_postgres(tmp_path / "pg14", "14.17"))

    with pytest.raises(DevError) as error:
        select_installation(fake_repo, "postgres", "15")

    assert "found: 14" in error.value.message
    assert EXTRA_DIRS_VARIABLE in error.value.hint


@pytest.fixture
def node_dirs(tmp_path, monkeypatch):
    def use(*versions):
        directories = [write_executable(tmp_path / f"node{v}" / "node", f"v{v}").parent for v in versions]
        monkeypatch.setattr(discovery, "get_node_dirs", lambda: directories)
        monkeypatch.setenv("PATH", "/nonexistent")
        return directories

    return use


def test_find_frontend_tools_uses_a_matching_pnpm(fake_repo, node_dirs):
    (node_dir,) = node_dirs("22.1.0")
    write_executable(node_dir / "pnpm", "10.28.1")

    tools = find_frontend_tools(fake_repo)

    assert tools["pnpm"] == str(node_dir / "pnpm")
    assert tools["pnpm_source"] == "installed"


def test_find_frontend_tools_falls_back_to_corepack(fake_repo, node_dirs):
    _, new = node_dirs("20.13.1", "23.11.0")
    write_executable(new / "pnpm", "10.2.1")
    write_executable(new / "corepack", "0.32.0")

    tools = find_frontend_tools(fake_repo)

    assert tools["node_version"] == "23.11.0"
    assert tools["pnpm"] == str(new / "corepack")
    assert tools["pnpm_source"] == "corepack"


def test_find_frontend_tools_requires_the_minimum_node(fake_repo, node_dirs):
    node_dirs("20.13.1")

    with pytest.raises(DevError, match="Node 22 or newer"):
        find_frontend_tools(fake_repo)


@mock.patch.object(discovery.sys, "platform", "darwin")
def test_install_hint_on_macos():
    assert discovery.get_install_hint("postgres", "16") == "brew install postgresql@16"
