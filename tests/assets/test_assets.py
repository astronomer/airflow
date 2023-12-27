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
import pathlib
import typing

import pandas

from airflow.assets import asset
from airflow.assets.assets import Asset
from airflow.assets.fileformats import ParquetFormat
from airflow.assets.targets import File
from airflow.utils.state import DagRunState

if typing.TYPE_CHECKING:
    from airflow.assets.inputs import AssetInput


def test_create_asset_dag(tmp_path: pathlib.Path) -> None:
    target_path = tmp_path.joinpath("first")

    @asset(
        at=File(target_path.as_uri(), fmt=ParquetFormat()),
        schedule="@daily",
    )
    def first():
        return pandas.DataFrame([[1, 2]], columns=["a", "b"])

    assert isinstance(first, Asset)

    dag = first.as_dag()
    assert dag.dag_id == "first"

    tasks = dag.tasks
    assert len(tasks) == 1

    task = tasks[0]
    assert task.task_id == "first"

    dr = dag.test()
    assert dr.state == DagRunState.SUCCESS

    df = pandas.read_parquet(target_path)
    assert df.to_dict() == {"a": {0: 1}, "b": {0: 2}}


def test_depend_asset(tmp_path: pathlib.Path) -> None:
    path1 = tmp_path.joinpath("1")
    path2 = tmp_path.joinpath("2")

    @asset(
        at=File(path1.as_uri(), fmt=ParquetFormat()),
        schedule="@daily",
    )
    def first():
        return pandas.DataFrame(data={"a": [1], "b": [2]})

    @asset(
        at=File(path2.as_uri(), fmt=ParquetFormat()),
        schedule={"data": first},
    )
    def second(*, assets: collections.abc.Mapping[str, AssetInput]):
        return assets["data"].as_df().rename(columns=str.upper)

    dr1 = first.as_dag().test()
    assert dr1.state == DagRunState.SUCCESS
    assert pandas.read_parquet(path1).to_dict() == {"a": {0: 1}, "b": {0: 2}}

    dr2 = second.as_dag().test()
    assert dr2.state == DagRunState.SUCCESS
    assert pandas.read_parquet(path2).to_dict() == {"A": {0: 1}, "B": {0: 2}}
