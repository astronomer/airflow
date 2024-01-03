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
import shlex
import sqlite3
import tempfile
import typing

import pandas

from airflow.assets import asset
from airflow.assets.assets import Asset
from airflow.assets.fileformats import ParquetFormat
from airflow.assets.targets import File, Table
from airflow.decorators import task
from airflow.operators.bash import BashOperator
from airflow.utils.state import DagRunState

if typing.TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from airflow.assets.inputs import AssetInput


def test_create_asset_dag(tmp_path: pathlib.Path) -> None:
    target_path = tmp_path.joinpath("target")

    @asset(
        at=File(target_path.as_uri(), fmt=ParquetFormat()),
        schedule="@daily",
    )
    def abc() -> pandas.DataFrame:
        return pandas.DataFrame({"a": [1], "b": [2]})

    assert isinstance(abc, Asset)

    dag = abc.as_dag()
    assert dag.dag_id == "abc"

    tasks = dag.tasks
    assert len(tasks) == 1

    task = tasks[0]
    assert task.task_id == "__airflow_output_asset__"

    dr = dag.test()
    assert dr.state == DagRunState.SUCCESS

    df = pandas.read_parquet(target_path)
    assert df.to_dict() == {"a": {0: 1}, "b": {0: 2}}


def _connect_default_sqlite() -> sqlite3.Connection:
    # This is where the database file is created in by Airflow.
    # See ``airflow.utils.db.create_default_connections``.
    return sqlite3.connect(pathlib.Path(tempfile.gettempdir(), "sqlite_default.db"))


def test_table_asset(tmp_path: pathlib.Path) -> None:
    @asset(
        at=Table("sqlite_default", name="test_table_asset", mode="replace"),
        schedule="@hourly",
    )
    def abc() -> pandas.DataFrame:
        return pandas.DataFrame({"a": [1], "b": [2]})

    dag = abc.as_dag()
    dr = dag.test()
    assert dr.state == DagRunState.SUCCESS

    with _connect_default_sqlite() as conn:
        rows = conn.execute("""SELECT a, b FROM test_table_asset""").fetchall()
    assert rows == [(1, 2)]


def test_depend_asset(tmp_path: pathlib.Path) -> None:
    path1 = tmp_path.joinpath("1")
    path2 = tmp_path.joinpath("2")

    @asset(
        at=Table("sqlite_default", name="test_depend_asset", mode="replace"),
        schedule="@hourly",
    )
    def zero() -> pandas.DataFrame:
        return pandas.DataFrame({"a": [1], "b": [2]})

    @asset(
        at=File(path1.as_uri(), fmt=ParquetFormat()),
        schedule={"data": zero},
    )
    def one(*, assets: collections.abc.Mapping[str, AssetInput]):
        return assets["data"].as_df().rename(columns=str.upper)

    @asset(
        at=File(path2.as_uri(), fmt=ParquetFormat()),
        schedule={"data": one},
    )
    def two(*, assets: collections.abc.Mapping[str, AssetInput]):
        dep = assets["data"].as_df().filter(["A", "B"])
        return pandas.concat([dep, pandas.DataFrame({"A": [3], "B": [4]})], ignore_index=True)

    dr0 = zero.as_dag().test()
    assert dr0.state == DagRunState.SUCCESS

    dr1 = one.as_dag().test()
    assert dr1.state == DagRunState.SUCCESS

    dr2 = two.as_dag().test()
    assert dr2.state == DagRunState.SUCCESS
    assert pandas.read_parquet(path2).to_dict() == {"A": {0: 1, 1: 3}, "B": {0: 2, 1: 4}}


def test_asset_attach_tasks(session: Session, tmp_path: pathlib.Path) -> None:
    container_path = tmp_path.joinpath("container")
    target_path = container_path.joinpath("target")

    @task
    def container() -> str:
        container_path.mkdir()
        return "created!"

    @task
    def check(msg: str) -> None:
        if msg != "created!":
            raise RuntimeError("wrong")

    @asset(
        at=File(target_path.as_uri(), fmt=ParquetFormat()),
        schedule="@daily",
    )
    def target() -> pandas.DataFrame:
        return pandas.DataFrame({"a": [1], "b": [2]})

    with target.attach() as t:
        clean = BashOperator(task_id="clean", bash_command=f"rm -r { shlex.quote(str(container_path)) }")
        check(container()) >> t >> clean

    dr = target.as_dag().create_dagrun(
        state=DagRunState.RUNNING,
        run_id="test_asset_attach_tasks",
        session=session,
    )

    # From a clean slate.
    assert not container_path.exists()

    decision = dr.task_instance_scheduling_decisions(session)
    assert {ti.task_id for ti in decision.schedulable_tis} == {"container"}
    decision.schedulable_tis[0].run(session=session)
    assert container_path.is_dir()

    decision = dr.task_instance_scheduling_decisions(session)
    assert {ti.task_id for ti in decision.schedulable_tis} == {"check"}
    decision.schedulable_tis[0].run(session=session)

    decision = dr.task_instance_scheduling_decisions(session)
    assert {ti.task_id for ti in decision.schedulable_tis} == {"__airflow_output_asset__"}
    decision.schedulable_tis[0].run(session=session)
    assert pandas.read_parquet(target_path).to_dict() == {"a": {0: 1}, "b": {0: 2}}

    decision = dr.task_instance_scheduling_decisions(session)
    assert {ti.task_id for ti in decision.schedulable_tis} == {"clean"}
    decision.schedulable_tis[0].run(session=session)
    assert not container_path.exists()

    decision = dr.task_instance_scheduling_decisions(session)
    assert not decision.schedulable_tis
