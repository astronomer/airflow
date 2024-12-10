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
"""Serialized DAG table in database."""
from __future__ import annotations

from typing import Any, ClassVar

import pydantic


class DagInfo(pydantic.BaseModel):  # noqa: D101
    data: dict

    NULLABLE_PROPERTIES: ClassVar[set[str]] = {
        "is_paused_upon_creation",
        "owner",
        "dag_display_name",
        "description",
        "max_active_tasks",
        "max_active_runs",
        "max_consecutive_failed_dag_runs",
        "owner_links",
    }

    @property
    def hash(self) -> str:
        from airflow.models.serialized_dag import SerializedDagModel

        return SerializedDagModel.hash(self.data)

    def next_dagrun_info(self, last):
        return None

    def __getattr__(self, name: str, /) -> Any:
        if name in self.NULLABLE_PROPERTIES:
            return self.data["dag"].get(name)
        try:
            return self.data["dag"][name]
        except KeyError:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}") from None

    @property
    def timetable(self):
        from airflow.serialization.serialized_objects import decode_timetable

        return decode_timetable(self.data["dag"]["timetable"])

    @property
    def has_task_concurrency_limits(self):
        return any(task.get("max_active_tis_per_dag") is not None for task in self.data["dag"]["tasks"])
