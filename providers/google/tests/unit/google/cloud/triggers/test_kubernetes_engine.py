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

import asyncio
import datetime
import logging
from asyncio import Future
from unittest import mock

import pytest
from google.cloud.container_v1.types import Operation
from kubernetes.client import models as k8s

try:
    from airflow.providers.cncf.kubernetes.triggers.pod import ContainerState
except ImportError:
    # preserve backward compatibility for older versions of cncf.kubernetes provider, remove this when minimum cncf.kubernetes provider is 10.0
    from airflow.providers.cncf.kubernetes.triggers.kubernetes_pod import (  # type: ignore[no-redef]
        ContainerState,
    )
from airflow.providers.google.cloud.triggers.kubernetes_engine import (
    GKEJobTrigger,
    GKEOperationTrigger,
    GKEStartPodTrigger,
)
from airflow.triggers.base import TriggerEvent

GKE_TRIGGERS_PATH = "airflow.providers.google.cloud.triggers.kubernetes_engine"
TRIGGER_GKE_POD_PATH = GKE_TRIGGERS_PATH + ".GKEStartPodTrigger"
TRIGGER_GKE_JOB_PATH = GKE_TRIGGERS_PATH + ".GKEJobTrigger"
TRIGGER_KUB_POD_PATH = "airflow.providers.cncf.kubernetes.triggers.pod.KubernetesPodTrigger"
POD_NAME = "test-pod-name"
JOB_NAME = "test-job-name"
NAMESPACE = "default"
POLL_INTERVAL = 2
CLUSTER_CONTEXT = "test-context"
IN_CLUSTER = False
SHOULD_DELETE_POD = True
GET_LOGS = True
STARTUP_TIMEOUT_SECS = 120
TRIGGER_START_TIME = datetime.datetime.now(tz=datetime.timezone.utc)
CLUSTER_URL = "https://test-host"
SSL_CA_CERT = "TEST_SSL_CA_CERT_CONTENT"
FAILED_RESULT_MSG = "Test message that appears when trigger have failed event."
BASE_CONTAINER_NAME = "base"
ON_FINISH_ACTION = "delete_pod"
XCOM_PUSH = False

OPERATION_NAME = "test-operation-name"
PROJECT_ID = "test-project-id"
LOCATION = "us-central1-c"
GCP_CONN_ID = "test-non-existing-project-id"
IMPERSONATION_CHAIN = ["impersonate", "this", "test"]
TRIGGER_PATH = f"{GKE_TRIGGERS_PATH}.GKEOperationTrigger"
EXC_MSG = "test error msg"


@pytest.fixture
def trigger():
    return GKEStartPodTrigger(
        pod_name=POD_NAME,
        pod_namespace=NAMESPACE,
        poll_interval=POLL_INTERVAL,
        cluster_context=CLUSTER_CONTEXT,
        in_cluster=IN_CLUSTER,
        get_logs=GET_LOGS,
        startup_timeout=STARTUP_TIMEOUT_SECS,
        trigger_start_time=TRIGGER_START_TIME,
        cluster_url=CLUSTER_URL,
        ssl_ca_cert=SSL_CA_CERT,
        base_container_name=BASE_CONTAINER_NAME,
        gcp_conn_id=GCP_CONN_ID,
        impersonation_chain=IMPERSONATION_CHAIN,
        on_finish_action=ON_FINISH_ACTION,
    )


@pytest.fixture
def job_trigger():
    return GKEJobTrigger(
        cluster_url=CLUSTER_URL,
        ssl_ca_cert=SSL_CA_CERT,
        job_name=JOB_NAME,
        job_namespace=NAMESPACE,
        pod_names=[
            POD_NAME,
        ],
        pod_namespace=NAMESPACE,
        base_container_name=BASE_CONTAINER_NAME,
        gcp_conn_id=GCP_CONN_ID,
        poll_interval=POLL_INTERVAL,
        impersonation_chain=IMPERSONATION_CHAIN,
        get_logs=GET_LOGS,
        do_xcom_push=XCOM_PUSH,
    )


class TestGKEStartPodTrigger:
    @staticmethod
    def _mock_pod_result(result_to_mock):
        f = Future()
        f.set_result(result_to_mock)
        return f

    def test_serialize_should_execute_successfully(self, trigger):
        classpath, kwargs_dict = trigger.serialize()

        assert classpath == TRIGGER_GKE_POD_PATH
        assert kwargs_dict == {
            "pod_name": POD_NAME,
            "pod_namespace": NAMESPACE,
            "poll_interval": POLL_INTERVAL,
            "cluster_context": CLUSTER_CONTEXT,
            "in_cluster": IN_CLUSTER,
            "get_logs": GET_LOGS,
            "startup_timeout": STARTUP_TIMEOUT_SECS,
            "trigger_start_time": TRIGGER_START_TIME,
            "cluster_url": CLUSTER_URL,
            "ssl_ca_cert": SSL_CA_CERT,
            "base_container_name": BASE_CONTAINER_NAME,
            "on_finish_action": ON_FINISH_ACTION,
            "should_delete_pod": SHOULD_DELETE_POD,
            "gcp_conn_id": GCP_CONN_ID,
            "impersonation_chain": IMPERSONATION_CHAIN,
            "last_log_time": None,
            "logging_interval": None,
        }

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_KUB_POD_PATH}._wait_for_pod_start")
    @mock.patch(f"{TRIGGER_GKE_POD_PATH}.hook")
    async def test_run_loop_return_success_event_should_execute_successfully(
        self, mock_hook, mock_wait_pod, trigger
    ):
        mock_hook.get_pod.return_value = self._mock_pod_result(mock.MagicMock())
        mock_wait_pod.return_value = ContainerState.TERMINATED

        expected_event = TriggerEvent(
            {
                "name": POD_NAME,
                "namespace": NAMESPACE,
                "status": "success",
                "message": "All containers inside pod have started successfully.",
            }
        )
        actual_event = await trigger.run().asend(None)

        assert actual_event == expected_event

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_KUB_POD_PATH}._wait_for_pod_start")
    @mock.patch(f"{TRIGGER_GKE_POD_PATH}.hook")
    async def test_run_loop_return_failed_event_should_execute_successfully(
        self, mock_hook, mock_wait_pod, trigger
    ):
        mock_hook.get_pod.return_value = self._mock_pod_result(
            mock.MagicMock(
                status=mock.MagicMock(
                    message=FAILED_RESULT_MSG,
                )
            )
        )
        mock_wait_pod.return_value = ContainerState.FAILED

        expected_event = TriggerEvent(
            {
                "name": POD_NAME,
                "namespace": NAMESPACE,
                "status": "failed",
                "message": "pod failed",
            }
        )
        actual_event = await trigger.run().asend(None)

        assert actual_event == expected_event

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_KUB_POD_PATH}._wait_for_pod_start")
    @mock.patch(f"{TRIGGER_KUB_POD_PATH}.define_container_state")
    @mock.patch(f"{TRIGGER_GKE_POD_PATH}.hook")
    async def test_run_loop_return_waiting_event_should_execute_successfully(
        self, mock_hook, mock_method, mock_wait_pod, trigger, caplog
    ):
        mock_hook.get_pod.return_value = self._mock_pod_result(mock.MagicMock())
        mock_method.return_value = ContainerState.WAITING

        caplog.set_level(logging.INFO)

        task = asyncio.create_task(trigger.run().__anext__())
        await asyncio.sleep(0.5)

        assert not task.done()
        assert "Container is not completed and still working."
        assert f"Sleeping for {POLL_INTERVAL} seconds."

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_KUB_POD_PATH}._wait_for_pod_start")
    @mock.patch(f"{TRIGGER_KUB_POD_PATH}.define_container_state")
    @mock.patch(f"{TRIGGER_GKE_POD_PATH}.hook")
    async def test_run_loop_return_running_event_should_execute_successfully(
        self, mock_hook, mock_method, mock_wait_pod, trigger, caplog
    ):
        mock_hook.get_pod.return_value = self._mock_pod_result(mock.MagicMock())
        mock_method.return_value = ContainerState.RUNNING

        caplog.set_level(logging.INFO)

        task = asyncio.create_task(trigger.run().__anext__())
        await asyncio.sleep(0.5)

        assert not task.done()
        assert "Container is not completed and still working."
        assert f"Sleeping for {POLL_INTERVAL} seconds."

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_KUB_POD_PATH}._wait_for_pod_start")
    @mock.patch(f"{TRIGGER_GKE_POD_PATH}.hook")
    async def test_logging_in_trigger_when_exception_should_execute_successfully(
        self, mock_hook, mock_wait_pod, trigger, caplog
    ):
        """
        Test that GKEStartPodTrigger fires the correct event in case of an error.
        """
        mock_hook.get_pod.side_effect = Exception("Test exception")

        generator = trigger.run()
        actual = await generator.asend(None)
        actual_stack_trace = actual.payload.pop("stack_trace")
        assert (
            TriggerEvent(
                {"name": POD_NAME, "namespace": NAMESPACE, "status": "error", "message": "Test exception"}
            )
            == actual
        )
        assert actual_stack_trace.startswith("Traceback (most recent call last):")

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_KUB_POD_PATH}.define_container_state")
    @mock.patch(f"{TRIGGER_GKE_POD_PATH}.hook")
    async def test_logging_in_trigger_when_fail_should_execute_successfully(
        self, mock_hook, mock_method, trigger, caplog
    ):
        """
        Test that GKEStartPodTrigger fires the correct event in case of fail.
        """
        mock_hook.get_pod.return_value = self._mock_pod_result(mock.MagicMock())
        mock_method.return_value = ContainerState.FAILED
        caplog.set_level(logging.INFO)

        generator = trigger.run()
        await generator.asend(None)
        assert "Container logs:"

    @pytest.mark.parametrize(
        "container_state, expected_state",
        [
            (
                {"running": k8s.V1ContainerStateRunning(), "terminated": None, "waiting": None},
                ContainerState.RUNNING,
            ),
            (
                {"running": None, "terminated": k8s.V1ContainerStateTerminated(exit_code=0), "waiting": None},
                ContainerState.TERMINATED,
            ),
            (
                {"running": None, "terminated": None, "waiting": k8s.V1ContainerStateWaiting()},
                ContainerState.WAITING,
            ),
        ],
    )
    def test_define_container_state_should_execute_successfully(
        self, trigger, container_state, expected_state
    ):
        pod = k8s.V1Pod(
            metadata=k8s.V1ObjectMeta(name="base", namespace="default"),
            status=k8s.V1PodStatus(
                container_statuses=[
                    k8s.V1ContainerStatus(
                        name="base",
                        image="alpine",
                        image_id="1",
                        ready=True,
                        restart_count=1,
                        state=k8s.V1ContainerState(**container_state),
                    )
                ]
            ),
        )

        assert expected_state == trigger.define_container_state(pod)


@pytest.fixture
def operation_trigger():
    return GKEOperationTrigger(
        operation_name=OPERATION_NAME,
        project_id=PROJECT_ID,
        location=LOCATION,
        gcp_conn_id=GCP_CONN_ID,
        impersonation_chain=IMPERSONATION_CHAIN,
        poll_interval=POLL_INTERVAL,
    )


@pytest.fixture
def async_get_operation_result():
    def func(**kwargs):
        m = mock.MagicMock()
        m.configure_mock(**kwargs)
        f = Future()
        f.set_result(m)
        return f

    return func


class TestGKEOperationTrigger:
    def test_serialize(self, operation_trigger):
        classpath, trigger_init_kwargs = operation_trigger.serialize()
        assert classpath == TRIGGER_PATH
        assert trigger_init_kwargs == {
            "operation_name": OPERATION_NAME,
            "project_id": PROJECT_ID,
            "location": LOCATION,
            "gcp_conn_id": GCP_CONN_ID,
            "impersonation_chain": IMPERSONATION_CHAIN,
            "poll_interval": POLL_INTERVAL,
        }

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_PATH}._get_hook")
    async def test_run_loop_return_success_event(
        self, mock_hook, operation_trigger, async_get_operation_result
    ):
        mock_hook.return_value.get_operation.return_value = async_get_operation_result(
            name=OPERATION_NAME,
            status=Operation.Status.DONE,
        )

        expected_event = TriggerEvent(
            {
                "status": "success",
                "message": "Operation is successfully ended.",
                "operation_name": OPERATION_NAME,
            }
        )
        actual_event = await operation_trigger.run().asend(None)

        assert actual_event == expected_event

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_PATH}._get_hook")
    async def test_run_loop_return_failed_event_status_unspecified(
        self,
        mock_hook,
        operation_trigger,
        async_get_operation_result,
    ):
        mock_hook.return_value.get_operation.return_value = async_get_operation_result(
            name=OPERATION_NAME,
            status=Operation.Status.STATUS_UNSPECIFIED,
        )

        expected_event = TriggerEvent(
            {
                "status": "failed",
                "message": f"Operation has failed with status: {Operation.Status.STATUS_UNSPECIFIED}",
            }
        )
        actual_event = await operation_trigger.run().asend(None)

        assert actual_event == expected_event

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_PATH}._get_hook")
    async def test_run_loop_return_failed_event_status_aborting(
        self,
        mock_hook,
        operation_trigger,
        async_get_operation_result,
    ):
        mock_hook.return_value.get_operation.return_value = async_get_operation_result(
            name=OPERATION_NAME,
            status=Operation.Status.ABORTING,
        )

        expected_event = TriggerEvent(
            {
                "status": "failed",
                "message": f"Operation has failed with status: {Operation.Status.ABORTING}",
            }
        )
        actual_event = await operation_trigger.run().asend(None)

        assert actual_event == expected_event

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_PATH}._get_hook")
    async def test_run_loop_return_error_event(
        self, mock_hook, operation_trigger, async_get_operation_result
    ):
        mock_hook.return_value.get_operation.side_effect = Exception(EXC_MSG)

        expected_event = TriggerEvent(
            {
                "status": "error",
                "message": EXC_MSG,
            }
        )
        actual_event = await operation_trigger.run().asend(None)

        assert actual_event == expected_event

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_PATH}._get_hook")
    async def test_run_loop_return_waiting_event_pending_status(
        self,
        mock_hook,
        operation_trigger,
        async_get_operation_result,
        caplog,
    ):
        mock_hook.return_value.get_operation.return_value = async_get_operation_result(
            name=OPERATION_NAME,
            status=Operation.Status.PENDING,
        )

        caplog.set_level(logging.INFO)

        task = asyncio.create_task(operation_trigger.run().__anext__())
        await asyncio.sleep(0.5)

        assert not task.done()
        assert "Operation is still running."
        assert f"Sleeping for {POLL_INTERVAL}s..."

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_PATH}._get_hook")
    async def test_run_loop_return_waiting_event_running_status(
        self,
        mock_hook,
        operation_trigger,
        async_get_operation_result,
        caplog,
    ):
        mock_hook.return_value.get_operation.return_value = async_get_operation_result(
            name=OPERATION_NAME,
            status=Operation.Status.RUNNING,
        )

        caplog.set_level(logging.INFO)

        task = asyncio.create_task(operation_trigger.run().__anext__())
        await asyncio.sleep(0.5)

        assert not task.done()
        assert "Operation is still running."
        assert f"Sleeping for {POLL_INTERVAL}s..."


class TestGKEStartJobTrigger:
    def test_serialize(self, job_trigger):
        classpath, kwargs_dict = job_trigger.serialize()

        assert classpath == TRIGGER_GKE_JOB_PATH
        assert kwargs_dict == {
            "cluster_url": CLUSTER_URL,
            "ssl_ca_cert": SSL_CA_CERT,
            "job_name": JOB_NAME,
            "job_namespace": NAMESPACE,
            "pod_names": [
                POD_NAME,
            ],
            "pod_namespace": NAMESPACE,
            "base_container_name": BASE_CONTAINER_NAME,
            "gcp_conn_id": GCP_CONN_ID,
            "poll_interval": POLL_INTERVAL,
            "impersonation_chain": IMPERSONATION_CHAIN,
            "get_logs": GET_LOGS,
            "do_xcom_push": XCOM_PUSH,
        }

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_GKE_JOB_PATH}.hook")
    async def test_run_success(self, mock_hook, job_trigger):
        mock_job = mock.MagicMock()
        mock_job.metadata.name = JOB_NAME
        mock_job.metadata.namespace = NAMESPACE
        mock_hook.wait_until_job_complete.side_effect = mock.AsyncMock(return_value=mock_job)

        mock_pod = mock.MagicMock()
        mock_pod.metadata.name = POD_NAME
        mock_pod.metadata.namespace = NAMESPACE
        mock_hook.get_pod.side_effect = mock.AsyncMock(return_value=mock_pod)

        mock_is_job_failed = mock_hook.is_job_failed
        mock_is_job_failed.return_value = False

        mock_job_dict = mock_job.to_dict.return_value

        event_actual = await job_trigger.run().asend(None)

        mock_hook.wait_until_job_complete.assert_called_once_with(
            name=JOB_NAME, namespace=NAMESPACE, poll_interval=POLL_INTERVAL
        )
        mock_job.to_dict.assert_called_once()
        mock_is_job_failed.assert_called_once_with(job=mock_job)
        assert event_actual == TriggerEvent(
            {
                "name": JOB_NAME,
                "namespace": NAMESPACE,
                "pod_names": [
                    POD_NAME,
                ],
                "pod_namespace": NAMESPACE,
                "status": "success",
                "message": "Job completed successfully",
                "job": mock_job_dict,
                "xcom_result": None,
            }
        )

    @pytest.mark.asyncio
    @mock.patch(f"{TRIGGER_GKE_JOB_PATH}.hook")
    async def test_run_fail(self, mock_hook, job_trigger):
        mock_job = mock.MagicMock()
        mock_job.metadata.name = JOB_NAME
        mock_job.metadata.namespace = NAMESPACE
        mock_hook.wait_until_job_complete.side_effect = mock.AsyncMock(return_value=mock_job)

        mock_pod = mock.MagicMock()
        mock_pod.metadata.name = POD_NAME
        mock_pod.metadata.namespace = NAMESPACE
        mock_hook.get_pod.side_effect = mock.AsyncMock(return_value=mock_pod)

        mock_is_job_failed = mock_hook.is_job_failed
        mock_is_job_failed.return_value = "Error"

        mock_job_dict = mock_job.to_dict.return_value

        event_actual = await job_trigger.run().asend(None)

        mock_hook.wait_until_job_complete.assert_called_once_with(
            name=JOB_NAME, namespace=NAMESPACE, poll_interval=POLL_INTERVAL
        )
        mock_job.to_dict.assert_called_once()
        mock_is_job_failed.assert_called_once_with(job=mock_job)
        assert event_actual == TriggerEvent(
            {
                "name": JOB_NAME,
                "namespace": NAMESPACE,
                "pod_names": [
                    POD_NAME,
                ],
                "pod_namespace": NAMESPACE,
                "status": "error",
                "message": "Job failed with error: Error",
                "job": mock_job_dict,
                "xcom_result": None,
            }
        )

    @mock.patch(f"{GKE_TRIGGERS_PATH}.GKEKubernetesAsyncHook")
    def test_hook(self, mock_hook, job_trigger):
        hook_expected = mock_hook.return_value

        hook_actual = job_trigger.hook

        mock_hook.assert_called_once_with(
            cluster_url=CLUSTER_URL,
            ssl_ca_cert=SSL_CA_CERT,
            gcp_conn_id=GCP_CONN_ID,
            impersonation_chain=IMPERSONATION_CHAIN,
        )
        assert hook_actual == hook_expected
