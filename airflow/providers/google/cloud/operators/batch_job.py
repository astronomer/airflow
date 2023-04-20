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

from enum import Enum
from typing import Any

from google.cloud import batch_v1
from google.cloud.batch_v1.types import (
    AllocationPolicy,
    LogsPolicy,
)

from airflow.models import BaseOperator
from airflow.providers.google.cloud.hooks.batch_job import BatchJobHook
from airflow.providers.google.cloud.operators.cloud_base import GoogleCloudBaseOperator
from airflow.utils.context import Context

"""
(1)
job_name
region
zone

(2)
------
vm provision model
--------------

(3)
----
machine
---------

(4)
task
------
- runnable List[(container/script)] strict this to 1


task resource
- core
- memory

"""


class BatchJobOperation(Enum):
    CREATE = "create"


class NewBatchJobOperator(GoogleCloudBaseOperator):
    def __init__(
        self,
        operation: str = BatchJobOperation.CREATE,
        config: dict | None = None,
        gcp_conn_id: str | None = "gcloud_default",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.operation = operation
        self.config = config
        self.gcp_conn_id = gcp_conn_id

    def execute(self, context: Context) -> Any:
        hook = BatchJobHook(gcp_conn_id=self.gcp_conn_id)
        if self.operation == BatchJobOperation.CREATE:
            hook.new_create_job(self.config)


class BatchJobOperator(BaseOperator):
    """Test"""

    def __init__(
        self,
        job_name: str,
        machine_type: str | None = None,
        bash_script: str | None = None,
        container_commands: str | None = None,
        logs_policy: str | None = None,
        gcp_conn_id: str | None = "gcloud_default",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.job_name = job_name
        self.bash_script = bash_script
        self.container_commands = container_commands
        self.logs_policy = logs_policy
        self.gcp_conn_id = gcp_conn_id
        self.machine_type = machine_type

    def execute(self, context: Context) -> Any:
        # create_job
        hook = BatchJobHook(gcp_conn_id=self.gcp_conn_id)
        response = hook.create_job(job_name=self.job_name, job=self._job)
        return response

    @property
    def _job(self):
        job = batch_v1.Job()
        job.task_groups = [self._task_groups]
        job.allocation_policy = self._allocation_policy
        job.logs_policy = self._logs_policy
        return job

    @property
    def _task_groups(self):
        group = batch_v1.TaskGroup()
        group.task_spec = self._task_spec
        return group

    @property
    def _allocation_policy(self):
        policy = AllocationPolicy.InstancePolicy()
        policy.machine_type = self.machine_type
        instances = AllocationPolicy.InstancePolicyOrTemplate()
        instances.policy = policy
        allocation_policy = AllocationPolicy()
        allocation_policy.instances = [instances]
        return allocation_policy

    @property
    def _logs_policy(self):
        logs_policy = LogsPolicy()
        logs_policy.destination = LogsPolicy.Destination.DESTINATION_UNSPECIFIED
        if self.logs_policy == "CLOUD_LOGGING":
            logs_policy.destination = LogsPolicy.Destination.CLOUD_LOGGING
        elif self.logs_policy == "PATH":
            logs_policy.destination = LogsPolicy.Destination.CLOUD_LOGGING
        return logs_policy

    @property
    def _task_spec(self):
        task_spec = batch_v1.TaskSpec()
        task_spec.runnables = [self._runnables]
        return task_spec

    @property
    def _runnables(self):
        runnable = batch_v1.Runnable()
        if self.bash_script:
            runnable.script = batch_v1.Runnable.Script()
            runnable.script.text = self.bash_script
        else:
            runnable.container = batch_v1.Runnable.Container()
            runnable.container.image_uri = "gcr.io/google-containers/busybox"
            runnable.container.entrypoint = "/bin/sh"
            runnable.container.commands = ["-c", self.container_commands]
        return [runnable]
