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
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from pathlib import Path
from unittest import mock

import httpx2
import psutil
import pytest
from sqlalchemy.exc import OperationalError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from airflow.api_fastapi.auth.managers.simple.user import SimpleAuthManagerUser
from airflow.local_run import ui_server
from airflow.local_run.runner import ConfigSetupError
from airflow.local_run.ui import PROJECT_SERVER_ENVIRONMENT, build_run_url, get_ui_file, read_live_ui_url
from airflow.sdk.definitions.local_run import run_dag_file


@pytest.fixture
def mock_get_auth_manager() -> Iterator[mock.MagicMock]:
    with mock.patch.object(ui_server, "get_auth_manager", autospec=True) as mock_get_auth_manager:
        mock_get_auth_manager.return_value.generate_jwt.return_value = "local-token"
        yield mock_get_auth_manager


async def accept_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.close()


@pytest.fixture
def client(mock_get_auth_manager) -> Iterator[TestClient]:
    """The served app around a stand-in for Airflow's, which echoes the credentials it receives."""
    echo = Starlette(
        routes=[
            *(
                Route(
                    path,
                    lambda request: JSONResponse(request.headers.getlist("authorization")),
                    methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"],
                )
                for path in ("/", "/execution/task-instances")
            ),
            WebSocketRoute("/ws", accept_websocket),
        ]
    )
    with mock.patch.object(ui_server, "create_app", autospec=True, return_value=echo) as mock_create_app:
        yield TestClient(ui_server.build_app())
    mock_create_app.assert_called_once_with(apps="core,execution")


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


def test_every_request_is_served_as_the_local_user_an_admin(client, mock_get_auth_manager):
    response = client.get("/", headers={"Host": "127.0.0.1:8080", "Authorization": "Bearer other-token"})

    assert response.json() == ["Bearer local-token"]
    mock_get_auth_manager.return_value.generate_jwt.assert_called_once_with(
        SimpleAuthManagerUser(username=getpass.getuser(), role="ADMIN")
    )


@pytest.mark.parametrize(
    ("method", "headers", "expected_status"),
    [
        pytest.param("GET", {"Sec-Fetch-Site": "cross-site"}, 200, id="safe-method-from-another-site"),
        pytest.param("POST", {}, 200, id="program"),
        pytest.param("POST", {"Sec-Fetch-Site": "same-origin"}, 200, id="own-page"),
        pytest.param(
            "POST",
            {"Sec-Fetch-Site": "same-origin", "Origin": "http://evil.example"},
            200,
            id="own-page-whatever-its-origin",
        ),
        pytest.param("POST", {"Sec-Fetch-Site": "same-site"}, 403, id="page-on-another-port"),
        pytest.param("POST", {"Sec-Fetch-Site": "cross-site"}, 403, id="page-of-another-site"),
        pytest.param("POST", {"Sec-Fetch-Site": "none"}, 403, id="no-page"),
        pytest.param("POST", {"Origin": "http://127.0.0.1:8080"}, 200, id="own-origin"),
        pytest.param(
            "POST",
            {"Origin": "http://localhost:8080", "Host": "localhost:8080"},
            200,
            id="own-origin-by-name",
        ),
        pytest.param("POST", {"Origin": "http://localhost:8080"}, 403, id="origin-of-the-other-name"),
        pytest.param("POST", {"Origin": "http://127.0.0.1:9999"}, 403, id="origin-on-another-port"),
        pytest.param("POST", {"Origin": "http://evil.example"}, 403, id="origin-of-another-site"),
        pytest.param("POST", {"Origin": "null"}, 403, id="opaque-origin"),
        pytest.param("PUT", {"Sec-Fetch-Site": "cross-site"}, 403, id="put"),
        pytest.param("PATCH", {"Sec-Fetch-Site": "cross-site"}, 403, id="patch"),
        pytest.param("DELETE", {"Sec-Fetch-Site": "cross-site"}, 403, id="delete"),
    ],
)
def test_changes_are_accepted_only_from_the_servers_own_pages(client, method, headers, expected_status):
    response = client.request(method, "/", headers={"Host": "127.0.0.1:8080", **headers})

    assert response.status_code == expected_status
    if expected_status == 403:
        assert response.json() == {"detail": "This server accepts changes only from its own pages."}


def test_websocket_from_another_site_is_refused(client):
    headers = {"Host": "127.0.0.1:8080"}
    with client.websocket_connect("/ws", headers={**headers, "Origin": "http://127.0.0.1:8080"}):
        pass

    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/ws", headers={**headers, "Origin": "http://evil.example"}):
            pass
    assert refused.value.code == 1008


def test_execution_api_requests_keep_their_task_token(client, mock_get_auth_manager):
    response = client.get(
        "/execution/task-instances", headers={"Host": "127.0.0.1:8080", "Authorization": "Bearer task-token"}
    )

    assert response.json() == ["Bearer task-token"]
    mock_get_auth_manager.return_value.generate_jwt.assert_not_called()


def test_ignore_files_keep_the_dag_processor_out_of_folders_tools_keep(tmp_path):
    home = tmp_path / ".airflow"
    tool_folders = [".airflow", ".git", "node_modules", ".venv", "services/api/env"]
    for folder in [*tool_folders, ".github", "dags", "services/api/src"]:
        (tmp_path / folder).mkdir(parents=True)
    for venv in (".venv", "services/api/env"):
        (tmp_path / venv / "pyvenv.cfg").touch()

    ui_server.write_ignore_files(tmp_path, home)

    written = sorted(
        path.parent.relative_to(tmp_path).as_posix() for path in tmp_path.rglob(".airflowignore")
    )
    assert written == sorted(tool_folders)
    assert (home / ".airflowignore").read_text() == "*\n"


@mock.patch.object(ui_server, "report", autospec=True)
def test_folders_that_cannot_be_written_or_read_do_not_stop_the_server(mock_report, tmp_path):
    home = tmp_path / ".airflow"
    home.mkdir()
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").touch()
    unreadable = tmp_path / "private"
    unreadable.mkdir()
    venv.chmod(0o555)
    unreadable.chmod(0)
    try:
        ui_server.write_ignore_files(tmp_path, home)
    finally:
        venv.chmod(0o755)
        unreadable.chmod(0o755)

    assert (home / ".airflowignore").exists()
    assert not (venv / ".airflowignore").exists()
    (message,) = mock_report.call_args.args
    assert message.startswith(f"Warning: the Dag processor will look for Dags in {venv}: cannot write")


@pytest.mark.parametrize("name", sorted(PROJECT_SERVER_ENVIRONMENT))
def test_components_share_the_servers_environment_except_its_own_settings(monkeypatch, name):
    monkeypatch.setenv("AIRFLOW__API_AUTH__JWT_SECRET", "server-secret")
    monkeypatch.setenv(name, PROJECT_SERVER_ENVIRONMENT[name])

    env = ui_server.build_component_environment("http://127.0.0.1:8080/")

    assert env["AIRFLOW__API_AUTH__JWT_SECRET"] == "server-secret"
    assert env["AIRFLOW__CORE__EXECUTION_API_SERVER_URL"] == "http://127.0.0.1:8080/execution/"
    assert env["AIRFLOW__CORE__EXECUTOR"] == "LocalExecutor"
    assert name not in env


@mock.patch.object(ui_server.subprocess, "Popen", autospec=True)
def test_each_server_keeps_the_previous_servers_component_logs(mock_popen, tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "scheduler.log").write_text("previous server")
    (tmp_path / "logs" / "scheduler.log.1").write_text("the server before")

    ui_server.start_components(tmp_path, "http://127.0.0.1:8080/")

    assert (tmp_path / "logs" / "scheduler.log.1").read_text() == "previous server"
    assert (tmp_path / "logs" / "scheduler.log").read_text() == ""
    assert mock_popen.call_count == len(ui_server.COMPONENTS)


# Prints the worker's pid only once its SIGTERM handler is installed.
COMPONENT_WITH_WORKER = """
import signal, subprocess, sys, time

signal.signal(signal.SIGTERM, signal.SIG_IGN if sys.argv[2] == "ignore" else signal.SIG_DFL)
worker = subprocess.Popen(
    [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print(flush=True); time.sleep(60)"],
    stdout=subprocess.PIPE,
    process_group=0 if sys.argv[1] == "group" else None,
    start_new_session=sys.argv[1] == "session",
)
worker.stdout.readline()
print(worker.pid, flush=True)
time.sleep(60)
"""


def start_component_with_worker(
    *, worker_group: str = "same", ignore_sigterm: bool = True
) -> tuple[subprocess.Popen, int]:
    component = subprocess.Popen(
        [sys.executable, "-c", COMPONENT_WITH_WORKER, worker_group, "ignore" if ignore_sigterm else "exit"],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert component.stdout is not None
    return component, int(component.stdout.readline())


def wait_for_exit(pid: int) -> bool:
    with suppress(psutil.NoSuchProcess):
        psutil.Process(pid).wait(timeout=10)
    return not psutil.pid_exists(pid)


@mock.patch.object(ui_server, "COMPONENT_STOP_TIMEOUT", 1.0)
def test_a_component_that_does_not_stop_is_killed_with_its_workers():
    stops = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    stubborn, worker_pid = start_component_with_worker()

    ui_server.stop_components([stops, stubborn])

    assert stops.returncode == -signal.SIGTERM
    assert stubborn.returncode == -signal.SIGKILL
    assert wait_for_exit(worker_pid)


def test_stopping_components_ends_the_wait_when_forced():
    stubborn, worker_pid = start_component_with_worker()
    started = time.monotonic()

    ui_server.stop_components([stubborn], should_force=lambda: True)

    assert time.monotonic() - started < ui_server.COMPONENT_STOP_TIMEOUT
    assert stubborn.returncode == -signal.SIGKILL
    assert wait_for_exit(worker_pid)


@pytest.mark.parametrize("worker_group", ["group", "session"])
@pytest.mark.parametrize(("ignore_sigterm", "force"), [(True, False), (True, True), (False, False)])
@mock.patch.object(ui_server, "COMPONENT_STOP_TIMEOUT", 0.1)
@mock.patch.object(ui_server, "COMPONENT_POLL_INTERVAL", 0.01)
def test_stopping_components_kills_tasks_outside_the_component_group(worker_group, ignore_sigterm, force):
    component, worker_pid = start_component_with_worker(
        worker_group=worker_group, ignore_sigterm=ignore_sigterm
    )
    worker = psutil.Process(worker_pid)
    try:
        ui_server.stop_components([component], should_force=lambda: force)

        assert component.returncode == (-signal.SIGKILL if ignore_sigterm else -signal.SIGTERM)
        assert wait_for_exit(worker_pid)
    finally:
        with suppress(psutil.NoSuchProcess):
            worker.kill()
            worker.wait(timeout=10)
        if component.poll() is None:
            component.kill()
        component.wait(timeout=10)
        if component.stdout is not None:
            component.stdout.close()


@mock.patch.object(ui_server, "report", autospec=True)
@mock.patch.object(ui_server, "COMPONENT_POLL_INTERVAL", 0.01)
def test_a_component_that_stops_while_serving_is_reported(mock_report, tmp_path):
    stop = threading.Event()
    exited = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    running = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    exited.wait()
    mock_report.side_effect = lambda message: stop.set()
    try:
        ui_server.watch_components({"scheduler": exited, "triggerer": running}, tmp_path, stop)
    finally:
        running.kill()
        running.wait()

    mock_report.assert_called_once_with(
        "The scheduler stopped (exit code 3), so the project's Dags are not scheduled until the server is "
        f"restarted. Its log: {tmp_path / 'logs' / 'scheduler.log'}"
    )


@mock.patch.object(ui_server, "report_abandoned_runs", autospec=True)
@mock.patch.object(ui_server, "fail_abandoned_runs", autospec=True)
@mock.patch.object(ui_server, "create_session", autospec=True)
@mock.patch.object(ui_server, "ABANDONED_RUN_CHECK_INTERVAL", 0)
def test_abandoned_runs_are_checked_until_stopped(
    mock_create_session, mock_fail_abandoned_runs, mock_report_abandoned_runs, tmp_path
):
    stop = threading.Event()
    session = mock_create_session.return_value.__enter__.return_value
    # A failed check is logged and the next one still runs.
    mock_fail_abandoned_runs.side_effect = [OperationalError("SELECT", {}, Exception("locked")), ["run"]]
    mock_report_abandoned_runs.side_effect = lambda home, runs: stop.set()

    ui_server.check_abandoned_runs(tmp_path, stop)

    assert mock_fail_abandoned_runs.call_args_list == [mock.call(tmp_path, session=session)] * 2
    mock_report_abandoned_runs.assert_called_once_with(tmp_path, ["run"])


@mock.patch.object(
    ui_server, "ensure_database", autospec=True, side_effect=ConfigSetupError("created by a newer Airflow")
)
def test_database_it_cannot_use_is_refused_with_the_setup_code(_, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIRFLOW_HOME", str(tmp_path))

    assert ui_server.main([]) == 4
    assert capsys.readouterr().err == "Error: created by a newer Airflow\n"


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


@mock.patch.object(ui_server, "ProjectServer", autospec=True)
@mock.patch.object(ui_server, "write_ignore_files", autospec=True)
@mock.patch.object(ui_server, "build_app", autospec=True)
@mock.patch.object(ui_server, "ensure_database", autospec=True)
def test_port_of_a_stopped_server_is_served_again(
    mock_ensure_database, mock_build_app, mock_write_ignore_files, mock_project_server, tmp_path, monkeypatch
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

    (sock,) = mock_project_server.return_value.run.call_args.kwargs["sockets"]
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
        unpause = {"url": f"{url}api/v2/dags/greeting", "json": {"is_paused": False}}
        assert httpx2.patch(**unpause, headers={"Origin": "http://evil.example"}).status_code == 403
        assert httpx2.patch(**unpause, headers={"Origin": url.rstrip("/")}).status_code == 200
        assert httpx2.get(f"{url}api/v2/dags/greeting").json()["is_paused"] is False

        server.send_signal(signal.SIGINT)
        assert server.wait(timeout=60) == 0
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()
    assert not get_ui_file(home).exists()
    assert f"Airflow UI for {project}: {url}  (Ctrl-C to stop)" in server_output.read_text().splitlines()


SCHEDULED = """
import datetime

from airflow.providers.standard.triggers.temporal import TimeDeltaTrigger
from airflow.sdk import BaseOperator, dag, task


@task
def hello():
    return "hi"


class Waits(BaseOperator):
    def execute(self, context):
        self.defer(trigger=TimeDeltaTrigger(datetime.timedelta(0)), method_name="resume")

    def resume(self, context, event=None):
        return "resumed"


@dag(schedule="@once", start_date=datetime.datetime(2026, 1, 1))
def scheduled():
    hello() >> Waits(task_id="waits")


workflow = scheduled()
"""


def query(home: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(home / "airflow.db") as conn:
        return conn.execute(sql).fetchall()


def wait_until(condition: Callable[[], object], server: subprocess.Popen, what: str) -> None:
    deadline = time.monotonic() + 180
    while not condition():
        assert server.poll() is None, "the server exited"
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.5)


def test_server_schedules_the_projects_dags(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0"\n')
    (project / "scheduled.py").write_text(textwrap.dedent(SCHEDULED))
    # Airflow's own source, as a virtual environment holds it, looks like Dag files.
    venv = project / ".venv"
    (venv / "lib").mkdir(parents=True)
    (venv / "pyvenv.cfg").touch()
    (venv / "lib" / "example.py").write_text(textwrap.dedent(SCHEDULED).replace("scheduled", "example"))
    home = project / ".airflow"
    server = subprocess.Popen(
        [sys.executable, "-m", "airflow", "standalone", "--project"],
        cwd=project,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        url = wait_for_ui(home, server)
        wait_until(
            lambda: query(home, "SELECT dag_id FROM dag"), server, "the Dag processor to store the Dag"
        )
        components = psutil.Process(server.pid).children()
        assert sorted(component.cmdline()[-1] for component in components) == [
            "dag-processor",
            "scheduler",
            "triggerer",
        ]
        # As the UI's pause toggle does.
        response = httpx2.patch(
            f"{url}api/v2/dags/scheduled",
            json={"is_paused": False},
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        assert response.status_code == 200
        # Its deferred task resumes once the project's triggerer fires its trigger.
        wait_until(
            lambda: query(home, "SELECT state FROM dag_run WHERE run_type = 'scheduled'") == [("success",)],
            server,
            "the scheduled run to succeed",
        )
        assert query(home, "SELECT dag_id FROM dag") == [("scheduled",)]

        # The scheduler examines the unpaused Dag's runs, and the triggerer claims unassigned triggers.
        local = run_dag_file(project / "scheduled.py")

        assert local.output("waits") == "resumed"
        # Run by the local process alone: no try queued by the scheduler, none run twice.
        tries = (
            f"SELECT task_id, try_number, queued_by_job_id FROM task_instance WHERE run_id = '{local.run_id}'"
        )
        assert sorted(query(home, tries)) == [("hello", 1, None), ("waits", 1, None)]
        assert query(
            home, "SELECT count(*) FROM trigger WHERE queue = 'local-run' AND triggerer_id IS NOT NULL"
        ) == [(0,)]

        server.send_signal(signal.SIGINT)
        assert server.wait(timeout=90) == 0
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()
    assert not any(component.is_running() for component in components)
    assert {path.name for path in (home / "logs").glob("*.log")} >= {
        "scheduler.log",
        "dag-processor.log",
        "triggerer.log",
    }
