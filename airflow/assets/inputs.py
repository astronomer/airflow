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
import sqlalchemy as sa

from airflow.models.dagrun import DagRun
from airflow.models.taskinstance import TaskInstance
from airflow.utils.session import create_session

if typing.TYPE_CHECKING:
    import pandas

    from airflow.assets.assets import Asset
    from airflow.assets.targets import AssetTarget


@attrs.define(kw_only=True)
class AssetInput:
    """Asset reference as a dependency."""

    target: AssetTarget
    source: TaskInstance

    def as_df(self) -> pandas.DataFrame:
        return self.target.read_pandas_dataframe(self.source.get_template_context())


@attrs.define(kw_only=True)
class AssetInputs(typing.Mapping[str, AssetInput]):
    """Lazy asset reference lookup."""

    assets: dict[str, Asset]
    logical_date: datetime.datetime

    def __iter__(self) -> typing.Iterator[str]:
        return iter(self.assets)

    def __len__(self) -> int:
        return len(self.assets)

    def __getitem__(self, key: str) -> AssetInput:
        asset = self.assets[key]
        with create_session() as session:
            source: TaskInstance | None = session.scalar(
                sa.select(TaskInstance)
                .where(
                    TaskInstance.dag_id == asset.dag_id,
                    TaskInstance.task_id == asset.task_id,
                    TaskInstance.map_index == -1,
                    DagRun.execution_date <= self.logical_date,
                )
                .order_by(DagRun.execution_date.desc())
                .limit(1)
            )
        if source is None:  # No previous input found.
            raise KeyError(key)
        source.refresh_from_task(asset.as_dag().get_task(asset.task_id))
        return AssetInput(target=asset.at, source=source)
