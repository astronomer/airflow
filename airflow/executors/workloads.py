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

import os
import uuid
from typing import TYPE_CHECKING, Literal, Union

from pydantic import BaseModel

if TYPE_CHECKING:
    from airflow.models.taskinstance import TaskInstance as TIModel
    from airflow.models.taskinstancekey import TaskInstanceKey


__all__ = [
    "All",
    "ExecuteTask",
]


class BaseActivity(BaseModel):
    token: str
    """The identity token for this workload"""


class TaskInstance(BaseModel):
    """Schema for TaskInstance with minimal required fields needed for Executors and Task SDK."""

    id: uuid.UUID

    task_id: str
    dag_id: str
    run_id: str
    try_number: int
    map_index: int | None = None

    # TODO: Task-SDK: see if we can replace TIKey with this class entirely?
    @property
    def key(self) -> TaskInstanceKey:
        from airflow.models.taskinstancekey import TaskInstanceKey

        return TaskInstanceKey(
            dag_id=self.dag_id,
            task_id=self.task_id,
            run_id=self.run_id,
            try_number=self.try_number,
            map_index=-1 if self.map_index is None else self.map_index,
        )


class ExecuteTask(BaseActivity):
    """Execute the given Task."""

    ti: TaskInstance
    """The TaskInstance to execute"""
    dag_path: os.PathLike[str]
    """The filepath where the DAG can be found (likely prefixed with `DAG_FOLDER/`)"""

    log_filename_suffix: str
    """The rendered log filename template the task logs should be written to"""

    kind: Literal["ExecuteTask"]

    @classmethod
    def make(cls, ti: TIModel) -> ExecuteTask:
        from pathlib import Path

        from airflow.utils.helpers import log_filename_template_renderer

        ser_ti = TaskInstance.model_validate(ti, from_attributes=True)
        path = Path(ti.dag_run.dag_model.relative_fileloc)

        if path and not path.is_absolute():
            # TODO: What about multiple dag sub folders
            path = "DAGS_FOLDER" / path

        fname = log_filename_template_renderer()(ti=ti)
        return cls(ti=ser_ti, dag_path=path, token="", log_filename_suffix=fname, kind="ExecuteTask")


All = Union[ExecuteTask]
