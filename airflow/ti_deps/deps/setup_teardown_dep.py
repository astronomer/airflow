#
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

from typing import TYPE_CHECKING, Iterator

from airflow.ti_deps.dep_context import DepContext
from airflow.ti_deps.deps.base_ti_dep import BaseTIDep, TIDepStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from airflow.models.taskinstance import TaskInstance


class SetupTeardownDep(BaseTIDep):
    NAME = "Setup and Teardown rules"
    IGNORABLE = True
    IS_TASK_DEP = True

    def _get_dep_statuses(
        self,
        ti: TaskInstance,
        session: Session,
        dep_context: DepContext,
    ) -> Iterator[TIDepStatus]:
        # ti -> taskgroup -> tg.setup, see if it is done

        task = ti.task

        if not task.task_group.setup_children:
            return

        setup_task_ids = {x.task_id for x in task.task_group.setup_children.values()}
        teardown_task_ids = {x.task_id for x in task.task_group.teardown_children.values()}
        normal_task_ids = (
            {x.task_id for x in task.task_group.iter_tasks()} - setup_task_ids - teardown_task_ids
        )

        is_setup_task = task.task_id in setup_task_ids
        is_teardown_task = task.task_id in teardown_task_ids

        if is_setup_task:
            yield self._passing_status(reason="Task is a setup task")
            return

        finished_tis = dep_context.ensure_finished_tis(ti.get_dagrun(session), session)
        finished_task_ids = {x.task_id for x in finished_tis}

        if is_teardown_task:
            remaining = normal_task_ids - finished_task_ids
            print(f"remaining normal: {remaining}")
            if remaining:
                yield self._failing_status(reason=f"Not all normal tasks have finished: {len(remaining)}")

        # normal tasks
        remaining = setup_task_ids - finished_task_ids
        print(f"remaining normal: {remaining}")

        if remaining:
            yield self._failing_status(reason=f"Not all setup tasks have finished: {len(remaining)}")
