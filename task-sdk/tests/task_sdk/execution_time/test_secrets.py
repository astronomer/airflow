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

import pytest


class DummyComms:
    def send(self, msg):  # pragma: no cover - simple helper
        raise NotImplementedError


@pytest.fixture
def mock_supervisor_comms(monkeypatch):
    from airflow.sdk.execution_time import task_runner

    comms = DummyComms()
    comms.send = lambda msg: msg  # echo response for tests
    monkeypatch.setattr(task_runner, "SUPERVISOR_COMMS", comms, raising=False)
    yield comms


class TestRoleBasedContextDetection:
    """Test role-based chain detection in ensure_secrets_backend_loaded."""

    def test_worker_task_runner_role(self, mock_supervisor_comms, monkeypatch):
        from airflow.sdk.execution_time.supervisor import (
            _detect_secrets_role,
            ensure_secrets_backend_loaded,
        )
        from airflow.secrets.roles import SecretsRole

        monkeypatch.delenv("_AIRFLOW_PROCESS_CONTEXT", raising=False)

        assert _detect_secrets_role() == SecretsRole.WORKER_TASK_RUNNER

        backends = ensure_secrets_backend_loaded()
        backend_names = [type(backend).__name__ for backend in backends]
        assert "ExecutionAPISecretsBackend" in backend_names
        assert "MetastoreBackend" not in backend_names

    def test_api_server_role(self, monkeypatch):
        import sys

        from airflow.sdk.execution_time.supervisor import (
            _detect_secrets_role,
            ensure_secrets_backend_loaded,
        )
        from airflow.secrets.roles import SecretsRole

        monkeypatch.setenv("_AIRFLOW_PROCESS_CONTEXT", "server")
        if "airflow.sdk.execution_time.task_runner" in sys.modules:
            monkeypatch.delitem(sys.modules, "airflow.sdk.execution_time.task_runner")

        assert _detect_secrets_role() == SecretsRole.API_SERVER

        backends = ensure_secrets_backend_loaded()
        backend_names = [type(backend).__name__ for backend in backends]
        assert "MetastoreBackend" in backend_names
        assert "ExecutionAPISecretsBackend" not in backend_names

    def test_worker_supervisor_role(self, monkeypatch):
        import sys

        from airflow.sdk.execution_time.supervisor import (
            _detect_secrets_role,
            ensure_secrets_backend_loaded,
        )
        from airflow.secrets.roles import SecretsRole

        monkeypatch.delenv("_AIRFLOW_PROCESS_CONTEXT", raising=False)
        if "airflow.sdk.execution_time.task_runner" in sys.modules:
            monkeypatch.delitem(sys.modules, "airflow.sdk.execution_time.task_runner")

        assert _detect_secrets_role() == SecretsRole.WORKER_SUPERVISOR

        backends = ensure_secrets_backend_loaded()
        backend_names = [type(backend).__name__ for backend in backends]
        assert backend_names == ["EnvironmentVariablesBackend"]


class TestSupervisorAPIClientSecretsBackend:
    """Test SupervisorAPIClientSecretsBackend."""

    def test_get_connection_via_client(self):
        """Test fetching connection via API client."""
        from unittest.mock import Mock

        from airflow.sdk.api.datamodels._generated import ConnectionResponse
        from airflow.sdk.execution_time.secrets.supervisor_api import SupervisorAPIClientSecretsBackend

        mock_client = Mock()
        mock_client.connections.get.return_value = ConnectionResponse(
            conn_id="test_conn",
            conn_type="http",
        )

        backend = SupervisorAPIClientSecretsBackend(mock_client)
        conn = backend.get_connection("test_conn")

        assert conn is not None
        assert conn.conn_id == "test_conn"
        mock_client.connections.get.assert_called_once_with("test_conn")

    def test_get_connection_not_found(self):
        """Test backend returns None when connection not found."""
        from unittest.mock import Mock

        from airflow.sdk.execution_time.secrets.supervisor_api import SupervisorAPIClientSecretsBackend

        mock_client = Mock()
        mock_client.connections.get.side_effect = Exception("Not found")

        backend = SupervisorAPIClientSecretsBackend(mock_client)
        conn = backend.get_connection("nonexistent")

        assert conn is None

    def test_get_variable_returns_none(self):
        """Test that get_variable always returns None (not needed for supervisor)."""
        from unittest.mock import Mock

        from airflow.sdk.execution_time.secrets.supervisor_api import SupervisorAPIClientSecretsBackend

        mock_client = Mock()
        backend = SupervisorAPIClientSecretsBackend(mock_client)
        var = backend.get_variable("test_key")

        assert var is None
        mock_client.variables.get.assert_not_called()

