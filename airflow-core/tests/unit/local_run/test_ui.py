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
import subprocess
import sys
from collections.abc import Iterator

import pytest

from airflow.local_run.ui import (
    build_run_url,
    get_ui_file,
    read_live_ui_url,
    remove_ui_file,
    write_ui_file,
)


@pytest.fixture
def listening_url() -> Iterator[str]:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        yield f"http://127.0.0.1:{server.getsockname()[1]}/"


def get_ended_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_written_url_is_live_while_its_server_listens(tmp_path, listening_url):
    write_ui_file(tmp_path, listening_url)

    assert read_live_ui_url(tmp_path) == listening_url
    assert [path.name for path in tmp_path.iterdir()] == ["ui.json"]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(None, id="missing"),
        pytest.param("{not json", id="corrupt"),
        pytest.param("[]", id="not-a-record"),
        pytest.param(json.dumps({"url": "http://127.0.0.1:1/"}), id="no-pid"),
    ],
)
def test_unreadable_record_is_not_live(tmp_path, content):
    if content is not None:
        get_ui_file(tmp_path).write_text(content)

    assert read_live_ui_url(tmp_path) is None


def test_record_of_an_ended_process_is_not_live(tmp_path, listening_url):
    get_ui_file(tmp_path).write_text(json.dumps({"url": listening_url, "pid": get_ended_pid()}))

    assert read_live_ui_url(tmp_path) is None


def test_record_whose_port_no_longer_listens_is_not_live(tmp_path):
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{closed.getsockname()[1]}/"
    write_ui_file(tmp_path, url)

    assert read_live_ui_url(tmp_path) is None


def test_remove_ui_file_removes_this_process_record(tmp_path):
    write_ui_file(tmp_path, "http://127.0.0.1:1/")

    remove_ui_file(tmp_path)

    assert not get_ui_file(tmp_path).exists()


def test_remove_ui_file_keeps_a_record_another_server_wrote(tmp_path):
    record = json.dumps({"url": "http://127.0.0.1:1/", "pid": os.getpid() + 1})
    get_ui_file(tmp_path).write_text(record)

    remove_ui_file(tmp_path)

    assert get_ui_file(tmp_path).read_text() == record


@pytest.mark.parametrize(
    ("dag_id", "run_id", "expected"),
    [
        pytest.param(
            "example",
            "manual__2026-11-05T15:15:22.432829+00:00",
            "http://127.0.0.1:8080/dags/example/runs/manual__2026-11-05T15:15:22.432829+00:00",
            id="timestamp",
        ),
        pytest.param(
            "example",
            "my run/1?x#y",
            "http://127.0.0.1:8080/dags/example/runs/my%20run%2F1%3Fx%23y",
            id="quoted",
        ),
    ],
)
def test_build_run_url(dag_id, run_id, expected):
    assert build_run_url("http://127.0.0.1:8080/", dag_id, run_id) == expected
