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

# Install the Airflow Task SDK, S3 logging provider, and pyspark.
#
# pyspark is installed explicitly here even though spark:python3 ships it,
# because our driver processes are launched as subprocesses of a JVM shim
# (AirflowDriverLauncher) and do not go through Spark's normal Python
# bootstrap that sets up PYTHONPATH.  A regular pip install makes pyspark
# importable without any PYTHONPATH magic.
#
# The pyspark version is pinned to the Spark version already present in the
# base image so the Python bindings match the running JVM.
RUN SPARK_VER=$(cat /opt/spark/RELEASE | awk 'NR==1{print $2}') \
    && pip install --no-cache-dir \
         apache-airflow-task-sdk \
         apache-airflow-providers-amazon \
         "pyspark==${SPARK_VER}"

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

# Explicitly set PYTHONPATH so pip-installed packages are visible to python3
# subprocesses spawned by the JVM shim.  When the Spark Worker launches our
# driver JVM, it inherits a minimal environment (only SPARK_HOME + PATH).
# Without this, site.py may not locate /usr/local/lib/python3.10/dist-packages
# and pyspark/airflow-sdk imports fail inside the driver.
ENV PYTHONPATH=/usr/local/lib/python3.10/dist-packages:/opt/spark/python

# spark:python3 runs as the `spark` user (uid 185); keep that convention.
USER spark
