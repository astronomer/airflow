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

with DAG(
    dag_id="example_setup_teardown_taskflow",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    # You can use the setup and teardown decorators to add setup and teardown tasks at the DAG level
    @setup
    @task
    def root_setup():
        print("Hello from root_setup")

    @teardown
    @task
    def root_teardown():
        print("Goodbye from root_teardown")

    @task
    def normal():
        print("I am just a normal task")

    @task_group
    def section_1():
        # You can also have setup and teardown tasks at the task group level
        @setup
        @task
        def my_setup():
            print("I set up")

        @teardown
        @task
        def my_teardown():
            print("I tear down")

        @task
        def hello():
            raise ValueError("fail!")
            print("I say hello")

        my_setup_task = my_setup()
        my_teardown_task = my_teardown()
        my_setup_task >> hello() >> my_teardown_task
        my_setup_task >> my_teardown_task

    # root_setup()
    # normal() >> section_1()
    # root_teardown()

    @task_group
    def section_2():
        # You can also mark task groups as setup and teardown
        # and all tasks in them will be setup/teardown tasks
        @setup
        @task_group
        def my_setup_taskgroup():
            @task
            def first_setup():
                print("I set some stuff up")

            @task
            def second_setup():
                print("I set some other stuff up")

            first_setup()
            second_setup()

        @task
        def hello():
            print("I say hello")

        my_setup_taskgroup() >> hello()

    root_setup_task = root_setup()
    # breakpoint()
    normal() >> section_1() >> section_2()
    root_setup_task >> dag
    root_teardown_task = root_teardown()
    root_setup_task >> root_teardown_task

    dag >> root_teardown_task
