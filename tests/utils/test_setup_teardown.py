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

import pytest

from airflow.decorators import setup, task, teardown
from airflow.exceptions import AirflowException
from airflow.utils.setup_teardown import SetupTeardownContext, setup_teardown


class TestSetupTearDownContext:
    def test_setup(self):
        assert SetupTeardownContext.is_setup is False
        assert SetupTeardownContext.is_teardown is False

        with SetupTeardownContext.setup():
            assert SetupTeardownContext.is_setup is True
            assert SetupTeardownContext.is_teardown is False

        assert SetupTeardownContext.is_setup is False
        assert SetupTeardownContext.is_teardown is False

    def test_teardown(self):
        assert SetupTeardownContext.is_setup is False
        assert SetupTeardownContext.is_teardown is False

        with SetupTeardownContext.setup():
            assert SetupTeardownContext.is_setup is True
            assert SetupTeardownContext.is_teardown is False

        assert SetupTeardownContext.is_setup is False
        assert SetupTeardownContext.is_teardown is False

    def test_setup_exception(self):
        """Ensure context is reset even if an exception happens"""
        with pytest.raises(Exception, match="Hello"):
            with SetupTeardownContext.setup():
                raise Exception("Hello")

        assert SetupTeardownContext.is_setup is False
        assert SetupTeardownContext.is_teardown is False

    def test_teardown_exception(self):
        """Ensure context is reset even if an exception happens"""
        with pytest.raises(Exception, match="Hello"):
            with SetupTeardownContext.teardown():
                raise Exception("Hello")

        assert SetupTeardownContext.is_setup is False
        assert SetupTeardownContext.is_teardown is False

    def test_setup_block_nested(self):
        with SetupTeardownContext.setup():
            with pytest.raises(
                AirflowException,
                match=("You cannot mark a setup or teardown task as setup or teardown again."),
            ):
                with SetupTeardownContext.setup():
                    raise Exception("This should not be reached")

        assert SetupTeardownContext.is_setup is False
        assert SetupTeardownContext.is_teardown is False

    def test_teardown_block_nested(self):
        with SetupTeardownContext.teardown():
            with pytest.raises(
                AirflowException,
                match=("You cannot mark a setup or teardown task as setup or teardown again."),
            ):
                with SetupTeardownContext.teardown():
                    raise Exception("This should not be reached")

        assert SetupTeardownContext.is_setup is False
        assert SetupTeardownContext.is_teardown is False

    def test_teardown_nested_in_setup_blocked(self):
        with SetupTeardownContext.setup():
            with pytest.raises(
                AirflowException,
                match=("You cannot mark a setup or teardown task as setup or teardown again."),
            ):
                with SetupTeardownContext.teardown():
                    raise Exception("This should not be reached")

        assert SetupTeardownContext.is_setup is False
        assert SetupTeardownContext.is_teardown is False

    def test_setup_nested_in_teardown_blocked(self):
        with SetupTeardownContext.teardown():
            with pytest.raises(
                AirflowException,
                match=("You cannot mark a setup or teardown task as setup or teardown again."),
            ):
                with SetupTeardownContext.setup():
                    raise Exception("This should not be reached")

        assert SetupTeardownContext.is_setup is False
        assert SetupTeardownContext.is_teardown is False

    def test_setup_teardown_context(self, dag_maker):
        @setup
        def setup_task():
            print(1)

        @setup
        def setup_task2():
            print(1)

        @teardown
        def teardown_task():
            print(2)

        @teardown
        def teardown_task2():
            print(2)

        @task
        def normal_task():
            print(3)

        @task
        def normal_task2():
            print(4)

        setup1 = setup_task()
        setup2 = setup_task2()
        teardown1 = teardown_task()
        teardown2 = teardown_task2()
        with dag_maker() as dag:
            with setup_teardown([setup1, setup2], [teardown1, teardown2]):
                task1 = normal_task()
                task2 = normal_task2()
                task1 >> task2

        task_group = dag.task_group
        assert task_group.roots == [setup1.operator]
        assert task_group.leaves == [teardown1.operator]
        assert task_group.children["setup_task2"].upstream_list == [setup1.operator]
        assert set(task_group.children["setup_task2"].downstream_list) == {task1.operator, teardown2.operator}
        assert set(task_group.children["setup_task"].downstream_list) == {setup2.operator, teardown1.operator}
        assert task_group.children["normal_task2"].upstream_list == [task1.operator]
        assert task_group.children["normal_task2"].downstream_list == [teardown2.operator]
        assert set(task_group.children["teardown_task"].upstream_list) == {
            teardown2.operator,
            setup1.operator,
        }
