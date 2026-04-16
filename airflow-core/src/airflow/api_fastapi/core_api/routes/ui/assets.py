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

from contextlib import suppress
from typing import TYPE_CHECKING, cast

from fastapi import Depends, HTTPException, status
from sqlalchemy import ColumnElement, and_, case, exists, func, select, true

from airflow.api_fastapi.common.db.common import SessionDep
from airflow.api_fastapi.common.router import AirflowRouter
from airflow.api_fastapi.core_api.routes.ui.partitioned_dag_runs import _load_timetable
from airflow.api_fastapi.core_api.security import requires_access_asset, requires_access_dag
from airflow.models import DagModel
from airflow.models.asset import (
    AssetDagRunQueue,
    AssetEvent,
    AssetModel,
    AssetPartitionDagRun,
    DagScheduleAssetReference,
    PartitionedAssetKeyLog,
)

if TYPE_CHECKING:
    from airflow.partition_mappers.base import RollupMapper

assets_router = AirflowRouter(tags=["Asset"])


@assets_router.get(
    "/next_run_assets/{dag_id}",
    dependencies=[Depends(requires_access_asset(method="GET")), Depends(requires_access_dag(method="GET"))],
)
def next_run_assets(
    dag_id: str,
    session: SessionDep,
) -> dict:
    dag_model = DagModel.get_dagmodel(dag_id, session=session)
    if dag_model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Dag with id {dag_id} was not found")

    latest_run = dag_model.get_last_dagrun(session=session)
    event_filter = (
        AssetEvent.timestamp >= latest_run.logical_date if latest_run and latest_run.logical_date else true()
    )

    pending_partition_count: int | None = None

    queued_expr: ColumnElement[int]
    if is_partitioned := dag_model.timetable_summary == "Partitioned Asset":
        pending_partition_count = session.scalar(
            select(func.count())
            .select_from(AssetPartitionDagRun)
            .where(
                AssetPartitionDagRun.target_dag_id == dag_id,
                AssetPartitionDagRun.created_dag_run_id.is_(None),
            )
        )
        queued_expr = case(
            (
                exists(
                    select(PartitionedAssetKeyLog.id)
                    .join(
                        AssetPartitionDagRun,
                        PartitionedAssetKeyLog.asset_partition_dag_run_id == AssetPartitionDagRun.id,
                    )
                    .where(
                        PartitionedAssetKeyLog.asset_id == AssetModel.id,
                        PartitionedAssetKeyLog.target_dag_id == dag_id,
                        AssetPartitionDagRun.created_dag_run_id.is_(None),
                    )
                ),
                1,
            ),
            else_=0,
        )
    else:
        queued_expr = func.max(case((AssetDagRunQueue.asset_id.is_not(None), 1), else_=0))

    query = (
        select(
            AssetModel.id,
            AssetModel.uri,
            AssetModel.name,
            func.max(AssetEvent.timestamp).label("last_update"),
            queued_expr.label("queued"),
        )
        .join(DagScheduleAssetReference, DagScheduleAssetReference.asset_id == AssetModel.id)
        .join(AssetEvent, and_(AssetEvent.asset_id == AssetModel.id, event_filter), isouter=True)
        .where(DagScheduleAssetReference.dag_id == dag_id, AssetModel.active.has())
        .group_by(AssetModel.id, AssetModel.uri, AssetModel.name)
        .order_by(AssetModel.uri)
    )

    if not is_partitioned:
        query = query.join(
            AssetDagRunQueue,
            and_(
                AssetDagRunQueue.asset_id == AssetModel.id,
                AssetDagRunQueue.target_dag_id == DagScheduleAssetReference.dag_id,
            ),
            isouter=True,
        )

    events = [dict(info._mapping) for info in session.execute(query)]
    for event in events:
        if not event.pop("queued", None):
            event["last_update"] = None

    # For partitioned Dags: enrich events with per-asset received/required counts,
    # using to_upstream for rollup mappers, and fix last_update for partial receipt.
    if is_partitioned:
        timetable = _load_timetable(dag_id, session)

        pending_apdr = session.execute(
            select(AssetPartitionDagRun.id, AssetPartitionDagRun.partition_key)
            .where(
                AssetPartitionDagRun.target_dag_id == dag_id,
                AssetPartitionDagRun.created_dag_run_id.is_(None),
            )
            .order_by(AssetPartitionDagRun.created_at.desc())
            .limit(1)
        ).one_or_none()

        if pending_apdr is not None:
            # Collect received upstream partition keys per asset for this partition run.
            # Use a set to deduplicate: multiple events for the same key count as one.
            received_keys_by_asset: dict[int, set[str]] = {}
            for row in session.execute(
                select(
                    PartitionedAssetKeyLog.asset_id,
                    PartitionedAssetKeyLog.source_partition_key,
                ).where(PartitionedAssetKeyLog.asset_partition_dag_run_id == pending_apdr.id)
            ):
                received_keys_by_asset.setdefault(row.asset_id, set()).add(row.source_partition_key or "")

            for event in events:
                asset_id = event["id"]
                received_keys = sorted(received_keys_by_asset.get(asset_id, set()))
                required_keys: list[str] = [pending_apdr.partition_key]
                is_rollup = False
                if timetable is not None:
                    with suppress(Exception):
                        mapper = timetable.get_partition_mapper(
                            name=event["name"],
                            uri=event["uri"],
                        )
                        if mapper.is_rollup:
                            required_keys = sorted(
                                cast("RollupMapper", mapper).to_upstream(pending_apdr.partition_key)
                            )
                            is_rollup = True
                received_count = len(received_keys)
                required_count = len(required_keys)
                event["received_count"] = received_count
                event["required_count"] = required_count
                event["received_keys"] = received_keys
                event["required_keys"] = required_keys
                event["is_rollup"] = is_rollup
                # Only show last_update when all required upstream keys are received
                if received_count < required_count:
                    event["last_update"] = None
        else:
            # No pending APDR yet — mark rollup assets so the UI can handle them
            # correctly (e.g. skip "Asset Triggered" in favour of the asset name view).
            for event in events:
                is_rollup = False
                if timetable is not None:
                    with suppress(Exception):
                        mapper = timetable.get_partition_mapper(
                            name=event["name"],
                            uri=event["uri"],
                        )
                        is_rollup = mapper.is_rollup
                event["received_count"] = 0
                event["required_count"] = 1
                event["received_keys"] = []
                event["required_keys"] = []
                event["is_rollup"] = is_rollup

    data: dict = {"asset_expression": dag_model.asset_expression, "events": events}
    if pending_partition_count is not None:
        data["pending_partition_count"] = pending_partition_count
    return data
