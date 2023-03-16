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
    dag_id="example_setup_teardown_sequence",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    create_bucket = BashOperator.as_setup(task_id="create_bucket", bash_command="echo 1")
    load_data = BashOperator(task_id="load_data", bash_command="echo 1")
    create_rds = BashOperator(task_id="create_rds", bash_command="echo 1")
    run_query = BashOperator(task_id="run_query", bash_command="echo 1")
    delete_rds = BashOperator.as_teardown(task_id="delete_rds", bash_command="echo 1")
    copy_to_azure = BashOperator(task_id="copy_to_azure", bash_command="echo 1")
    delete_bucket = BashOperator.as_teardown(task_id="delete_bucket", bash_command="echo 1")
    # create_bucket >> load_data >> create_rds >> run_query >> delete_rds >> copy_to_azure >> delete_bucket
    create_bucket >> load_data >> create_rds >> run_query >> delete_bucket >> copy_to_azure >> delete_rds
    create_bucket >> delete_bucket
    create_rds >> delete_rds
