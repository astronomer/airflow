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

from airflow import DAG
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.utils.dates import datetime

with DAG(
    "example_duckdb_sql_execute_query",
    description="Example DAG for DuckDB SQLExecuteQueryOperator.",
    start_date=datetime(2021, 1, 1),
    schedule=None,
    catchup=False,
) as dag:
    """
    ### Example SQL execute query DAG

    Runs the SQLExecuteQueryOperator against the Airflow metadata DB.
    """

    # [START howto_operator_duckdb_sql_create_table]
    create_table = SQLExecuteQueryOperator(
        task_id="create_table",
        sql=f"CREATE TABLE people(id INTEGER, name VARCHAR);",
        conn_id="duckdb_default",
    )
    # [END howto_operator_duckdb_sql_create_table]

    # [START howto_operator_duckdb_sql_create_table]
    insert_table = SQLExecuteQueryOperator(
        task_id="insert_table",
        sql=f"INSERT INTO people VALUES (1, 'Mark'), (2, 'Hannes');",
        conn_id="duckdb_default",
    )
    # [END howto_operator_duckdb_sql_create_table]

    # [START howto_operator_duckdb_sql_select_table]
    select_table = SQLExecuteQueryOperator(
        task_id="select_table", sql=f"select * from people;", conn_id="duckdb_default"
    )
    # [END howto_operator_duckdb_sql_create_table]

    create_table >> insert_table >> select_table

from tests.system.utils import get_test_run

# Needed to run the example DAG with pytest (see: tests/system/README.md#run_via_pytest)
test_run = get_test_run(dag)
