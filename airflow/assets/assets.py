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

import datetime
import typing

import attrs

from airflow.decorators import task
from airflow.models.dag import DAG
from airflow.operators.python import get_current_context

if typing.TYPE_CHECKING:
    from airflow.assets.targets import AssetTarget
    from airflow.timetables.base import Timetable

__all__ = ["Asset"]

F = typing.TypeVar("F", bound=typing.Callable)


@attrs.define(kw_only=True)
class Asset(typing.Generic[F]):
    """Representation of an asset."""

    at: AssetTarget
    function: F
    schedule: str | Timetable

    def as_dag(self) -> DAG:
        with DAG(
            dag_id=self.function.__name__,
            schedule=self.schedule,
            start_date=datetime.datetime.min,
            catchup=False,
        ) as dag:

            @task.python(task_id=self.function.__name__)
            def do():
                data = self.function()
                self.at.write_data(data, get_current_context())

            do()

        return dag
