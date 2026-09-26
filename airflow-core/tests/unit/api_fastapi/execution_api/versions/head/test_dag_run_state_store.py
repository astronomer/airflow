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

from typing import TYPE_CHECKING
from unittest import mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from airflow.models.dag_run_state_store import DagRunStateStoreModel
from airflow.models.dagrun import DagRun
from airflow.state import DagRunScope, TaskScope
from airflow.state.metastore import MetastoreBackend
from airflow.utils.session import create_session

if TYPE_CHECKING:
    from tests_common.pytest_plugin import CreateTaskInstance


pytestmark = pytest.mark.db_test


@pytest.fixture(autouse=True)
def reset_state_tables():
    with create_session() as session:
        session.execute(delete(DagRunStateStoreModel))
        session.execute(delete(DagRun))


def _api_url(ti_id, key: str | None = None) -> str:
    base = f"/execution/store/dag-run/{ti_id}"
    return f"{base}/{key}" if key else base


class TestDagRunStateStoreRoutes:
    def test_set_then_get_returns_value(self, client: TestClient, create_task_instance: CreateTaskInstance):
        ti = create_task_instance()
        client.put(_api_url(ti.id, "model"), json={"value": "claude-haiku-4-5"})

        response = client.get(_api_url(ti.id, "model"))

        assert response.status_code == 200
        assert response.json() == {"value": "claude-haiku-4-5"}

    def test_get_missing_key_returns_404(self, client: TestClient, create_task_instance: CreateTaskInstance):
        ti = create_task_instance()
        assert client.get(_api_url(ti.id, "never_set")).status_code == 404

    def test_unknown_task_instance_returns_404(self, client: TestClient):
        assert client.get(_api_url(uuid4(), "model")).status_code == 404

    def test_scope_comes_from_the_task_instance_not_the_caller(
        self, client: TestClient, create_task_instance: CreateTaskInstance
    ):
        """The row is keyed on the caller's own run, so no request field can redirect the write."""
        ti = create_task_instance()
        client.put(_api_url(ti.id, "model"), json={"value": "v"})

        with create_session() as session:
            row = session.scalar(select(DagRunStateStoreModel))
            assert row is not None
            assert (row.dag_id, row.run_id) == (ti.dag_id, ti.run_id)

    def test_delete_removes_one_key(self, client: TestClient, create_task_instance: CreateTaskInstance):
        ti = create_task_instance()
        client.put(_api_url(ti.id, "a"), json={"value": 1})
        client.put(_api_url(ti.id, "b"), json={"value": 2})

        assert client.delete(_api_url(ti.id, "a")).status_code == 204

        assert client.get(_api_url(ti.id, "a")).status_code == 404
        assert client.get(_api_url(ti.id, "b")).status_code == 200

    def test_clear_removes_every_key(self, client: TestClient, create_task_instance: CreateTaskInstance):
        ti = create_task_instance()
        client.put(_api_url(ti.id, "a"), json={"value": 1})
        client.put(_api_url(ti.id, "b"), json={"value": 2})

        assert client.delete(_api_url(ti.id)).status_code == 204

        with create_session() as session:
            assert session.scalars(select(DagRunStateStoreModel)).all() == []

    def test_null_value_is_rejected(self, client: TestClient, create_task_instance: CreateTaskInstance):
        ti = create_task_instance()
        assert client.put(_api_url(ti.id, "model"), json={"value": None}).status_code == 422

    def test_backend_without_dag_run_scope_is_rejected(
        self, client: TestClient, create_task_instance: CreateTaskInstance
    ):
        ti = create_task_instance()
        backend = MetastoreBackend()
        with mock.patch.object(backend, "supported_scopes", frozenset({TaskScope})):
            with mock.patch(
                "airflow.api_fastapi.execution_api.routes.dag_run_state_store.get_state_backend",
                return_value=backend,
            ):
                response = client.put(_api_url(ti.id, "model"), json={"value": "v"})

        assert response.status_code == 501
        assert response.json()["detail"]["reason"] == "unsupported_scope"

    def test_supported_scopes_declares_dag_run_scope(self):
        assert DagRunScope in MetastoreBackend.supported_scopes
