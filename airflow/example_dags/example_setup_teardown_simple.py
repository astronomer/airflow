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
        root_setup1 = BashOperator(
            task_id="root_setup_1", bash_command="sleep 5 && echo 'Hello from root_setup'"
        ).as_setup()
        root_setup2 = BashOperator(
            task_id="root_setup_2", bash_command="sleep 5 && echo 'Hello from root_setup'"
        ).as_setup()
    normal = BashOperator(task_id="normal", bash_command="sleep 5 && echo 'I am just a normal task'")

    skip_op = EmptySkipOperator(task_id="op.skip")
    skip_normal_op = EmptySkipOperator(task_id="normal_op.skip")
    skip_setup = BashOperator(task_id="setup.skip", bash_command="sleep 5").as_setup()
    skip_teardown = BashOperator(task_id="teardown.skip", bash_command="sleep 5").as_teardown()
    normal >> skip_op >> skip_setup >> skip_normal_op >> skip_teardown.teardown_for(skip_setup)

    op_skip_after = BashOperator(task_id="op.skip_after", bash_command="echo 1")
    normal_op_skip_after = EmptySkipOperator(task_id="normal_op.skip_after")
    setup_skip_after = BashOperator(task_id="setup.skip_after", bash_command="sleep 5").as_setup()
    teardown_skip_after = BashOperator(task_id="teardown.skip_after", bash_command="sleep 5")
    (
        normal
        >> op_skip_after
        >> setup_skip_after
        >> normal_op_skip_after
        >> teardown_skip_after.teardown_for(setup_skip_after)
    )

    fail_op = EmptyFailOperator(task_id="op.fail")
    fail_normal_op = EmptyFailOperator(task_id="normal_op.fail")
    fail_setup = BashOperator(task_id="setup.fail", bash_command="sleep 5").as_setup()
    fail_teardown = BashOperator(task_id="teardown.fail", bash_command="sleep 5").as_teardown()
    normal >> fail_op >> fail_setup >> fail_normal_op >> fail_teardown.teardown_for(fail_setup)

    with TaskGroup("section_1") as section_1:
        s_setup = BashOperator(
            task_id="taskgroup_setup", bash_command="sleep 5 && echo 'Hello from taskgroup_setup'"
        ).as_setup()
        s_normal = BashOperator(task_id="normal", bash_command="sleep 5 && exit 1")
        s_teardown = BashOperator(
            task_id="taskgroup_teardown",
            bash_command="sleep 5 && echo 'Hello from taskgroup_teardown'",
        ).as_teardown()

        s_setup >> s_normal >> s_teardown.teardown_for(s_setup)

    normal2 = BashOperator(task_id="normal2", bash_command="sleep 5 && echo 'I am just another normal task'")
    with TaskGroup("dag_teardown", is_teardown=True) as dag_teardown:
        # todo; if taskgroup is marked as teardown, all of its tasks must be teardown
        #     and you can't specify them as such (?)
        # todo: we actually need to be able to mark groups as teardown or setup?????
        #    authoring convenience but is that enough?
        root_teardown1 = BashOperator(
            task_id="root_teardown1",
            bash_command="sleep 5 && echo 'Goodbye from root_teardown'",
        ).teardown_for(root_setup1)
        root_teardown2 = BashOperator(
            task_id="root_teardown2",
            bash_command="sleep 5 && echo 'Goodbye from root_teardown'",
        ).teardown_for(root_setup2)

    dag_setup >> normal >> section_1 >> normal2 >> dag_teardown
    # dag_teardown >> normal_abc  # todo: when all leaves are teardown

# todo: can we chop is_setup from task_instance table
# todo: do we still need is_setup / is_teardown for task groups
