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

from copy import deepcopy
from unittest import mock

import pytest as pytest

from airflow.providers.google.cloud.operators.dataflow import (
    DataflowStartFlexTemplateOperator,
    DataflowStartSqlJobOperator,
    DataflowStopJobOperator,
    DataflowTemplatedJobStartOperator,
)

TASK_ID = "test-dataflow-operator"
JOB_ID = "test-dataflow-pipeline-id"
JOB_NAME = "test-dataflow-pipeline-name"
TEMPLATE = "gs://dataflow-templates/wordcount/template_file"
PARAMETERS = {
    "inputFile": "gs://dataflow-samples/shakespeare/kinglear.txt",
    "output": "gs://test/output/my_output",
}
DEFAULT_OPTIONS_TEMPLATE = {
    "project": "test",
    "stagingLocation": "gs://test/staging",
    "tempLocation": "gs://test/temp",
    "zone": "us-central1-f",
}
POLL_SLEEP = 30
TEST_FLEX_PARAMETERS = {
    "containerSpecGcsPath": "gs://test-bucket/test-file",
    "jobName": "test-job-name",
    "parameters": {
        "inputSubscription": "test-subscription",
        "outputTable": "test-project:test-dataset.streaming_beam_sql",
    },
}
TEST_LOCATION = "custom-location"
TEST_PROJECT = "test-project"
TEST_SQL_JOB_NAME = "test-sql-job-name"
TEST_DATASET = "test-dataset"
TEST_SQL_OPTIONS = {
    "bigquery-project": TEST_PROJECT,
    "bigquery-dataset": TEST_DATASET,
    "bigquery-table": "beam_output",
    "bigquery-write-disposition": "write-truncate",
}
TEST_SQL_QUERY = """
SELECT
    sales_region as sales_region,
    count(state_id) as count_state
FROM
    bigquery.table.test-project.beam_samples.beam_table
GROUP BY sales_region;
"""
TEST_SQL_JOB = {"id": "test-job-id"}
GCP_CONN_ID = "test_gcp_conn_id"
IMPERSONATION_CHAIN = ["impersonate", "this"]
CANCEL_TIMEOUT = 10 * 420


class TestDataflowTemplateOperator:
    @pytest.fixture
    def sync_operator(self):
        return DataflowTemplatedJobStartOperator(
            project_id=TEST_PROJECT,
            task_id=TASK_ID,
            template=TEMPLATE,
            job_name=JOB_NAME,
            parameters=PARAMETERS,
            options=DEFAULT_OPTIONS_TEMPLATE,
            dataflow_default_options={"EXTRA_OPTION": "TEST_A"},
            poll_sleep=POLL_SLEEP,
            location=TEST_LOCATION,
            environment={"maxWorkers": 2},
        )

    @pytest.fixture
    def deferrable_operator(self):
        return DataflowTemplatedJobStartOperator(
            project_id=TEST_PROJECT,
            task_id=TASK_ID,
            template=TEMPLATE,
            job_name=JOB_NAME,
            parameters=PARAMETERS,
            options=DEFAULT_OPTIONS_TEMPLATE,
            dataflow_default_options={"EXTRA_OPTION": "TEST_A"},
            poll_sleep=POLL_SLEEP,
            location=TEST_LOCATION,
            environment={"maxWorkers": 2},
            deferrable=True,
            gcp_conn_id=GCP_CONN_ID,
            impersonation_chain=IMPERSONATION_CHAIN,
            cancel_timeout=CANCEL_TIMEOUT,
        )

    @mock.patch("airflow.providers.google.cloud.operators.dataflow.DataflowHook")
    def test_exec(self, dataflow_mock, sync_operator):
        start_template_hook = dataflow_mock.return_value.start_template_dataflow
        sync_operator.execute(None)
        assert dataflow_mock.called
        expected_options = {
            "project": "test",
            "stagingLocation": "gs://test/staging",
            "tempLocation": "gs://test/temp",
            "zone": "us-central1-f",
            "EXTRA_OPTION": "TEST_A",
        }
        start_template_hook.assert_called_once_with(
            job_name=JOB_NAME,
            variables=expected_options,
            parameters=PARAMETERS,
            dataflow_template=TEMPLATE,
            on_new_job_callback=mock.ANY,
            project_id=TEST_PROJECT,
            location=TEST_LOCATION,
            environment={"maxWorkers": 2},
            append_job_name=True,
        )

    @mock.patch("airflow.providers.google.cloud.operators.dataflow.DataflowTemplatedJobStartOperator.defer")
    @mock.patch("airflow.providers.google.cloud.operators.dataflow.DataflowTemplatedJobStartOperator.hook")
    def test_execute_with_deferrable_mode(self, mock_hook, mock_defer_method, deferrable_operator):
        deferrable_operator.execute(mock.MagicMock())
        mock_defer_method.assert_called_once()

    def test_validation_deferrable_params_raises_error(self):
        init_kwargs = {
            "project_id": TEST_PROJECT,
            "task_id": TASK_ID,
            "template": TEMPLATE,
            "job_name": JOB_NAME,
            "parameters": PARAMETERS,
            "options": DEFAULT_OPTIONS_TEMPLATE,
            "dataflow_default_options": {"EXTRA_OPTION": "TEST_A"},
            "poll_sleep": POLL_SLEEP,
            "location": TEST_LOCATION,
            "environment": {"maxWorkers": 2},
            "wait_until_finished": True,
            "deferrable": True,
            "gcp_conn_id": GCP_CONN_ID,
            "impersonation_chain": IMPERSONATION_CHAIN,
            "cancel_timeout": CANCEL_TIMEOUT,
        }
        with pytest.raises(ValueError):
            DataflowTemplatedJobStartOperator(**init_kwargs)


class TestDataflowStartFlexTemplateOperator:
    @pytest.fixture
    def sync_operator(self):
        return DataflowStartFlexTemplateOperator(
            task_id="start_flex_template_streaming_beam_sql",
            body={"launchParameter": TEST_FLEX_PARAMETERS},
            do_xcom_push=True,
            project_id=TEST_PROJECT,
            location=TEST_LOCATION,
        )

    @pytest.fixture
    def deferrable_operator(self):
        return DataflowStartFlexTemplateOperator(
            task_id="start_flex_template_streaming_beam_sql",
            body={"launchParameter": TEST_FLEX_PARAMETERS},
            do_xcom_push=True,
            project_id=TEST_PROJECT,
            location=TEST_LOCATION,
            deferrable=True,
        )

    @mock.patch("airflow.providers.google.cloud.operators.dataflow.DataflowHook")
    def test_execute(self, mock_dataflow, sync_operator):
        sync_operator.execute(mock.MagicMock())
        mock_dataflow.assert_called_once_with(
            gcp_conn_id="google_cloud_default",
            drain_pipeline=False,
            cancel_timeout=600,
            wait_until_finished=None,
            impersonation_chain=None,
        )
        mock_dataflow.return_value.start_flex_template.assert_called_once_with(
            body={"launchParameter": TEST_FLEX_PARAMETERS},
            location=TEST_LOCATION,
            project_id=TEST_PROJECT,
            on_new_job_callback=mock.ANY,
        )

    def test_on_kill(self, sync_operator):
        sync_operator.hook = mock.MagicMock()
        sync_operator.job = {"id": JOB_ID, "projectId": TEST_PROJECT, "location": TEST_LOCATION}
        sync_operator.on_kill()
        sync_operator.hook.cancel_job.assert_called_once_with(
            job_id="test-dataflow-pipeline-id", project_id=TEST_PROJECT, location=TEST_LOCATION
        )

    def test_validation_deferrable_params_raises_error(self):
        init_kwargs = {
            "task_id": "start_flex_template_streaming_beam_sql",
            "body": {"launchParameter": TEST_FLEX_PARAMETERS},
            "do_xcom_push": True,
            "location": TEST_LOCATION,
            "project_id": TEST_PROJECT,
            "wait_until_finished": True,
            "deferrable": True,
        }
        with pytest.raises(ValueError):
            DataflowStartFlexTemplateOperator(**init_kwargs)

    @mock.patch("airflow.providers.google.cloud.operators.dataflow.DataflowStartFlexTemplateOperator.defer")
    @mock.patch("airflow.providers.google.cloud.operators.dataflow.DataflowHook")
    def test_execute_with_deferrable_mode(self, mock_hook, mock_defer_method, deferrable_operator):
        deferrable_operator.execute(mock.MagicMock())

        mock_hook.return_value.start_flex_template.assert_called_once_with(
            body={"launchParameter": TEST_FLEX_PARAMETERS},
            location=TEST_LOCATION,
            project_id=TEST_PROJECT,
            on_new_job_callback=mock.ANY,
        )
        mock_defer_method.assert_called_once()


class TestDataflowSqlOperator:
    @mock.patch("airflow.providers.google.cloud.operators.dataflow.DataflowHook")
    def test_execute(self, mock_hook):
        start_sql = DataflowStartSqlJobOperator(
            task_id="start_sql_query",
            job_name=TEST_SQL_JOB_NAME,
            query=TEST_SQL_QUERY,
            options=deepcopy(TEST_SQL_OPTIONS),
            location=TEST_LOCATION,
            do_xcom_push=True,
        )

        start_sql.execute(mock.MagicMock())
        mock_hook.assert_called_once_with(
            gcp_conn_id="google_cloud_default",
            drain_pipeline=False,
            impersonation_chain=None,
        )
        mock_hook.return_value.start_sql_job.assert_called_once_with(
            job_name=TEST_SQL_JOB_NAME,
            query=TEST_SQL_QUERY,
            options=TEST_SQL_OPTIONS,
            location=TEST_LOCATION,
            project_id=None,
            on_new_job_callback=mock.ANY,
        )
        start_sql.job = TEST_SQL_JOB
        start_sql.on_kill()
        mock_hook.return_value.cancel_job.assert_called_once_with(
            job_id="test-job-id", project_id=None, location=None
        )


class TestDataflowStopJobOperator:
    @mock.patch("airflow.providers.google.cloud.operators.dataflow.DataflowHook")
    def test_exec_job_id(self, dataflow_mock):
        self.dataflow = DataflowStopJobOperator(
            task_id=TASK_ID,
            project_id=TEST_PROJECT,
            job_id=JOB_ID,
            poll_sleep=POLL_SLEEP,
            location=TEST_LOCATION,
        )
        """
        Test DataflowHook is created and the right args are passed to cancel_job.
        """
        cancel_job_hook = dataflow_mock.return_value.cancel_job
        self.dataflow.execute(None)
        assert dataflow_mock.called
        cancel_job_hook.assert_called_once_with(
            job_name=None,
            project_id=TEST_PROJECT,
            location=TEST_LOCATION,
            job_id=JOB_ID,
        )

    @mock.patch("airflow.providers.google.cloud.operators.dataflow.DataflowHook")
    def test_exec_job_name_prefix(self, dataflow_mock):
        self.dataflow = DataflowStopJobOperator(
            task_id=TASK_ID,
            project_id=TEST_PROJECT,
            job_name_prefix=JOB_NAME,
            poll_sleep=POLL_SLEEP,
            location=TEST_LOCATION,
        )
        """
        Test DataflowHook is created and the right args are passed to cancel_job
        and is_job_dataflow_running.
        """
        is_job_running_hook = dataflow_mock.return_value.is_job_dataflow_running
        cancel_job_hook = dataflow_mock.return_value.cancel_job
        self.dataflow.execute(None)
        assert dataflow_mock.called
        is_job_running_hook.assert_called_once_with(
            name=JOB_NAME,
            project_id=TEST_PROJECT,
            location=TEST_LOCATION,
        )
        cancel_job_hook.assert_called_once_with(
            job_name=JOB_NAME,
            project_id=TEST_PROJECT,
            location=TEST_LOCATION,
            job_id=None,
        )
