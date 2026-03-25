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

from unittest.mock import MagicMock, patch

import pytest
import requests

from airflow.providers.apache.spark.executors.spark_standalone_executor import (
    _DRIVER_STATE_SUCCESS,
    _DRIVER_STATE_TERMINAL_FAILURE,
    SparkStandaloneExecutor,
)
from airflow.utils.state import TaskInstanceState


def _make_workload(dag_id="test_dag", task_id="test_task", run_id="run_1", try_number=1, map_index=-1):
    """Build a minimal mock ExecuteTask workload."""
    ti = MagicMock()
    ti.dag_id = dag_id
    ti.task_id = task_id
    ti.run_id = run_id
    ti.try_number = try_number
    ti.map_index = map_index
    ti.executor_config = None
    ti.key = MagicMock()
    ti.key.__hash__ = lambda self: hash((dag_id, task_id, run_id, try_number, map_index))
    ti.key.__eq__ = lambda self, other: self is other

    workload = MagicMock()
    workload.ti = ti
    workload.token = "test-jwt-token"
    return workload


@pytest.fixture
def executor(monkeypatch):
    """Return a SparkStandaloneExecutor with config pre-populated (no airflow.cfg needed)."""
    exc = SparkStandaloneExecutor(parallelism=4)
    exc._rest_url = "http://spark-master:6066/v1/submissions"
    exc._master_url = "spark://spark-master:7077"
    exc._task_runner_script = "file:///opt/airflow/scripts/airflow_task_runner.py"
    exc._spark_version = "3.5.0"
    exc._driver_memory = "512m"
    exc._executor_memory = "1g"
    exc._executor_cores = "1"
    exc._submission_timeout = 30
    return exc


class TestSparkStandaloneExecutorSubmit:
    def test_submit_returns_submission_id_on_success(self, executor):
        workload = _make_workload()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": True, "submissionId": "driver-001"}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            submission_id = executor._submit(workload)

        assert submission_id == "driver-001"
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        assert payload["action"] == "CreateSubmissionRequest"
        assert payload["sparkProperties"]["spark.submit.deployMode"] == "cluster"
        assert payload["sparkProperties"]["spark.master"] == "spark://spark-master:7077"

    def test_submit_returns_none_when_spark_rejects(self, executor):
        workload = _make_workload()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": False, "message": "No resources available"}

        with patch("requests.post", return_value=mock_resp):
            submission_id = executor._submit(workload)

        assert submission_id is None

    def test_submit_returns_none_on_connection_error(self, executor):
        workload = _make_workload()

        with patch("requests.post", side_effect=requests.exceptions.ConnectionError("refused")):
            submission_id = executor._submit(workload)

        assert submission_id is None

    def test_submit_includes_env_vars(self, executor):
        import json

        workload = _make_workload(dag_id="my_dag", task_id="my_task", run_id="run_42")
        # model_dump_json() must return a real JSON string so the assertion can inspect it
        workload.model_dump_json.return_value = json.dumps(
            {"dag_id": "my_dag", "task_id": "my_task", "run_id": "run_42"}
        )
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": True, "submissionId": "driver-002"}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            with patch("airflow.configuration.conf.get", return_value=""):
                executor._submit(workload)

        env = mock_post.call_args.kwargs["json"]["environmentVariables"]
        # Full workload JSON is passed — same mechanism as KubernetesExecutor
        assert "AIRFLOW_EXECUTE_WORKLOAD" in env
        workload_json = env["AIRFLOW_EXECUTE_WORKLOAD"]
        assert "my_dag" in workload_json
        assert "my_task" in workload_json
        assert "run_42" in workload_json

    def test_submit_applies_executor_config_spark_properties(self, executor):
        workload = _make_workload()
        workload.ti.executor_config = {"spark_properties": {"spark.executor.memory": "4g"}}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": True, "submissionId": "driver-003"}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            executor._submit(workload)

        props = mock_post.call_args.kwargs["json"]["sparkProperties"]
        assert props["spark.executor.memory"] == "4g"


class TestSparkStandaloneExecutorSync:
    def test_sync_marks_success_on_finished(self, executor):
        key = MagicMock()
        executor._submissions[key] = "driver-001"
        executor.running.add(key)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"driverState": _DRIVER_STATE_SUCCESS}

        with patch("requests.get", return_value=mock_resp):
            executor.sync()

        assert key not in executor._submissions
        assert (key, TaskInstanceState.SUCCESS) in [(k, v[0]) for k, v in executor.event_buffer.items()]

    @pytest.mark.parametrize("driver_state", list(_DRIVER_STATE_TERMINAL_FAILURE))
    def test_sync_marks_failed_on_terminal_states(self, executor, driver_state):
        key = MagicMock()
        executor._submissions[key] = "driver-002"
        executor.running.add(key)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"driverState": driver_state}

        with patch("requests.get", return_value=mock_resp):
            executor.sync()

        assert key not in executor._submissions
        assert (key, TaskInstanceState.FAILED) in [(k, v[0]) for k, v in executor.event_buffer.items()]

    def test_sync_leaves_in_progress_tasks_running(self, executor):
        key = MagicMock()
        executor._submissions[key] = "driver-003"
        executor.running.add(key)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"driverState": "RUNNING"}

        with patch("requests.get", return_value=mock_resp):
            executor.sync()

        assert key in executor._submissions
        assert key not in executor.event_buffer

    def test_sync_tolerates_request_error(self, executor):
        key = MagicMock()
        executor._submissions[key] = "driver-004"
        executor.running.add(key)

        with patch("requests.get", side_effect=requests.exceptions.ConnectionError("timeout")):
            executor.sync()  # must not raise

        # Task should remain in-flight to be retried next sync cycle
        assert key in executor._submissions


class TestSparkStandaloneExecutorConnectivity:
    def test_validate_connectivity_succeeds_on_any_http_response(self, executor):
        mock_resp = MagicMock(status_code=404)
        with patch("requests.get", return_value=mock_resp):
            executor._validate_connectivity(timeout=5)  # must not raise

    def test_validate_connectivity_raises_on_connection_error(self, executor):
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
            with pytest.raises(RuntimeError, match="cannot reach Spark REST API"):
                executor._validate_connectivity(timeout=5)


class TestSparkStandaloneExecutorTerminate:
    def test_end_kills_all_running_submissions(self, executor):
        key1, key2 = MagicMock(), MagicMock()
        executor._submissions[key1] = "driver-001"
        executor._submissions[key2] = "driver-002"

        with patch("requests.post") as mock_post:
            executor.end()

        assert mock_post.call_count == 2
        called_urls = {call.args[0] for call in mock_post.call_args_list}
        assert "http://spark-master:6066/v1/submissions/kill/driver-001" in called_urls
        assert "http://spark-master:6066/v1/submissions/kill/driver-002" in called_urls
        assert len(executor._submissions) == 0
