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
Private Postgres and MySQL servers for one checkout.

Each server listens on 127.0.0.1 only and trusts its local admin account; it is a development
database for one user, not a shared service. Data lives under ``.build/airflow-dev/db/``.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from airflow_dev.discovery import Installation, select_installation
from airflow_dev.repo import DevError, get_pinned_requirements

if TYPE_CHECKING:
    from collections.abc import Iterator

TEST_DATABASE_PREFIX = "airflow_test_"
STARTUP_TIMEOUT = 60
# Unix socket paths are limited to about 104 bytes on macOS.
MAX_SOCKET_PATH = 100


def build_client_env() -> dict[str, str]:
    """Drop client settings that could point a command at another server."""
    return {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("PG", "MYSQL")) and name not in {"LIBMYSQL_ENABLE_CLEARTEXT_PLUGIN"}
    }


def run(command: list[str], *, input: str | None = None, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            command,
            input=input,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=build_client_env(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise DevError(f"{Path(command[0]).name} timed out after {timeout}s.", exit_code=3)
    if result.returncode != 0:
        raise DevError(
            f"{Path(command[0]).name} failed: {(result.stderr or result.stdout).strip()}", exit_code=3
        )
    return result.stdout


def get_free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def is_pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Server:
    engine: str
    drivers: list[str]

    def __init__(self, repo: Path, installation: Installation):
        self.repo = repo
        self.installation = installation
        self.directory = repo / ".build" / "airflow-dev" / "db" / f"{self.engine}-{installation.major}"
        self.data_dir = self.directory / "data"
        self.state_file = self.directory / "server.json"
        self.log_file = self.directory / "server.log"

    @property
    def name(self) -> str:
        return f"{self.engine}-{self.installation.major}"

    def read_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return {}

    def write_state(self, **values) -> None:
        state = {**self.read_state(), **values}
        self.state_file.write_text(json.dumps(state, indent=2))

    @property
    def port(self) -> int:
        return self.read_state()["port"]

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / ".lock").open("w") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            yield

    def ensure_running(self) -> None:
        with self.lock():
            state = self.read_state()
            if not state.get("initialized"):
                if self.data_dir.exists():
                    raise DevError(
                        f"{self.data_dir} exists but was never fully initialized.",
                        hint=f"Remove {self.directory} and retry.",
                        exit_code=3,
                    )
                self.write_state(
                    port=get_free_port(),
                    version=self.installation.version,
                    bin_dir=str(self.installation.bin_dir),
                    client_dir=str(self.installation.client_dir),
                )
                self.initialize()
                self.write_state(initialized=True)
            if not self.is_running():
                self.start()
                self.wait_until_ready()

    def wait_until_ready(self) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self.is_ready():
                return
            time.sleep(0.2)
        raise DevError(f"{self.name} did not become ready.", hint=f"See {self.log_file}.", exit_code=3)

    def is_ready(self) -> bool:
        try:
            self.execute("SELECT 1")
        except DevError:
            return False
        return True

    def status(self) -> dict:
        state = self.read_state()
        running = bool(state.get("initialized")) and self.is_running()
        return {
            "name": self.name,
            **self.installation.to_dict(),
            "directory": str(self.directory),
            "initialized": bool(state.get("initialized")),
            "running": running,
            "port": state.get("port"),
            "url": self.get_url("<database>") if state.get("port") else None,
            "test_databases": self.list_databases(TEST_DATABASE_PREFIX) if running else [],
        }

    def get_driver_requirements(self) -> list[str]:
        return get_pinned_requirements(self.repo, self.drivers)

    # Engine-specific operations.
    def initialize(self) -> None:
        raise NotImplementedError

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def is_running(self) -> bool:
        raise NotImplementedError

    def execute(self, sql: str, database: str | None = None) -> str:
        raise NotImplementedError

    def create_database(self, name: str) -> None:
        raise NotImplementedError

    def drop_database(self, name: str) -> None:
        raise NotImplementedError

    def list_databases(self, prefix: str) -> list[str]:
        raise NotImplementedError

    def get_url(self, database: str) -> str:
        raise NotImplementedError


class Postgres(Server):
    engine = "postgres"
    drivers = ["psycopg", "psycopg-binary"]

    def pg(self, name: str) -> str:
        return str(self.installation.get_executable(name))

    def initialize(self) -> None:
        run(
            [
                self.pg("initdb"),
                f"--pgdata={self.data_dir}",
                "--username=postgres",
                "--auth=trust",
                "--encoding=UTF8",
                "--locale=C",
                "--no-instructions",
            ],
            timeout=120,
        )

    def start(self) -> None:
        # TCP only: an empty socket directory list avoids Unix socket path-length limits.
        options = f"-h 127.0.0.1 -p {self.port} -k '' -c fsync=off -c full_page_writes=off"
        run(
            [
                self.pg("pg_ctl"),
                "start",
                f"--pgdata={self.data_dir}",
                f"--log={self.log_file}",
                f"--options={options}",
                "--wait",
                f"--timeout={STARTUP_TIMEOUT}",
            ],
            timeout=STARTUP_TIMEOUT + 5,
        )

    def stop(self) -> None:
        with self.lock():
            if self.is_running():
                run(
                    [self.pg("pg_ctl"), "stop", f"--pgdata={self.data_dir}", "--mode=fast", "--wait"],
                    timeout=40,
                )

    def is_running(self) -> bool:
        if not self.data_dir.exists():
            return False
        result = subprocess.run(
            [self.pg("pg_ctl"), "status", f"--pgdata={self.data_dir}"],
            capture_output=True,
            env=build_client_env(),
            check=False,
        )
        return result.returncode == 0

    def execute(self, sql: str, database: str | None = None) -> str:
        return run(
            [
                self.pg("psql"),
                "--no-psqlrc",
                "--quiet",
                "--no-align",
                "--tuples-only",
                "--set=ON_ERROR_STOP=1",
                "--host=127.0.0.1",
                f"--port={self.port}",
                "--username=postgres",
                f"--dbname={database or 'postgres'}",
                f"--command={sql}",
            ],
            timeout=60,
        )

    def create_database(self, name: str) -> None:
        self.execute(f"CREATE DATABASE \"{name}\" TEMPLATE template0 ENCODING 'UTF8'")

    def drop_database(self, name: str) -> None:
        self.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    def list_databases(self, prefix: str) -> list[str]:
        output = self.execute(f"SELECT datname FROM pg_database WHERE starts_with(datname, '{prefix}')")
        return sorted(line for line in output.splitlines() if line)

    def get_url(self, database: str) -> str:
        return f"postgresql+psycopg://postgres@127.0.0.1:{self.port}/{database}"


class MySQL(Server):
    engine = "mysql"
    drivers = ["pymysql", "aiomysql"]

    @property
    def socket_path(self) -> Path:
        path = self.directory / "mysqld.sock"
        if len(str(path)) <= MAX_SOCKET_PATH:
            return path
        digest = hashlib.sha1(str(self.directory).encode()).hexdigest()[:12]
        return Path("/tmp") / f"airflow-dev-{digest}.sock"

    @property
    def pid_file(self) -> Path:
        return self.directory / "mysqld.pid"

    def get_server_args(self) -> list[str]:
        mysqld = self.installation.get_executable("mysqld")
        return [
            str(mysqld),
            "--no-defaults",
            f"--basedir={mysqld.resolve().parent.parent}",
            f"--datadir={self.data_dir}",
            "--character-set-server=utf8mb4",
            "--collation-server=utf8mb4_unicode_ci",
            # Breeze's scripts/ci/mysql/conf.d settings that tests depend on.
            "--explicit-defaults-for-timestamp=1",
            "--local-infile=1",
            "--innodb-print-all-deadlocks=1",
        ]

    def mysql_client(self, name: str, *, tcp: bool = True) -> list[str]:
        connection = (
            ["--protocol=TCP", "--host=127.0.0.1", f"--port={self.port}"]
            if tcp
            else ["--protocol=SOCKET", f"--socket={self.socket_path}"]
        )
        return [str(self.installation.get_executable(name)), "--no-defaults", "--user=root", *connection]

    def initialize(self) -> None:
        self.data_dir.parent.mkdir(parents=True, exist_ok=True)
        run([*self.get_server_args(), "--initialize-insecure"], timeout=180)
        # --initialize-insecure creates root@localhost only; add root@127.0.0.1 for TCP clients.
        self.start()
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while True:
            try:
                run(
                    [*self.mysql_client("mysql", tcp=False), "--batch"],
                    input=(
                        "CREATE USER IF NOT EXISTS 'root'@'127.0.0.1';\n"
                        "GRANT ALL PRIVILEGES ON *.* TO 'root'@'127.0.0.1' WITH GRANT OPTION;\n"
                    ),
                )
                return
            except DevError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)

    def start(self) -> None:
        with self.log_file.open("ab") as log:
            subprocess.Popen(
                [
                    *self.get_server_args(),
                    "--bind-address=127.0.0.1",
                    f"--port={self.port}",
                    f"--socket={self.socket_path}",
                    f"--pid-file={self.pid_file}",
                    "--mysqlx=0",
                    "--skip-log-bin",
                    "--skip-name-resolve",
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=build_client_env(),
                start_new_session=True,
            )

    def get_pid(self) -> int | None:
        try:
            return int(self.pid_file.read_text().strip())
        except (OSError, ValueError):
            return None

    def is_running(self) -> bool:
        return is_pid_alive(self.get_pid())

    def stop(self) -> None:
        with self.lock():
            pid = self.get_pid()
            if not is_pid_alive(pid):
                return
            with contextlib.suppress(DevError):
                run([*self.mysql_client("mysqladmin"), "shutdown"])
            deadline = time.monotonic() + 30
            while is_pid_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.2)
            if is_pid_alive(pid):
                os.kill(pid, signal.SIGKILL)  # type: ignore[arg-type]

    def execute(self, sql: str, database: str | None = None) -> str:
        command = [*self.mysql_client("mysql"), "--batch", "--skip-column-names", f"--execute={sql}"]
        if database:
            command.append(database)
        return run(command)

    def create_database(self, name: str) -> None:
        self.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")

    def drop_database(self, name: str) -> None:
        self.execute(f"DROP DATABASE IF EXISTS `{name}`")

    def list_databases(self, prefix: str) -> list[str]:
        output = self.execute(
            "SELECT schema_name FROM information_schema.schemata "
            f"WHERE schema_name LIKE '{prefix.replace('_', chr(92) + '_')}%'"
        )
        return sorted(line for line in output.splitlines() if line)

    def get_url(self, database: str) -> str:
        # Some migrations send several statements in one call, which mysqlclient (CI's driver)
        # allows by default; PyMySQL needs CLIENT.MULTI_STATEMENTS (1 << 16) asked for.
        return f"mysql+pymysql://root@127.0.0.1:{self.port}/{database}?charset=utf8mb4&client_flag=65536"


SERVERS: dict[str, type[Server]] = {"postgres": Postgres, "mysql": MySQL}


def get_server(repo: Path, backend: str, version: str | None) -> Server:
    return SERVERS[backend](repo, select_installation(repo, backend, version))


def load_known_servers(repo: Path) -> list[Server]:
    """Return every server this checkout has initialized, using the binaries it was created with."""
    servers = []
    for directory in sorted((repo / ".build" / "airflow-dev" / "db").glob("*-*")):
        try:
            state = json.loads((directory / "server.json").read_text())
            engine = directory.name.split("-", 1)[0]
            installation = Installation(
                engine, state["version"], Path(state["bin_dir"]), Path(state["client_dir"])
            )
        except (OSError, ValueError, KeyError):
            continue
        if engine in SERVERS and state.get("initialized"):
            servers.append(SERVERS[engine](repo, installation))
    return servers
