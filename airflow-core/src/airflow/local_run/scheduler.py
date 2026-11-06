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
"""The scheduler of a project's history, which leaves alone the runs a local run's process is driving."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
from sqlalchemy.sql import expression

from airflow._shared.timezones import timezone
from airflow.jobs.scheduler_job_runner import SchedulerJobRunner
from airflow.local_run.ownership import (
    build_locally_driven_run_filter,
    build_locally_driven_ti_filter,
    get_running_local_job_ids,
)
from airflow.models.dag import DagModel
from airflow.models.dagrun import DagRun
from airflow.models.taskinstance import TaskInstance
from airflow.models.trigger import TRIGGER_FAIL_REPR, TriggerFailureReason
from airflow.utils.retries import MAX_DB_RETRIES, run_with_db_retries
from airflow.utils.session import NEW_SESSION, provide_session
from airflow.utils.state import DagRunState, TaskInstanceState

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.orm import Session

    from airflow.callbacks.callback_requests import DagCallbackRequest
    from airflow.utils.sqlalchemy import CommitProhibitorGuard


class LocalSchedulerJobRunner(SchedulerJobRunner):
    """
    Airflow's scheduler, except for the runs that a local run's process is driving.

    That process runs the run's tries itself, so a scheduler that also ran them would run each try twice. Its
    triggers carry a queue, which keeps a triggerer started without ``--queues`` away from them. The one write
    to such a run is its ``last_scheduling_decision``.
    """

    def _schedule_all_dag_runs(
        self,
        guard: CommitProhibitorGuard,
        dag_runs: Iterable[DagRun],
        session: Session,
    ) -> list[tuple[DagRun, DagCallbackRequest]]:
        driving_jobs = get_running_local_job_ids(session=session)
        scheduled = []
        for run in dag_runs:
            if run.creating_job_id in driving_jobs:
                # As examining the run would. Its own loop updates this only between tries, so a run waiting on
                # a long one would otherwise sort first in every examination and hold one of its places.
                run.last_scheduling_decision = timezone.utcnow()
            else:
                scheduled.append(run)
        return super()._schedule_all_dag_runs(guard, scheduled, session)

    def _build_schedulable_tis_query(self, *args, **kwargs) -> Select[tuple[TaskInstance]]:
        # A local run's own loop is not the only writer of SCHEDULED: a fired trigger, or an answer to a
        # human-in-the-loop task given in the UI, sets its try SCHEDULED too.
        return super()._build_schedulable_tis_query(*args, **kwargs).where(~build_locally_driven_ti_filter())

    @provide_session
    def _update_dag_run_state_for_paused_dags(self, *, session: Session = NEW_SESSION) -> None:
        # SchedulerJobRunner._update_dag_run_state_for_paused_dags with one more condition; keep them in step.
        try:
            paused_runs = list(
                session.scalars(
                    select(DagRun)
                    .join(DagRun.dag_model)
                    .join(TaskInstance)
                    .where(
                        DagModel.is_paused == expression.true(),
                        DagRun.state == DagRunState.RUNNING,
                        ~build_locally_driven_run_filter(),
                    )
                    .having(DagRun.last_scheduling_decision <= func.max(TaskInstance.updated_at))
                    .group_by(DagRun)
                )
            )
            self._stamp_team_names(paused_runs, session)
            for dag_run in paused_runs:
                dag = self.scheduler_dag_bag.get_dag_for_run(dag_run=dag_run, session=session)
                if dag is not None:
                    dag_run.dag = dag
                    _, callback_to_run = dag_run.update_state(execute_callbacks=False, session=session)
                    if callback_to_run:
                        self._send_dag_callbacks_to_processor(dag, callback_to_run)
        except Exception as e:  # should not fail the scheduler
            self.log.exception("Failed to update dag run state for paused dags due to %s", e)

    @provide_session
    def check_trigger_timeouts(
        self, max_retries: int = MAX_DB_RETRIES, *, session: Session = NEW_SESSION
    ) -> None:
        # SchedulerJobRunner.check_trigger_timeouts with one more condition; keep them in step.
        for attempt in run_with_db_retries(max_retries, logger=self.log):
            with attempt:
                result = session.execute(
                    update(TaskInstance)
                    .where(
                        TaskInstance.state == TaskInstanceState.DEFERRED,
                        TaskInstance.trigger_timeout < timezone.utcnow(),
                        ~build_locally_driven_ti_filter(),
                    )
                    .values(
                        state=TaskInstanceState.SCHEDULED,
                        next_method=TRIGGER_FAIL_REPR,
                        next_kwargs={"error": TriggerFailureReason.TRIGGER_TIMEOUT},
                        scheduled_dttm=timezone.utcnow(),
                        trigger_id=None,
                    )
                )
                num_timed_out_tasks = getattr(result, "rowcount", 0)
                if num_timed_out_tasks:
                    self.log.info("Timed out %i deferred tasks without fired triggers", num_timed_out_tasks)
