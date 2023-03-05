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

from airflow.models.dag import DAG
from airflow.operators.bash import BashOperator
from airflow.utils.task_group import TaskGroup



with DAG(dag_id="hi", start_date=pendulum.now()) as dag1:
    with TaskGroup("a") as t:
        w1 = BashOperator(task_id="w1", bash_command="echo 1")
        w2 = BashOperator(task_id="w2", bash_command="echo 1")
        w1 >> w2

    w3 = BashOperator(task_id="w3", bash_command="echo 1")

"""
todo: docs:

normal_task >> group

in this case we ignore teardown roots.

setup_task >> dag

in this case we shouldn't ignore

"""

#
w3 >> t
# w3.roots
#
# w3.get_direct_relative_ids(upstream=False)
w3.downstream_task_ids

with DAG(
    dag_id="example_setup_teardown",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    BashOperator.as_setup(task_id="root_setup", bash_command="echo 'Hello from root_setup'")
    normal = BashOperator(task_id="normal", bash_command="echo 'I am just a normal task'")
    BashOperator.as_teardown(task_id="root_teardown", bash_command="echo 'Goodbye from root_teardown'")

    with TaskGroup("section_1") as section_1:
        BashOperator.as_setup(task_id="taskgroup_setup", bash_command="echo 'Hello from taskgroup_setup'")
        BashOperator(task_id="normal", bash_command="echo 'I am just a normal task'")
        BashOperator.as_setup(
            task_id="taskgroup_teardown", bash_command="echo 'Hello from taskgroup_teardown'"
        )

    normal >> section_1

import os
os.environ["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"]="mysql+mysqldb://root@localhost/testing"
from airflow.settings import Session
session = Session()
from airflow.models.taskinstance import TaskInstance
tis = list(session.query(TaskInstance).all())
[x for x in tis if x.is_setup]
