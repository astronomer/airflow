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
``airflow-dev test``: run pytest for one workspace member on a chosen database.

Test selection, database initialization and markers stay with the repository's own pytest plugin
(``tests_common.pytest_plugin``). This module only provides a fresh home and database per run, or per
xdist worker, and removes them afterwards.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from airflow_dev.db import TEST_DATABASE_PREFIX, Server, get_server, is_pid_alive, load_known_servers
from airflow_dev.repo import DevError, find_member, get_pinned_requirements

BACKENDS = ("none", "sqlite", "postgres", "mysql")
NO_DATABASE_MEMBERS = {"task-sdk"}
CLEARED_VARIABLES = {"BACKEND", "PYTEST_ADDOPTS", "_AIRFLOW_SKIP_DB_TESTS", "_AIRFLOW_RUN_DB_TESTS_ONLY"}
# Test dependencies a member's own dependency groups leave to the CI image. Without rfc3339-validator,
# jsonschema skips the date-time format check that task-sdk's Param tests expect to fail.
EXTRA_TEST_REQUIREMENTS = {"task-sdk": ["rfc3339-validator"]}
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
GREEN, RED, BOLD, RESET = "\x1b[32m", "\x1b[31m", "\x1b[1m", "\x1b[0m"


def use_color(output) -> bool:
    return "NO_COLOR" not in os.environ and output.isatty()


@dataclass
class PytestRun:
    repo: Path
    member: str
    targets: list[str]
    backend: str
    workers: int
    pytest_args: list[str]
    server: Server | None = None
    color: bool = False
    run_id: str = field(default_factory=lambda: f"{TEST_DATABASE_PREFIX}{uuid.uuid4().hex[:10]}")

    @property
    def home_root(self) -> Path:
        return self.repo / ".build" / "airflow-dev" / "runs" / self.run_id

    @property
    def results_dir(self) -> Path:
        return self.repo / "files" / "airflow-dev" / "runs" / self.run_id

    @property
    def worker_names(self) -> list[str]:
        return ["main", *(f"gw{index}" for index in range(self.workers if self.workers > 1 else 0))]

    @property
    def database_names(self) -> list[str]:
        return [f"{self.run_id}_{worker}" for worker in self.worker_names] if self.server else []

    def build_env(self) -> dict[str, str]:
        env = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith("AIRFLOW") and name not in CLEARED_VARIABLES
        }
        env["AIRFLOW_DEV_HOME_TEMPLATE"] = str(self.home_root / "{worker}")
        if self.backend != "none":
            env["BACKEND"] = self.backend
        if self.server:
            env["AIRFLOW_DEV_DB_URL_TEMPLATE"] = self.server.get_url(f"{self.run_id}_{{worker}}")
        return env

    def build_command(self) -> list[str]:
        requirements = get_pinned_requirements(self.repo, EXTRA_TEST_REQUIREMENTS.get(self.member, []))
        if self.server:
            requirements += self.server.get_driver_requirements()
        with_args = [arg for requirement in requirements for arg in ("--with", requirement)]
        pytest_args = [*self.targets]
        if self.backend == "none":
            pytest_args.append("--skip-db-tests")
        if self.workers > 1:
            pytest_args += ["-n", str(self.workers)]
        if self.color:
            # pytest writes to our pipe, not the terminal, so it would turn colors off by itself.
            # Before the user's arguments, so a --color of theirs wins.
            pytest_args.append("--color=yes")
        pytest_args += ["--junitxml", str(self.results_dir / "junit.xml"), *self.pytest_args]
        return ["uv", "run", "--project", self.member, *with_args, "pytest", *pytest_args]

    def prepare(self) -> None:
        for worker in self.worker_names:
            (self.home_root / worker).mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        owner = {
            "pid": os.getpid(),
            "server_dir": str(self.server.directory) if self.server else None,
            "databases": self.database_names,
        }
        (self.home_root / "owner.json").write_text(json.dumps(owner))
        if self.server:
            self.server.ensure_running()
            for database in self.database_names:
                self.server.create_database(database)

    def cleanup(self) -> None:
        if self.server:
            for database in self.database_names:
                with contextlib.suppress(DevError):
                    self.server.drop_database(database)
        shutil.rmtree(self.home_root, ignore_errors=True)


def resolve_targets(repo: Path, cwd: Path, targets: list[str]) -> tuple[str, list[str]]:
    """Return the owning member and the targets as repo-relative pytest node IDs."""
    members = set()
    resolved = []
    for target in targets:
        path_part, separator, node_suffix = target.partition("::")
        path = (cwd / path_part).resolve()
        if not path.exists():
            raise DevError(f"Test target {target} does not exist.")
        members.add(find_member(repo, path))
        resolved.append(path.relative_to(repo).as_posix() + separator + node_suffix)
    if len(members) != 1:
        raise DevError(
            f"Targets span {', '.join(sorted(members))}.", hint="Run one workspace member at a time."
        )
    return members.pop(), resolved


def stream(command: list[str], *, cwd: Path, env: dict[str, str], log_path: Path, output) -> int:
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    def forward_sigterm(signum, frame):
        process.send_signal(signal.SIGTERM)

    previous = signal.signal(signal.SIGTERM, forward_sigterm)
    try:
        with log_path.open("w") as log:
            for line in process.stdout:  # type: ignore[union-attr]
                output.write(line)
                output.flush()
                log.write(ANSI_ESCAPE.sub("", line))
        return process.wait()
    except KeyboardInterrupt:
        # The terminal already sent SIGINT to pytest, which shares our process group.
        return process.wait()
    finally:
        signal.signal(signal.SIGTERM, previous)


def run_tests(
    repo: Path,
    cwd: Path,
    targets: list[str],
    *,
    backend: str | None,
    db_version: str | None,
    workers: int,
    keep_db: bool,
    pytest_args: list[str],
    as_json: bool,
) -> int:
    member, node_ids = resolve_targets(repo, cwd, targets)
    backend = backend or ("none" if member in NO_DATABASE_MEMBERS else "sqlite")
    if member in NO_DATABASE_MEMBERS and backend != "none":
        raise DevError(f"{member} tests never use the metadata database.", hint="Use --backend none.")
    server = get_server(repo, backend, db_version) if backend in ("postgres", "mysql") else None
    # With --json, stdout carries only the summary document, so pytest's output goes to stderr.
    output = sys.stderr if as_json else sys.stdout
    pytest_run = PytestRun(
        repo, member, node_ids, backend, workers, pytest_args, server, color=use_color(output)
    )
    exit_code = 3
    try:
        pytest_run.prepare()
        log_path = pytest_run.results_dir / "pytest.log"
        exit_code = stream(
            pytest_run.build_command(),
            cwd=repo,
            env=pytest_run.build_env(),
            log_path=log_path,
            output=output,
        )
    finally:
        if not keep_db:
            pytest_run.cleanup()
    summary = {
        "exit_code": exit_code,
        "run_id": pytest_run.run_id,
        "member": member,
        "backend": backend,
        "db_version": server.installation.version if server else None,
        "workers": workers,
        "junit": str(pytest_run.results_dir / "junit.xml"),
        "log": str(pytest_run.results_dir / "pytest.log"),
        "kept": {"home": str(pytest_run.home_root), "databases": pytest_run.database_names}
        if keep_db
        else None,
    }
    if as_json:
        print(json.dumps(summary, indent=2))
    else:
        print(format_summary(summary, color=use_color(sys.stderr)), file=sys.stderr)
    return exit_code


def format_summary(summary: dict, *, color: bool) -> str:
    db_version = f" {summary['db_version']}" if summary["db_version"] else ""
    result = f"exited {summary['exit_code']}"
    if color:
        result = f"{BOLD}{GREEN if summary['exit_code'] == 0 else RED}{result}{RESET}"
    return (
        f"\nairflow-dev: {summary['member']} on {summary['backend']}{db_version} {result};"
        f" JUnit {summary['junit']}"
    )


def prune(repo: Path) -> list[str]:
    """Drop databases and homes left by runs whose airflow-dev process is gone."""
    removed: list[str] = []
    live_runs = set()
    for run_dir in sorted((repo / ".build" / "airflow-dev" / "runs").glob(f"{TEST_DATABASE_PREFIX}*")):
        try:
            owner = json.loads((run_dir / "owner.json").read_text())
        except (OSError, ValueError):
            owner = {}
        if is_pid_alive(owner.get("pid")):
            live_runs.add(run_dir.name)
            continue
        shutil.rmtree(run_dir, ignore_errors=True)
        removed.append(str(run_dir))
    for server in load_known_servers(repo):
        if not server.is_running():
            continue
        for database in server.list_databases(TEST_DATABASE_PREFIX):
            if database.rsplit("_", 1)[0] not in live_runs:
                server.drop_database(database)
                removed.append(f"{server.name}/{database}")
    return removed
