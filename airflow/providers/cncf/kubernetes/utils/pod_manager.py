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
"""Launches PODs."""
from __future__ import annotations

import enum
import json
import logging
import math
import time
import warnings
from collections.abc import Iterable
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Generator, cast

import pendulum
import tenacity
from kubernetes import client, watch
from kubernetes.client.models.v1_container_status import V1ContainerStatus
from kubernetes.client.models.v1_pod import V1Pod
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream as kubernetes_stream
from pendulum import DateTime
from pendulum.parsing.exceptions import ParserError
from tenacity import before_log
from urllib3.exceptions import HTTPError as BaseHTTPError
from urllib3.response import HTTPResponse

from airflow.exceptions import AirflowException, AirflowProviderDeprecationWarning
from airflow.providers.cncf.kubernetes.pod_generator import PodDefaults
from airflow.providers.cncf.kubernetes.utils.istio import Istio
from airflow.typing_compat import Literal, Protocol
from airflow.utils.log.logging_mixin import LoggingMixin
from airflow.utils.timezone import utcnow

if TYPE_CHECKING:
    from kubernetes.client.models.core_v1_event_list import CoreV1EventList


class PodLaunchFailedException(AirflowException):
    """When pod launching fails in KubernetesPodOperator."""


def should_retry_start_pod(exception: BaseException) -> bool:
    """Check if an Exception indicates a transient error and warrants retrying."""
    if isinstance(exception, ApiException):
        return exception.status == 409
    return False


class PodPhase:
    """
    Possible pod phases.

    See https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-phase.
    """

    PENDING = "Pending"
    RUNNING = "Running"
    FAILED = "Failed"
    SUCCEEDED = "Succeeded"

    terminal_states = {FAILED, SUCCEEDED}


class PodOperatorHookProtocol(Protocol):
    """
    Protocol to define methods relied upon by KubernetesPodOperator.

    Subclasses of KubernetesPodOperator, such as GKEStartPodOperator, may use
    hooks that don't extend KubernetesHook.  We use this protocol to document the
    methods used by KPO and ensure that these methods exist on such other hooks.
    """

    @property
    def core_v1_client(self) -> client.CoreV1Api:
        """Get authenticated client object."""

    @property
    def is_in_cluster(self) -> bool:
        """Expose whether the hook is configured with ``load_incluster_config`` or not."""

    def get_pod(self, name: str, namespace: str) -> V1Pod:
        """Read pod object from kubernetes API."""

    def get_namespace(self) -> str | None:
        """Returns the namespace that defined in the connection."""


def get_container_status(pod: V1Pod, container_name: str) -> V1ContainerStatus | None:
    """Retrieves container status."""
    container_statuses = pod.status.container_statuses if pod and pod.status else None
    if container_statuses:
        # In general the variable container_statuses can store multiple items matching different containers.
        # The following generator expression yields all items that have name equal to the container_name.
        # The function next() here calls the generator to get only the first value. If there's nothing found
        # then None is returned.
        return next((x for x in container_statuses if x.name == container_name), None)
    return None


def container_is_running(pod: V1Pod, container_name: str) -> bool:
    """
    Examines V1Pod ``pod`` to determine whether ``container_name`` is running.

    If that container is present and running, returns True.  Returns False otherwise.
    """
    container_status = get_container_status(pod, container_name)
    if not container_status:
        return False
    return container_status.state.running is not None


def container_is_completed(pod: V1Pod, container_name: str) -> bool:
    """
    Examines V1Pod ``pod`` to determine whether ``container_name`` is completed.

    If that container is present and completed, returns True.  Returns False otherwise.
    """
    container_status = get_container_status(pod, container_name)
    if not container_status:
        return False
    return container_status.state.terminated is not None


def container_is_terminated(pod: V1Pod, container_name: str) -> bool:
    """
    Examines V1Pod ``pod`` to determine whether ``container_name`` is terminated.

    If that container is present and terminated, returns True.  Returns False otherwise.
    """
    container_statuses = pod.status.container_statuses if pod and pod.status else None
    if not container_statuses:
        return False
    container_status = next((x for x in container_statuses if x.name == container_name), None)
    if not container_status:
        return False
    return container_status.state.terminated is not None


def get_container_termination_message(pod: V1Pod, container_name: str):
    with suppress(AttributeError, TypeError):
        container_statuses = pod.status.container_statuses
        container_status = next((x for x in container_statuses if x.name == container_name), None)
        return container_status.state.terminated.message if container_status else None


class PodLogsConsumer:
    """
    Responsible for pulling pod logs from a stream with checking a container status before reading data.

    This class is a workaround for the issue https://github.com/apache/airflow/issues/23497.

    :param response: HTTP response with logs
    :param pod: Pod instance from Kubernetes client
    :param pod_manager: Pod manager instance
    :param container_name: Name of the container that we're reading logs from
    :param post_termination_timeout: (Optional) The period of time in seconds representing for how long time
        logs are available after the container termination.
    :param read_pod_cache_timeout: (Optional) The container's status cache lifetime.
        The container status is cached to reduce API calls.

    :meta private:
    """

    def __init__(
        self,
        response: HTTPResponse,
        pod: V1Pod,
        pod_manager: PodManager,
        container_name: str,
        post_termination_timeout: int = 120,
        read_pod_cache_timeout: int = 120,
    ):
        self.response = response
        self.pod = pod
        self.pod_manager = pod_manager
        self.container_name = container_name
        self.post_termination_timeout = post_termination_timeout
        self.last_read_pod_at = None
        self.read_pod_cache = None
        self.read_pod_cache_timeout = read_pod_cache_timeout

    def __iter__(self) -> Generator[bytes, None, None]:
        r"""The generator yields log items divided by the '\n' symbol."""
        incomplete_log_item: list[bytes] = []
        if self.logs_available():
            for data_chunk in self.response.stream(amt=None, decode_content=True):
                if b"\n" in data_chunk:
                    log_items = data_chunk.split(b"\n")
                    yield from self._extract_log_items(incomplete_log_item, log_items)
                    incomplete_log_item = self._save_incomplete_log_item(log_items[-1])
                else:
                    incomplete_log_item.append(data_chunk)
                if not self.logs_available():
                    break
        if incomplete_log_item:
            yield b"".join(incomplete_log_item)

    @staticmethod
    def _extract_log_items(incomplete_log_item: list[bytes], log_items: list[bytes]):
        yield b"".join(incomplete_log_item) + log_items[0] + b"\n"
        for x in log_items[1:-1]:
            yield x + b"\n"

    @staticmethod
    def _save_incomplete_log_item(sub_chunk: bytes):
        return [sub_chunk] if [sub_chunk] else []

    def logs_available(self):
        remote_pod = self.read_pod()
        if container_is_running(pod=remote_pod, container_name=self.container_name):
            return True
        container_status = get_container_status(pod=remote_pod, container_name=self.container_name)
        state = container_status.state if container_status else None
        terminated = state.terminated if state else None
        if terminated:
            termination_time = terminated.finished_at
            if termination_time:
                return termination_time + timedelta(seconds=self.post_termination_timeout) > utcnow()
        return False

    def read_pod(self):
        _now = utcnow()
        if (
            self.read_pod_cache is None
            or self.last_read_pod_at + timedelta(seconds=self.read_pod_cache_timeout) < _now
        ):
            self.read_pod_cache = self.pod_manager.read_pod(self.pod)
            self.last_read_pod_at = _now
        return self.read_pod_cache


@dataclass
class PodLoggingStatus:
    """Used for returning the status of the pod and last log time when exiting from `fetch_container_logs`."""

    running: bool
    last_log_time: DateTime | None


class SleepConfig:
    """Configure sleeps used for polling."""

    # Only polls during the start of a pod
    POD_STARTING_POLL = 1
    # Used to detect all cleanup jobs are completed
    # and the entire Pod is cleaned up
    POD_RUNNING_POLL = 1
    # Polls for the duration of the task execution
    # to detect when the task is done. The difference
    # between this and POD_RUNNING_POLL is sidecars.
    BASE_CONTAINER_RUNNING_POLL = 2


class PodManager(LoggingMixin):
    """Create, monitor, and otherwise interact with Kubernetes pods for use with the KubernetesPodOperator."""

    def __init__(
        self,
        kube_client: client.CoreV1Api,
    ):
        """
        Creates the launcher.

        :param kube_client: kubernetes client
        """
        super().__init__()
        self._client = kube_client
        self._watch = watch.Watch()
        self.istio = Istio(self._client)

    def run_pod_async(self, pod: V1Pod, **kwargs) -> V1Pod:
        """Runs POD asynchronously."""
        sanitized_pod = self._client.api_client.sanitize_for_serialization(pod)
        json_pod = json.dumps(sanitized_pod, indent=2)

        self.log.debug("Pod Creation Request: \n%s", json_pod)
        try:
            resp = self._client.create_namespaced_pod(
                body=sanitized_pod, namespace=pod.metadata.namespace, **kwargs
            )
            self.log.debug("Pod Creation Response: %s", resp)
        except Exception as e:
            self.log.exception(
                "Exception when attempting to create Namespaced Pod: %s", str(json_pod).replace("\n", " ")
            )
            raise e
        return resp

    def delete_pod(self, pod: V1Pod) -> None:
        """Deletes POD."""
        try:
            self._client.delete_namespaced_pod(
                pod.metadata.name, pod.metadata.namespace, body=client.V1DeleteOptions()
            )
        except ApiException as e:
            # If the pod is already deleted
            if e.status != 404:
                raise

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_random_exponential(),
        reraise=True,
        retry=tenacity.retry_if_exception(should_retry_start_pod),
    )
    def create_pod(self, pod: V1Pod) -> V1Pod:
        """Launches the pod asynchronously."""
        return self.run_pod_async(pod)

    def await_pod_start(self, pod: V1Pod, startup_timeout: int = 120) -> None:
        """
        Waits for the pod to reach phase other than ``Pending``.

        :param pod:
        :param startup_timeout: Timeout (in seconds) for startup of the pod
            (if pod is pending for too long, fails task)
        :return:
        """
        curr_time = datetime.now()
        while True:
            remote_pod = self.read_pod(pod)
            if remote_pod.status.phase != PodPhase.PENDING:
                break
            self.log.warning("Pod not yet started: %s", pod.metadata.name)
            delta = datetime.now() - curr_time
            if delta.total_seconds() >= startup_timeout:
                msg = (
                    f"Pod took longer than {startup_timeout} seconds to start. "
                    "Check the pod events in kubernetes to determine why."
                )
                raise PodLaunchFailedException(msg)
            time.sleep(SleepConfig.POD_STARTING_POLL)
            self.log.debug("Pod not yet started")

    def follow_container_logs(self, pod: V1Pod, container_name: str) -> PodLoggingStatus:
        warnings.warn(
            "Method `follow_container_logs` is deprecated.  Use `fetch_container_logs` instead"
            "with option `follow=True`.",
            AirflowProviderDeprecationWarning,
        )
        return self.fetch_container_logs(pod=pod, container_name=container_name, follow=True)

    def fetch_container_logs(
        self,
        pod: V1Pod,
        container_name: str,
        *,
        follow=False,
        since_time: DateTime | None = None,
        post_termination_timeout: int = 120,
    ) -> PodLoggingStatus:
        """
        Follows the logs of container and streams to airflow logging.

        Returns when container exits.

        Between when the pod starts and logs being available, there might be a delay due to CSR not approved
        and signed yet. In such situation, ApiException is thrown. This is why we are retrying on this
        specific exception.
        """

        @tenacity.retry(
            retry=tenacity.retry_if_exception_type(ApiException),
            stop=tenacity.stop_after_attempt(10),
            wait=tenacity.wait_fixed(1),
            before=before_log(self.log, logging.INFO),
        )
        def consume_logs(
            *, since_time: DateTime | None = None, follow: bool = True, termination_timeout: int = 120
        ) -> DateTime | None:
            """
            Tries to follow container logs until container completes.

            For a long-running container, sometimes the log read may be interrupted
            Such errors of this kind are suppressed.

            Returns the last timestamp observed in logs.
            """
            timestamp = None
            try:
                logs = self.read_pod_logs(
                    pod=pod,
                    container_name=container_name,
                    timestamps=True,
                    since_seconds=(
                        math.ceil((pendulum.now() - since_time).total_seconds()) if since_time else None
                    ),
                    follow=follow,
                    post_termination_timeout=termination_timeout,
                )
                for raw_line in logs:
                    line = raw_line.decode("utf-8", errors="backslashreplace")
                    timestamp, message = self.parse_log_line(line)
                    self.log.info("[%s] %s", container_name, message)
            except BaseHTTPError as e:
                self.log.warning(
                    "Reading of logs interrupted for container %r with error %r; will retry. "
                    "Set log level to DEBUG for traceback.",
                    container_name,
                    e,
                )
                self.log.debug(
                    "Traceback for interrupted logs read for pod %r",
                    pod.metadata.name,
                    exc_info=True,
                )
            return timestamp or since_time

        # note: `read_pod_logs` follows the logs, so we shouldn't necessarily *need* to
        # loop as we do here. But in a long-running process we might temporarily lose connectivity.
        # So the looping logic is there to let us resume following the logs.
        last_log_time = since_time
        while True:
            last_log_time = consume_logs(
                since_time=last_log_time, follow=follow, termination_timeout=post_termination_timeout
            )
            if not self.container_is_running(pod, container_name=container_name):
                return PodLoggingStatus(running=False, last_log_time=last_log_time)
            if not follow:
                return PodLoggingStatus(running=True, last_log_time=last_log_time)
            else:
                self.log.warning(
                    "Pod %s log read interrupted but container %s still running",
                    pod.metadata.name,
                    container_name,
                )
                time.sleep(1)

    def fetch_requested_container_logs(
        self, pod: V1Pod, container_logs: Iterable[str] | str | Literal[True], follow_logs=False
    ) -> list[PodLoggingStatus]:
        """
        Follow the logs of containers in the specified pod and publish it to airflow logging.

        Returns when all the containers exit.
        """
        pod_logging_statuses = []
        all_containers = self.get_container_names(pod)
        if len(all_containers) == 0:
            self.log.error("Could not retrieve containers for the pod: %s", pod.metadata.name)
        else:
            if isinstance(container_logs, str):
                # fetch logs only for requested container if only one container is provided
                if container_logs in all_containers:
                    status = self.fetch_container_logs(
                        pod=pod, container_name=container_logs, follow=follow_logs
                    )
                    pod_logging_statuses.append(status)
                else:
                    self.log.error(
                        "container %s whose logs were requested not found in the pod %s",
                        container_logs,
                        pod.metadata.name,
                    )
            elif isinstance(container_logs, bool):
                # if True is provided, get logs for all the containers
                if container_logs is True:
                    for container_name in all_containers:
                        status = self.fetch_container_logs(
                            pod=pod, container_name=container_name, follow=follow_logs
                        )
                        pod_logging_statuses.append(status)
                else:
                    self.log.error(
                        "False is not a valid value for container_logs",
                    )
            else:
                # if a sequence of containers are provided, iterate for every container in the pod
                if isinstance(container_logs, Iterable):
                    for container in container_logs:
                        if container in all_containers:
                            status = self.fetch_container_logs(
                                pod=pod, container_name=container, follow=follow_logs
                            )
                            pod_logging_statuses.append(status)
                        else:
                            self.log.error(
                                "Container %s whose logs were requests not found in the pod %s",
                                container,
                                pod.metadata.name,
                            )
                else:
                    self.log.error(
                        "Invalid type %s specified for container names input parameter", type(container_logs)
                    )

        return pod_logging_statuses

    def await_container_completion(self, pod: V1Pod, container_name: str) -> None:
        """
        Waits for the given container in the given pod to be completed.

        :param pod: pod spec that will be monitored
        :param container_name: name of the container within the pod to monitor
        """
        while True:
            remote_pod = self.read_pod(pod)
            terminated = container_is_completed(remote_pod, container_name)
            if terminated:
                break
            self.log.info("Waiting for container '%s' state to be completed", container_name)
            time.sleep(SleepConfig.BASE_CONTAINER_RUNNING_POLL)

    def await_pod_completion(self, pod: V1Pod) -> V1Pod:
        """
        Monitors a pod and returns the final state.

        :param pod: pod spec that will be monitored
        :return: tuple[State, str | None]
        """
        istio_shut_down_initiated = False
        while True:
            remote_pod = self.read_pod(pod)
            if remote_pod.status.phase in PodPhase.terminal_states:
                break
            self.log.info("Pod %s has phase %s", pod.metadata.name, remote_pod.status.phase)
            time.sleep(SleepConfig.POD_RUNNING_POLL)
            if not istio_shut_down_initiated:
                istio_shut_down_initiated = self.istio.handle_istio_proxy(remote_pod)
        return remote_pod

    def parse_log_line(self, line: str) -> tuple[DateTime | None, str]:
        """
        Parse K8s log line and returns the final state.

        :param line: k8s log line
        :return: timestamp and log message
        """
        split_at = line.find(" ")
        if split_at == -1:
            self.log.error(
                "Error parsing timestamp (no timestamp in message %r). "
                "Will continue execution but won't update timestamp",
                line,
            )
            return None, line
        timestamp = line[:split_at]
        message = line[split_at + 1 :].rstrip()
        try:
            last_log_time = cast(DateTime, pendulum.parse(timestamp))
        except ParserError:
            self.log.error("Error parsing timestamp. Will continue execution but won't update timestamp")
            return None, line
        return last_log_time, message

    def container_is_running(self, pod: V1Pod, container_name: str) -> bool:
        """Reads pod and checks if container is running."""
        remote_pod = self.read_pod(pod)
        return container_is_running(pod=remote_pod, container_name=container_name)

    def container_is_terminated(self, pod: V1Pod, container_name: str) -> bool:
        """Reads pod and checks if container is terminated."""
        remote_pod = self.read_pod(pod)
        return container_is_terminated(pod=remote_pod, container_name=container_name)

    @tenacity.retry(stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_exponential(), reraise=True)
    def read_pod_logs(
        self,
        pod: V1Pod,
        container_name: str,
        tail_lines: int | None = None,
        timestamps: bool = False,
        since_seconds: int | None = None,
        follow=True,
        post_termination_timeout: int = 120,
    ) -> PodLogsConsumer:
        """Reads log from the POD."""
        additional_kwargs = {}
        if since_seconds:
            additional_kwargs["since_seconds"] = since_seconds

        if tail_lines:
            additional_kwargs["tail_lines"] = tail_lines

        try:
            logs = self._client.read_namespaced_pod_log(
                name=pod.metadata.name,
                namespace=pod.metadata.namespace,
                container=container_name,
                follow=follow,
                timestamps=timestamps,
                _preload_content=False,
                **additional_kwargs,
            )
        except BaseHTTPError:
            self.log.exception("There was an error reading the kubernetes API.")
            raise

        return PodLogsConsumer(
            response=logs,
            pod=pod,
            pod_manager=self,
            container_name=container_name,
            post_termination_timeout=post_termination_timeout,
        )

    @tenacity.retry(stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_exponential(), reraise=True)
    def get_container_names(self, pod: V1Pod) -> list[str]:
        """Return container names from the POD except for the airflow-xcom-sidecar container."""
        pod_info = self.read_pod(pod)
        return [
            container_spec.name
            for container_spec in pod_info.spec.containers
            if container_spec.name != PodDefaults.SIDECAR_CONTAINER_NAME
        ]

    @tenacity.retry(stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_exponential(), reraise=True)
    def read_pod_events(self, pod: V1Pod) -> CoreV1EventList:
        """Reads events from the POD."""
        try:
            return self._client.list_namespaced_event(
                namespace=pod.metadata.namespace, field_selector=f"involvedObject.name={pod.metadata.name}"
            )
        except BaseHTTPError as e:
            raise AirflowException(f"There was an error reading the kubernetes API: {e}")

    @tenacity.retry(stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_exponential(), reraise=True)
    def read_pod(self, pod: V1Pod) -> V1Pod:
        """Read POD information."""
        try:
            return self._client.read_namespaced_pod(pod.metadata.name, pod.metadata.namespace)
        except BaseHTTPError as e:
            raise AirflowException(f"There was an error reading the kubernetes API: {e}")

    def await_xcom_sidecar_container_start(self, pod: V1Pod) -> None:
        self.log.info("Checking if xcom sidecar container is started.")
        warned = False
        while True:
            if self.container_is_running(pod, PodDefaults.SIDECAR_CONTAINER_NAME):
                self.log.info("The xcom sidecar container is started.")
                break
            if not warned:
                self.log.warning("The xcom sidecar container is not yet started.")
                warned = True
            time.sleep(1)

    def extract_xcom(self, pod: V1Pod) -> str:
        """Retrieves XCom value and kills xcom sidecar container."""
        try:
            result = self.extract_xcom_json(pod)
            return result
        finally:
            self.extract_xcom_kill(pod)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=1, min=4, max=10),
        reraise=True,
    )
    def extract_xcom_json(self, pod: V1Pod) -> str:
        """Retrieves XCom value and also checks if xcom json is valid."""
        with closing(
            kubernetes_stream(
                self._client.connect_get_namespaced_pod_exec,
                pod.metadata.name,
                pod.metadata.namespace,
                container=PodDefaults.SIDECAR_CONTAINER_NAME,
                command=["/bin/sh"],
                stdin=True,
                stdout=True,
                stderr=True,
                tty=False,
                _preload_content=False,
            )
        ) as resp:
            result = self._exec_pod_command(
                resp,
                f"if [ -s {PodDefaults.XCOM_MOUNT_PATH}/return.json ]; then cat {PodDefaults.XCOM_MOUNT_PATH}/return.json; else echo __airflow_xcom_result_empty__; fi",  # noqa
            )
            if result and result.rstrip() != "__airflow_xcom_result_empty__":
                # Note: result string is parsed to check if its valid json.
                # This function still returns a string which is converted into json in the calling method.
                json.loads(result)

        if result is None:
            raise AirflowException(f"Failed to extract xcom from pod: {pod.metadata.name}")
        return result

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=1, min=4, max=10),
        reraise=True,
    )
    def extract_xcom_kill(self, pod: V1Pod):
        """Kills xcom sidecar container."""
        with closing(
            kubernetes_stream(
                self._client.connect_get_namespaced_pod_exec,
                pod.metadata.name,
                pod.metadata.namespace,
                container=PodDefaults.SIDECAR_CONTAINER_NAME,
                command=["/bin/sh"],
                stdin=True,
                stdout=True,
                stderr=True,
                tty=False,
                _preload_content=False,
            )
        ) as resp:
            self._exec_pod_command(resp, "kill -s SIGINT 1")

    def _exec_pod_command(self, resp, command: str) -> str | None:
        res = None
        if resp.is_open():
            self.log.info("Running command... %s\n", command)
            resp.write_stdin(command + "\n")
            while resp.is_open():
                resp.update(timeout=1)
                while resp.peek_stdout():
                    res = res + resp.read_stdout() if res else resp.read_stdout()
                error_res = None
                while resp.peek_stderr():
                    error_res = error_res + resp.read_stderr() if error_res else resp.read_stderr()
                if error_res:
                    self.log.info("stderr from command: %s", error_res)
                    break
                if res:
                    return res
        return res


class OnFinishAction(enum.Enum):
    """Action to take when the pod finishes."""

    KEEP_POD = "keep_pod"
    DELETE_POD = "delete_pod"
    DELETE_SUCCEEDED_POD = "delete_succeeded_pod"
