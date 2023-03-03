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

from airflow.models.baseoperator import BaseOperator
from airflow.ti_deps.dep_context import DepContext
from airflow.ti_deps.deps.setup_teardown_dep import SetupTeardownDep
from airflow.utils.state import TaskInstanceState
from airflow.utils.task_group import TaskGroup


class TestSetupTeardownDep:
    def test_return_if_setup_task(self, session, dag_maker):
        """Setup tasks should pass dep even if nothing has run. Other types, no."""
        with dag_maker(session=session):
            BaseOperator.as_setup(task_id="setup_task")
            BaseOperator(task_id="normal_task")
            BaseOperator.as_teardown(task_id="teardown_task")
        dr = dag_maker.create_dagrun()
        ti_normal = [x for x in dr.task_instances if x.task_id == "normal_task"][0]
        ti_setup = [x for x in dr.task_instances if x.task_id == "setup_task"][0]
        ti_teardown = [x for x in dr.task_instances if x.task_id == "teardown_task"][0]
        assert SetupTeardownDep().is_met(ti_setup)
        assert not SetupTeardownDep().is_met(ti_normal)
        assert not SetupTeardownDep().is_met(ti_teardown)

    def test__get_dep_statuses_none_finished(self, session, dag_maker):
        with dag_maker(session=session):
            BaseOperator.as_setup(task_id="setup_task")
            BaseOperator(task_id="normal_task")
            BaseOperator.as_teardown(task_id="teardown_task")
        dr = dag_maker.create_dagrun()
        ti_setup = [x for x in dr.task_instances if x.task_id == "setup_task"][0]
        ti_normal = [x for x in dr.task_instances if x.task_id == "normal_task"][0]
        ti_teardown = [x for x in dr.task_instances if x.task_id == "teardown_task"][0]
        actual = list(SetupTeardownDep()._get_dep_statuses(ti_setup, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Task is a setup task and ancestors complete"
        actual = list(SetupTeardownDep()._get_dep_statuses(ti_normal, session, DepContext()))[0]
        assert actual.passed is False
        assert actual.reason == "Not all setup tasks have finished: 1"
        actual = list(SetupTeardownDep()._get_dep_statuses(ti_teardown, session, DepContext()))[0]
        assert actual.passed is False
        assert actual.reason == "Not all normal tasks have finished: 1"

    def test__get_dep_statuses_setup_finished(self, session, dag_maker):
        with dag_maker(session=session):
            BaseOperator.as_setup(task_id="setup_task")
            BaseOperator(task_id="normal_task")
            BaseOperator.as_teardown(task_id="teardown_task")
        dr = dag_maker.create_dagrun()
        ti_setup = [x for x in dr.task_instances if x.task_id == "setup_task"][0]

        # mark setup task as done
        ti_setup.state = TaskInstanceState.SUCCESS
        session.commit()

        ti_normal = [x for x in dr.task_instances if x.task_id == "normal_task"][0]
        ti_teardown = [x for x in dr.task_instances if x.task_id == "teardown_task"][0]
        actual = list(SetupTeardownDep()._get_dep_statuses(ti_setup, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Task is a setup task and ancestors complete"

        actual = list(SetupTeardownDep()._get_dep_statuses(ti_normal, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Setup tasks have completed without failure."

        actual = list(SetupTeardownDep()._get_dep_statuses(ti_teardown, session, DepContext()))[0]
        assert actual.passed is False
        assert actual.reason == "Not all normal tasks have finished: 1"

    def test__get_dep_statuses_normal_success(self, session, dag_maker):
        with dag_maker(session=session):
            BaseOperator.as_setup(task_id="setup_task")
            BaseOperator(task_id="normal_task")
            BaseOperator.as_teardown(task_id="teardown_task")
        dr = dag_maker.create_dagrun()
        ti_setup = [x for x in dr.task_instances if x.task_id == "setup_task"][0]
        ti_normal = [x for x in dr.task_instances if x.task_id == "normal_task"][0]
        ti_teardown = [x for x in dr.task_instances if x.task_id == "teardown_task"][0]

        # mark setup task as done
        ti_setup.state = TaskInstanceState.SUCCESS
        ti_normal.state = TaskInstanceState.SUCCESS
        session.commit()

        actual = list(SetupTeardownDep()._get_dep_statuses(ti_setup, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Task is a setup task and ancestors complete"

        actual = list(SetupTeardownDep()._get_dep_statuses(ti_normal, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Setup tasks have completed without failure."

        actual = list(SetupTeardownDep()._get_dep_statuses(ti_teardown, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Setup completed successfully and normal tasks finished."

    def test__get_dep_statuses_normal_failed(self, session, dag_maker):
        with dag_maker(session=session):
            BaseOperator.as_setup(task_id="setup_task")
            BaseOperator(task_id="normal_task")
            BaseOperator.as_teardown(task_id="teardown_task")
        dr = dag_maker.create_dagrun()
        ti_setup = [x for x in dr.task_instances if x.task_id == "setup_task"][0]
        ti_normal = [x for x in dr.task_instances if x.task_id == "normal_task"][0]
        ti_teardown = [x for x in dr.task_instances if x.task_id == "teardown_task"][0]

        # mark setup task as done
        ti_setup.state = TaskInstanceState.SUCCESS
        ti_normal.state = TaskInstanceState.FAILED
        session.commit()

        actual = list(SetupTeardownDep()._get_dep_statuses(ti_setup, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Task is a setup task and ancestors complete"

        actual = list(SetupTeardownDep()._get_dep_statuses(ti_normal, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Setup tasks have completed without failure."

        actual = list(SetupTeardownDep()._get_dep_statuses(ti_teardown, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Setup completed successfully and normal tasks finished."

    def test__get_dep_statuses_setup_failed(self, session, dag_maker):
        with dag_maker(session=session):
            BaseOperator.as_setup(task_id="setup_task")
            BaseOperator(task_id="normal_task")
            BaseOperator.as_teardown(task_id="teardown_task")
        dr = dag_maker.create_dagrun()
        ti_setup = [x for x in dr.task_instances if x.task_id == "setup_task"][0]

        # mark setup task as done
        ti_setup.state = TaskInstanceState.FAILED
        session.commit()

        ti_normal = [x for x in dr.task_instances if x.task_id == "normal_task"][0]
        ti_teardown = [x for x in dr.task_instances if x.task_id == "teardown_task"][0]
        actual = list(SetupTeardownDep()._get_dep_statuses(ti_setup, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Task is a setup task and ancestors complete"

        # dep check should fail and state updated to upstream failed
        actual = list(SetupTeardownDep()._get_dep_statuses(ti_normal, session, DepContext()))[0]
        assert actual.passed is False
        assert actual.reason == "Some setup tasks were not in 'success', 'skipped'."
        assert ti_normal.state == TaskInstanceState.UPSTREAM_FAILED

        # doesn't run cus normal tasks didn't run
        actual = list(SetupTeardownDep()._get_dep_statuses(ti_teardown, session, DepContext()))[0]
        assert actual.passed is False
        assert actual.reason == "Not all normal tasks have finished: 1"

    def test__get_dep_statuses_in_taskgroup(self, session, dag_maker):
        with dag_maker(session=session):
            with TaskGroup("group1"):
                BaseOperator.as_setup(task_id="setup_task")
                BaseOperator.as_teardown(task_id="teardown_task")
                BaseOperator(task_id="normal_task")

        dr = dag_maker.create_dagrun()
        ti_setup = [x for x in dr.task_instances if x.task_id == "group1.setup_task"][0]
        ti_normal = [x for x in dr.task_instances if x.task_id == "group1.normal_task"][0]
        ti_teardown = [x for x in dr.task_instances if x.task_id == "group1.teardown_task"][0]
        actual = list(SetupTeardownDep()._get_dep_statuses(ti_setup, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Task is a setup task and ancestors complete"

        ti_setup.state = TaskInstanceState.SUCCESS
        session.merge(ti_setup)
        session.commit()
        actual = list(SetupTeardownDep()._get_dep_statuses(ti_normal, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Setup tasks have completed without failure."

        # Complete normal task
        ti_normal.state = TaskInstanceState.SUCCESS
        session.merge(ti_normal)
        session.commit()
        # assert teardown passed
        actual = list(SetupTeardownDep()._get_dep_statuses(ti_teardown, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Setup completed successfully and normal tasks finished."

    def test__get_dep_statuses_in_for_setup_tasks_in_taskgroup_with_subgroup(self, session, dag_maker):
        with dag_maker(session=session):
            with TaskGroup("group1"):
                BaseOperator.as_setup(task_id="setup_task_1")
                BaseOperator(task_id="normal_task_1")
                with TaskGroup("subgroup1"):
                    BaseOperator.as_setup(task_id="setup_task_2")
                    BaseOperator(task_id="normal_task_2")

        dr = dag_maker.create_dagrun()
        ti_setup_1 = [x for x in dr.task_instances if x.task_id == "group1.setup_task_1"][0]
        ti_normal_1 = [x for x in dr.task_instances if x.task_id == "group1.normal_task_1"][0]
        ti_setup_2 = [x for x in dr.task_instances if x.task_id == "group1.subgroup1.setup_task_2"][0]

        actual = list(SetupTeardownDep()._get_dep_statuses(ti_setup_1, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Task is a setup task and ancestors complete"

        # Setup 1 in outer group must be done before setup 2 in inner group can run
        actual = list(SetupTeardownDep()._get_dep_statuses(ti_setup_2, session, DepContext()))[0]
        assert actual.passed is False
        assert actual.reason == "Setup tasks in parent group not complete: 1"

        # Complete setup 1 in outer group and also the normal task in outer group
        ti_setup_1.state = TaskInstanceState.SUCCESS
        ti_normal_1.state = TaskInstanceState.SUCCESS
        session.merge(ti_setup_1)
        session.merge(ti_normal_1)
        session.commit()
        actual = list(SetupTeardownDep()._get_dep_statuses(ti_setup_2, session, DepContext()))[0]
        assert actual.passed is True
        assert actual.reason == "Task is a setup task and ancestors complete"
