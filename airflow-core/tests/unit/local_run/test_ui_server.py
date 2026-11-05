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

import getpass
import signal
import socket
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import httpx2
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from airflow.api_fastapi.auth.managers.simple.user import SimpleAuthManagerUser
from airflow.local_run import ui_server
from airflow.local_run.ui import build_run_url, get_ui_file, read_live_ui_url
from airflow.sdk.definitions.local_run import run_dag_file


@pytest.fixture
def mock_get_auth_manager() -> Iterator[mock.MagicMock]:
    with mock.patch.object(ui_server, "get_auth_manager", autospec=True) as mock_get_auth_manager:
        mock_get_auth_manager.return_value.generate_jwt.return_value = "viewer-token"
        yield mock_get_auth_manager


@pytest.fixture
def client(mock_get_auth_manager) -> Iterator[TestClient]:
    """The served app around a stand-in for Airflow's, which echoes the credentials it receives."""
    echo = Starlette(
        routes=[Route("/", lambda request: JSONResponse(request.headers.getlist("authorization")))]
    )
    with mock.patch.object(ui_server, "create_app", autospec=True, return_value=echo) as mock_create_app:
        yield TestClient(ui_server.build_app())
    mock_create_app.assert_called_once_with(apps="core")


@pytest.mark.parametrize(
    ("host", "expected_status"),
    [
        pytest.param("127.0.0.1:8080", 200, id="loopback-address"),
        pytest.param("localhost:8080", 200, id="localhost"),
        pytest.param("evil.example:8080", 400, id="rebound-name"),
        pytest.param("127.0.0.1.evil.example", 400, id="loopback-lookalike"),
    ],
)
def test_only_loopback_host_names_are_served(client, host, expected_status):
    assert client.get("/", headers={"Host": host}).status_code == expected_status


def test_every_request_is_served_as_a_viewer(client, mock_get_auth_manager):
    response = client.get("/", headers={"Host": "127.0.0.1:8080", "Authorization": "Bearer admin-token"})

    assert response.json() == ["Bearer viewer-token"]
    mock_get_auth_manager.return_value.generate_jwt.assert_called_once_with(
        SimpleAuthManagerUser(username=getpass.getuser(), role="VIEWER")
    )


@mock.patch.object(ui_server, "build_app", autospec=True)
@mock.patch.object(ui_server, "ensure_database", autospec=True)
def test_port_in_use_is_refused(mock_ensure_database, mock_build_app, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIRFLOW_HOME", str(tmp_path))
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]

        assert ui_server.main([str(port)]) == 2

    err = capsys.readouterr().err
    assert err.startswith(f"Error: cannot serve on 127.0.0.1:{port} (")
    assert err.endswith("choose another port, or leave out --port to use a free one.\n")
    mock_build_app.assert_not_called()


@mock.patch.object(ui_server, "HistoryServer", autospec=True)
@mock.patch.object(ui_server, "build_app", autospec=True)
@mock.patch.object(ui_server, "ensure_database", autospec=True)
def test_port_of_a_stopped_server_is_served_again(
    mock_ensure_database, mock_build_app, mock_history_server, tmp_path, monkeypatch
):
    monkeypatch.setenv("AIRFLOW_HOME", str(tmp_path))
    with socket.socket() as stopped:
        stopped.bind(("127.0.0.1", 0))
        stopped.listen()
        port = stopped.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port)) as client:
            connection, _ = stopped.accept()
            # Closed by the server first, as a stopping server does, so it stays on the port in TIME_WAIT.
            connection.close()
            client.recv(1)

    assert ui_server.main([str(port)]) == 0

    (sock,) = mock_history_server.return_value.run.call_args.kwargs["sockets"]
    with sock:
        assert sock.getsockname() == ("127.0.0.1", port)


GREETING = """
from airflow.sdk import dag, task


@task
def hello():
    return "hi"


@dag(schedule=None)
def greeting():
    hello()


workflow = greeting()
"""


def wait_for_ui(home: Path, server: subprocess.Popen) -> str:
    deadline = time.monotonic() + 120
    while (url := read_live_ui_url(home)) is None:
        assert server.poll() is None, "the UI server exited"
        assert time.monotonic() < deadline, "the UI server did not start"
        time.sleep(0.2)
    return url


def test_ui_serves_the_project_history_and_runs_link_to_it(tmp_path, capfd):
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0"\n')
    source = project / "greeting.py"
    source.write_text(textwrap.dedent(GREETING))
    home = project / ".airflow"
    server_output = tmp_path / "server.out"
    with server_output.open("w") as out:
        server = subprocess.Popen(
            [sys.executable, "-m", "airflow", "standalone", "--project"],
            cwd=project,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    try:
        url = wait_for_ui(home, server)
        result = run_dag_file(source)

        run_url = build_run_url(url, "greeting", result.run_id)
        assert capfd.readouterr().err.splitlines()[-1].endswith(f". View it at {run_url}")
        response = httpx2.get(f"{url}api/v2/dags/greeting/dagRuns/{result.run_id}")
        assert response.status_code == 200
        assert response.json()["state"] == "success"
        assert httpx2.get(url, headers={"Host": "evil.example"}).status_code == 400
        assert httpx2.patch(f"{url}api/v2/dags/greeting", json={"is_paused": False}).status_code == 403

        server.send_signal(signal.SIGINT)
        assert server.wait(timeout=60) == 0
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()
    assert not get_ui_file(home).exists()
    assert f"Airflow UI for {project}: {url}  (Ctrl-C to stop)" in server_output.read_text().splitlines()
