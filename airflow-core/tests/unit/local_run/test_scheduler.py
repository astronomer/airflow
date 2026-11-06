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
from unittest import mock

import pytest
import time_machine

from airflow._shared.timezones import timezone
from airflow.jobs.job import Job, JobState
from airflow.local_run.ownership import LOCAL_RUN_JOB_TYPE
from airflow.local_run.scheduler import LocalSchedulerJobRunner
from airflow.models.dag import DagModel
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.utils.sqlalchemy import prohibit_commit
from airflow.utils.state import DagRunState, TaskInstanceState

from tests_common.test_utils.db import clear_db_dags, clear_db_jobs, clear_db_runs

pytestmark = pytest.mark.db_test

DEFAULT_DATE = timezone.datetime(2026, 1, 1)
NOW = timezone.datetime(2026, 2, 1)

# A run driven by a local run's process that is still running, one whose process has ended, and one that no
# local run's process drives.
JOB_STATES = (JobState.RUNNING, JobState.SUCCESS, None)


@pytest.fixture(autouse=True)
def clean_db():
    clear_db_runs()
    clear_db_dags()
    clear_db_jobs()
    yield
    clear_db_runs()
    clear_db_dags()
    clear_db_jobs()


@pytest.fixture
def scheduler() -> LocalSchedulerJobRunner:
    return LocalSchedulerJobRunner(job=Job())


@pytest.fixture
def dag_runs(dag_maker, session):
    """Create a running run of Dag ``local`` for each of ``JOB_STATES``, with the job driving it in that state."""
    with dag_maker("local", session=session, max_active_tasks=16):
        EmptyOperator(task_id="task")
    runs = []
    for index, job_state in enumerate(JOB_STATES):
        dag_run = dag_maker.create_dagrun(
            run_id=f"run_{index}",
            logical_date=DEFAULT_DATE + timedelta(days=index),
            state=DagRunState.RUNNING,
            session=session,
        )
        if job_state is not None:
            job = Job(job_type=LOCAL_RUN_JOB_TYPE, state=job_state)
            session.add(job)
            session.flush()
            dag_run.creating_job_id = job.id
        runs.append(dag_run)
    session.flush()
    return runs


@time_machine.travel(NOW, tick=False)
@mock.patch.object(LocalSchedulerJobRunner, "_schedule_dag_run", autospec=True, return_value=None)
def test_runs_a_local_process_drives_are_not_scheduled(schedule_dag_run, scheduler, dag_runs, session):
    driven, ended, other = dag_runs

    with prohibit_commit(session) as guard:
        scheduler._schedule_all_dag_runs(guard, dag_runs, session)

    assert [call.args[1] for call in schedule_dag_run.call_args_list] == [ended, other]
    # So that the run sorts behind the ones examined before it, as if it had been examined.
    assert driven.last_scheduling_decision == NOW


def test_tries_of_runs_a_local_process_drives_are_not_queued(scheduler, dag_runs, session):
    for dag_run in dag_runs:
        dag_run.get_task_instance("task", session=session).state = TaskInstanceState.SCHEDULED
    session.flush()

    query = scheduler._build_schedulable_tis_query(set(), set(), set(), set(), 32)

    assert sorted(ti.run_id for ti in session.scalars(query)) == ["run_1", "run_2"]


def test_paused_dag_pass_leaves_runs_a_local_process_drives(scheduler, dag_runs, session):
    for dag_run in dag_runs:
        dag_run.last_scheduling_decision = timezone.utcnow() - timedelta(minutes=1)
        dag_run.get_task_instance("task", session=session).set_state(
            TaskInstanceState.SUCCESS, session=session
        )
    DagModel.get_dagmodel("local", session=session).is_paused = True
    session.flush()

    scheduler._update_dag_run_state_for_paused_dags(session=session)

    for dag_run in dag_runs:
        session.refresh(dag_run)
    assert [dag_run.state for dag_run in dag_runs] == [
        DagRunState.RUNNING,
        DagRunState.SUCCESS,
        DagRunState.SUCCESS,
    ]


def test_trigger_timeouts_leave_tries_a_local_process_drives(scheduler, dag_runs, session):
    tis = [dag_run.get_task_instance("task", session=session) for dag_run in dag_runs]
    for ti in tis:
        ti.state = TaskInstanceState.DEFERRED
        ti.trigger_timeout = timezone.utcnow() - timedelta(minutes=1)
    session.flush()

    scheduler.check_trigger_timeouts(session=session)

    for ti in tis:
        session.refresh(ti)
    assert [ti.state for ti in tis] == [
        TaskInstanceState.DEFERRED,
        TaskInstanceState.SCHEDULED,
        TaskInstanceState.SCHEDULED,
    ]
