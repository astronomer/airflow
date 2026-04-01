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

import datetime

import pytest

from airflow._shared.timezones import timezone
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.sdk.bases.operator import BaseOperator
from airflow.sdk.serde import deserialize as serde_deserialize, serialize as serde_serialize
from airflow.serialization.serialized_objects import BaseSerialization
from airflow.triggers.base import StartTriggerArgs
from airflow.utils.state import DagRunState, State, TaskInstanceState

from tests_common.test_utils.db import (
    clear_db_dags,
    clear_db_runs,
    clear_db_serialized_dags,
)

pytestmark = pytest.mark.db_test

TIMESTAMP_STR = "2024-09-30T12:00:00Z"
TIMESTAMP = timezone.parse(TIMESTAMP_STR)

RUN_PATCH_BODY = {
    "state": "running",
    "hostname": "test-hostname",
    "unixname": "test-user",
    "pid": 12345,
    "start_date": TIMESTAMP_STR,
}


@pytest.fixture
def old_ver_client(client):
    """Last released execution API before nullable DagRun.start_date (2026-04-06 bundle)."""
    client.headers["Airflow-API-Version"] = "2025-11-05"
    return client


class TestDagRunStartDateNullableBackwardCompat:
    """Test that older API versions get a non-null start_date fallback."""

    @pytest.fixture(autouse=True)
    def _freeze_time(self, time_machine):
        time_machine.move_to(TIMESTAMP_STR, tick=False)

    def setup_method(self):
        clear_db_runs()

    def teardown_method(self):
        clear_db_runs()

    def test_old_version_gets_run_after_when_start_date_is_null(
        self,
        old_ver_client,
        session,
        create_task_instance,
    ):
        ti = create_task_instance(
            task_id="test_start_date_nullable",
            state=State.QUEUED,
            dagrun_state=DagRunState.QUEUED,
            session=session,
            start_date=TIMESTAMP,
        )
        ti.dag_run.start_date = None  # DagRun has not started yet
        session.commit()

        response = old_ver_client.patch(f"/execution/task-instances/{ti.id}/run", json=RUN_PATCH_BODY)
        dag_run = response.json()["dag_run"]

        assert response.status_code == 200
        assert dag_run["start_date"] is not None
        assert dag_run["start_date"] == dag_run["run_after"]

    def test_head_version_allows_null_start_date(
        self,
        client,
        session,
        create_task_instance,
    ):
        ti = create_task_instance(
            task_id="test_start_date_null_head",
            state=State.QUEUED,
            dagrun_state=DagRunState.QUEUED,
            session=session,
            start_date=TIMESTAMP,
        )
        ti.dag_run.start_date = None  # DagRun has not started yet
        session.commit()

        response = client.patch(f"/execution/task-instances/{ti.id}/run", json=RUN_PATCH_BODY)
        dag_run = response.json()["dag_run"]

        assert response.status_code == 200
        assert dag_run["start_date"] is None

    def test_old_version_preserves_real_start_date(
        self,
        old_ver_client,
        session,
        create_task_instance,
    ):
        ti = create_task_instance(
            task_id="test_start_date_preserved",
            state=State.QUEUED,
            dagrun_state=DagRunState.RUNNING,
            session=session,
            start_date=TIMESTAMP,
        )
        assert ti.dag_run.start_date == TIMESTAMP  # DagRun has already started
        session.commit()

        response = old_ver_client.patch(f"/execution/task-instances/{ti.id}/run", json=RUN_PATCH_BODY)
        dag_run = response.json()["dag_run"]

        assert response.status_code == 200
        assert dag_run["start_date"] is not None, "start_date should not be None when DagRun has started"
        assert dag_run["start_date"] == TIMESTAMP.isoformat().replace("+00:00", "Z")


@pytest.fixture
def serde_ver_client(client):
    """Client configured to use API version that understands serde format."""
    client.headers["Airflow-API-Version"] = "2026-04-06"
    return client


class TestDeferredNextKwargsBackwardCompat:
    def setup_method(self):
        clear_db_runs()
        clear_db_serialized_dags()
        clear_db_dags()

    def teardown_method(self):
        clear_db_runs()
        clear_db_serialized_dags()
        clear_db_dags()

    def test_old_version_gets_legacy_next_kwargs_for_serde_stored_simple_data(
        self, old_ver_client, session, create_task_instance, time_machine
    ):
        """Old workers receive BaseSerialization format for serde-stored simple data."""
        time_machine.move_to(TIMESTAMP_STR, tick=False)
        logical_next_kwargs = {
            "event": {"message": "ready"},
            "attempt": 2,
        }
        ti = create_task_instance(
            task_id="test_legacy_next_kwargs_simple",
            state=State.QUEUED,
            dagrun_state=DagRunState.RUNNING,
            session=session,
            start_date=TIMESTAMP,
        )
        ti.next_method = "execute_complete"
        ti.next_kwargs = serde_serialize(logical_next_kwargs)
        session.commit()

        response = old_ver_client.patch(f"/execution/task-instances/{ti.id}/run", json=RUN_PATCH_BODY)

        assert response.status_code == 200
        result = response.json()["next_kwargs"]
        assert BaseSerialization.deserialize(result) == logical_next_kwargs

    def test_old_version_gets_legacy_next_kwargs_for_serde_stored_complex_types(
        self, old_ver_client, session, create_task_instance, time_machine
    ):
        """Old workers receive BaseSerialization format for serde-stored complex types (datetime, timedelta, tuple)."""
        time_machine.move_to(TIMESTAMP_STR, tick=False)
        logical_next_kwargs = {
            "when": datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
            "delay": datetime.timedelta(minutes=5),
            "items": ("alpha", 2),
        }
        ti = create_task_instance(
            task_id="test_legacy_next_kwargs_complex",
            state=State.QUEUED,
            dagrun_state=DagRunState.RUNNING,
            session=session,
            start_date=TIMESTAMP,
        )
        ti.next_method = "execute_complete"
        ti.next_kwargs = serde_serialize(logical_next_kwargs)
        session.commit()

        response = old_ver_client.patch(f"/execution/task-instances/{ti.id}/run", json=RUN_PATCH_BODY)

        assert response.status_code == 200
        result = response.json()["next_kwargs"]
        deserialized = BaseSerialization.deserialize(result)
        assert deserialized["when"] == logical_next_kwargs["when"]
        assert deserialized["delay"] == logical_next_kwargs["delay"]
        assert deserialized["items"] == logical_next_kwargs["items"]

    def test_v2026_04_06_keeps_serde_next_kwargs(
        self, serde_ver_client, session, create_task_instance, time_machine
    ):
        """Workers >= 2026-04-06 receive serde format unchanged."""
        time_machine.move_to(TIMESTAMP_STR, tick=False)
        logical_next_kwargs = {
            "when": datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
            "delay": datetime.timedelta(minutes=5),
            "items": ("alpha", 2),
        }
        encoded_next_kwargs = serde_serialize(logical_next_kwargs)
        ti = create_task_instance(
            task_id="test_v2026_04_06_keeps_serde",
            state=State.QUEUED,
            dagrun_state=DagRunState.RUNNING,
            session=session,
            start_date=TIMESTAMP,
        )
        ti.next_method = "execute_complete"
        ti.next_kwargs = encoded_next_kwargs
        session.commit()

        response = serde_ver_client.patch(f"/execution/task-instances/{ti.id}/run", json=RUN_PATCH_BODY)

        assert response.status_code == 200
        assert response.json()["next_kwargs"] == encoded_next_kwargs

    def test_old_version_preserves_legacy_next_kwargs_for_legacy_rows(
        self, old_ver_client, session, create_task_instance, time_machine
    ):
        """Old workers receive BaseSerialization format unchanged for legacy-stored data."""
        time_machine.move_to(TIMESTAMP_STR, tick=False)
        logical_next_kwargs = {
            "event": {"message": "ready"},
            "attempt": 2,
        }
        encoded_next_kwargs = BaseSerialization.serialize(logical_next_kwargs)
        ti = create_task_instance(
            task_id="test_legacy_next_kwargs_preserved",
            state=State.QUEUED,
            dagrun_state=DagRunState.RUNNING,
            session=session,
            start_date=TIMESTAMP,
        )
        ti.next_method = "execute_complete"
        ti.next_kwargs = encoded_next_kwargs
        session.commit()

        response = old_ver_client.patch(f"/execution/task-instances/{ti.id}/run", json=RUN_PATCH_BODY)

        assert response.status_code == 200
        result = response.json()["next_kwargs"]
        assert BaseSerialization.deserialize(result) == logical_next_kwargs

    def test_missing_next_kwargs_is_unchanged(
        self, old_ver_client, session, create_task_instance, time_machine
    ):
        """When next_kwargs is absent, the response is unmodified."""
        time_machine.move_to(TIMESTAMP_STR, tick=False)
        ti = create_task_instance(
            task_id="test_missing_next_kwargs",
            state=State.QUEUED,
            dagrun_state=DagRunState.RUNNING,
            session=session,
            start_date=TIMESTAMP,
        )
        session.commit()

        response = old_ver_client.patch(f"/execution/task-instances/{ti.id}/run", json=RUN_PATCH_BODY)

        assert response.status_code == 200
        assert "next_kwargs" not in response.json()

    @pytest.mark.need_serialized_dag
    def test_start_from_trigger_scheduler_path_stores_serde_next_kwargs(self, session, dag_maker):
        """The scheduler's defer_task() stores next_kwargs in serde format."""
        logical_next_kwargs = {
            "when": datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
            "delay": datetime.timedelta(minutes=5),
            "items": ("alpha", 2),
        }

        class TestOperator(BaseOperator):
            start_trigger_args = StartTriggerArgs(
                trigger_cls="airflow.triggers.testing.SuccessTrigger",
                trigger_kwargs=None,
                next_method="execute_complete",
                next_kwargs=logical_next_kwargs,
                timeout=None,
            )
            start_from_trigger = True

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.start_trigger_args.trigger_kwargs = {}

            def execute_complete(self):
                pass

        with dag_maker(session=session):
            EmptyOperator(task_id="upstream")
            TestOperator(task_id="test_task")

        dr = dag_maker.create_dagrun(state=DagRunState.RUNNING)
        ti = dr.get_task_instance("test_task")
        assert ti is not None
        ti.task = dr.dag.get_task("test_task")

        dr.schedule_tis((ti,), session=session)
        session.commit()

        assert ti.state == TaskInstanceState.DEFERRED
        assert ti.next_kwargs != logical_next_kwargs
        stored_next_kwargs = ti.next_kwargs
        assert serde_deserialize(stored_next_kwargs)["delay"] == logical_next_kwargs["delay"]
        assert serde_deserialize(stored_next_kwargs)["items"] == logical_next_kwargs["items"]
        assert serde_deserialize(stored_next_kwargs)["when"] == logical_next_kwargs["when"]
