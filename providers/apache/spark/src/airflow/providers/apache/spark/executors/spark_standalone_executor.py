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
SparkStandaloneExecutor — submits Airflow tasks to a Spark Standalone cluster.

Motivation
----------
The ``SparkSubmitOperator`` (and ``SparkKubernetesOperator``) require every
task that should run on Spark to be explicitly declared as a Spark operator in
the DAG.  This mirrors the ``KubernetesPodOperator`` story before
``KubernetesExecutor`` existed.

``SparkStandaloneExecutor`` solves the same problem for Spark Standalone
clusters: configure the executor once, and every Airflow task is transparently
submitted to the Spark cluster without any DAG-level changes.  Tasks that use
``SparkSession`` obtain a live session for free because they run inside a Spark
*driver* process on the cluster.

Architecture
------------
::

    Scheduler
      │
      └─► SparkStandaloneExecutor._process_workloads()
            │
            └─► POST /v1/submissions/create   (Spark REST Submission API)
                  │
                  Spark master creates a driver process on a worker node
                  │
                  Driver runs dev/spark-standalone/scripts/airflow_task_runner.py
                  │  (which calls the Airflow task SDK — full impl: TODO AIP-72)
                  │
            SparkStandaloneExecutor.sync()
            └─► GET /v1/submissions/status/{id}
                  │
                  Maps driverState → TaskInstanceState
                  │
      Scheduler: task succeeded / failed

Configuration  (airflow.cfg)
----------------------------
.. code-block:: ini

    [spark_standalone_executor]
    # Spark master URL used inside submitted jobs
    master_url = spark://localhost:7077

    # Base URL of the Spark REST Submission API
    rest_url = http://localhost:6066/v1/submissions

    # Path to the Python task runner script on the Spark worker nodes
    task_runner_script = /opt/airflow/scripts/airflow_task_runner.py

    # Path to the JVM launcher JAR on the Spark worker nodes.
    # Spark Standalone cluster mode does not support Python appResource;
    # this JAR is the real appResource — it spawns python3 as a subprocess.
    driver_launcher_jar = file:///opt/airflow/jars/airflow-driver-launcher.jar

    # Spark version reported to the REST API (must match the cluster)
    spark_version = 3.5.0

    # Per-task resource defaults (can be overridden via executor_config)
    driver_memory   = 512m
    executor_memory = 1g
    executor_cores  = 1

    # Seconds to wait for the REST API during start()
    startup_timeout = 30

    # Seconds to wait for each submission request
    submission_timeout = 30
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import requests
from requests.exceptions import ConnectionError, RequestException

from airflow.executors.base_executor import PARALLELISM, BaseExecutor

if TYPE_CHECKING:
    from collections.abc import Sequence

    from airflow.executors import workloads
    from airflow.models.taskinstancekey import TaskInstanceKey

log = logging.getLogger(__name__)

# Driver states returned by the Spark REST Submission API.
_DRIVER_STATE_SUCCESS = "FINISHED"
_DRIVER_STATE_TERMINAL_FAILURE = frozenset({"FAILED", "KILLED", "ERROR", "UNKNOWN"})
_DRIVER_STATE_IN_PROGRESS = frozenset({"SUBMITTED", "RUNNING", "RELAUNCHING"})


class SparkStandaloneExecutor(BaseExecutor):
    """
    Execute Airflow tasks on a Spark Standalone cluster via the REST Submission API.

    Each task is submitted as a Spark *driver* application (cluster deploy mode).
    The driver runs ``airflow_task_runner.py`` on a Spark worker node; tasks that
    call ``SparkSession.builder.getOrCreate()`` receive a live session because they
    are already inside a Spark driver process.

    This is the Spark analogue of ``KubernetesExecutor``: changing the executor
    in ``airflow.cfg`` is sufficient — no ``SparkSubmitOperator`` needed in DAGs.
    """

    def __init__(self, parallelism: int = PARALLELISM) -> None:
        super().__init__(parallelism=parallelism)
        self._rest_url: str = ""
        self._master_url: str = ""
        self._task_runner_script: str = ""
        self._driver_launcher_jar: str = ""
        self._spark_version: str = "3.5.0"
        self._driver_memory: str = "512m"
        self._executor_memory: str = "1g"
        self._executor_cores: str = "1"
        self._submission_timeout: int = 30
        # Maps TaskInstanceKey → Spark submissionId for in-flight tasks.
        self._submissions: dict[TaskInstanceKey, str] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        from airflow.configuration import conf

        self._rest_url = conf.get(
            "spark_standalone_executor", "rest_url", fallback="http://localhost:6066/v1/submissions"
        )
        self._master_url = conf.get(
            "spark_standalone_executor", "master_url", fallback="spark://localhost:7077"
        )
        self._task_runner_script = conf.get(
            "spark_standalone_executor",
            "task_runner_script",
            fallback="/opt/airflow/scripts/airflow_task_runner.py",
        )
        self._driver_launcher_jar = conf.get(
            "spark_standalone_executor",
            "driver_launcher_jar",
            fallback="file:///opt/airflow/jars/airflow-driver-launcher.jar",
        )
        self._spark_version = conf.get("spark_standalone_executor", "spark_version", fallback="3.5.0")
        self._driver_memory = conf.get("spark_standalone_executor", "driver_memory", fallback="512m")
        self._executor_memory = conf.get("spark_standalone_executor", "executor_memory", fallback="1g")
        self._executor_cores = conf.get("spark_standalone_executor", "executor_cores", fallback="1")
        self._submission_timeout = conf.getint("spark_standalone_executor", "submission_timeout", fallback=30)
        startup_timeout = conf.getint("spark_standalone_executor", "startup_timeout", fallback=30)

        self._validate_connectivity(startup_timeout)
        self.log.info("SparkStandaloneExecutor started — master=%s rest=%s", self._master_url, self._rest_url)

    def end(self) -> None:
        self._kill_all_submissions()

    def terminate(self) -> None:
        self._kill_all_submissions()

    # ------------------------------------------------------------------
    # Workload dispatch
    # ------------------------------------------------------------------

    def _process_workloads(self, workload_list: Sequence[workloads.All]) -> None:
        from airflow.executors.workloads import ExecuteTask

        for workload in workload_list:
            if not isinstance(workload, ExecuteTask):
                raise RuntimeError(
                    f"{type(self).__name__} only handles ExecuteTask workloads, got {type(workload)}"
                )

            key = workload.ti.key
            del self.queued_tasks[key]

            submission_id = self._submit(workload)
            if submission_id:
                self._submissions[key] = submission_id
                self.running.add(key)
                self.log.info("Task %s submitted to Spark — submissionId=%s", key, submission_id)
            else:
                self.fail(key, info="Spark submission failed")

    # ------------------------------------------------------------------
    # Sync (poll running submissions)
    # ------------------------------------------------------------------

    def sync(self) -> None:
        for key, submission_id in list(self._submissions.items()):
            try:
                driver_state = self._get_driver_state(submission_id)
            except RequestException as exc:
                self.log.warning("Could not fetch status for %s (%s): %s", key, submission_id, exc)
                continue

            if driver_state == _DRIVER_STATE_SUCCESS:
                self.log.info("Task %s finished successfully (submissionId=%s)", key, submission_id)
                self.success(key)
                del self._submissions[key]
            elif driver_state in _DRIVER_STATE_TERMINAL_FAILURE:
                self.log.error(
                    "Task %s failed — driverState=%s (submissionId=%s)", key, driver_state, submission_id
                )
                self.fail(key, info=f"driverState={driver_state}")
                del self._submissions[key]
            else:
                self.log.debug("Task %s in progress — driverState=%s", key, driver_state)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _submit(self, workload: Any) -> str | None:
        """Submit a task to the Spark cluster. Returns the submissionId or None on failure."""
        ti = workload.ti
        payload: dict[str, Any] = {
            "action": "CreateSubmissionRequest",
            "clientSparkVersion": self._spark_version,
            # Spark Standalone cluster mode does not support Python appResource.
            # We submit a thin JVM shim (AirflowDriverLauncher) that spawns
            # python3 as a subprocess, inheriting AIRFLOW_EXECUTE_WORKLOAD.
            "appResource": self._driver_launcher_jar,
            "mainClass": "AirflowDriverLauncher",
            "appArgs": [],
            "sparkProperties": {
                "spark.master": self._master_url,
                "spark.submit.deployMode": "cluster",
                "spark.app.name": f"airflow-{ti.dag_id}-{ti.task_id}-{ti.run_id[:8]}",
                "spark.driver.memory": self._driver_memory,
                "spark.executor.memory": self._executor_memory,
                "spark.executor.cores": self._executor_cores,
            },
            "environmentVariables": self._build_env(workload),
        }

        # Allow per-task overrides via executor_config
        if ti.executor_config:
            spark_props = ti.executor_config.get("spark_properties", {})
            payload["sparkProperties"].update(spark_props)

        try:
            resp = requests.post(
                f"{self._rest_url}/create",
                json=payload,
                timeout=self._submission_timeout,
            )
            if not resp.ok:
                self.log.error("Spark REST API returned %s for %s: %s", resp.status_code, ti.key, resp.text)
                return None
            data = resp.json()
            if data.get("success"):
                return data["submissionId"]
            self.log.error("Spark rejected submission for %s: %s", ti.key, data)
            return None
        except (ConnectionError, RequestException) as exc:
            self.log.error("Failed to submit task %s to Spark REST API: %s", ti.key, exc)
            return None

    def _build_env(self, workload: Any) -> dict[str, str]:
        """Build the environment variables dict injected into the Spark driver process."""
        # Serialize the full workload as JSON — identical to what KubernetesExecutor passes
        # to the pod via `python -m airflow.sdk.execution_time.execute_workload --json-string`.
        env: dict[str, str] = {
            "AIRFLOW_EXECUTE_WORKLOAD": workload.model_dump_json(),
            # Script path for AirflowDriverLauncher (the JVM shim) to invoke.
            "AIRFLOW_TASK_RUNNER_SCRIPT": self._task_runner_script,
            # Spark worker images may run as a system user with HOME=/nonexistent.
            # Airflow's logging init tries to mkdir under $HOME/airflow/logs; use a
            # path that doesn't collide with any volume mounts under /tmp/airflow.
            "HOME": "/tmp",
            "AIRFLOW__LOGGING__BASE_LOG_FOLDER": "/tmp/airflow-driver-logs",
        }

        import os

        # Execution API URL so the task runner can communicate back to Airflow.
        # The Task SDK reads AIRFLOW__CORE__EXECUTION_API_SERVER_URL via
        # conf.get("core", "execution_api_server_url"). Read from os.environ
        # directly so we pick it up regardless of which env var the operator set.
        execution_api_url = os.environ.get("AIRFLOW__CORE__EXECUTION_API_SERVER_URL") or os.environ.get(
            "AIRFLOW__EXECUTION_API__URL"
        )
        if execution_api_url:
            env["AIRFLOW__CORE__EXECUTION_API_SERVER_URL"] = execution_api_url

        # Ensure pip-installed packages (pyspark, airflow-sdk) are importable inside
        # the python3 subprocess spawned by AirflowDriverLauncher.  The Spark Worker
        # starts the driver JVM with a minimal environment (SPARK_HOME + PATH only),
        # so site.py may not resolve /usr/local/lib/python3.10/dist-packages unless
        # PYTHONPATH is set explicitly.  Preserve any existing value from the image.
        if "PYTHONPATH" not in env:
            env["PYTHONPATH"] = "/usr/local/lib/python3.10/dist-packages:/opt/spark/python"

        # Propagate remote-logging configuration so Spark driver processes upload
        # task logs to the same remote store (e.g. MinIO) that the Airflow UI reads.
        for key in (
            "AIRFLOW__LOGGING__REMOTE_LOGGING",
            "AIRFLOW__LOGGING__REMOTE_BASE_LOG_FOLDER",
            "AIRFLOW__LOGGING__REMOTE_LOG_CONN_ID",
        ):
            val = os.environ.get(key)
            if val:
                env[key] = val

        # Propagate any AIRFLOW_CONN_* env vars so the remote logging connection
        # (e.g. minio_logs) is available inside the driver process.
        for key, val in os.environ.items():
            if key.startswith("AIRFLOW_CONN_"):
                env[key] = val

        return env

    def _get_driver_state(self, submission_id: str) -> str:
        """
        Return the driverState string for the given submission.

        When Spark cannot find the submission (master restarted, driver cleaned
        up after completion, etc.) it returns a response with ``success=false``
        and no ``driverState`` key.  Fall back to ``"UNKNOWN"`` in that case,
        which is already mapped to terminal failure.
        """
        resp = requests.get(
            f"{self._rest_url}/status/{submission_id}",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if "driverState" not in data:
            self.log.warning(
                "Spark REST API response for %s has no driverState — treating as UNKNOWN. Response: %s",
                submission_id,
                data,
            )
        return data.get("driverState", "UNKNOWN")

    def _kill_all_submissions(self) -> None:
        for key, submission_id in list(self._submissions.items()):
            try:
                requests.post(f"{self._rest_url}/kill/{submission_id}", timeout=10)
                self.log.info("Killed Spark submission %s for task %s", submission_id, key)
            except RequestException as exc:
                self.log.warning("Failed to kill submission %s: %s", submission_id, exc)
        self._submissions.clear()

    def _validate_connectivity(self, timeout: int) -> None:
        """Probe the REST API to fail fast if the Spark master is unreachable."""
        probe_url = f"{self._rest_url}/status/probe"
        try:
            # A 404 is expected (no such submission) — we just want an HTTP response.
            requests.get(probe_url, timeout=timeout)
            self.log.debug("Spark REST API reachable at %s", self._rest_url)
        except ConnectionError as exc:
            raise RuntimeError(
                f"SparkStandaloneExecutor cannot reach Spark REST API at {self._rest_url!r}. "
                "Ensure the Spark master is running with REST enabled "
                "(SPARK_MASTER_REST_ENABLED=true or spark.master.rest.enabled=true). "
                f"Original error: {exc}"
            ) from exc
