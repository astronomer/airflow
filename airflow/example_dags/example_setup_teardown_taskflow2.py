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

from airflow.decorators import setup, task, task_group, teardown
from airflow.models.dag import DAG
from airflow.operators.bash import BashOperator
from airflow.utils.task_group import TaskGroup


def my_setup(task_id):
    return BashOperator.as_setup(task_id=task_id, bash_command=f"echo 'task_id={task_id}'")


def my_teardown(task_id):
    return BashOperator.as_teardown(task_id=task_id, bash_command=f"echo 'task_id={task_id}'")


def my_work(task_id):
    return BashOperator(task_id=task_id, bash_command=f"echo 'task_id={task_id}'")


with DAG(
    dag_id="example_setup_teardown_teardown_conditions",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    setup1 = my_setup("setup1")
    setup2 = my_setup("setup2")
    work1 = my_work("work1")
    teardown1 = my_teardown("teardown1")
    teardown2 = my_teardown("teardown2")
    [setup1, setup2] >> work1 >> [teardown1, teardown2]
    setup1 >> teardown1
    setup2 >> teardown2


with DAG(
    dag_id="example_setup_teardown_clearing_behavior",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    setup1 = my_setup("setup1")
    work1 = my_work("work1")
    teardown1 = my_teardown("teardown1")
    setup1 >> work1 >> teardown1
    setup1 >> teardown1
    work1 >> my_work("work2")


with DAG(
    dag_id="example_setup_teardown_task_group_to_task",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    with TaskGroup("my_group1") as tg1:
        setup1 = my_setup("setup")
        work1 = my_work("work")
        teardown1 = my_teardown("teardown")
        setup1 >> work1 >> teardown1
        setup1 >> teardown1
    work2 = my_work("work")
    tg1 >> work2

with DAG(
    dag_id="example_setup_teardown_inner_outer",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    dag_setup = my_setup("dag_setup")
    dag_work = my_work("dag_work")
    dag_teardown = my_teardown("dag_teardown")
    dag_setup >> dag_work >> dag_teardown
    dag_setup >> dag_teardown
    with TaskGroup("my_group1") as tg1:
        setup1 = my_setup("setup")
        work1 = my_work("work")
        teardown1 = my_teardown("teardown")
        setup1 >> work1 >> teardown1
        setup1 >> teardown1
    dag_setup >> tg1 >> dag_teardown
    teardown1 >> dag_teardown

with DAG(
    dag_id="example_setup_teardown_chain_task_group",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    with TaskGroup("my_group1") as tg1:
        setup1 = my_setup("setup")
        work1 = my_work("work")
        teardown1 = my_teardown("teardown")
        setup1 >> work1 >> teardown1
        setup1 >> teardown1
    with TaskGroup("my_group2") as tg2:
        setup2 = my_setup("setup")
        work2 = my_work("work")
        teardown2 = my_teardown("teardown")
        setup2 >> work2 >> teardown2
        setup2 >> teardown2
    tg1 >> tg2

with DAG(
    dag_id="example_setup_teardown_complicated_nested",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    with TaskGroup("group1") as tg1:
        setup1 = my_setup("g1_setup")
        work1 = my_work("g1_work")
        teardown1 = my_teardown("g1_teardown")
        setup1 >> work1 >> teardown1
        setup1 >> teardown1
        with TaskGroup("group2") as tg2:
            setup2 = my_setup("g2_setup")
            work2 = my_work("g2_work")
            teardown2 = my_teardown("g2_teardown")
            setup2 >> work2 >> teardown2
            setup2 >> teardown2
        work1 >> setup2
    with TaskGroup("dag_setup", is_setup=True) as dag_setup_group:
        dag_setup1 = my_setup("dag_setup1")
        dag_setup2 = my_setup("dag_setup2")
    with TaskGroup("dag_teardown", is_teardown=True) as dag_teardown_group:
        dag_teardown1 = my_teardown("dag_teardown1")
        dag_teardown2 = my_teardown("dag_teardown2")
    dag_setup_group >> my_work("dag_work1") >> dag_teardown_group
    dag_setup_group >> tg1
    tg1 >> my_work("dag_work2") >> dag_teardown_group
    dag_setup1 >> dag_teardown1
    dag_setup2 >> dag_teardown2



with DAG(
    dag_id="example_setup_teardown_complicated",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    with TaskGroup("group1") as tg1:
        setup1 = my_setup("g1_setup")
        work1 = my_work("g1_work")
        teardown1 = my_teardown("g1_teardown")
        setup1 >> work1 >> teardown1
        setup1 >> teardown1
    with TaskGroup("dag_setup", is_setup=True) as dag_setup_group:
        dag_setup1 = my_setup("dag_setup1")
        dag_setup2 = my_setup("dag_setup2")
    with TaskGroup("dag_teardown", is_teardown=True) as dag_teardown_group:
        dag_teardown1 = my_teardown("dag_teardown1")
        dag_teardown2 = my_teardown("dag_teardown2")
    dag_setup_group >> my_work("dag_work1") >> dag_teardown_group
    dag_setup_group >> tg1
    tg1 >> my_work("dag_work2") >> dag_teardown_group
    dag_setup1 >> dag_teardown1
    dag_setup2 >> dag_teardown2








