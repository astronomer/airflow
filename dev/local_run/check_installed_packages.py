#!/usr/bin/env python3
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
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Check that the "Run Dags locally" guide works with Airflow installed from wheels built from this checkout.

Builds the wheels, creates a project outside the repository with ``airflow bootstrap`` run by ``uvx`` from
them, installs them there, and follows the guide with the example Dag ``airflow bootstrap`` wrote: running
the file, ``airflow run``, rerunning one task with it, and ``airflow standalone --project``
serving the runs and scheduling a run triggered through the API. Packages the guide does not build come from
PyPI, as they would for a new user.

    uv run dev/local_run/check_installed_packages.py [--wheels DIR] [--keep]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# What `uv add apache-airflow` brings in that this checkout changes.
PACKAGES = (
    "apache-airflow",
    "apache-airflow-core",
    "apache-airflow-task-sdk",
    "apache-airflow-providers-standard",
    "apache-airflow-providers-common-compat",
)
SERVER_TIMEOUT = 180.0


class CheckFailed(Exception):
    """A step of the guide did not do what the guide says."""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--wheels", type=Path, help="install these wheels instead of building them")
    parser.add_argument("--keep", action="store_true", help="keep the project folder for a look afterwards")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="airflow-installed-check-"))
    try:
        wheels = args.wheels or build_wheels(work / "wheels")
        env = build_environment(work)
        project = create_project(work, wheels, env=env)
        check_the_guide(project, env=env)
    except CheckFailed as e:
        print(f"FAILED: {e}", file=sys.stderr)
        print(f"The project is kept in {work}", file=sys.stderr)
        return 1
    if args.keep:
        print(f"The project is kept in {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    print("The guide works with the installed packages.")
    return 0


def build_wheels(out_dir: Path) -> Path:
    for package in PACKAGES:
        step(f"Building {package}")
        run(["uv", "build", "--wheel", "--package", package, "--out-dir", str(out_dir)], cwd=REPO_ROOT)
    return out_dir


def create_project(work: Path, wheels: Path, *, env: dict[str, str]) -> Path:
    step("uvx --from apache-airflow-core airflow bootstrap demo")
    core_wheels = sorted(str(path) for path in wheels.glob("apache_airflow_core-*.whl"))
    if not core_wheels:
        raise CheckFailed(f"no apache-airflow-core wheel in {wheels}")
    core_wheel = core_wheels[0]
    wheel_files = sorted(str(path) for path in wheels.glob("*.whl"))
    # The rest of this checkout's wheels, since apache-airflow-core needs their unreleased versions.
    with_wheels = [f"--with={path}" for path in wheel_files if path != core_wheel]
    result = run(
        ["uvx", "--from", core_wheel, *with_wheels, "airflow", "bootstrap", "demo"],
        cwd=work,
        env=env,
    )
    project = work / "demo"
    expect((project / "pipeline.py").exists(), "airflow bootstrap wrote no pipeline.py", result)
    expect(
        not Path(env["AIRFLOW_HOME"], "airflow.cfg").exists(),
        "airflow bootstrap wrote an airflow.cfg",
        result,
    )

    step("Installing the wheels")
    run(["uv", "add", *wheel_files], cwd=project, env=env)
    return project


def build_environment(work: Path) -> dict[str, str]:
    """A new user's environment: no Airflow settings, and an Airflow home that is not the developer's."""
    env = {
        name: value for name, value in os.environ.items() if not name.startswith(("AIRFLOW_", "VIRTUAL_ENV"))
    }
    env["AIRFLOW_HOME"] = str(work / "airflow-home")
    return env


def check_the_guide(project: Path, *, env: dict[str, str]) -> None:
    step("uv run pipeline.py")
    result = run(["uv", "run", "pipeline.py"], cwd=project, env=env)
    expect("total: 12" in result.stdout, "the script did not print `total: 12`", result)
    expect("Succeeded in" in result.stderr, "the run did not report success", result)
    expect((project / ".airflow" / "airflow.db").exists(), "no history in .airflow/", result)

    step("uv run airflow run pipeline.py")
    result = run(["uv", "run", "airflow", "run", "pipeline.py"], cwd=project, env=env)
    expect("Succeeded in" in result.stderr, "airflow run did not report success", result)

    step("uv run airflow run pipeline.py --task total")
    result = run(["uv", "run", "airflow", "run", "pipeline.py", "--task", "total"], cwd=project, env=env)
    expect("total (try 2)" in result.stderr, "the rerun did not run total as its second try", result)
    expect("total = 12" in result.stdout, "the rerun did not print `total = 12`", result)

    step("uv run airflow standalone --project")
    port = find_free_port()
    url = f"http://127.0.0.1:{port}/"
    with (project.parent / "server.log").open("w") as server_log:
        server = subprocess.Popen(
            ["uv", "run", "airflow", "standalone", "--project", "--port", str(port)],
            cwd=project,
            env=env,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
    try:
        wait_until(
            lambda: get_json(f"{url}api/v2/dags/example") is not None, server, "the server to serve the Dag"
        )
        runs = get_json(f"{url}api/v2/dags/example/dagRuns") or {}
        states = sorted(run["state"] for run in runs.get("dag_runs", []))
        expect(states == ["success", "success"], f"the UI shows runs {states}, not the two local ones")

        result = run(["uv", "run", "pipeline.py"], cwd=project, env=env)
        expect(
            f"View it at {url}dags/example/runs/" in result.stderr, "the run did not link to its page", result
        )

        # As the UI's pause toggle and Trigger button do; the scheduler then runs the triggered run.
        send_json("PATCH", f"{url}api/v2/dags/example", {"is_paused": False})
        triggered = send_json("POST", f"{url}api/v2/dags/example/dagRuns", {"logical_date": None})
        run_url = f"{url}api/v2/dags/example/dagRuns/{urllib.parse.quote(triggered['dag_run_id'], safe='')}"
        wait_until(
            lambda: (get_json(run_url) or {}).get("state") == "success",
            server,
            "the triggered run to succeed",
        )

        server.send_signal(signal.SIGINT)
        try:
            code = server.wait(timeout=90)
        except subprocess.TimeoutExpired:
            raise CheckFailed("the server did not stop within 90 seconds of Ctrl-C") from None
        expect(code == 0, f"the server exited with {code}")
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()


def step(message: str) -> None:
    print(f"==> {message}", flush=True)


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(command, check=False, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise CheckFailed(
            f"`{' '.join(command)}` exited with {result.returncode}\n{result.stdout}{result.stderr}"
        )
    return result


def expect(condition: bool, message: str, result: subprocess.CompletedProcess | None = None) -> None:
    if not condition:
        output = f"\n{result.stdout}{result.stderr}" if result is not None else ""
        raise CheckFailed(f"{message}{output}")


def find_free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until(condition, server: subprocess.Popen, what: str) -> None:
    deadline = time.monotonic() + SERVER_TIMEOUT
    while not condition():
        if server.poll() is not None:
            raise CheckFailed(f"the server exited with {server.returncode} while waiting for {what}")
        if time.monotonic() > deadline:
            raise CheckFailed(f"timed out waiting for {what}")
        time.sleep(1)


def get_json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.load(response)
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return None


def send_json(method: str, url: str, body: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        raise CheckFailed(f"{method} {url} answered {e.code}: {e.read().decode()}") from None


if __name__ == "__main__":
    sys.exit(main())
