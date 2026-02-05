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

import pendulum
import pytest
from sqlalchemy import select

from airflow.models.asset import AssetEvent, AssetModel, AssetPartitionDagRun, PartitionedAssetKeyLog
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.sdk import IdentityMapper
from airflow.sdk.definitions.asset import Asset
from airflow.sdk.definitions.timetables.assets import PartitionedAssetTimetable

from tests_common.test_utils.asserts import assert_queries_count
from tests_common.test_utils.db import clear_db_apdr, clear_db_dags, clear_db_pakl, clear_db_serialized_dags

pytestmark = pytest.mark.db_test


@pytest.fixture(autouse=True)
def cleanup():
    clear_db_dags()
    clear_db_serialized_dags()
    clear_db_apdr()
    clear_db_pakl()


@pytest.mark.parametrize(
    ("client_fixture", "expected_status"),
    [
        ("unauthenticated_test_client", 401),
        ("unauthorized_test_client", 403),
    ],
    ids=["401", "403"],
)
def test_auth(client_fixture, expected_status, request):
    client = request.getfixturevalue(client_fixture)
    assert client.get("/partitioned_dag_runs?dag_id=any").status_code == expected_status


def test_missing_dag_returns_404(test_client):
    assert test_client.get("/partitioned_dag_runs?dag_id=no_such_dag").status_code == 404


def test_non_partitioned_dag_returns_empty(test_client, dag_maker):
    with dag_maker(dag_id="normal", schedule=[Asset(uri="s3://bucket/a", name="a")], serialized=True):
        EmptyOperator(task_id="t")
    dag_maker.create_dagrun()
    dag_maker.sync_dagbag_to_db()

    with assert_queries_count(2):
        resp = test_client.get("/partitioned_dag_runs?dag_id=normal&pending=true")
    assert resp.status_code == 200
    assert resp.json() == {"partitioned_dag_runs": [], "total": 0, "asset_expressions": None}


@pytest.mark.parametrize(
    ("fulfilled", "pending_filter", "expected_total", "expected_state"),
    [
        (False, True, 1, "pending"),
        (True, True, 0, None),
        (True, False, 1, "running"),
    ],
    ids=["pending-included", "fulfilled-excluded", "fulfilled-included"],
)
def test_partition_filtering(
    test_client, dag_maker, session, fulfilled, pending_filter, expected_total, expected_state
):
    asset = Asset(uri="s3://bucket/pf", name="pf")
    with dag_maker(
        dag_id="pf_dag",
        schedule=PartitionedAssetTimetable(assets=asset, partition_mapper=IdentityMapper()),
        serialized=True,
    ):
        EmptyOperator(task_id="t")

    dr = dag_maker.create_dagrun()
    dag_maker.sync_dagbag_to_db()

    asset_model = session.scalars(select(AssetModel).where(AssetModel.uri == "s3://bucket/pf")).one()
    event = AssetEvent(asset_id=asset_model.id, timestamp=pendulum.now())
    session.add(event)
    session.flush()

    pdr = AssetPartitionDagRun(
        target_dag_id="pf_dag",
        partition_key="2024-06-01",
        created_dag_run_id=dr.id if fulfilled else None,
    )
    session.add(pdr)
    session.flush()

    session.add(
        PartitionedAssetKeyLog(
            asset_id=asset_model.id,
            asset_event_id=event.id,
            asset_partition_dag_run_id=pdr.id,
            source_partition_key="2024-06-01",
            target_dag_id="pf_dag",
            target_partition_key="2024-06-01",
        )
    )
    session.commit()

    with assert_queries_count(2):
        resp = test_client.get(f"/partitioned_dag_runs?dag_id=pf_dag&pending={str(pending_filter).lower()}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == expected_total
    if expected_total > 0:
        assert body["partitioned_dag_runs"][0]["state"] == expected_state


@pytest.mark.parametrize(
    ("received_count", "expected_received"),
    [(0, 0), (1, 1), (2, 2), (3, 3)],
    ids=["0/3", "1/3", "2/3", "3/3"],
)
def test_receipt_count(test_client, dag_maker, session, received_count, expected_received):
    a1 = Asset(uri="s3://bucket/r1", name="r1")
    a2 = Asset(uri="s3://bucket/r2", name="r2")
    a3 = Asset(uri="s3://bucket/r3", name="r3")
    uris = ["s3://bucket/r1", "s3://bucket/r2", "s3://bucket/r3"]

    with dag_maker(
        dag_id="partial",
        schedule=PartitionedAssetTimetable(assets=a1 & a2 & a3, partition_mapper=IdentityMapper()),
        serialized=True,
    ):
        EmptyOperator(task_id="t")

    dag_maker.create_dagrun()
    dag_maker.sync_dagbag_to_db()

    assets = {a.uri: a for a in session.scalars(select(AssetModel).where(AssetModel.uri.in_(uris)))}

    pdr = AssetPartitionDagRun(target_dag_id="partial", partition_key="2024-06-01", created_dag_run_id=None)
    session.add(pdr)
    session.flush()

    for uri in uris[:received_count]:
        event = AssetEvent(asset_id=assets[uri].id, timestamp=pendulum.now())
        session.add(event)
        session.flush()
        session.add(
            PartitionedAssetKeyLog(
                asset_id=assets[uri].id,
                asset_event_id=event.id,
                asset_partition_dag_run_id=pdr.id,
                source_partition_key="2024-06-01",
                target_dag_id="partial",
                target_partition_key="2024-06-01",
            )
        )
    session.commit()

    resp = test_client.get("/partitioned_dag_runs?dag_id=partial&pending=true")
    assert resp.status_code == 200
    pdr_resp = resp.json()["partitioned_dag_runs"][0]
    assert pdr_resp["total_received"] == expected_received
    assert pdr_resp["total_required"] == 3
