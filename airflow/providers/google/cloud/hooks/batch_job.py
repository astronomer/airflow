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

from airflow.providers.google.common.hooks.base_google import GoogleBaseHook


ENDPOINT = "https://batch.googleapis.com/v1"


class BatchJobHook(GoogleBaseHook):
    """Test"""

    hook_name = "Google Batch"

    def __init__(
        self,
        gcp_conn_id: str = GoogleBaseHook.default_conn_name,
        region: str | None = None,
    ) -> None:
        super().__init__(gcp_conn_id=gcp_conn_id)
        self.region = region

    def get_client(self):
        return batch_v1.BatchServiceClient(credentials=self.get_credentials())

    def new_create_job(self, job_id:str = "test", config: dict | None = None):
        path = f"{ENDPOINT}/projects/{self.project_id}/location/{self.region}?job_id={job_id}"

        parent = f"projects/{self.project_id}/locations/{self.region}"
        return self.get_client().create_job(job_id="test", parent=parent, job=config)

    def create_job(
        self,
        job_name: str,
        job: batch_v1.Job,
    ):
        """Test"""
        request = batch_v1.CreateJobRequest()
        request.job = job
        request.job_id = job_name
        request.parent = f"projects/{self.project_id}/locations/{self.region}"
        return self.get_client().create_job(request)
