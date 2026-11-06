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
"""
Which Dag runs a local run's process is driving.

The process registers a job and records it as its run's creator. While that job is running, the run and its
tries belong to the process; once it ends, the run is an ordinary manual run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from airflow.jobs.job import Job, JobState
from airflow.models.dagrun import DagRun
from airflow.models.taskinstance import TaskInstance

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.orm import Mapper, Session
    from sqlalchemy.sql.elements import ColumnElement

    from airflow.models.trigger import Trigger

LOCAL_RUN_JOB_TYPE = "LocalRunJob"
# A triggerer started without --queues, as the project's is, claims only triggers without a queue.
LOCAL_RUN_TRIGGER_QUEUE = "local-run"


def assign_local_trigger_queue(mapper: Mapper, connection: Connection, trigger: Trigger) -> None:
    """Keep the project's triggerer away from a trigger a local run's process creates, and runs itself."""
    trigger.queue = LOCAL_RUN_TRIGGER_QUEUE


def get_running_local_job_ids(*, session: Session) -> set[int]:
    return set(
        session.scalars(
            select(Job.id).where(Job.job_type == LOCAL_RUN_JOB_TYPE, Job.state == JobState.RUNNING)
        )
    )


def build_locally_driven_run_filter() -> ColumnElement[bool]:
    """Match the Dag runs whose local run's process is still running."""
    return (
        select(Job.id)
        .where(
            Job.id == DagRun.creating_job_id,
            Job.job_type == LOCAL_RUN_JOB_TYPE,
            Job.state == JobState.RUNNING,
        )
        .correlate(DagRun)
        .exists()
    )


def build_locally_driven_ti_filter() -> ColumnElement[bool]:
    """Match the task instances of the Dag runs whose local run's process is still running."""
    return (
        select(DagRun.id)
        .join(Job, Job.id == DagRun.creating_job_id)
        .where(
            DagRun.dag_id == TaskInstance.dag_id,
            DagRun.run_id == TaskInstance.run_id,
            Job.job_type == LOCAL_RUN_JOB_TYPE,
            Job.state == JobState.RUNNING,
        )
        .correlate(TaskInstance)
        .exists()
    )
