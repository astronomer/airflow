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
"""Example DAG demonstrating the usage of the TaskGroup."""
from __future__ import annotations

import pendulum

from airflow.models.dag import DAG
from airflow.operators.bash import BashOperator
from airflow.utils.task_group import TaskGroup

# [START howto_task_group]
with DAG(
    dag_id="example_task_group_with_setup",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    setup_dag = BashOperator.as_setup(task_id="setup_dag", bash_command="sleep 15")
    teardown_dag = BashOperator.as_teardown(task_id="teardown_dag", bash_command="sleep 15")
    start = BashOperator(task_id="start", bash_command="sleep 15")

    # [START howto_task_group_section_1]
    with TaskGroup("section_1", tooltip="Tasks for section_1") as section_1:
        setup_section_1 = BashOperator.as_setup(task_id="setup_1", bash_command="sleep 15")
        teardown_section_1 = BashOperator.as_teardown(task_id="teardown_1", bash_command="sleep 15")
        task_1 = BashOperator(task_id="task_1", bash_command="sleep 15")
        task_2 = BashOperator(task_id="task_2", bash_command="sleep 15")
        task_3 = BashOperator(task_id="task_3", bash_command="sleep 15")

        task_1 >> [task_2, task_3]
    # [END howto_task_group_section_1]

    # [START howto_task_group_section_2]
    with TaskGroup("section_2", tooltip="Tasks for section_2") as section_2:
        setup_section_2 = BashOperator.as_setup(task_id="setup_2", bash_command="sleep 15")
        teardown_section_2 = BashOperator.as_teardown(task_id="teardown_2", bash_command="sleep 15")
        task_1 = BashOperator(task_id="task_1", bash_command="sleep 15")

        # [START howto_task_group_inner_section_2]
        with TaskGroup("inner_section_2", tooltip="Tasks for inner_section2") as inner_section_2:
            setup_inner_section_2 = BashOperator.as_setup(task_id="setup_2_inner", bash_command="sleep 15")
            teardown_inner_section_2 = BashOperator.as_teardown(
                task_id="teardown_2_inner", bash_command="sleep 15"
            )
            task_2 = BashOperator(task_id="task_2", bash_command="sleep 15")
            task_3 = BashOperator(task_id="task_3", bash_command="sleep 15")
            task_4 = BashOperator(task_id="task_4", bash_command="sleep 15")

            [task_2, task_3] >> task_4
        # [END howto_task_group_inner_section_2]

    # [END howto_task_group_section_2]

    end = BashOperator(task_id="end", bash_command="sleep 15")

    start >> section_1 >> section_2 >> end
# [END howto_task_group]
