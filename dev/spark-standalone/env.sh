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

# Source this file to configure Airflow to use SparkStandaloneExecutor:
#
#   source dev/spark-standalone/env.sh
#
# Then start the scheduler and API server normally:
#
#   airflow api-server &
#   airflow scheduler

# --- Core: switch executor ---
export AIRFLOW__CORE__EXECUTOR=airflow.providers.apache.spark.executors.spark_standalone_executor.SparkStandaloneExecutor

# --- Spark Standalone Executor config ---
# REST API and master are reachable from the host via mapped ports.
export AIRFLOW__SPARK_STANDALONE_EXECUTOR__REST_URL=http://localhost:6066/v1/submissions
export AIRFLOW__SPARK_STANDALONE_EXECUTOR__MASTER_URL=spark://localhost:7077
export AIRFLOW__SPARK_STANDALONE_EXECUTOR__TASK_RUNNER_SCRIPT=file:///opt/airflow/scripts/airflow_task_runner.py
export AIRFLOW__SPARK_STANDALONE_EXECUTOR__SPARK_VERSION=4.0.1

# --- Execution API: Spark drivers run inside Docker, so they reach the host via host.docker.internal ---
# The Airflow API server must be started on port 8081 (default: 8080, may conflict with Spark UI).
export AIRFLOW__API_SERVER__PORT=8081
export AIRFLOW__EXECUTION_API__URL=http://host.docker.internal:8081/execution/

echo "SparkStandaloneExecutor environment set."
echo "  Spark master:  spark://localhost:7077"
echo "  REST API:      http://localhost:6066"
echo "  Airflow API:   http://host.docker.internal:8081/execution/ (as seen from Spark workers)"
