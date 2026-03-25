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

# Spark worker image with the Airflow Task SDK installed.
#
# This is what makes SparkStandaloneExecutor equivalent to KubernetesExecutor:
# the Spark driver process can call `execute_workload` to run real Airflow tasks,
# exactly as a Kubernetes Pod does.
#
# Build:   docker build -t airflow-spark:latest dev/spark-standalone/
# Or via:  docker compose up --build

FROM spark:python3

USER root

# Install the Airflow Task SDK — the only Airflow component needed on workers.
# This is equivalent to the Airflow image used by KubernetesExecutor.
RUN pip install --no-cache-dir apache-airflow-task-sdk

# Copy the Python task runner.
RUN mkdir -p /opt/airflow/scripts /opt/airflow/jars
COPY scripts/airflow_task_runner.py /opt/airflow/scripts/airflow_task_runner.py

# Build the JVM shim that launches the Python task runner.
# Spark Standalone cluster mode does not support Python appResource directly;
# we submit this JAR instead and it spawns python3 as a subprocess.
COPY AirflowDriverLauncher.java /tmp/AirflowDriverLauncher.java
RUN cd /tmp \
    && javac AirflowDriverLauncher.java \
    && jar cf /opt/airflow/jars/airflow-driver-launcher.jar AirflowDriverLauncher.class \
    && rm AirflowDriverLauncher.java AirflowDriverLauncher.class

# spark:python3 runs as the `spark` user (uid 185); keep that convention.
USER spark
