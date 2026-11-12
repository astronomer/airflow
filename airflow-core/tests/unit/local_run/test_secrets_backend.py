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

import pytest

from airflow.local_run.secrets_backend import LocalRunSecretsBackend
from airflow.sdk import Connection
from airflow.sdk.exceptions import AirflowSecretsBackendAccessDenied
from airflow.secrets.base_secrets import BaseSecretsBackend

RECORDING_BACKEND = "unit.local_run.test_secrets_backend.RecordingBackend"


class RecordingBackend(BaseSecretsBackend):
    """A project's backend that has every secret and keeps what it was created with and asked for."""

    def __init__(self, **kwargs):
        super().__init__()
        self.kwargs = kwargs
        self.team_names: list[str | None] = []

    def get_conn_value(self, conn_id, team_name=None):
        return f"sqlite://project/{conn_id}"

    def get_variable(self, key, team_name=None):
        self.team_names.append(team_name)
        return f"{key} from the project"

    def get_config(self, key):
        return f"{key} from the project"


class DenyingBackend(BaseSecretsBackend):
    def get_variable(self, key, team_name=None):
        raise AirflowSecretsBackendAccessDenied(key)


@pytest.fixture
def files(tmp_path) -> dict[str, str]:
    connections = tmp_path / "connections.json"
    connections.write_text(json.dumps({"in_file": "sqlite://file"}))
    variables = tmp_path / "variables.json"
    variables.write_text(json.dumps({"in_file": "from the file"}))
    return {"connections_file_path": str(connections), "variables_file_path": str(variables)}


def test_files_are_looked_in_before_the_project_backend(files):
    backend = LocalRunSecretsBackend(backend=RECORDING_BACKEND, **files)

    assert backend.get_connection("in_file").host == "file"
    assert backend.get_connection("elsewhere").host == "project"
    assert backend.get_variable("in_file") == "from the file"
    assert backend.get_variable("elsewhere") == "elsewhere from the project"
    assert backend.get_config("sql_alchemy_conn") == "sql_alchemy_conn from the project"


def test_per_key_settings_override_the_project_backend_kwargs():
    backend = LocalRunSecretsBackend(
        backend=RECORDING_BACKEND, backend_kwargs={"url": "https://dev", "role_id": "file"}, role_id="env"
    )

    (project_backend,) = backend.get_backends()

    assert project_backend.kwargs == {"url": "https://dev", "role_id": "env"}


def test_project_backend_is_created_on_first_use():
    backend = LocalRunSecretsBackend(backend="missing_provider.secrets.Backend")

    with pytest.raises(ModuleNotFoundError, match="missing_provider"):
        backend.get_backends()


def test_failing_backend_is_skipped(tmp_path):
    variables = tmp_path / "variables.json"
    variables.write_text("{not json")
    backend = LocalRunSecretsBackend(backend=RECORDING_BACKEND, variables_file_path=str(variables))

    assert backend.get_variable("region") == "region from the project"


def test_denial_is_final(files):
    backend = LocalRunSecretsBackend(backend="unit.local_run.test_secrets_backend.DenyingBackend", **files)

    with pytest.raises(AirflowSecretsBackendAccessDenied):
        backend.get_variable("elsewhere")


def test_connection_class_and_team_name_reach_the_project_backend():
    backend = LocalRunSecretsBackend(backend=RECORDING_BACKEND)
    backend._set_connection_class(Connection)

    assert isinstance(backend.get_connection("warehouse"), Connection)
    backend.get_variable("region", team_name="analytics")
    assert backend.get_backends()[0].team_names == ["analytics"]
