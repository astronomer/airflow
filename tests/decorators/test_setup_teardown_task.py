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

from airflow.decorators import setup, task, teardown
from airflow.decorators.setup_teardown_task import setup_task, teardown_task


class TestSetupTearDownTask:
    def test_marking_functions_as_setup_task(self, dag_maker):
        @setup
        def mytask():
            print("I am a setup task")

        with dag_maker() as dag:
            for i in range(3):
                mytask.override(task_id=f"mytask_{i}")

        for t in dag.tasks:
            assert t._airflow_setup_task is True

    def test_marking_decorated_task_as_setup_task(self, dag_maker):
        @setup
        @task
        def mytask():
            print("I am a setup task")

        with dag_maker() as dag:
            for i in range(3):
                mytask.override(task_id=f"mytask_{i}")

        for t in dag.tasks:
            assert t._airflow_setup_task is True

    def test_marking_operator_as_setup_task(self, dag_maker):

        from airflow.operators.bash import BashOperator

        with dag_maker() as dag:
            setup_task(BashOperator(task_id="mytask", bash_command='echo "I am a setup task"'))

        for t in dag.tasks:
            assert t._airflow_setup_task is True

    def test_marking_functions_as_teardown_task(self, dag_maker):
        @teardown
        def mytask():
            print("I am a setup task")

        with dag_maker() as dag:
            for i in range(3):
                mytask.override(task_id=f"mytask_{i}")

        for t in dag.tasks:
            assert t._airflow_teardown_task is True

    def test_marking_decorated_task_as_teardown_task(self, dag_maker):
        @teardown
        @task
        def mytask():
            print("I am a setup task")

        with dag_maker() as dag:
            for i in range(3):
                mytask.override(task_id=f"mytask_{i}")

        for t in dag.tasks:
            assert t._airflow_teardown_task is True

    def test_marking_operator_as_teardown_task(self, dag_maker):

        from airflow.operators.bash import BashOperator

        with dag_maker() as dag:
            teardown_task(BashOperator(task_id="mytask", bash_command='echo "I am a setup task"'))

        for t in dag.tasks:
            assert t._airflow_teardown_task is True
