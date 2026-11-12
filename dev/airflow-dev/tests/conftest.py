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

import json
from pathlib import Path

import pytest

BREEZE_CONSTANTS = """
CURRENT_POSTGRES_VERSIONS = ["14", "15"]
MYSQL_LTS_RELEASES: list[str] = ["8.4"]
MYSQL_OLD_RELEASES = ["8.0"]
MYSQL_INNOVATION_RELEASE: str | None = None
DEFAULT_POSTGRES_VERSION = CURRENT_POSTGRES_VERSIONS[0]
"""

UV_LOCK = """
version = 1

[[package]]
name = "psycopg"
version = "3.3.8"

[[package]]
name = "psycopg-binary"
version = "3.3.8"

[[package]]
name = "pymysql"
version = "1.1.3"

[[package]]
name = "aiomysql"
version = "0.3.2"

[[package]]
name = "rfc3339-validator"
version = "0.1.4"

[[package]]
name = "apache-airflow-core"
source = { editable = "airflow-core" }
"""


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A minimal checkout layout with the files airflow-dev reads."""
    repo = tmp_path / "airflow"
    (repo / "airflow-core" / "tests" / "unit" / "models").mkdir(parents=True)
    (repo / "airflow-core" / "pyproject.toml").write_text("")
    (repo / "airflow-core" / "tests" / "unit" / "models" / "test_x.py").write_text("")
    (repo / "task-sdk" / "tests").mkdir(parents=True)
    (repo / "task-sdk" / "tests" / "test_y.py").write_text("")
    (repo / "providers" / "standard" / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = [".", "airflow-core", "task-sdk", "providers/standard"]\n'
    )
    (repo / "uv.lock").write_text(UV_LOCK)
    constants = repo / "dev" / "breeze" / "src" / "airflow_breeze" / "global_constants.py"
    constants.parent.mkdir(parents=True)
    constants.write_text(BREEZE_CONSTANTS)
    ui = repo / "airflow-core" / "src" / "airflow" / "ui"
    ui.mkdir(parents=True)
    (ui / "package.json").write_text(
        json.dumps({"engines": {"node": ">=22"}, "packageManager": "pnpm@10.28.1"})
    )
    return repo


def write_executable(path: Path, output: str) -> Path:
    """Write a fake tool that prints ``output`` for ``--version``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho '{output}'\n")
    path.chmod(0o755)
    return path
