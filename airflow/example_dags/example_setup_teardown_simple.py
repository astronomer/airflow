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
"""Example DAG demonstrating the usage of setup and teardown tasks."""
from __future__ import annotations

import pendulum

from airflow.example_dags.example_skip_dag import EmptySkipOperator
from airflow.models.baseoperator import BaseOperator
from airflow.models.dag import DAG
from airflow.operators.bash import BashOperator
from airflow.utils.task_group import TaskGroup


class EmptyFailOperator(BaseOperator):
    """Fails."""

    def execute(self, context):
        raise ValueError("i fail")


with DAG(
    dag_id="example_setup_teardown_simple",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    with TaskGroup("dag_setup", is_setup=True) as dag_setup:
        root_setup1 = BashOperator.as_setup(
            task_id="root_setup_1", bash_command="sleep 5 && echo 'Hello from root_setup'"
        )
        root_setup2 = BashOperator.as_setup(
            task_id="root_setup_2", bash_command="sleep 5 && echo 'Hello from root_setup'"
        )
    normal = BashOperator(task_id="normal", bash_command="sleep 5 && echo 'I am just a normal task'")
    skip_op = EmptySkipOperator(task_id="skip_op")
    skip_normal_op = EmptySkipOperator(task_id="skip_normal_op")
    skip_setup = BashOperator.as_setup(task_id="skip_setup", bash_command="sleep 5")
    skip_teardown = BashOperator.as_teardown(task_id="skip_teardown", bash_command="sleep 5")
    normal >> skip_op >> skip_setup >> skip_normal_op >> skip_teardown
    skip_setup >> skip_teardown
    fail_op = EmptyFailOperator(task_id="fail_op")
    fail_normal_op = EmptyFailOperator(task_id="fail_normal_op")
    fail_setup = BashOperator.as_setup(task_id="fail_setup", bash_command="sleep 5")
    fail_teardown = BashOperator.as_teardown(task_id="fail_teardown", bash_command="sleep 5")
    normal >> fail_op >> fail_setup >> fail_normal_op >> fail_teardown
    fail_setup >> fail_teardown
    # todo: currently we ignore setup >> teardown directly. but maybe should only do that when dag>>teardown
    #  or perhaps throw error in that case. right now, setup >> teardown is silently ignored.
    with TaskGroup("section_1") as section_1:
        s_setup = BashOperator.as_setup(
            task_id="taskgroup_setup", bash_command="sleep 5 && echo 'Hello from taskgroup_setup'"
        )
        s_normal = BashOperator(task_id="normal", bash_command="sleep 5 && exit 1")
        s_teardown = BashOperator.as_teardown(
            task_id="taskgroup_teardown", bash_command="sleep 5 && echo 'Hello from taskgroup_teardown'"
        )
        s_setup >> s_normal >> s_teardown
    list(section_1.get_leaves())
    assert list(x.task_id for x in section_1.get_leaves()) == ["section_1.normal"]
    normal2 = BashOperator(task_id="normal2", bash_command="sleep 5 && echo 'I am just another normal task'")
    with TaskGroup("dag_teardown", is_teardown=True) as dag_teardown:
        root_teardown1 = BashOperator.as_teardown(
            task_id="root_teardown1", bash_command="sleep 5 && echo 'Goodbye from root_teardown'"
        )
        root_teardown2 = BashOperator.as_teardown(
            task_id="root_teardown2", bash_command="sleep 5 && echo 'Goodbye from root_teardown'"
        )

    dag_setup >> normal >> section_1 >> normal2 >> dag_teardown
    root_setup1 >> root_teardown1
    root_setup2 >> root_teardown2
    root_setup1.downstream_list
    print(normal2.downstream_list)
    assert [x.task_id for x in normal2.upstream_list] == ["section_1.normal"]
    print(root_setup1.get_serialized_fields())
