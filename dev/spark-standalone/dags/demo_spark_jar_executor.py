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
SparkStandaloneExecutor — Java JAR demo.

Submits the built-in SparkPi example from the Spark distribution as a Java
application using executor_config.  No SparkSubmitOperator, no new operator
class — just a plain @task with a spark_jar hint.

The executor skips AirflowDriverLauncher entirely and posts the JAR directly
to the Spark REST Submission API.  Airflow maps driverState → task success/failure.

Run with SparkStandaloneExecutor configured (see dev/spark-standalone/README.md).
"""

from __future__ import annotations

from datetime import datetime

from airflow.sdk import DAG, task

# SparkPi ships with every Spark distribution under $SPARK_HOME/examples/jars/.
# The filename encodes the Scala version and Spark version — glob it at runtime
# or pin the exact name for your cluster.  For the spark:python3 base image
# (Spark 4.0.x, Scala 2.13) the path below is correct.
_SPARK_PI_JAR = "file:///opt/spark/examples/jars/spark-examples_2.13-4.0.1.jar"
_SPARK_PI_CLASS = "org.apache.spark.examples.SparkPi"


@task(executor_config={
    "spark_jar": {
        "app_resource": _SPARK_PI_JAR,
        "main_class": _SPARK_PI_CLASS,
        # Number of Monte Carlo partitions — higher = more accurate Pi estimate.
        "app_args": ["100"],
    }
})
def compute_pi() -> None:
    """
    Submits SparkPi as a Java application directly to the Spark cluster.

    This function body is never executed — the executor intercepts the task,
    sees spark_jar in executor_config, and submits the JAR to Spark REST API.
    Airflow marks the task succeeded when Spark reports driverState=FINISHED.
    """


with DAG(
    dag_id="spark_jar_demo",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    tags=["spark", "poc", "java"],
    doc_md=__doc__,
):
    compute_pi()
