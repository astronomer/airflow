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

import structlog
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from airflow.api_fastapi.execution_api.datamodels import taskinstance as ti_datamodel  # noqa: TC001
from airflow.utils.state import TaskInstanceState

if TYPE_CHECKING:
    from airflow.typing_compat import Self

log = structlog.get_logger(__name__)


class BaseCallbackRequest(BaseModel):
    """
    Base Class with information about the callback to be executed.

    :param msg: Additional Message that can be used for logging
    """

    filepath: str
    """File Path to use to run the callback"""
    bundle_name: str
    bundle_version: str | None
    msg: str | None = None
    """Additional Message that can be used for logging to determine failure/task heartbeat timeout"""

    @classmethod
    def from_json(cls, data: str | bytes | bytearray) -> Self:
        return cls.model_validate_json(data)

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(**kwargs)


class TaskCallbackRequest(BaseCallbackRequest):
    """
    Task callback status information.

    A Class with information about the success/failure TI callback to be executed. Currently, only failure
    callbacks when tasks are externally killed or experience heartbeat timeouts are run via DagFileProcessorProcess.
    """

    ti: ti_datamodel.TaskInstance
    """Simplified Task Instance representation"""
    task_callback_type: TaskInstanceState | None = None
    """Whether on success, on failure, on retry"""
    context_from_server: ti_datamodel.TIRunContext | None = None
    """Task execution context from the Server"""
    type: Literal["TaskCallbackRequest"] = "TaskCallbackRequest"

    @property
    def is_failure_callback(self) -> bool:
        """Returns True if the callback is a failure callback."""
        if self.task_callback_type is None:
            return True
        return self.task_callback_type in {
            TaskInstanceState.FAILED,
            TaskInstanceState.UP_FOR_RETRY,
            TaskInstanceState.UPSTREAM_FAILED,
        }


class EmailRequest(BaseCallbackRequest):
    """Email notification request for task failures/retries."""

    ti: ti_datamodel.TaskInstance
    """Simplified Task Instance representation"""
    email_type: Literal["failure", "retry"] = "failure"
    """Whether this is for a failure or retry email"""
    context_from_server: ti_datamodel.TIRunContext
    """Task execution context from the Server"""
    type: Literal["EmailRequest"] = "EmailRequest"


class DagRunContext(BaseModel):
    """Class to pass context info from the server to build a Execution context object."""

    dag_run: ti_datamodel.DagRun | None = None
    last_ti: ti_datamodel.TaskInstance | None = None

    @model_validator(mode="before")
    @classmethod
    def _handle_orm_dagrun(cls, data: Any) -> Any:
        """
        Handle ORM DagRun objects and protect against DetachedInstanceError.

        When converting ORM DagRun to Pydantic datamodel, if consumed_asset_events
        is not eager-loaded and the session is detached, accessing it raises
        DetachedInstanceError. This validator catches that and converts to datamodel
        with empty consumed_asset_events.
        """
        if not isinstance(data, dict):
            return data

        dag_run = data.get("dag_run")
        if dag_run is None:
            return data

        # Check if it's an ORM object (has __tablename__ attribute)
        if not hasattr(dag_run, "__tablename__"):
            return data

        # Try to convert ORM object to dict, catching DetachedInstanceError
        try:
            # This will trigger lazy loading of consumed_asset_events if not eager-loaded
            # Pydantic will handle the conversion, but we need to ensure it doesn't crash
            _ = dag_run.consumed_asset_events
        except Exception as e:
            # If we get DetachedInstanceError, manually build the dict with empty list
            error_type = type(e).__name__
            if "DetachedInstanceError" in error_type or "DetachedInstance" in str(e):
                log.warning(
                    "DetachedInstanceError accessing consumed_asset_events for DagRun. "
                    "This indicates a bug - the relationship should have been eager-loaded. "
                    "Defaulting to empty list to prevent scheduler crash.",
                    dag_id=getattr(dag_run, "dag_id", None),
                    run_id=getattr(dag_run, "run_id", "unknown"),
                    exc_info=True,
                )
                # Build a minimal dict from the ORM object without consumed_asset_events
                # Pydantic will use this and won't try to access the detached relationship
                safe_dag_run_dict = {
                    "dag_id": dag_run.dag_id,
                    "run_id": dag_run.run_id,
                    "logical_date": dag_run.logical_date,
                    "data_interval_start": dag_run.data_interval_start,
                    "data_interval_end": dag_run.data_interval_end,
                    "run_after": dag_run.run_after,
                    "start_date": dag_run.start_date,
                    "end_date": dag_run.end_date,
                    "clear_number": getattr(dag_run, "clear_number", 0),
                    "run_type": dag_run.run_type,
                    "state": dag_run.state,
                    "conf": dag_run.conf,
                    "triggering_user_name": getattr(dag_run, "triggering_user_name", None),
                    "consumed_asset_events": [],  # Safe default
                    "partition_key": getattr(dag_run, "partition_key", None),
                }
                data["dag_run"] = safe_dag_run_dict
            else:
                # Re-raise if it's not a DetachedInstanceError
                raise

        return data


class DagCallbackRequest(BaseCallbackRequest):
    """A Class with information about the success/failure DAG callback to be executed."""

    dag_id: str
    run_id: str
    context_from_server: DagRunContext | None = None
    is_failure_callback: bool | None = True
    """Flag to determine whether it is a Failure Callback or Success Callback"""
    type: Literal["DagCallbackRequest"] = "DagCallbackRequest"


CallbackRequest = Annotated[
    DagCallbackRequest | TaskCallbackRequest | EmailRequest,
    Field(discriminator="type"),
]

# Backwards compatibility alias
EmailNotificationRequest = EmailRequest
