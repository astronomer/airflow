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
"""Find installed database servers, Node and pnpm. Nothing is downloaded or installed."""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from airflow_dev.repo import DevError, get_supported_db_versions

EXTRA_DIRS_VARIABLE = "AIRFLOW_DEV_TOOL_DIRS"
HOMEBREW_PREFIXES = ("/opt/homebrew", "/usr/local", "/home/linuxbrew/.linuxbrew")
UI_PACKAGE = Path("airflow-core/src/airflow/ui/package.json")

SERVER_EXECUTABLE = {"postgres": "postgres", "mysql": "mysqld"}
CLIENT_EXECUTABLES = {"postgres": ("initdb", "pg_ctl", "psql"), "mysql": ("mysql", "mysqladmin")}
VERSION_PATTERNS = {
    "postgres": re.compile(r"\(PostgreSQL\) (\d+)\.(\d+)"),
    "mysql": re.compile(r"Ver (\d+)\.(\d+)\.(\d+)"),
}
ENGINE_DIR_PATTERNS = {
    "postgres": [
        *(f"{prefix}/opt/postgresql@*/bin" for prefix in HOMEBREW_PREFIXES),
        "/Applications/Postgres.app/Contents/Versions/*/bin",
        "/usr/lib/postgresql/*/bin",
        "/usr/pgsql-*/bin",
    ],
    "mysql": [
        *(f"{prefix}/opt/mysql*/bin" for prefix in HOMEBREW_PREFIXES),
        "/usr/local/mysql/bin",
        "/usr/sbin",
    ],
}


@dataclass(frozen=True)
class Installation:
    engine: str
    version: str
    bin_dir: Path
    client_dir: Path

    @property
    def major(self) -> str:
        """Release line used for selection: ``14`` for Postgres, ``8.4`` for MySQL."""
        parts = self.version.split(".")
        return parts[0] if self.engine == "postgres" else ".".join(parts[:2])

    def get_executable(self, name: str) -> Path:
        directory = self.bin_dir if name == SERVER_EXECUTABLE[self.engine] else self.client_dir
        return directory / name

    def to_dict(self) -> dict[str, str]:
        return {"engine": self.engine, "version": self.version, "bin_dir": str(self.bin_dir)}


def get_search_dirs(engine: str) -> list[Path]:
    extra = [entry for entry in os.environ.get(EXTRA_DIRS_VARIABLE, "").split(os.pathsep) if entry]
    patterns = [*extra, *os.get_exec_path(), *ENGINE_DIR_PATTERNS[engine]]
    directories: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for match in sorted(glob.glob(os.path.expanduser(pattern)), reverse=True):
            path = Path(match)
            # One installation can sit behind several aliases, such as Homebrew's mysql@8.0 -> mysql.
            resolved = path.resolve()
            if path.is_dir() and resolved not in seen:
                seen.add(resolved)
                directories.append(path)
    return directories


def get_version(engine: str, server: Path) -> str | None:
    try:
        output = subprocess.run(
            [str(server), "--version"], capture_output=True, text=True, timeout=30, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    if match := VERSION_PATTERNS[engine].search(output):
        return ".".join(match.groups())
    return None


def find_client_dir(engine: str, bin_dir: Path) -> Path | None:
    # Linux packages put mysqld in sbin and the clients in the sibling bin.
    for directory in (bin_dir, bin_dir.parent / "bin"):
        if all((directory / name).is_file() for name in CLIENT_EXECUTABLES[engine]):
            return directory
    return None


def find_installations(engine: str) -> list[Installation]:
    installations: list[Installation] = []
    seen: set[Path] = set()
    for directory in get_search_dirs(engine):
        server = directory / SERVER_EXECUTABLE[engine]
        if not (server.is_file() and os.access(server, os.X_OK)) or server.resolve() in seen:
            continue
        seen.add(server.resolve())
        version = get_version(engine, server)
        client_dir = find_client_dir(engine, directory)
        if version and client_dir:
            installations.append(Installation(engine, version, directory, client_dir))
    return installations


def get_install_hint(engine: str, version: str) -> str:
    if sys.platform == "darwin":
        return f"brew install {'postgresql' if engine == 'postgres' else 'mysql'}@{version}"
    if engine == "postgres":
        return f"sudo apt install postgresql-{version}  (or your distribution's package)"
    return f"install MySQL {version} from https://dev.mysql.com/downloads/mysql/ and add its bin to PATH"


def select_installation(repo: Path, engine: str, version: str | None) -> Installation:
    supported = get_supported_db_versions(repo)[engine]
    installations = find_installations(engine)
    wanted = [version] if version else supported
    for release in wanted:
        for installation in installations:
            if installation.major == release:
                return installation
    found = ", ".join(sorted({i.major for i in installations})) or "none"
    release = version or supported[0]
    raise DevError(
        f"No installed {engine} {release} found (found: {found}; Airflow supports {', '.join(supported)}).",
        hint=f"{get_install_hint(engine, release)}, or add its bin directory to {EXTRA_DIRS_VARIABLE}.",
        exit_code=3,
    )


def get_ui_requirements(repo: Path) -> tuple[int, str]:
    package = json.loads((repo / UI_PACKAGE).read_text())
    minimum_node = int(re.search(r"\d+", package["engines"]["node"]).group())  # type: ignore[union-attr]
    pnpm = package["packageManager"].split("@", 1)[1]
    return minimum_node, pnpm


def get_node_dirs() -> list[Path]:
    home = Path.home()
    patterns = [
        *os.get_exec_path(),
        f"{os.environ.get('NVM_DIR', home / '.nvm')}/versions/node/*/bin",
        f"{os.environ.get('FNM_DIR', home / '.local/share/fnm')}/node-versions/*/installation/bin",
        f"{home}/Library/Application Support/fnm/node-versions/*/installation/bin",
        f"{os.environ.get('VOLTA_HOME', home / '.volta')}/tools/image/node/*/bin",
        *(f"{prefix}/opt/node*/bin" for prefix in HOMEBREW_PREFIXES),
    ]
    return [Path(match) for pattern in patterns for match in sorted(glob.glob(str(pattern)), reverse=True)]


def run_version(executable: Path, env: dict[str, str] | None = None) -> str | None:
    try:
        result = subprocess.run(
            [str(executable), "--version"], capture_output=True, text=True, timeout=60, env=env, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    version = result.stdout.strip().removeprefix("v")
    return version if result.returncode == 0 and re.fullmatch(r"\d+\.\d+\.\d+", version) else None


def find_node(minimum: int) -> tuple[Path, str]:
    best: tuple[tuple[int, ...], Path, str] | None = None
    for directory in get_node_dirs():
        node = directory / "node"
        if node.is_file() and (version := run_version(node)):
            key = tuple(int(part) for part in version.split("."))
            if key[0] >= minimum and (best is None or key > best[0]):
                best = (key, directory, version)
    if best is None:
        raise DevError(
            f"Node {minimum} or newer is required to build the UI.",
            hint=f"nvm install {minimum}  (or brew install node@{minimum})",
            exit_code=3,
        )
    return best[1], best[2]


def find_frontend_tools(repo: Path) -> dict[str, str]:
    """
    Return the Node bin dir and how to run the UI's pinned pnpm.

    A matching ``pnpm`` on PATH or next to Node is used as is. Otherwise Node's own corepack provides
    the version the UI's ``packageManager`` field pins.
    """
    minimum_node, pinned_pnpm = get_ui_requirements(repo)
    node_dir, node_version = find_node(minimum_node)
    env = {**os.environ, "PATH": os.pathsep.join([str(node_dir), os.environ.get("PATH", "")])}
    for directory in [node_dir, *map(Path, os.get_exec_path())]:
        pnpm = directory / "pnpm"
        if pnpm.is_file() and run_version(pnpm, env) == pinned_pnpm:
            return {
                "node_dir": str(node_dir),
                "node_version": node_version,
                "pnpm": str(pnpm),
                "pnpm_version": pinned_pnpm,
                "pnpm_source": "installed",
            }
    corepack = node_dir / "corepack"
    if not corepack.is_file():
        raise DevError(
            f"pnpm {pinned_pnpm} is required and Node {node_version} has no corepack.",
            hint=f"npm install -g pnpm@{pinned_pnpm}",
            exit_code=3,
        )
    return {
        "node_dir": str(node_dir),
        "node_version": node_version,
        "pnpm": str(corepack),
        "pnpm_version": pinned_pnpm,
        "pnpm_source": "corepack",
    }
