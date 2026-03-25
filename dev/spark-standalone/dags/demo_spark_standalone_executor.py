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
"""
SparkStandaloneExecutor — demonstration DAG.

This DAG exists to contrast the OLD approach (explicit SparkSubmitOperator per
task) with the NEW approach (SparkStandaloneExecutor configured once, no DAG
changes needed).

OLD approach
------------
Every task that needs Spark must be an explicit operator::

    from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator

    heavy_transform = SparkSubmitOperator(
        task_id="heavy_transform",
        application="/path/to/heavy_transform.py",
        conn_id="spark_default",
        ...
    )

NEW approach (this DAG)
-----------------------
Configure ``executor = SparkStandaloneExecutor`` in airflow.cfg.  Every task
is transparently submitted to the Spark cluster — no operator change needed.
Tasks that use ``SparkSession`` get a live session for free.

Running
-------
1. Start the Spark cluster:  ``cd dev/spark-standalone && docker compose up -d``
2. Configure Airflow:

   .. code-block:: ini

       [core]
       executor = airflow.providers.apache.spark.executors.spark_standalone_executor.SparkStandaloneExecutor

       [spark_standalone_executor]
       master_url = spark://localhost:7077
       rest_url   = http://localhost:6066/v1/submissions

3. Trigger the DAG from the Airflow UI or CLI.
"""

from __future__ import annotations

from datetime import datetime

from airflow.sdk import DAG, task

# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@task
def ingest() -> dict:
    """
    Lightweight ingestion step — no Spark needed.

    With SparkStandaloneExecutor this still runs on the Spark cluster (as a
    driver process), but it does not request a SparkSession.
    """
    import os

    running_on_spark = "SPARK_HOME" in os.environ or "SPARK_YARN_MODE" in os.environ
    print(f"ingest: running_on_spark_worker={running_on_spark}")
    return {"rows": 1_000_000, "source": "s3://bucket/raw/"}


@task
def heavy_transform(meta: dict) -> dict:
    """
    Spark-intensive transformation — uses SparkSession transparently.

    No SparkSubmitOperator, no @task.pyspark decorator.  The SparkSession is
    available because this task runs inside a Spark *driver* process when
    SparkStandaloneExecutor is configured.
    """

    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("airflow-heavy-transform").getOrCreate()
    print(f"Spark version: {spark.version}")
    print(f"Application ID: {spark.sparkContext.applicationId}")

    # Demonstrate distributed compute: sum over a large range
    total = spark.range(meta["rows"]).selectExpr("sum(id) as s").collect()[0]["s"]
    print(f"Sum of 0..{meta['rows']}: {total}")

    spark.stop()
    return {"total": total, "source": meta["source"]}


@task
def publish(result: dict) -> None:
    """Final publish step — lightweight, no Spark needed."""
    print(f"publish: writing result total={result['total']} from {result['source']}")


# ---------------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------------

with DAG(
    dag_id="demo_spark_standalone_executor",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    tags=["spark", "poc"],
    doc_md=__doc__,
) as dag:
    meta = ingest()
    result = heavy_transform(meta)
    publish(result)
