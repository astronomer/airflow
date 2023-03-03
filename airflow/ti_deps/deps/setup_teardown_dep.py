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
from airflow.utils.state import TaskInstanceState

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from airflow.models.baseoperator import BaseOperator
    from airflow.models.taskinstance import TaskInstance


class SetupTeardownDep(BaseTIDep):
    """Check for dependencies between setup / teardown tasks and the "normal" tasks they serve."""

    NAME = "Setup and Teardown"
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

        finished_tis = dep_context.ensure_finished_tis(ti.get_dagrun(session), session)
        finished_setup_tis = [x for x in finished_tis if x.task_id in setup_task_ids]
        finished_task_ids = {x.task_id for x in finished_tis}

        if is_setup_task:
            # a single setup task should run only if the following
            #  * group roots have no upstreams (or they are done)
            #  * parent group has no setup tasks (or they are done)
            # todo: test to add: if parent setup is task, easy; if group, check roots

            roots: set[BaseOperator] = {*ti.task.task_group.get_roots()}
            # todo: add test for parent has normal to normal and no other deps
            # todo: test interdeps in setup group
            # todo: remove ability to set upstream between normal and setup
            # todo: how do we accomplish setup-to-setup deps....
            root_upstream_ids = {task_id for root in roots for task_id in root.upstream_task_ids}
            # todo: add test for parent group has only setup and no normal
            # todo: for teardown, have to do reverse

            # todo: if this is group, must check only leaves!!!
            # todo: what is the "trigger rule" for passing setup groups -- leaves are success or skipped?
            parent_setup_task_ids = set()
            if task.task_group.parent_group:
                parent_setup_task_ids |= {
                    x.task_id for x in task.task_group.parent_group.setup_children.values()
                }
            unfinished_parent_setup = parent_setup_task_ids.difference(finished_task_ids)
            if unfinished_parent_setup:
                yield self._failing_status(
                    reason=f"Setup tasks in parent group not complete: {len(unfinished_parent_setup)}"
                )
                return
            unfinished_group_upstream = root_upstream_ids.difference(finished_task_ids)
            if unfinished_group_upstream:
                yield self._failing_status(
                    reason=f"Group upstream tasks not complete: {len(unfinished_group_upstream)}"
                )
                return
            yield self._passing_status(reason="Task is a setup task and ancestors complete")
            return

        if is_teardown_task:
            remaining_normal = normal_task_ids - finished_task_ids
            print(f"remaining normal: {remaining_normal}")
            if remaining_normal:
                yield self._failing_status(
                    reason=f"Not all normal tasks have finished: {len(remaining_normal)}"
                )
                return
            else:
                yield self._passing_status("Setup completed successfully and normal tasks finished.")
                return

        # we are dealing with a normal task

        # first check if there are remaining setup tasks
        remaining_setup = setup_task_ids - finished_task_ids
        print(f"remaining setup: {remaining_setup}")
        if remaining_setup:
            yield self._failing_status(reason=f"Not all setup tasks have finished: {len(remaining_setup)}")
            return

        # all setup tasks complete; check if state is ok now.
        changed = False
        can_proceed_states = {TaskInstanceState.SUCCESS, TaskInstanceState.SKIPPED}
        if not all(x.state in can_proceed_states for x in finished_setup_tis):
            # todo: do we need to check dep_context.flag_upstream_failed?
            changed = ti.set_state(TaskInstanceState.UPSTREAM_FAILED, session)
        if changed:
            dep_context.have_changed_ti_states = True
        if ti.state == TaskInstanceState.UPSTREAM_FAILED:
            yield self._failing_status(reason="Some setup tasks were not in 'success', 'skipped'.")
            return
        else:
            yield self._passing_status(reason="Setup tasks have completed without failure.")
            return
