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

"""Task instance filter parameters for API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Query, status

from airflow.api_fastapi.common.parameters.base import BaseParam
from airflow.models.taskinstance import TaskInstance

if TYPE_CHECKING:
    from sqlalchemy.sql import Select

    from airflow.serialization.definitions.dag import SerializedDAG


class QueryTaskInstanceTaskGroupFilter(BaseParam[str]):
    """
    Task group filter - returns all tasks in the specified group.

    The DAG context must be set via ``with_dag()`` before ``to_orm()`` is called,
    since the DAG is not available at FastAPI dependency resolution time.
    """

    def __init__(self, skip_none: bool = True):
        super().__init__(skip_none=skip_none)
        self.dag: None | SerializedDAG = None

    def with_dag(self, dag: SerializedDAG) -> QueryTaskInstanceTaskGroupFilter:
        """Set the DAG context for task group resolution. Returns self for chaining."""
        self.dag = dag
        return self

    def to_orm(self, select: Select) -> Select:
        if self.value is None and self.skip_none:
            return select

        if not self.dag:
            raise ValueError("Dag must be set via with_dag() before calling to_orm")

        if not hasattr(self.dag, "task_group"):
            return select

        # Exact matching on group_id
        task_groups = self.dag.task_group.get_task_group_dict()
        task_group = task_groups.get(self.value)
        if not task_group:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={
                    "reason": "not_found",
                    "message": f"Task group {self.value} not found",
                },
            )

        return select.where(TaskInstance.task_id.in_(task.task_id for task in task_group.iter_tasks()))

    @classmethod
    def depends(
        cls,
        value: str | None = Query(
            alias="task_group_id",
            default=None,
            description="Filter by exact task group ID. Returns all tasks within the specified task group.",
        ),
    ) -> QueryTaskInstanceTaskGroupFilter:
        return cls().set_value(value)
