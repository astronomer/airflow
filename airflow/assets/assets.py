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

import collections.abc
import contextlib
import datetime
import typing

import attrs

from airflow.assets.inputs import AssetInputs
from airflow.datasets import Dataset
from airflow.models.dag import DAG
from airflow.operators.python import PythonOperator

if typing.TYPE_CHECKING:
    from airflow.assets.targets import AssetTarget
    from airflow.models.dag import ScheduleArg
    from airflow.timetables.base import Timetable
    from airflow.utils.context import Context

__all__ = ["Asset"]

F = typing.TypeVar("F", bound=typing.Callable)


class _AssetOperator(PythonOperator):
    custom_operator_name = "@asset"

    def __init__(self, *, assets: dict[str, Asset], target: AssetTarget, **kwargs: typing.Any) -> None:
        super().__init__(**kwargs)
        self.assets = assets
        self.target = target

    def execute(self, context: Context) -> typing.Any:
        inputs = AssetInputs(assets=self.assets, logical_date=context["logical_date"])

        # TODO: Add assets to the formal context definition and generate the
        # accessor in TaskInstance.get_template_context() instead.
        context["assets"] = inputs  # type: ignore[typeddict-unknown-key]
        result = super().execute(context)

        self.target.write_data(result, context)
        return result


@attrs.define(kw_only=True)
class Asset(typing.Generic[F]):
    """Representation of an asset."""

    at: AssetTarget
    function: F
    schedule: str | Timetable | dict[str, Asset]

    # We don't want to recreate the DAG repeated (it wouldn't work well with
    # DagBag anyway), this caches the result from as_dag().
    __created_dag: DAG = attrs.field(init=False)

    @property
    def dag_id(self) -> str:
        return self.function.__name__

    @property
    def task_id(self) -> str:
        return self.function.__name__

    # TODO: Since currently Airflow doesn't recognize an asset, we need to call
    # this explicitly to create a DAG in the DAG file for Airflow to pick it up.
    # Eventually Airflow will be able to pick up an asset automatically and
    # eliminate the need to call this manually.
    def as_dag(self) -> DAG:
        with contextlib.suppress(AttributeError):
            return self.__created_dag

        if isinstance(self.schedule, collections.abc.Mapping):
            assets = self.schedule
            schedule: ScheduleArg = [Dataset(target.at.as_dataset_uri()) for target in assets.values()]
        else:
            assets = {}
            schedule = self.schedule

        with DAG(
            dag_id=self.function.__name__,
            schedule=schedule,
            start_date=datetime.datetime.min,
            catchup=False,
        ) as dag:
            _AssetOperator(
                task_id=self.function.__name__,
                python_callable=self.function,
                assets=assets,
                target=self.at,
                do_xcom_push=False,
                show_return_value_in_logs=False,
            )

        self.__created_dag = dag
        return dag
