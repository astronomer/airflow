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
A persistent Airflow instance from the checkout's sources: plain ``airflow standalone``.

Each backend and database version gets its own home and database, kept across stops. The UI is
built with the repository's own ``compile_ui_assets.py``, which skips unchanged sources.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from airflow_dev.db import Server, get_free_port, get_server, is_pid_alive
from airflow_dev.discovery import find_frontend_tools
from airflow_dev.repo import DevError

INSTANCE_DATABASE = "airflow_instance"
# The standard provider's workspace sources pull in core and the Task SDK, so examples can run.
RUNTIME_MEMBER = "providers/standard"
HEALTH_COMPONENTS = ("metadatabase", "scheduler", "triggerer", "dag_processor")
STOP_TIMEOUT = 45


@dataclass
class Instance:
    repo: Path
    backend: str
    server: Server | None

    @property
    def name(self) -> str:
        return self.server.name if self.server else "sqlite"

    @property
    def home(self) -> Path:
        return self.repo / ".build" / "airflow-dev" / "instances" / self.name

    @property
    def state_file(self) -> Path:
        return self.home / "instance.json"

    @property
    def log_file(self) -> Path:
        return self.home / "standalone.log"

    def read_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return {}

    def is_running(self) -> bool:
        return is_pid_alive(self.read_state().get("pid"))

    def build_env(self, *, port: int, dags_folder: Path, examples: bool) -> dict[str, str]:
        env = {name: value for name, value in os.environ.items() if not name.startswith("AIRFLOW")}
        env.update(
            AIRFLOW_HOME=str(self.home),
            AIRFLOW__API__PORT=str(port),
            AIRFLOW__CORE__DAGS_FOLDER=str(dags_folder),
            AIRFLOW__CORE__LOAD_EXAMPLES=str(examples),
            AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS="True",
            # Fixed defaults (8793, 8794) would stop two instances from running side by side.
            AIRFLOW__LOGGING__WORKER_LOG_SERVER_PORT=str(get_free_port()),
            AIRFLOW__LOGGING__TRIGGER_LOG_SERVER_PORT=str(get_free_port()),
            # standalone's output goes to a log file; keep it current for `airflow-dev logs`.
            PYTHONUNBUFFERED="1",
        )
        if self.server:
            env["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"] = self.server.get_url(INSTANCE_DATABASE)
        return env

    def build_command(self) -> list[str]:
        with_args = []
        if self.server:
            for requirement in self.server.get_driver_requirements():
                with_args += ["--with", requirement]
        return ["uv", "run", "--project", RUNTIME_MEMBER, *with_args, "airflow", "standalone"]

    def get_health(self) -> dict | None:
        port = self.read_state().get("port")
        if not port:
            return None
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v2/monitor/health", timeout=3) as r:
                return json.loads(r.read())
        except (OSError, ValueError, urllib.error.URLError):
            return None

    def status(self) -> dict:
        state = self.read_state()
        health = self.get_health() if self.is_running() else None
        return {
            "name": self.name,
            "running": self.is_running(),
            "healthy": is_healthy(health),
            "url": f"http://127.0.0.1:{state['port']}" if state.get("port") else None,
            "pid": state.get("pid"),
            "home": str(self.home),
            "log": str(self.log_file),
            "dags_folder": state.get("dags_folder"),
            "database": self.server.get_url(INSTANCE_DATABASE) if self.server else "sqlite (in home)",
            "health": health,
        }


def is_healthy(health: dict | None) -> bool:
    return bool(health) and all(
        (health.get(name) or {}).get("status") == "healthy"  # type: ignore[union-attr]
        for name in HEALTH_COMPONENTS
    )


def get_instance(repo: Path, backend: str, db_version: str | None) -> Instance:
    server = get_server(repo, backend, db_version) if backend in ("postgres", "mysql") else None
    return Instance(repo, backend, server)


def is_port_free(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def build_ui(repo: Path, *, log) -> None:
    tools = find_frontend_tools(repo)
    bin_dirs = [tools["node_dir"]]
    if tools["pnpm_source"] == "corepack":
        shim_dir = repo / ".build" / "airflow-dev" / "bin"
        shim_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [tools["pnpm"], "enable", "pnpm", "--install-directory", str(shim_dir)],
            check=True,
            env={**os.environ, "PATH": os.pathsep.join([tools["node_dir"], os.environ["PATH"]])},
        )
        bin_dirs.insert(0, str(shim_dir))
    env = {
        **os.environ,
        "PATH": os.pathsep.join([*bin_dirs, os.environ["PATH"]]),
        "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
    }
    print(
        f"airflow-dev: building UI assets with Node {tools['node_version']} and pnpm {tools['pnpm_version']}",
        file=sys.stderr,
    )
    result = subprocess.run(
        ["uv", "run", "--project", "scripts", "python", "scripts/ci/prek/compile_ui_assets.py"],
        cwd=repo,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise DevError(
            "Building the UI failed.", hint=f"See {getattr(log, 'name', 'the output')}.", exit_code=3
        )


def start(
    instance: Instance,
    *,
    port: int,
    dags_folder: Path | None,
    examples: bool,
    background: bool,
    timeout: int,
) -> dict:
    if instance.is_running():
        raise DevError(f"Instance {instance.name} is already running.", hint="airflow-dev status")
    if not is_port_free(port):
        raise DevError(f"Port {port} is in use.", hint="Pass --port with a free port.")
    instance.home.mkdir(parents=True, exist_ok=True)
    dags = (dags_folder or instance.home / "dags").resolve()
    dags.mkdir(parents=True, exist_ok=True)
    with instance.log_file.open("a") as log:
        build_ui(instance.repo, log=log if background else sys.stderr)
    if instance.server:
        instance.server.ensure_running()
        if INSTANCE_DATABASE not in instance.server.list_databases(INSTANCE_DATABASE):
            instance.server.create_database(INSTANCE_DATABASE)
    env = instance.build_env(port=port, dags_folder=dags, examples=examples)
    state = {"port": port, "dags_folder": str(dags), "backend": instance.backend}
    if not background:
        process = subprocess.Popen(instance.build_command(), cwd=instance.repo, env=env)
        # Foreground: the terminal's job group, so `stop` from another shell ends this job too.
        state["pgid"] = os.getpgid(0)
        instance.state_file.write_text(json.dumps({**state, "pid": process.pid}))
        try:
            return {"exit_code": process.wait()}
        except KeyboardInterrupt:
            # The terminal's SIGINT reaches standalone too; wait for its own shutdown.
            return {"exit_code": process.wait()}
        finally:
            instance.state_file.unlink(missing_ok=True)
    with instance.log_file.open("a") as log:
        process = subprocess.Popen(
            instance.build_command(),
            cwd=instance.repo,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    instance.state_file.write_text(json.dumps({**state, "pid": process.pid, "pgid": process.pid}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise DevError(
                f"airflow standalone exited with code {process.returncode}.",
                hint=f"See {instance.log_file}.",
                exit_code=3,
            )
        if is_healthy(instance.get_health()):
            return instance.status()
        time.sleep(1)
    stop_group(process.pid, process.pid, reap=process.poll)
    process.wait()
    instance.state_file.unlink(missing_ok=True)
    raise DevError(
        f"Instance {instance.name} was not healthy within {timeout}s and was stopped.",
        hint=f"See {instance.log_file}.",
        exit_code=3,
    )


def signal_group(pgid: int, signum: int) -> bool:
    """Signal a process group; return whether any process was left in it."""
    try:
        os.killpg(pgid, signum)
    except ProcessLookupError:
        return False
    return True


def stop_group(pid: int, pgid: int, reap=None) -> None:
    """
    SIGTERM ``uv``, wait for the whole group to exit, then SIGKILL whatever is left.

    Only ``uv`` is signalled: it forwards SIGTERM to standalone, which stops its components itself.
    Signalling the whole group would hit standalone twice (directly and through ``uv``), and the
    second signal arrives after standalone has restored the default handler, killing it mid-shutdown.
    """
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_TIMEOUT
    while time.monotonic() < deadline:
        if reap:
            reap()
        if not signal_group(pgid, 0):
            return
        time.sleep(0.5)
    signal_group(pgid, signal.SIGKILL)


def stop(instance: Instance) -> bool:
    """Stop the instance's process group. Return whether anything was running."""
    state = instance.read_state()
    if not is_pid_alive(state.get("pid")) and not (state.get("pgid") and signal_group(state["pgid"], 0)):
        instance.state_file.unlink(missing_ok=True)
        return False
    stop_group(state["pid"], state["pgid"])
    instance.state_file.unlink(missing_ok=True)
    return True


def tail(path: Path, lines: int) -> str:
    try:
        return "".join(path.read_text(errors="replace").splitlines(keepends=True)[-lines:])
    except OSError:
        return ""


def follow(path: Path) -> None:
    with path.open(errors="replace") as file:
        file.seek(0, os.SEEK_END)
        try:
            while True:
                line = file.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            return
