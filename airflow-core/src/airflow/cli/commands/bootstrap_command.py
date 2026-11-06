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
"""Create a project to run Dags locally."""

from __future__ import annotations

import re
import shlex
import sys
from importlib import metadata, resources
from pathlib import Path

from airflow import __version__ as airflow_version

EXAMPLE_DAG_FILE = "pipeline.py"


def bootstrap(args) -> None:
    """
    Create a project in ``args.path`` that depends on this version of Airflow, for uv to install.

    The project's ``.python-version`` names the Python this command runs on, which Airflow supports, and with
    which ``uvx`` already downloaded Airflow. Not wrapped in ``action_cli``: that would log the command to
    the ambient database.
    """
    project = Path(args.path).resolve()
    if (project / "pyproject.toml").exists():
        raise SystemExit(f"{project} already has a pyproject.toml")
    try:
        is_new = not project.exists() or not any(project.iterdir())
        project.mkdir(parents=True, exist_ok=True)
        (project / "pyproject.toml").write_text(build_pyproject(build_project_name(project.name)))
        python_version = project / ".python-version"
        if not python_version.exists():
            python_version.write_text(f"{sys.version_info.major}.{sys.version_info.minor}\n")
        if is_new:
            (project / EXAMPLE_DAG_FILE).write_text(read_example_dag())
    except OSError as e:
        raise SystemExit(f"Error: {e}")
    if is_new:
        print(f"Created a project for Airflow {airflow_version}, with an example Dag. Run it:")
    else:
        print(f"Created a project for Airflow {airflow_version}. Run a Dag:")
    if project != Path.cwd():
        print(f"  cd {shlex.quote(args.path)}")
    print(f"  uv run {EXAMPLE_DAG_FILE}" if is_new else "  uv run airflow run your_dag.py")


def build_project_name(directory_name: str) -> str:
    # A distribution name, normalized as uv does; "dags" when nothing of the folder's name is usable.
    return re.sub(r"[^a-z0-9]+", "-", directory_name.lower()).strip("-") or "dags"


def build_pyproject(name: str) -> str:
    requires_python = metadata.metadata("apache-airflow-core")["Requires-Python"]
    return (
        "[project]\n"
        f'name = "{name}"\n'
        'version = "0.1.0"\n'
        f'requires-python = "{requires_python}"\n'
        "dependencies = [\n"
        f'    "apache-airflow>={airflow_version}",\n'
        "]\n"
    )


def read_example_dag() -> str:
    source = (resources.files("airflow.local_run") / "example_dags" / EXAMPLE_DAG_FILE).read_text()
    _, _, after_start = source.partition("# [START run_dags_locally_pipeline]\n")
    dag_source, _, _ = after_start.partition("# [END run_dags_locally_pipeline]\n")
    return dag_source
