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
"""Example DAG demonstrating the usage of the setup and teardown relationships."""
from __future__ import annotations

import pendulum

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.utils.task_group import TaskGroup

with DAG(
    dag_id="example_teardown_1",
    schedule="0 0 * * *",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
) as dag:
    """Example showing dag >> task without a "setup" concept."""
    dag_setup = BashOperator(
        task_id="dag_setup",
        bash_command="echo 1",
    )

    dag_teardown = BashOperator(
        task_id="dag_teardown",
        bash_command="echo 1",
    )

    for group_name in ("group1", "group2"):
        with TaskGroup(group_name):
            work_1 = BashOperator(
                task_id="work_1",
                bash_command="echo 1",
            )
            setup_1 = BashOperator(
                task_id="setup_1",
                bash_command="echo 1",
            )
            teardown_1 = BashOperator(
                task_id="teardown_1",
                bash_command="echo 1",
            )
            dag_setup >> setup_1 >> work_1 >> teardown_1 >> dag_teardown
# todo: if the clear work 1 with downstream false, it should still clear the downstream teardowns
# todo: when clearing upstream, we have to recurse the upstreams for their setup and teardowns
# todo: question: right now when clearing upstream, does it clear the downstreams of each upstream?
# simple_setup_teardown


#     dag >> teardown_1
#     group_1 = None
#     group_1 >> teardown_1
#     setup_1 >> group_1  # todo: don't connect the setup to the teardown roots?
# # todo: when task marked teardown, ignore arrowed if arrowed at task group level
# for task in dag.tasks:
#     print(task, task.upstream_task_ids)
# todo: when clearing work task in group, then we clear setup in parent group but don't clear the other
#  descendents of the parent group setup. different behavior.
#
# todo: when clearing tasks, we need to keep track of each teardown which is downstream of a setup
