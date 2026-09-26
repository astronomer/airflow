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
from sqlalchemy import select

from airflow._shared.timezones import timezone
from airflow.models.dag_run_state_store import DagRunStateStoreModel
from airflow.models.dagrun import DagRun
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.utils.types import DagRunType

from tests_common.test_utils.db import clear_db_dag_bundles, clear_db_dags, clear_db_runs

pytestmark = pytest.mark.db_test

DAG_ID = "test_dag"
TASK_ID = "test_task"
LOGICAL_DATE = timezone.datetime(2026, 1, 1)
RUN_ID = DagRun.generate_run_id(run_type=DagRunType.MANUAL, logical_date=LOGICAL_DATE, run_after=LOGICAL_DATE)

BASE_URL = f"/dags/{DAG_ID}/dagRuns/{RUN_ID}/state-store"


class TestDagRunStateStoreEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self, dag_maker, session):
        with dag_maker(DAG_ID, schedule=None, start_date=LOGICAL_DATE):
            EmptyOperator(task_id=TASK_ID)
        dag_maker.create_dagrun(run_id=RUN_ID, run_type=DagRunType.MANUAL, logical_date=LOGICAL_DATE)
        dag_maker.sync_dagbag_to_db()
        session.merge(dag_maker.dag_model)
        session.commit()
        self.dag_run = session.scalar(select(DagRun).where(DagRun.run_id == RUN_ID))
        self._session = session

    def teardown_method(self):
        clear_db_dags()
        clear_db_runs()
        clear_db_dag_bundles()

    def _add_row(self, key: str, value) -> None:
        self._session.add(
            DagRunStateStoreModel(
                dag_run_id=self.dag_run.id,
                dag_id=DAG_ID,
                run_id=RUN_ID,
                key=key,
                value=json.dumps(value),
            )
        )
        self._session.commit()

    def test_list_returns_empty_when_no_state(self, test_client):
        response = test_client.get(BASE_URL)

        assert response.status_code == 200
        assert response.json() == {"dag_run_state_store": [], "total_entries": 0}

    def test_list_returns_all_keys_sorted(self, test_client):
        self._add_row("model", "claude-haiku-4-5")
        self._add_row("budget", 50)

        response = test_client.get(BASE_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["total_entries"] == 2
        assert [item["key"] for item in data["dag_run_state_store"]] == ["budget", "model"]
        assert data["dag_run_state_store"][1]["value"] == "claude-haiku-4-5"

    def test_list_paginates(self, test_client):
        for key in ("a", "b", "c"):
            self._add_row(key, key)

        response = test_client.get(BASE_URL, params={"limit": 2, "offset": 1})

        assert response.status_code == 200
        data = response.json()
        assert data["total_entries"] == 3
        assert [item["key"] for item in data["dag_run_state_store"]] == ["b", "c"]

    def test_get_returns_one_key(self, test_client):
        self._add_row("model", {"name": "claude-haiku-4-5"})

        response = test_client.get(f"{BASE_URL}/model")

        assert response.status_code == 200
        assert response.json()["value"] == {"name": "claude-haiku-4-5"}

    def test_get_missing_key_returns_404(self, test_client):
        assert test_client.get(f"{BASE_URL}/never_set").status_code == 404

    @pytest.mark.parametrize("path", ["", "/model"])
    def test_unknown_dag_run_returns_404(self, test_client, path):
        response = test_client.get(f"/dags/{DAG_ID}/dagRuns/no-such-run/state-store{path}")

        assert response.status_code == 404

    @pytest.mark.parametrize("path", ["", "/model"])
    def test_unauthenticated_is_rejected(self, unauthenticated_test_client, path):
        assert unauthenticated_test_client.get(f"{BASE_URL}{path}").status_code == 401

    @pytest.mark.parametrize("path", ["", "/model"])
    def test_unauthorized_is_rejected(self, unauthorized_test_client, path):
        assert unauthorized_test_client.get(f"{BASE_URL}{path}").status_code == 403
