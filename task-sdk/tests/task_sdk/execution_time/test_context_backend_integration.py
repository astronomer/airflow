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

from unittest.mock import patch

import pytest


class TestBackendIntegration:
    def test_execution_api_backend_in_worker_chain(self, monkeypatch):
        from airflow.sdk.execution_time.supervisor import ensure_secrets_backend_loaded
        from airflow.secrets.roles import SecretsRole
        from airflow.sdk.execution_time import supervisor

        with patch.object(supervisor, "_detect_secrets_role", return_value=SecretsRole.WORKER_TASK_RUNNER):
            backends = ensure_secrets_backend_loaded()
            names = [type(b).__name__ for b in backends]
            assert "ExecutionAPISecretsBackend" in names
            assert "MetastoreBackend" not in names

    def test_metastore_backend_in_server_chain(self, monkeypatch):
        from airflow.sdk.execution_time.supervisor import ensure_secrets_backend_loaded
        from airflow.secrets.roles import SecretsRole
        from airflow.sdk.execution_time import supervisor

        with patch.object(supervisor, "_detect_secrets_role", return_value=SecretsRole.API_SERVER):
            backends = ensure_secrets_backend_loaded()
            names = [type(b).__name__ for b in backends]
            assert "MetastoreBackend" in names
            assert "ExecutionAPISecretsBackend" not in names

    def test_get_connection_backend_fallback(self, mocker):
        from airflow.exceptions import AirflowNotFoundException
        from airflow.sdk.execution_time.context import _get_connection

        class EmptyBackend:
            def get_connection(self, conn_id):
                return None

        mocker.patch(
            "airflow.sdk.execution_time.supervisor.ensure_secrets_backend_loaded",
            return_value=[EmptyBackend()],
        )

        with pytest.raises(AirflowNotFoundException):
            _get_connection("missing_conn")

