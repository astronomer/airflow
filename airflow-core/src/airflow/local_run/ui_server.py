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
"""
Serve Airflow's UI on a project's local run history, and schedule the project's Dags, from this machine only.

Started as ``python -m airflow.local_run.ui_server`` by ``airflow standalone --project``, with the environment
a run's process gets, so the UI reads the project's database and task logs. Once it serves, it starts a
scheduler, a Dag processor and a triggerer for the project, and it stops them when it stops.
"""

from __future__ import annotations

import asyncio
import getpass
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

import psutil
import uvicorn
from starlette import status
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.websockets import WebSocketClose

from airflow import settings
from airflow.api_fastapi.app import create_app, get_auth_manager
from airflow.api_fastapi.auth.managers.simple.user import SimpleAuthManagerUser
from airflow.configuration import conf
from airflow.local_run.runner import (
    LocalRunSetupError,
    ensure_database,
    fail_abandoned_runs,
    project_lock,
    report,
    report_abandoned_runs,
)
from airflow.local_run.supervised import find_descendants
from airflow.local_run.ui import PROJECT_SERVER_ENVIRONMENT, remove_ui_file, write_ui_file
from airflow.utils.session import create_session

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger(__name__)

LOOPBACK_HOST = "127.0.0.1"
# The names a browser on this machine reaches the server by. A page on another site that makes its own name
# resolve to this address (DNS rebinding) still sends that name, so its requests are refused.
ALLOWED_HOSTS = (LOOPBACK_HOST, "localhost")
EXECUTION_API_PATH = "/execution"
# Methods that change nothing; any page may send them, and no page of another site can read the response.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

COMPONENTS_MODULE = "airflow.local_run.components"
COMPONENTS = ("scheduler", "dag-processor", "triggerer")
TOOL_FOLDER_NAMES = frozenset(
    {".git", ".hg", "node_modules", ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)
# Long enough for the scheduler to stop the tasks it runs before it is killed.
COMPONENT_STOP_TIMEOUT = 30.0
COMPONENT_POLL_INTERVAL = 0.2
ABANDONED_RUN_CHECK_INTERVAL = 10.0


class SameOriginChangesMiddleware:
    """
    Refuse a change that a browser sends from a page that is not one of the server's own.

    Any page open in the browser can send requests to a port on this machine, and the server makes every
    request the local user's. A browser says where a request comes from, in ``Sec-Fetch-Site`` or, if it
    does not send that, in ``Origin``. A request with neither comes from a program, such as ``curl`` or
    ``airflowctl``, run by a user who could open the project's database anyway, and passes. Pages on other
    ports of this machine count as the same site, so only the same origin is accepted.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if is_change(scope) and is_from_another_page(dict(scope["headers"])):
            refusal: ASGIApp
            if scope["type"] == "websocket":
                refusal = WebSocketClose(code=status.WS_1008_POLICY_VIOLATION)
            else:
                refusal = JSONResponse(
                    {"detail": "This server accepts changes only from its own pages."}, status_code=403
                )
            await refusal(scope, receive, send)
        else:
            await self.app(scope, receive, send)


def is_change(scope: Scope) -> bool:
    """Whether the request may change something: a websocket, whose messages are not checked, or an unsafe method."""
    return scope["type"] == "websocket" or (scope["type"] == "http" and scope["method"] not in SAFE_METHODS)


def is_from_another_page(headers: dict[bytes, bytes]) -> bool:
    if (fetch_site := headers.get(b"sec-fetch-site")) is not None:
        return fetch_site != b"same-origin"
    origin = headers.get(b"origin")
    # The server's origin is the address the browser asked for, which the Host check has accepted.
    return origin is not None and origin != b"http://" + headers.get(b"host", b"")


class LocalUserMiddleware:
    """
    Serve every request from a browser as the local user, an admin, without a login.

    The token replaces any credential the request carries. Changes from pages other than the server's own are
    refused before they get here. Requests to the Execution API come from the scheduler's tasks and keep the
    token of their task instance.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        # One person's project: nothing to keep from them, and the import errors of files with no stored Dag,
        # which the Dag processor reports, are shown to admins only.
        self.user = SimpleAuthManagerUser(username=getpass.getuser(), role="ADMIN")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and not is_execution_api_path(scope["path"]):
            token = get_auth_manager().generate_jwt(self.user)
            headers = [(name, value) for name, value in scope["headers"] if name != b"authorization"]
            scope = {**scope, "headers": [*headers, (b"authorization", f"Bearer {token}".encode())]}
        await self.app(scope, receive, send)


def is_execution_api_path(path: str) -> bool:
    return path == EXECUTION_API_PATH or path.startswith(f"{EXECUTION_API_PATH}/")


def build_app() -> TrustedHostMiddleware:
    app = SameOriginChangesMiddleware(LocalUserMiddleware(create_app(apps="core,execution")))
    return TrustedHostMiddleware(app, allowed_hosts=ALLOWED_HOSTS)


def find_tool_folders(root: Path, home: Path) -> Iterator[Path]:
    """
    Yield the folders of the project that tools keep and that hold no Dags of the project.

    Those are the history, version control, ``node_modules``, caches and virtual environments, at any depth.
    Folders a user may keep in version control, such as ``.github``, are left out: nothing is written there.
    """
    for folder, subfolders, _ in os.walk(root):
        tool_folders = [
            name
            for name in subfolders
            if name in TOOL_FOLDER_NAMES
            or name == home.name
            or os.path.isfile(os.path.join(folder, name, "pyvenv.cfg"))
        ]
        yield from (Path(folder, name) for name in tool_folders)
        subfolders[:] = [name for name in subfolders if name not in tool_folders]


def write_ignore_files(root: Path, home: Path) -> None:
    """
    Keep the Dag processor out of the folders of the project that tools keep.

    It walks the project every few seconds, and imports each file that mentions both Airflow and Dags. Those
    folders hold no Dags of the project, can hold many files, and a virtual environment holds Airflow's own
    source, which would be imported as Dag files.
    """
    pattern = "*" if conf.get("core", "dag_ignore_file_syntax") == "glob" else ".*"
    for folder in find_tool_folders(root, home):
        try:
            (folder / ".airflowignore").write_text(f"{pattern}\n")
        except OSError as e:
            report(
                f"Warning: the Dag processor will look for Dags in {folder}: cannot write its ignore file ({e})"
            )


def build_component_environment(url: str) -> dict[str, str]:
    """
    Return the components' environment: the server's, so they use its database and its JWT secret.

    The scheduler signs each task's token with that secret, and the server's Execution API checks it.
    """
    env = {name: value for name, value in os.environ.items() if name not in PROJECT_SERVER_ENVIRONMENT}
    env |= {
        "AIRFLOW__CORE__EXECUTOR": "LocalExecutor",
        "AIRFLOW__CORE__EXECUTION_API_SERVER_URL": f"{url.rstrip('/')}{EXECUTION_API_PATH}/",
        # As in ``airflow standalone``: look for new Dag files each time a bundle could be refreshed.
        "AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL": str(
            conf.getint("dag_processor", "bundle_refresh_check_interval")
        ),
    }
    return env


def get_component_log_path(home: Path, name: str) -> Path:
    return home / "logs" / f"{name}.log"


def start_components(home: Path, url: str) -> dict[str, subprocess.Popen]:
    """Start the scheduler, the Dag processor and the triggerer, each logging to a file in the history."""
    env = build_component_environment(url)
    (home / "logs").mkdir(exist_ok=True)
    processes = {}
    for name in COMPONENTS:
        log_path = get_component_log_path(home, name)
        # The previous server's log is kept beside this one's; the one before is dropped.
        with suppress(FileNotFoundError):
            log_path.replace(log_path.with_suffix(".log.1"))
        with log_path.open("wb") as log_file:
            processes[name] = subprocess.Popen(
                [sys.executable, "-m", COMPONENTS_MODULE, name],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                # Ctrl-C on the terminal reaches the server alone, which stops each component once.
                start_new_session=True,
            )
    return processes


def stop_components(
    processes: Iterable[subprocess.Popen], *, should_force: Callable[[], bool] = lambda: False
) -> None:
    """
    Ask each component to stop, then kill any remaining components and their descendants.

    ``should_force`` cuts the wait short, e.g. once Ctrl-C is pressed a second time.
    """
    processes = list(processes)
    descendants: set[psutil.Process] = set()
    for process in processes:
        if process.poll() is None:
            # Task tries and operators can start their own groups or sessions. Keep their identities before
            # stopping the component: once their parent exits, they can no longer be found through it.
            descendants.update(find_descendants(process.pid))
            process.terminate()
    deadline = time.monotonic() + COMPONENT_STOP_TIMEOUT
    while any(process.poll() is None for process in processes):
        if should_force() or time.monotonic() >= deadline:
            break
        time.sleep(COMPONENT_POLL_INTERVAL)
    for process in processes:
        if process.poll() is None:
            descendants.update(find_descendants(process.pid))
    for descendant in descendants:
        with suppress(psutil.NoSuchProcess):
            descendant.kill()
    for process in processes:
        if process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    psutil.wait_procs(descendants, timeout=5)


def watch_components(processes: dict[str, subprocess.Popen], home: Path, stop: threading.Event) -> None:
    """Say on the terminal when a component stops while the server runs; otherwise only its log would."""
    running = dict(processes)
    while running and not stop.wait(COMPONENT_POLL_INTERVAL):
        for name, process in list(running.items()):
            if (code := process.poll()) is not None and not stop.is_set():
                del running[name]
                report(
                    f"The {name} stopped (exit code {code}), so the project's Dags are not scheduled until the "
                    f"server is restarted. Its log: {get_component_log_path(home, name)}"
                )


def check_abandoned_runs(home: Path, stop: threading.Event) -> None:
    """Record as failed, while the server runs, each local run whose process ended before the run did."""
    while not stop.wait(ABANDONED_RUN_CHECK_INTERVAL):
        try:
            with project_lock(home), create_session() as session:
                abandoned = fail_abandoned_runs(home, session=session)
            report_abandoned_runs(home, abandoned)
        except Exception:
            log.exception("Could not check for local runs whose process has ended")


class ProjectServer(uvicorn.Server):
    """Serve the project, and run its scheduling components and checks while it serves."""

    def __init__(self, config: uvicorn.Config, *, home: Path, url: str) -> None:
        super().__init__(config)
        self.home = home
        self.url = url
        self.components: dict[str, subprocess.Popen] = {}
        self.stopping = threading.Event()

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets)
        if self.should_exit:
            return
        # The address is recorded so runs in the project can link to their page.
        write_ui_file(self.home, self.url)
        # Once the Execution API serves, which the scheduler's tasks call.
        self.components = start_components(self.home, self.url)
        threading.Thread(
            target=watch_components, args=(self.components, self.home, self.stopping), daemon=True
        ).start()
        threading.Thread(target=check_abandoned_runs, args=(self.home, self.stopping), daemon=True).start()
        print(f"Airflow UI for {self.home.parent}: {self.url}  (Ctrl-C to stop)", flush=True)

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        # Here, not once run() returns: uvicorn re-raises the stopping signal after shutting down, and a
        # re-raised SIGTERM ends the process before run() returns.
        remove_ui_file(self.home)
        self.stopping.set()
        # While the Execution API still serves, so the tasks the scheduler stops can report how they ended.
        await asyncio.to_thread(
            stop_components, self.components.values(), should_force=lambda: self.force_exit
        )
        await super().shutdown(sockets)


def main(argv: list[str]) -> int:
    """Serve until stopped; ``argv`` holds the port to serve on, or nothing to take a free one."""
    home = Path(os.environ["AIRFLOW_HOME"])
    port = int(argv[0]) if argv else 0
    try:
        ensure_database(home)
    except LocalRunSetupError as e:
        report(f"Error: {e}")
        return 2
    sock = socket.socket()
    # As uvicorn does when it binds: a stopped server's closed connections hold its port for up to a minute,
    # and without this the same --port is refused as in use until then.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((LOOPBACK_HOST, port))
    except (OSError, OverflowError) as e:
        sock.close()
        report(
            f"Error: cannot serve on {LOOPBACK_HOST}:{port} ({e}); choose another port, or leave out --port "
            "to use a free one."
        )
        return 2
    url = f"http://{LOOPBACK_HOST}:{sock.getsockname()[1]}/"
    write_ignore_files(Path(settings.DAGS_FOLDER), home)
    config = uvicorn.Config(
        build_app(),
        lifespan="on",
        proxy_headers=False,
        access_log=False,
        log_level="warning",
        log_config=None,
    )
    try:
        ProjectServer(config, home=home, url=url).run(sockets=[sock])
    except KeyboardInterrupt:
        pass
    finally:
        remove_ui_file(home)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
