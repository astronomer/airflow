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
Airflow task runner entry point for SparkStandaloneExecutor.

This script runs inside the Spark driver on the Spark cluster.
It replicates exactly what the KubernetesExecutor does inside a Pod:

    python -m airflow.sdk.execution_time.execute_workload --json-string <workload_json>

The serialized ExecuteTask workload is passed via the AIRFLOW_EXECUTE_WORKLOAD
environment variable, set by SparkStandaloneExecutor._build_env().

The driver process runs on a Spark worker node, so SparkSession is available
for free via SparkSession.builder.getOrCreate() — no SparkSubmitOperator needed.

Requirements on the Spark worker image
---------------------------------------
- apache-airflow-task-sdk must be installed (provides execute_workload entry point)
- Network access to the Airflow Execution API (AIRFLOW__EXECUTION_API__URL)

See dev/spark-standalone/Dockerfile for a ready-made worker image.
"""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("airflow.task_runner")


def main() -> None:
    workload_json = os.environ.get("AIRFLOW_EXECUTE_WORKLOAD")
    if not workload_json:
        log.error("AIRFLOW_EXECUTE_WORKLOAD env var is not set — cannot run task")
        sys.exit(1)

    log.info("Airflow task runner starting inside Spark driver")

    # SparkSession is available for free — this script runs inside a Spark driver.
    # Tasks that call SparkSession.builder.getOrCreate() will receive this session.
    try:
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        log.info("SparkSession ready — version=%s app_id=%s", spark.version, spark.sparkContext.applicationId)
    except ImportError:
        log.warning("pyspark not available — running without SparkSession")

    # Invoke the Airflow task SDK — identical to what KubernetesExecutor does:
    #   python -m airflow.sdk.execution_time.execute_workload --json-string <json>
    from airflow.sdk.execution_time.execute_workload import main as execute_workload

    sys.argv = ["execute_workload", "--json-string", workload_json]
    execute_workload()


if __name__ == "__main__":
    main()
