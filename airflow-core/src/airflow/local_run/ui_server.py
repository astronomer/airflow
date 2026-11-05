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
Serve Airflow's UI on a project's local run history, reachable from this machine only.

Started as ``python -m airflow.local_run.ui_server`` by ``airflow standalone --project``, with the environment
a run's process gets, so the UI reads the project's database and task logs.
"""

from __future__ import annotations

import getpass
import os
import socket
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from starlette.middleware.trustedhost import TrustedHostMiddleware

from airflow.api_fastapi.app import create_app, get_auth_manager
from airflow.api_fastapi.auth.managers.simple.user import SimpleAuthManagerUser
from airflow.local_run.runner import LocalRunSetupError, ensure_database, report
from airflow.local_run.ui import remove_ui_file, write_ui_file

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

LOOPBACK_HOST = "127.0.0.1"
# The names a browser on this machine reaches the server by. A page on another site that makes its own name
# resolve to this address (DNS rebinding) still sends that name, so its requests are refused.
ALLOWED_HOSTS = (LOOPBACK_HOST, "localhost")


class ViewerMiddleware:
    """
    Serve every request as a viewer, without a login.

    No scheduler runs, so a run triggered or cleared in the UI would wait forever; a viewer's changes are
    refused instead. The token replaces any credential the request carries, so no request is more than a
    viewer.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.user = SimpleAuthManagerUser(username=getpass.getuser(), role="VIEWER")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            token = get_auth_manager().generate_jwt(self.user)
            headers = [(name, value) for name, value in scope["headers"] if name != b"authorization"]
            scope = {**scope, "headers": [*headers, (b"authorization", f"Bearer {token}".encode())]}
        await self.app(scope, receive, send)


def build_app() -> TrustedHostMiddleware:
    app = ViewerMiddleware(create_app(apps="core"))
    return TrustedHostMiddleware(app, allowed_hosts=ALLOWED_HOSTS)


class HistoryServer(uvicorn.Server):
    """Record the server's address while it serves, so runs in the project can link to their page."""

    def __init__(self, config: uvicorn.Config, *, home: Path, url: str) -> None:
        super().__init__(config)
        self.home = home
        self.url = url

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets)
        write_ui_file(self.home, self.url)
        print(f"Airflow UI for {self.home.parent}: {self.url}  (Ctrl-C to stop)", flush=True)

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        # Here, not once run() returns: uvicorn re-raises the stopping signal after shutting down, and a
        # re-raised SIGTERM ends the process before run() returns.
        remove_ui_file(self.home)
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
    config = uvicorn.Config(
        build_app(),
        lifespan="on",
        proxy_headers=False,
        access_log=False,
        log_level="warning",
        log_config=None,
    )
    try:
        HistoryServer(config, home=home, url=url).run(sockets=[sock])
    except KeyboardInterrupt:
        pass
    finally:
        remove_ui_file(home)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
