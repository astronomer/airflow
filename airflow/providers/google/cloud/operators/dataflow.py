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
"""This module contains Google Dataflow operators."""
from __future__ import annotations

import uuid
from enum import Enum
from typing import TYPE_CHECKING, Any, Sequence

from airflow import AirflowException
from airflow.compat.functools import cached_property
from airflow.providers.google.cloud.hooks.dataflow import (
    DEFAULT_DATAFLOW_LOCATION,
    DataflowHook,
)
from airflow.providers.google.cloud.links.dataflow import DataflowJobLink
from airflow.providers.google.cloud.operators.cloud_base import GoogleCloudBaseOperator
from airflow.providers.google.cloud.triggers.dataflow import TemplateJobStartTrigger

if TYPE_CHECKING:
    from airflow.utils.context import Context


class CheckJobRunning(Enum):
    """
    Helper enum for choosing what to do if job is already running
    IgnoreJob - do not check if running
    FinishIfRunning - finish current dag run with no action
    WaitForRun - wait for job to finish and then continue with new job
    """

    IgnoreJob = 1
    FinishIfRunning = 2
    WaitForRun = 3


class DataflowConfiguration:
    """Dataflow configuration that can be passed to
    :class:`~airflow.providers.apache.beam.operators.beam.BeamRunJavaPipelineOperator` and
    :class:`~airflow.providers.apache.beam.operators.beam.BeamRunPythonPipelineOperator`.

    :param job_name: The 'jobName' to use when executing the Dataflow job
        (templated). This ends up being set in the pipeline options, so any entry
        with key ``'jobName'`` or  ``'job_name'``in ``options`` will be overwritten.
    :param append_job_name: True if unique suffix has to be appended to job name.
    :param project_id: Optional, the Google Cloud project ID in which to start a job.
        If set to None or missing, the default project_id from the Google Cloud connection is used.
    :param location: Job location.
    :param gcp_conn_id: The connection ID to use connecting to Google Cloud.
    :param poll_sleep: The time in seconds to sleep between polling Google
        Cloud Platform for the dataflow job status while the job is in the
        JOB_STATE_RUNNING state.
    :param impersonation_chain: Optional service account to impersonate using short-term
        credentials, or chained list of accounts required to get the access_token
        of the last account in the list, which will be impersonated in the request.
        If set as a string, the account must grant the originating account
        the Service Account Token Creator IAM role.
        If set as a sequence, the identities from the list must grant
        Service Account Token Creator IAM role to the directly preceding identity, with first
        account from the list granting this role to the originating account (templated).

        .. warning::
            This option requires Apache Beam 2.39.0 or newer.

    :param drain_pipeline: Optional, set to True if want to stop streaming job by draining it
        instead of canceling during killing task instance. See:
        https://cloud.google.com/dataflow/docs/guides/stopping-a-pipeline
    :param cancel_timeout: How long (in seconds) operator should wait for the pipeline to be
        successfully cancelled when task is being killed. (optional) default to 300s
    :param wait_until_finished: (Optional)
        If True, wait for the end of pipeline execution before exiting.
        If False, only submits job.
        If None, default behavior.

        The default behavior depends on the type of pipeline:

        * for the streaming pipeline, wait for jobs to start,
        * for the batch pipeline, wait for the jobs to complete.

        .. warning::
            You cannot call ``PipelineResult.wait_until_finish`` method in your pipeline code for the operator
            to work properly. i. e. you must use asynchronous execution. Otherwise, your pipeline will
            always wait until finished. For more information, look at:
            `Asynchronous execution
            <https://cloud.google.com/dataflow/docs/guides/specifying-exec-params#python_10>`__

        The process of starting the Dataflow job in Airflow consists of two steps:
        * running a subprocess and reading the stderr/stderr log for the job id.
        * loop waiting for the end of the job ID from the previous step by checking its status.

        Step two is started just after step one has finished, so if you have wait_until_finished in your
        pipeline code, step two will not start until the process stops. When this process stops,
        steps two will run, but it will only execute one iteration as the job will be in a terminal state.

        If you in your pipeline do not call the wait_for_pipeline method but pass wait_until_finish=True
        to the operator, the second loop will wait for the job's terminal state.

        If you in your pipeline do not call the wait_for_pipeline method, and pass wait_until_finish=False
        to the operator, the second loop will check once is job not in terminal state and exit the loop.
    :param multiple_jobs: If pipeline creates multiple jobs then monitor all jobs. Supported only by
        :class:`~airflow.providers.apache.beam.operators.beam.BeamRunJavaPipelineOperator`.
    :param check_if_running: Before running job, validate that a previous run is not in process.
        Supported only by:
        :class:`~airflow.providers.apache.beam.operators.beam.BeamRunJavaPipelineOperator`.
    :param service_account: Run the job as a specific service account, instead of the default GCE robot.
    """

    template_fields: Sequence[str] = ("job_name", "location")

    def __init__(
        self,
        *,
        job_name: str = "{{task.task_id}}",
        append_job_name: bool = True,
        project_id: str | None = None,
        location: str | None = DEFAULT_DATAFLOW_LOCATION,
        gcp_conn_id: str = "google_cloud_default",
        poll_sleep: int = 10,
        impersonation_chain: str | Sequence[str] | None = None,
        drain_pipeline: bool = False,
        cancel_timeout: int | None = 5 * 60,
        wait_until_finished: bool | None = None,
        multiple_jobs: bool | None = None,
        check_if_running: CheckJobRunning = CheckJobRunning.WaitForRun,
        service_account: str | None = None,
    ) -> None:
        self.job_name = job_name
        self.append_job_name = append_job_name
        self.project_id = project_id
        self.location = location
        self.gcp_conn_id = gcp_conn_id
        self.poll_sleep = poll_sleep
        self.impersonation_chain = impersonation_chain
        self.drain_pipeline = drain_pipeline
        self.cancel_timeout = cancel_timeout
        self.wait_until_finished = wait_until_finished
        self.multiple_jobs = multiple_jobs
        self.check_if_running = check_if_running
        self.service_account = service_account


class DataflowTemplatedJobStartOperator(GoogleCloudBaseOperator):
    """
    Start a Templated Cloud Dataflow job. The parameters of the operation
    will be passed to the job.

    .. seealso::
        For more information on how to use this operator, take a look at the guide:
        :ref:`howto/operator:DataflowTemplatedJobStartOperator`

    :param template: The reference to the Dataflow template.
    :param job_name: The 'jobName' to use when executing the Dataflow template
        (templated).
    :param options: Map of job runtime environment options.
        It will update environment argument if passed.

        .. seealso::
            For more information on possible configurations, look at the API documentation
            `https://cloud.google.com/dataflow/pipelines/specifying-exec-params
            <https://cloud.google.com/dataflow/docs/reference/rest/v1b3/RuntimeEnvironment>`__

    :param dataflow_default_options: Map of default job environment options.
    :param parameters: Map of job specific parameters for the template.
    :param project_id: Optional, the Google Cloud project ID in which to start a job.
        If set to None or missing, the default project_id from the Google Cloud connection is used.
    :param location: Job location.
    :param gcp_conn_id: The connection ID to use connecting to Google Cloud.
    :param poll_sleep: The time in seconds to sleep between polling Google
        Cloud Platform for the dataflow job status while the job is in the
        JOB_STATE_RUNNING state.
    :param impersonation_chain: Optional service account to impersonate using short-term
        credentials, or chained list of accounts required to get the access_token
        of the last account in the list, which will be impersonated in the request.
        If set as a string, the account must grant the originating account
        the Service Account Token Creator IAM role.
        If set as a sequence, the identities from the list must grant
        Service Account Token Creator IAM role to the directly preceding identity, with first
        account from the list granting this role to the originating account (templated).
    :param environment: Optional, Map of job runtime environment options.

        .. seealso::
            For more information on possible configurations, look at the API documentation
            `https://cloud.google.com/dataflow/pipelines/specifying-exec-params
            <https://cloud.google.com/dataflow/docs/reference/rest/v1b3/RuntimeEnvironment>`__
    :param cancel_timeout: How long (in seconds) operator should wait for the pipeline to be
        successfully cancelled when task is being killed.
    :param append_job_name: True if unique suffix has to be appended to job name.
    :param wait_until_finished: (Optional)
        If True, wait for the end of pipeline execution before exiting.
        If False, only submits job.
        If None, default behavior.

        The default behavior depends on the type of pipeline:

        * for the streaming pipeline, wait for jobs to start,
        * for the batch pipeline, wait for the jobs to complete.

        .. warning::

            You cannot call ``PipelineResult.wait_until_finish`` method in your pipeline code for the operator
            to work properly. i. e. you must use asynchronous execution. Otherwise, your pipeline will
            always wait until finished. For more information, look at:
            `Asynchronous execution
            <https://cloud.google.com/dataflow/docs/guides/specifying-exec-params#python_10>`__

        The process of starting the Dataflow job in Airflow consists of two steps:

        * running a subprocess and reading the stderr/stderr log for the job id.
        * loop waiting for the end of the job ID from the previous step.
          This loop checks the status of the job.

        Step two is started just after step one has finished, so if you have wait_until_finished in your
        pipeline code, step two will not start until the process stops. When this process stops,
        steps two will run, but it will only execute one iteration as the job will be in a terminal state.

        If you in your pipeline do not call the wait_for_pipeline method but pass wait_until_finish=True
        to the operator, the second loop will wait for the job's terminal state.

        If you in your pipeline do not call the wait_for_pipeline method, and pass wait_until_finish=False
        to the operator, the second loop will check once is job not in terminal state and exit the loop.

    It's a good practice to define dataflow_* parameters in the default_args of the dag
    like the project, zone and staging location.

    .. seealso::
        https://cloud.google.com/dataflow/docs/reference/rest/v1b3/LaunchTemplateParameters
        https://cloud.google.com/dataflow/docs/reference/rest/v1b3/RuntimeEnvironment

    .. code-block:: python

       default_args = {
           "dataflow_default_options": {
               "zone": "europe-west1-d",
               "tempLocation": "gs://my-staging-bucket/staging/",
           }
       }

    You need to pass the path to your dataflow template as a file reference with the
    ``template`` parameter. Use ``parameters`` to pass on parameters to your job.
    Use ``environment`` to pass on runtime environment variables to your job.

    .. code-block:: python

       t1 = DataflowTemplatedJobStartOperator(
           task_id="dataflow_example",
           template="{{var.value.gcp_dataflow_base}}",
           parameters={
               "inputFile": "gs://bucket/input/my_input.txt",
               "outputFile": "gs://bucket/output/my_output.txt",
           },
           gcp_conn_id="airflow-conn-id",
           dag=my_dag,
       )

    ``template``, ``dataflow_default_options``, ``parameters``, and ``job_name`` are
    templated, so you can use variables in them.

    Note that ``dataflow_default_options`` is expected to save high-level options
    for project information, which apply to all dataflow operators in the DAG.

        .. seealso::
            https://cloud.google.com/dataflow/docs/reference/rest/v1b3
            /LaunchTemplateParameters
            https://cloud.google.com/dataflow/docs/reference/rest/v1b3/RuntimeEnvironment
            For more detail on job template execution have a look at the reference:
            https://cloud.google.com/dataflow/docs/templates/executing-templates

    :param deferrable: Run operator in the deferrable mode.
    """

    template_fields: Sequence[str] = (
        "template",
        "job_name",
        "options",
        "parameters",
        "project_id",
        "location",
        "gcp_conn_id",
        "impersonation_chain",
        "environment",
        "dataflow_default_options",
    )
    ui_color = "#0273d4"
    operator_extra_links = (DataflowJobLink(),)

    def __init__(
        self,
        *,
        template: str,
        project_id: str | None = None,
        job_name: str = "{{task.task_id}}",
        options: dict[str, Any] | None = None,
        dataflow_default_options: dict[str, Any] | None = None,
        parameters: dict[str, str] | None = None,
        location: str = DEFAULT_DATAFLOW_LOCATION,
        gcp_conn_id: str = "google_cloud_default",
        poll_sleep: int = 10,
        impersonation_chain: str | Sequence[str] | None = None,
        environment: dict | None = None,
        cancel_timeout: int | None = 10 * 60,
        wait_until_finished: bool | None = None,
        append_job_name: bool = True,
        deferrable: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self.template = template
        self.job_name = job_name
        self.options = options or {}
        self.dataflow_default_options = dataflow_default_options or {}
        self.parameters = parameters or {}
        self.project_id = project_id
        self.location = location
        self.gcp_conn_id = gcp_conn_id
        self.poll_sleep = poll_sleep
        self.impersonation_chain = impersonation_chain
        self.environment = environment
        self.cancel_timeout = cancel_timeout
        self.wait_until_finished = wait_until_finished
        self.append_job_name = append_job_name
        self.deferrable = deferrable

        self.job: dict | None = None

        self._validate_deferrable_params()

    def _validate_deferrable_params(self):
        if self.deferrable and self.wait_until_finished:
            raise ValueError(
                "Conflict between deferrable and wait_until_finished parameters "
                "because it makes operator as blocking when it requires to be deferred. "
                "It should be True as deferrable parameter or True as wait_until_finished."
            )

        if self.deferrable and self.wait_until_finished is None:
            self.wait_until_finished = False

    @cached_property
    def hook(self) -> DataflowHook:
        hook = DataflowHook(
            gcp_conn_id=self.gcp_conn_id,
            poll_sleep=self.poll_sleep,
            impersonation_chain=self.impersonation_chain,
            cancel_timeout=self.cancel_timeout,
            wait_until_finished=self.wait_until_finished,
        )
        return hook

    def execute(self, context: Context):
        def set_current_job(current_job):
            self.job = current_job
            DataflowJobLink.persist(self, context, self.project_id, self.location, self.job.get("id"))

        options = self.dataflow_default_options
        options.update(self.options)

        self.job = self.hook.start_template_dataflow(
            job_name=self.job_name,
            variables=options,
            parameters=self.parameters,
            dataflow_template=self.template,
            on_new_job_callback=set_current_job,
            project_id=self.project_id,
            location=self.location,
            environment=self.environment,
            append_job_name=self.append_job_name,
        )
        job_id = self.job.get("id")

        if job_id is None:
            raise AirflowException(
                "While reading job object after template execution error occurred. Job object has no id."
            )

        if not self.deferrable:
            return job_id

        context["ti"].xcom_push(key="job_id", value=job_id)

        self.defer(
            trigger=TemplateJobStartTrigger(
                project_id=self.project_id,
                job_id=job_id,
                location=self.location,
                gcp_conn_id=self.gcp_conn_id,
                poll_sleep=self.poll_sleep,
                impersonation_chain=self.impersonation_chain,
                cancel_timeout=self.cancel_timeout,
            ),
            method_name="execute_complete",
        )

    def execute_complete(self, context: Context, event: dict[str, Any]):
        """Method which executes after trigger finishes its work."""
        if event["status"] == "error" or event["status"] == "stopped":
            self.log.info("status: %s, msg: %s", event["status"], event["message"])
            raise AirflowException(event["message"])

        job_id = event["job_id"]
        self.log.info("Task %s completed with response %s", self.task_id, event["message"])
        return job_id

    def on_kill(self) -> None:
        self.log.info("On kill.")
        if self.job is not None:
            self.log.info("Cancelling job %s", self.job_name)
            self.hook.cancel_job(
                job_name=self.job_name,
                job_id=self.job.get("id"),
                project_id=self.job.get("projectId"),
                location=self.job.get("location"),
            )


class DataflowStartFlexTemplateOperator(GoogleCloudBaseOperator):
    """
    Starts flex templates with the Dataflow pipeline.

    .. seealso::
        For more information on how to use this operator, take a look at the guide:
        :ref:`howto/operator:DataflowStartFlexTemplateOperator`

    :param body: The request body. See:
        https://cloud.google.com/dataflow/docs/reference/rest/v1b3/projects.locations.flexTemplates/launch#request-body
    :param location: The location of the Dataflow job (for example europe-west1)
    :param project_id: The ID of the GCP project that owns the job.
    :param gcp_conn_id: The connection ID to use connecting to Google Cloud
        Platform.
    :param drain_pipeline: Optional, set to True if want to stop streaming job by draining it
        instead of canceling during killing task instance. See:
        https://cloud.google.com/dataflow/docs/guides/stopping-a-pipeline
    :param cancel_timeout: How long (in seconds) operator should wait for the pipeline to be
        successfully cancelled when task is being killed.
    :param wait_until_finished: (Optional)
        If True, wait for the end of pipeline execution before exiting.
        If False, only submits job.
        If None, default behavior.

        The default behavior depends on the type of pipeline:

        * for the streaming pipeline, wait for jobs to start,
        * for the batch pipeline, wait for the jobs to complete.

        .. warning::

            You cannot call ``PipelineResult.wait_until_finish`` method in your pipeline code for the operator
            to work properly. i. e. you must use asynchronous execution. Otherwise, your pipeline will
            always wait until finished. For more information, look at:
            `Asynchronous execution
            <https://cloud.google.com/dataflow/docs/guides/specifying-exec-params#python_10>`__

        The process of starting the Dataflow job in Airflow consists of two steps:

        * running a subprocess and reading the stderr/stderr log for the job id.
        * loop waiting for the end of the job ID from the previous step.
          This loop checks the status of the job.

        Step two is started just after step one has finished, so if you have wait_until_finished in your
        pipeline code, step two will not start until the process stops. When this process stops,
        steps two will run, but it will only execute one iteration as the job will be in a terminal state.

        If you in your pipeline do not call the wait_for_pipeline method but pass wait_until_finish=True
        to the operator, the second loop will wait for the job's terminal state.

        If you in your pipeline do not call the wait_for_pipeline method, and pass wait_until_finish=False
        to the operator, the second loop will check once is job not in terminal state and exit the loop.
    :param impersonation_chain: Optional service account to impersonate using short-term
        credentials, or chained list of accounts required to get the access_token
        of the last account in the list, which will be impersonated in the request.
        If set as a string, the account must grant the originating account
        the Service Account Token Creator IAM role.
        If set as a sequence, the identities from the list must grant
        Service Account Token Creator IAM role to the directly preceding identity, with first
        account from the list granting this role to the originating account (templated).
    :param deferrable: Run operator in the deferrable mode.
    """

    template_fields: Sequence[str] = ("body", "location", "project_id", "gcp_conn_id")
    operator_extra_links = (DataflowJobLink(),)

    def __init__(
        self,
        body: dict,
        location: str,
        project_id: str | None = None,
        gcp_conn_id: str = "google_cloud_default",
        drain_pipeline: bool = False,
        cancel_timeout: int | None = 10 * 60,
        wait_until_finished: bool | None = None,
        impersonation_chain: str | Sequence[str] | None = None,
        deferrable: bool = False,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.body = body
        self.location = location
        self.project_id = project_id
        self.gcp_conn_id = gcp_conn_id
        self.drain_pipeline = drain_pipeline
        self.cancel_timeout = cancel_timeout
        self.wait_until_finished = wait_until_finished
        self.job: dict | None = None
        self.impersonation_chain = impersonation_chain
        self.deferrable = deferrable

        self._validate_deferrable_params()

    def _validate_deferrable_params(self):
        if self.deferrable and self.wait_until_finished:
            raise ValueError(
                "Conflict between deferrable and wait_until_finished parameters "
                "because it makes operator as blocking when it requires to be deferred. "
                "It should be True as deferrable parameter or True as wait_until_finished."
            )

        if self.deferrable and self.wait_until_finished is None:
            self.wait_until_finished = False

    @cached_property
    def hook(self) -> DataflowHook:
        hook = DataflowHook(
            gcp_conn_id=self.gcp_conn_id,
            drain_pipeline=self.drain_pipeline,
            cancel_timeout=self.cancel_timeout,
            wait_until_finished=self.wait_until_finished,
            impersonation_chain=self.impersonation_chain,
        )
        return hook

    def execute(self, context: Context):
        self._append_uuid_to_job_name()

        def set_current_job(current_job):
            self.job = current_job
            DataflowJobLink.persist(self, context, self.project_id, self.location, self.job.get("id"))

        self.job = self.hook.start_flex_template(
            body=self.body,
            location=self.location,
            project_id=self.project_id,
            on_new_job_callback=set_current_job,
        )

        job_id = self.job.get("id")
        if job_id is None:
            raise AirflowException(
                "While reading job object after template execution error occurred. Job object has no id."
            )

        if not self.deferrable:
            return self.job

        self.defer(
            trigger=TemplateJobStartTrigger(
                project_id=self.project_id,
                job_id=job_id,
                location=self.location,
                gcp_conn_id=self.gcp_conn_id,
                impersonation_chain=self.impersonation_chain,
                cancel_timeout=self.cancel_timeout,
            ),
            method_name="execute_complete",
        )

    def _append_uuid_to_job_name(self):
        job_body = self.body.get("launch_parameter") or self.body.get("launchParameter")
        job_name = job_body.get("jobName")
        if job_name:
            job_name += f"-{str(uuid.uuid4())[:8]}"
            job_body["jobName"] = job_name
            self.log.info("Job name was changed to %s", job_name)

    def execute_complete(self, context: Context, event: dict):
        """Method which executes after trigger finishes its work."""
        if event["status"] == "error" or event["status"] == "stopped":
            self.log.info("status: %s, msg: %s", event["status"], event["message"])
            raise AirflowException(event["message"])

        job_id = event["job_id"]
        self.log.info("Task %s completed with response %s", job_id, event["message"])
        job = self.hook.get_job(job_id=job_id, project_id=self.project_id, location=self.location)
        return job

    def on_kill(self) -> None:
        self.log.info("On kill.")
        if self.job is not None:
            self.hook.cancel_job(
                job_id=self.job.get("id"),
                project_id=self.job.get("projectId"),
                location=self.job.get("location"),
            )


class DataflowStartSqlJobOperator(GoogleCloudBaseOperator):
    """
    Starts Dataflow SQL query.

    .. seealso::
        For more information on how to use this operator, take a look at the guide:
        :ref:`howto/operator:DataflowStartSqlJobOperator`

    .. warning::
        This operator requires ``gcloud`` command (Google Cloud SDK) must be installed on the Airflow worker
        <https://cloud.google.com/sdk/docs/install>`__

    :param job_name: The unique name to assign to the Cloud Dataflow job.
    :param query: The SQL query to execute.
    :param options: Job parameters to be executed. It can be a dictionary with the following keys.

        For more information, look at:
        `https://cloud.google.com/sdk/gcloud/reference/beta/dataflow/sql/query
        <gcloud beta dataflow sql query>`__
        command reference

    :param location: The location of the Dataflow job (for example europe-west1)
    :param project_id: The ID of the GCP project that owns the job.
        If set to ``None`` or missing, the default project_id from the GCP connection is used.
    :param gcp_conn_id: The connection ID to use connecting to Google Cloud
        Platform.
    :param drain_pipeline: Optional, set to True if want to stop streaming job by draining it
        instead of canceling during killing task instance. See:
        https://cloud.google.com/dataflow/docs/guides/stopping-a-pipeline
    :param impersonation_chain: Optional service account to impersonate using short-term
        credentials, or chained list of accounts required to get the access_token
        of the last account in the list, which will be impersonated in the request.
        If set as a string, the account must grant the originating account
        the Service Account Token Creator IAM role.
        If set as a sequence, the identities from the list must grant
        Service Account Token Creator IAM role to the directly preceding identity, with first
        account from the list granting this role to the originating account (templated).
    """

    template_fields: Sequence[str] = (
        "job_name",
        "query",
        "options",
        "location",
        "project_id",
        "gcp_conn_id",
    )
    template_fields_renderers = {"query": "sql"}

    def __init__(
        self,
        job_name: str,
        query: str,
        options: dict[str, Any],
        location: str = DEFAULT_DATAFLOW_LOCATION,
        project_id: str | None = None,
        gcp_conn_id: str = "google_cloud_default",
        drain_pipeline: bool = False,
        impersonation_chain: str | Sequence[str] | None = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.job_name = job_name
        self.query = query
        self.options = options
        self.location = location
        self.project_id = project_id
        self.gcp_conn_id = gcp_conn_id
        self.drain_pipeline = drain_pipeline
        self.impersonation_chain = impersonation_chain
        self.job = None
        self.hook: DataflowHook | None = None

    def execute(self, context: Context):
        self.hook = DataflowHook(
            gcp_conn_id=self.gcp_conn_id,
            drain_pipeline=self.drain_pipeline,
            impersonation_chain=self.impersonation_chain,
        )

        def set_current_job(current_job):
            self.job = current_job

        job = self.hook.start_sql_job(
            job_name=self.job_name,
            query=self.query,
            options=self.options,
            location=self.location,
            project_id=self.project_id,
            on_new_job_callback=set_current_job,
        )

        return job

    def on_kill(self) -> None:
        self.log.info("On kill.")
        if self.job:
            self.hook.cancel_job(
                job_id=self.job.get("id"),
                project_id=self.job.get("projectId"),
                location=self.job.get("location"),
            )


class DataflowStopJobOperator(GoogleCloudBaseOperator):
    """
    Stops the job with the specified name prefix or Job ID.
    All jobs with provided name prefix will be stopped.
    Streaming jobs are drained by default.

    Parameter ``job_name_prefix`` and ``job_id`` are mutually exclusive.

    .. seealso::
        For more details on stopping a pipeline see:
        https://cloud.google.com/dataflow/docs/guides/stopping-a-pipeline

    .. seealso::
        For more information on how to use this operator, take a look at the guide:
        :ref:`howto/operator:DataflowStopJobOperator`

    :param job_name_prefix: Name prefix specifying which jobs are to be stopped.
    :param job_id: Job ID specifying which jobs are to be stopped.
    :param project_id: Optional, the Google Cloud project ID in which to start a job.
        If set to None or missing, the default project_id from the Google Cloud connection is used.
    :param location: Optional, Job location. If set to None or missing, "us-central1" will be used.
    :param gcp_conn_id: The connection ID to use connecting to Google Cloud.
    :param poll_sleep: The time in seconds to sleep between polling Google
        Cloud Platform for the dataflow job status to confirm it's stopped.
    :param impersonation_chain: Optional service account to impersonate using short-term
        credentials, or chained list of accounts required to get the access_token
        of the last account in the list, which will be impersonated in the request.
        If set as a string, the account must grant the originating account
        the Service Account Token Creator IAM role.
        If set as a sequence, the identities from the list must grant
        Service Account Token Creator IAM role to the directly preceding identity, with first
        account from the list granting this role to the originating account (templated).
    :param drain_pipeline: Optional, set to False if want to stop streaming job by canceling it
        instead of draining. See: https://cloud.google.com/dataflow/docs/guides/stopping-a-pipeline
    :param stop_timeout: wait time in seconds for successful job canceling/draining
    """

    def __init__(
        self,
        job_name_prefix: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        location: str = DEFAULT_DATAFLOW_LOCATION,
        gcp_conn_id: str = "google_cloud_default",
        poll_sleep: int = 10,
        impersonation_chain: str | Sequence[str] | None = None,
        stop_timeout: int | None = 10 * 60,
        drain_pipeline: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.poll_sleep = poll_sleep
        self.stop_timeout = stop_timeout
        self.job_name = job_name_prefix
        self.job_id = job_id
        self.project_id = project_id
        self.location = location
        self.gcp_conn_id = gcp_conn_id
        self.impersonation_chain = impersonation_chain
        self.hook: DataflowHook | None = None
        self.drain_pipeline = drain_pipeline

    def execute(self, context: Context) -> None:
        self.dataflow_hook = DataflowHook(
            gcp_conn_id=self.gcp_conn_id,
            poll_sleep=self.poll_sleep,
            impersonation_chain=self.impersonation_chain,
            cancel_timeout=self.stop_timeout,
            drain_pipeline=self.drain_pipeline,
        )
        if self.job_id or self.dataflow_hook.is_job_dataflow_running(
            name=self.job_name,
            project_id=self.project_id,
            location=self.location,
        ):
            self.dataflow_hook.cancel_job(
                job_name=self.job_name,
                project_id=self.project_id,
                location=self.location,
                job_id=self.job_id,
            )
        else:
            self.log.info("No jobs to stop")

        return None
