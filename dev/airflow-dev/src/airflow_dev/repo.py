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
"""Facts read from the Airflow checkout: its root, workspace members, locked versions and DB policy."""

from __future__ import annotations

import ast
import subprocess
import tomllib
from functools import cache
from pathlib import Path

BREEZE_CONSTANTS = Path("dev/breeze/src/airflow_breeze/global_constants.py")


class DevError(Exception):
    """A failure the user can act on; printed without a traceback."""

    def __init__(self, message: str, *, hint: str | None = None, exit_code: int = 2):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.exit_code = exit_code


def find_repo_root(start: Path) -> Path:
    try:
        output = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        raise DevError(f"{start} is not inside a Git checkout.", hint="Run from an Airflow worktree.")
    root = Path(output)
    if not (root / "airflow-core" / "pyproject.toml").is_file():
        raise DevError(f"{root} is not an Airflow checkout.", hint="Run from an Airflow worktree.")
    return root


@cache
def get_workspace_members(repo: Path) -> tuple[str, ...]:
    with (repo / "pyproject.toml").open("rb") as file:
        data = tomllib.load(file)
    return tuple(data["tool"]["uv"]["workspace"]["members"])


def find_member(repo: Path, target: Path) -> str:
    """Return the workspace member that owns ``target``, as a path relative to the repo root."""
    members = set(get_workspace_members(repo))
    path = target.resolve()
    try:
        path.relative_to(repo)
    except ValueError:
        raise DevError(f"{target} is outside the checkout {repo}.")
    for candidate in [path, *path.parents]:
        if candidate == repo:
            break
        relative = candidate.relative_to(repo).as_posix()
        if relative in members:
            return relative
    raise DevError(f"{target} does not belong to a workspace member.", hint="Pass a test file or directory.")


@cache
def get_locked_versions(repo: Path) -> dict[str, str]:
    with (repo / "uv.lock").open("rb") as file:
        data = tomllib.load(file)
    return {package["name"]: package["version"] for package in data["package"] if "version" in package}


def get_pinned_requirements(repo: Path, names: list[str]) -> list[str]:
    versions = get_locked_versions(repo)
    missing = [name for name in names if name not in versions]
    if missing:
        raise DevError(f"{', '.join(missing)} not found in uv.lock.", exit_code=3)
    return [f"{name}=={versions[name]}" for name in names]


@cache
def get_supported_db_versions(repo: Path) -> dict[str, list[str]]:
    """Read the database versions Breeze tests against, without importing Breeze."""
    tree = ast.parse((repo / BREEZE_CONSTANTS).read_text())
    values: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and node.value is not None:
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except ValueError:
                        continue
    mysql = [*values["MYSQL_OLD_RELEASES"], *values["MYSQL_LTS_RELEASES"]]  # type: ignore[misc]
    if innovation := values.get("MYSQL_INNOVATION_RELEASE"):
        mysql.append(innovation)
    return {"postgres": list(values["CURRENT_POSTGRES_VERSIONS"]), "mysql": mysql}  # type: ignore[call-overload]
