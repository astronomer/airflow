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

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from airflow_dev import instance as instances
from airflow_dev.db import get_server, load_known_servers
from airflow_dev.discovery import (
    find_frontend_tools,
    find_installations,
    get_install_hint,
)
from airflow_dev.repo import DevError, find_repo_root, get_supported_db_versions
from airflow_dev.testing import BACKENDS, prune, run_tests

EPILOG = """examples:
  airflow-dev doctor
  airflow-dev test airflow-core/tests/unit/models/test_variable.py --backend postgres
  airflow-dev test airflow-core/tests/unit/models/test_dagrun.py --backend mysql --workers 4 -- -x
  airflow-dev start --backend postgres --background
  airflow-dev db status
"""


def add_db_selection(parser: argparse.ArgumentParser, backends: tuple[str, ...]) -> None:
    parser.add_argument("--backend", choices=backends, help="Database backend.")
    parser.add_argument("--db-version", help="Server release, such as 14 or 8.4. Default: Breeze's default.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airflow-dev",
        description="Run Airflow source tests and a source instance on local databases, without Docker.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Print one JSON document on stdout.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", parents=[common], help="Show the tools this checkout can use.")

    test = commands.add_parser("test", parents=[common], help="Run pytest for one workspace member.")
    test.add_argument("targets", nargs="+", help="Test files, directories or node IDs.")
    add_db_selection(test, BACKENDS)
    test.add_argument(
        "--workers", "-n", type=int, default=1, help="pytest-xdist workers, each with its own DB."
    )
    test.add_argument("--keep-db", action="store_true", help="Keep the run's databases and homes.")

    db = commands.add_parser("db", help="Manage this checkout's database servers.")
    db_commands = db.add_subparsers(dest="db_command", required=True)
    for name, help_text in (
        ("start", "Start a server, initializing it on first use."),
        ("stop", "Stop a server."),
        ("url", "Print a SQLAlchemy URL for a database on a server."),
    ):
        sub = db_commands.add_parser(name, parents=[common], help=help_text)
        add_db_selection(sub, ("postgres", "mysql"))
        if name == "url":
            sub.add_argument("--database", default="airflow_instance")
    db_commands.add_parser("status", parents=[common], help="Show every server this checkout has created.")
    db_commands.add_parser(
        "prune", parents=[common], help="Drop databases and homes left by interrupted test runs."
    )

    start = commands.add_parser(
        "start", parents=[common], help="Start a persistent instance with airflow standalone."
    )
    add_db_selection(start, ("sqlite", "postgres", "mysql"))
    start.add_argument("--port", type=int, default=8080)
    start.add_argument("--dags-folder", type=Path, help="Default: the instance's own empty dags folder.")
    start.add_argument("--examples", action="store_true", help="Load the example Dags.")
    start.add_argument("--background", action="store_true", help="Return once every component is healthy.")
    start.add_argument("--timeout", type=int, default=240, help="Seconds to wait for health in background.")
    start.add_argument("--verbose", action="store_true", help="Show every component's output on screen.")
    for name, help_text in (("stop", "Stop an instance."), ("status", "Show an instance's health.")):
        sub = commands.add_parser(name, parents=[common], help=help_text)
        add_db_selection(sub, ("sqlite", "postgres", "mysql"))
    logs = commands.add_parser("logs", parents=[common], help="Show an instance's component logs.")
    logs.add_argument(
        "component", nargs="?", choices=instances.LOG_NAMES, help="One component. Default: all of them."
    )
    add_db_selection(logs, ("sqlite", "postgres", "mysql"))
    logs.add_argument("--lines", type=int, default=100)
    logs.add_argument("--follow", "-f", action="store_true")
    return parser


def split_pytest_args(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" in argv:
        index = argv.index("--")
        return argv[:index], argv[index + 1 :]
    return argv, []


def emit(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
    elif isinstance(result, str):
        print(result)
    else:
        print(json.dumps(result, indent=2))


def run_doctor(repo: Path) -> dict:
    supported = get_supported_db_versions(repo)
    report: dict = {"repo": str(repo), "uv": shutil.which("uv"), "databases": {}}
    for engine in ("postgres", "mysql"):
        installations = find_installations(engine)
        found = [
            {**installation.to_dict(), "supported": installation.major in supported[engine]}
            for installation in installations
        ]
        found_majors = {installation.major for installation in installations}
        missing = [version for version in supported[engine] if version not in found_majors]
        report["databases"][engine] = {
            "supported_versions": supported[engine],
            "found": found,
            "install_hints": {v: get_install_hint(engine, v) for v in missing},
        }
    try:
        report["ui"] = find_frontend_tools(repo)
    except DevError as error:
        report["ui"] = {"error": error.message, "hint": error.hint}
    return report


def get_instance(repo: Path, args: argparse.Namespace) -> instances.Instance:
    return instances.get_instance(repo, args.backend or "sqlite", args.db_version)


def dispatch(args: argparse.Namespace, pytest_args: list[str], repo: Path) -> int:
    if args.command == "doctor":
        emit(run_doctor(repo), args.json)
        return 0
    if args.command == "test":
        return run_tests(
            repo,
            Path.cwd(),
            args.targets,
            backend=args.backend,
            db_version=args.db_version,
            workers=args.workers,
            keep_db=args.keep_db,
            pytest_args=pytest_args,
            as_json=args.json,
        )
    if args.command == "db":
        if args.db_command == "status":
            emit([server.status() for server in load_known_servers(repo)], args.json)
        elif args.db_command == "prune":
            emit({"removed": prune(repo)}, args.json)
        else:
            server = get_server(repo, args.backend or "postgres", args.db_version)
            if args.db_command == "start":
                server.ensure_running()
                emit(server.status(), args.json)
            elif args.db_command == "stop":
                server.stop()
                emit(server.status(), args.json)
            else:
                server.ensure_running()
                if args.database not in server.list_databases(args.database):
                    server.create_database(args.database)
                emit(server.get_url(args.database), args.json)
        return 0
    instance = get_instance(repo, args)
    if args.command == "start":
        result = instances.start(
            instance,
            port=args.port,
            dags_folder=args.dags_folder,
            examples=args.examples,
            background=args.background,
            timeout=args.timeout,
            verbose=args.verbose,
        )
        if args.background:
            emit(result, args.json)
            return 0
        return result["exit_code"]
    if args.command == "stop":
        stopped = instances.stop(instance)
        emit({"name": instance.name, "stopped": stopped}, args.json)
        return 0
    if args.command == "status":
        status = instance.status()
        emit(status, args.json)
        return 0 if status["healthy"] else 1
    paths = instance.get_log_paths(args.component)
    print(instances.tail(paths, args.lines), end="")
    if args.follow:
        instances.follow(paths)
    return 0


def main(argv: list[str] | None = None) -> int:
    own_args, pytest_args = split_pytest_args(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(own_args)
    if pytest_args and args.command != "test":
        build_parser().error("arguments after -- are only accepted by 'test'")
    try:
        repo = find_repo_root(Path(os.environ.get("AIRFLOW_DEV_REPO", Path.cwd())))
        return dispatch(args, pytest_args, repo)
    except DevError as error:
        if args.json:
            print(json.dumps({"error": error.message, "hint": error.hint, "exit_code": error.exit_code}))
        else:
            print(f"airflow-dev: {error.message}", file=sys.stderr)
            if error.hint:
                print(f"  hint: {error.hint}", file=sys.stderr)
        return error.exit_code
