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

from datetime import timedelta

import pytest
from sqlalchemy import event

from airflow._shared.timezones import timezone
from airflow.local_run.ownership import assign_local_trigger_queue
from airflow.models.trigger import Trigger
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.utils.state import TaskInstanceState

from tests_common.test_utils.db import clear_db_dags, clear_db_runs, clear_db_triggers

pytestmark = pytest.mark.db_test

DEFAULT_DATE = timezone.datetime(2026, 1, 1)


@pytest.fixture(autouse=True)
def clean_db():
    clear_db_runs()
    clear_db_dags()
    clear_db_triggers()
    yield
    clear_db_runs()
    clear_db_dags()
    clear_db_triggers()


def test_triggerer_without_queues_leaves_a_local_runs_trigger_alone(dag_maker, session):
    with dag_maker("local", session=session):
        EmptyOperator(task_id="task")
    dag_runs = [
        dag_maker.create_dagrun(
            run_id=f"run_{index}", logical_date=DEFAULT_DATE + timedelta(days=index), session=session
        )
        for index in range(2)
    ]
    other_trigger = Trigger(classpath="airflow.triggers.testing.SuccessTrigger", kwargs={})
    session.add(other_trigger)
    session.flush()
    local_trigger = Trigger(classpath="airflow.triggers.testing.SuccessTrigger", kwargs={})
    # As a local run's process does once it has stored its Dags.
    event.listen(Trigger, "before_insert", assign_local_trigger_queue)
    try:
        session.add(local_trigger)
        session.flush()
    finally:
        event.remove(Trigger, "before_insert", assign_local_trigger_queue)
    for dag_run, trigger in zip(dag_runs, (local_trigger, other_trigger)):
        ti = dag_run.get_task_instance("task", session=session)
        ti.state = TaskInstanceState.DEFERRED
        ti.trigger_id = trigger.id
    session.flush()

    claimed = Trigger.get_sorted_triggers(capacity=10, alive_triggerer_ids=[], queues=None, session=session)

    assert [row.id for row in claimed] == [other_trigger.id]
