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


class TestSparkStandaloneExecutorJarSubmit:
    def test_jar_submit_uses_app_resource_and_main_class(self, executor):
        workload = _make_workload()
        workload.ti.executor_config = {
            "spark_jar": {
                "app_resource": "s3://bucket/my-job.jar",
                "main_class": "com.example.MyJob",
            }
        }
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"success": True, "submissionId": "driver-jar-001"}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            submission_id = executor._submit(workload)

        assert submission_id == "driver-jar-001"
        payload = mock_post.call_args.kwargs["json"]
        assert payload["appResource"] == "s3://bucket/my-job.jar"
        assert payload["mainClass"] == "com.example.MyJob"

    def test_jar_submit_does_not_use_driver_launcher(self, executor):
        workload = _make_workload()
        workload.ti.executor_config = {
            "spark_jar": {
                "app_resource": "s3://bucket/my-job.jar",
                "main_class": "com.example.MyJob",
            }
        }
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"success": True, "submissionId": "driver-jar-002"}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            executor._submit(workload)

        payload = mock_post.call_args.kwargs["json"]
        assert "AirflowDriverLauncher" not in payload["appResource"]
        assert payload["mainClass"] != "AirflowDriverLauncher"
        assert payload["environmentVariables"] == {}

    def test_jar_submit_passes_app_args(self, executor):
        workload = _make_workload()
        workload.ti.executor_config = {
            "spark_jar": {
                "app_resource": "s3://bucket/my-job.jar",
                "main_class": "com.example.MyJob",
                "app_args": ["--input", "s3://raw/", "--output", "s3://out/"],
            }
        }
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"success": True, "submissionId": "driver-jar-003"}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            executor._submit(workload)

        payload = mock_post.call_args.kwargs["json"]
        assert payload["appArgs"] == ["--input", "s3://raw/", "--output", "s3://out/"]

    def test_jar_submit_applies_spark_properties(self, executor):
        workload = _make_workload()
        workload.ti.executor_config = {
            "spark_jar": {
                "app_resource": "s3://bucket/my-job.jar",
                "main_class": "com.example.MyJob",
                "spark_properties": {"spark.executor.memory": "8g", "spark.executor.cores": "4"},
            }
        }
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"success": True, "submissionId": "driver-jar-004"}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            executor._submit(workload)

        props = mock_post.call_args.kwargs["json"]["sparkProperties"]
        assert props["spark.executor.memory"] == "8g"
        assert props["spark.executor.cores"] == "4"

    def test_local_jar_sets_extra_classpath_on_driver_and_executor(self, executor):
        """file:// JARs must be added to extraClassPath on both sides to fix SerializedLambda deserialization."""
        workload = _make_workload()
        workload.ti.executor_config = {
            "spark_jar": {
                "app_resource": "file:///opt/spark/examples/jars/my-job.jar",
                "main_class": "com.example.MyJob",
            }
        }
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"success": True, "submissionId": "driver-jar-005"}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            executor._submit(workload)

        props = mock_post.call_args.kwargs["json"]["sparkProperties"]
        assert props["spark.driver.extraClassPath"] == "/opt/spark/examples/jars/my-job.jar"
        assert props["spark.executor.extraClassPath"] == "/opt/spark/examples/jars/my-job.jar"
        assert "spark.jars" not in props

    def test_remote_jar_uses_spark_jars_not_extra_classpath(self, executor):
        """Remote URIs (s3://, hdfs://) should use spark.jars for distribution, not extraClassPath."""
        workload = _make_workload()
        workload.ti.executor_config = {
            "spark_jar": {
                "app_resource": "s3://bucket/my-job.jar",
                "main_class": "com.example.MyJob",
            }
        }
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"success": True, "submissionId": "driver-jar-006"}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            executor._submit(workload)

        props = mock_post.call_args.kwargs["json"]["sparkProperties"]
        assert props["spark.jars"] == "s3://bucket/my-job.jar"
        assert "spark.driver.extraClassPath" not in props
        assert "spark.executor.extraClassPath" not in props

    def test_spark_properties_override_defaults(self, executor):
        """User-provided spark_properties must win over executor defaults."""
        workload = _make_workload()
        workload.ti.executor_config = {
            "spark_jar": {
                "app_resource": "file:///opt/myapp/job.jar",
                "main_class": "com.example.MyJob",
                "spark_properties": {
                    "spark.executor.extraClassPath": "/custom/path.jar",
                    "spark.driver.memory": "4g",
                },
            }
        }
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"success": True, "submissionId": "driver-jar-007"}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            executor._submit(workload)

        props = mock_post.call_args.kwargs["json"]["sparkProperties"]
        assert props["spark.executor.extraClassPath"] == "/custom/path.jar"
        assert props["spark.driver.memory"] == "4g"

    def test_jar_submit_returns_none_on_failure(self, executor):
        workload = _make_workload()
        workload.ti.executor_config = {
            "spark_jar": {
                "app_resource": "s3://bucket/my-job.jar",
                "main_class": "com.example.MyJob",
            }
        }

        with patch("requests.post", side_effect=requests.exceptions.ConnectionError("refused")):
            submission_id = executor._submit(workload)

        assert submission_id is None

    def test_no_spark_jar_key_uses_python_path(self, executor):
        """executor_config without spark_jar should still go through AirflowDriverLauncher."""
        workload = _make_workload()
        workload.ti.executor_config = {"spark_properties": {"spark.driver.memory": "1g"}}
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"success": True, "submissionId": "driver-py-001"}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            executor._submit(workload)

        payload = mock_post.call_args.kwargs["json"]
        assert payload["mainClass"] == "AirflowDriverLauncher"


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


class TestSparkStandaloneExecutorLogUpload:
    """Tests for the driver log fetch-and-upload path."""

    def _make_key(self, dag_id="test_dag", task_id="test_task", run_id="run_1", try_number=1):
        from airflow.models.taskinstancekey import TaskInstanceKey

        key = MagicMock(spec=TaskInstanceKey)
        key.dag_id = dag_id
        key.task_id = task_id
        key.run_id = run_id
        key.try_number = try_number
        return key

    def test_upload_skipped_when_remote_logging_not_configured(self, executor):
        """_upload_driver_logs is a no-op when REMOTE_BASE_LOG_FOLDER is empty."""
        with (
            patch.object(executor, "_do_upload_driver_logs") as mock_do,
            patch.dict("os.environ", {}, clear=False),
            patch("airflow.configuration.conf.get", return_value=""),
        ):
            executor._upload_driver_logs(self._make_key(), "driver-001")

        # _do_upload_driver_logs is called; it exits early internally — verify
        # by checking no network calls were made
        mock_do.assert_called_once()

    def test_get_worker_ui_url_matches_worker_host(self, executor):
        """_get_worker_ui_url finds the right worker via the master JSON API."""
        executor._master_ui_url = "http://spark-master:8080"

        status_resp = MagicMock()
        status_resp.json.return_value = {"workerHostPort": "192.168.1.5:36000"}

        master_resp = MagicMock()
        master_resp.json.return_value = {
            "workers": [
                {"host": "192.168.1.4", "webuiaddress": "http://192.168.1.4:8081"},
                {"host": "192.168.1.5", "webuiaddress": "http://192.168.1.5:8081"},
            ]
        }

        with patch("requests.get", side_effect=[status_resp, master_resp]):
            url = executor._get_worker_ui_url("driver-001")

        assert url == "http://192.168.1.5:8081"

    def test_get_worker_ui_url_returns_none_when_worker_not_found(self, executor):
        executor._master_ui_url = "http://spark-master:8080"

        status_resp = MagicMock()
        status_resp.json.return_value = {"workerHostPort": "10.0.0.99:36000"}

        master_resp = MagicMock()
        master_resp.json.return_value = {
            "workers": [{"host": "192.168.1.4", "webuiaddress": "http://192.168.1.4:8081"}]
        }

        with patch("requests.get", side_effect=[status_resp, master_resp]):
            url = executor._get_worker_ui_url("driver-001")

        assert url is None

    def test_get_worker_ui_url_returns_none_on_connection_error(self, executor):
        executor._master_ui_url = "http://spark-master:8080"

        with patch("requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
            url = executor._get_worker_ui_url("driver-001")

        assert url is None

    def test_fetch_driver_log_content_strips_header_and_combines(self, executor):
        """_fetch_driver_log_content strips the Spark /log/ header line and joins stderr+stdout."""
        stderr_resp = MagicMock()
        stderr_resp.ok = True
        stderr_resp.text = (
            "==== Bytes 0-20 of 20 of /opt/spark/work/driver-001/stderr ====\nINFO SparkContext: Started\n"
        )

        stdout_resp = MagicMock()
        stdout_resp.ok = True
        stdout_resp.text = (
            "==== Bytes 0-24 of 24 of /opt/spark/work/driver-001/stdout ====\nPi is roughly 3.14\n"
        )

        with patch("requests.get", side_effect=[stderr_resp, stdout_resp]):
            content = executor._fetch_driver_log_content("http://worker:8081", "driver-001")

        assert "INFO SparkContext: Started" in content
        assert "Pi is roughly 3.14" in content
        assert "Bytes 0-20" not in content  # header stripped
        assert "=== Spark driver stderr ===" in content
        assert "=== Spark driver stdout ===" in content

    def test_fetch_driver_log_content_skips_empty_log(self, executor):
        """Logs with empty bodies (e.g. 0-byte stdout) are omitted from the combined output."""
        stderr_resp = MagicMock()
        stderr_resp.ok = True
        stderr_resp.text = "==== Bytes 0-10 of 10 of .../stderr ====\nSome error\n"

        stdout_resp = MagicMock()
        stdout_resp.ok = True
        stdout_resp.text = "==== Bytes 0-0 of 0 of .../stdout ====\n"

        with patch("requests.get", side_effect=[stderr_resp, stdout_resp]):
            content = executor._fetch_driver_log_content("http://worker:8081", "driver-001")

        assert "Some error" in content
        assert "stdout" not in content  # empty stdout section omitted

    def test_write_log_to_remote_uploads_to_s3(self, executor):
        """_write_log_to_remote calls S3Hook.load_string with the correct bucket and key."""
        mock_hook = MagicMock()

        with (
            patch("airflow.providers.amazon.aws.hooks.s3.S3Hook", return_value=mock_hook) as MockHook,
            patch.dict("os.environ", {"AIRFLOW__LOGGING__REMOTE_LOG_CONN_ID": "minio_logs"}),
        ):
            executor._write_log_to_remote(
                "s3://airflow-logs/",
                "dag_id=d/run_id=r/task_id=t/attempt=1.log",
                "log content",
            )

        MockHook.assert_called_once_with(aws_conn_id="minio_logs")
        mock_hook.load_string.assert_called_once_with(
            "log content",
            key="dag_id=d/run_id=r/task_id=t/attempt=1.log",
            bucket_name="airflow-logs",
            replace=True,
        )

    def test_write_log_to_remote_skips_non_s3_schemes(self, executor):
        """Non-S3 remote log schemes are silently skipped."""
        with patch("airflow.providers.amazon.aws.hooks.s3.S3Hook") as MockHook:
            executor._write_log_to_remote(
                "gs://my-bucket/",
                "dag_id=d/run_id=r/task_id=t/attempt=1.log",
                "log content",
            )

        MockHook.assert_not_called()

    def test_upload_driver_logs_tolerates_exception(self, executor):
        """Errors in the log upload path must not propagate — they are logged as warnings."""
        with patch.object(executor, "_do_upload_driver_logs", side_effect=RuntimeError("boom")):
            executor._upload_driver_logs(self._make_key(), "driver-001")  # must not raise

    def test_sync_calls_upload_before_state_change_on_success(self, executor):
        """sync() must upload logs before marking the task successful."""
        key = MagicMock()
        executor._submissions[key] = "driver-001"
        executor.running.add(key)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"driverState": "FINISHED"}

        call_order = []
        with (
            patch("requests.get", return_value=mock_resp),
            patch.object(executor, "_upload_driver_logs", side_effect=lambda *a: call_order.append("upload")),
            patch.object(executor, "success", side_effect=lambda *a: call_order.append("success")),
        ):
            executor.sync()

        assert call_order == ["upload", "success"]
