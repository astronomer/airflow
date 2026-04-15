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
from sqlalchemy import func, select

from airflow.api_fastapi.common.db.common import SessionDep, apply_filters_to_select
from airflow.api_fastapi.common.parameters import (
    QueryPartitionedDagRunDagIdFilter,
    QueryPartitionedDagRunHasCreatedDagRunIdFilter,
)
from airflow.api_fastapi.common.router import AirflowRouter
from airflow.api_fastapi.core_api.datamodels.ui.partitioned_dag_runs import (
    PartitionedDagRunAssetResponse,
    PartitionedDagRunCollectionResponse,
    PartitionedDagRunDetailResponse,
    PartitionedDagRunResponse,
)
from airflow.api_fastapi.core_api.security import (
    ReadableDagsFilterDep,
    requires_access_asset,
    requires_access_dag,
)
from airflow.models import DagModel
from airflow.models.asset import (
    AssetModel,
    AssetPartitionDagRun,
    DagScheduleAssetReference,
    PartitionedAssetKeyLog,
)
from airflow.models.dagrun import DagRun
from airflow.models.serialized_dag import SerializedDagModel
from airflow.timetables.simple import PartitionedAssetTimetable

if TYPE_CHECKING:
    from airflow.partition_mappers.base import RollupMapper


def _load_timetable_and_assets(
    dag_id: str, session
) -> tuple[PartitionedAssetTimetable | None, list[tuple[str, str]]]:
    """Load the DAG timetable and its active required assets as (name, uri) pairs."""
    timetable = None
    serdag = SerializedDagModel.get(dag_id=dag_id, session=session)
    if serdag is not None:
        with suppress(Exception):
            dag = serdag.dag
            if isinstance(dag.timetable, PartitionedAssetTimetable):
                timetable = dag.timetable

    asset_rows = session.execute(
        select(AssetModel.name, AssetModel.uri)
        .join(DagScheduleAssetReference, DagScheduleAssetReference.asset_id == AssetModel.id)
        .where(DagScheduleAssetReference.dag_id == dag_id, AssetModel.active.has())
    ).all()
    return timetable, [(r.name or "", r.uri or "") for r in asset_rows]


def _compute_total_required(
    timetable: PartitionedAssetTimetable | None,
    asset_info: list[tuple[str, str]],
    partition_key: str,
) -> int:
    """Sum required upstream events across all assets, using to_upstream for rollup mappers."""
    if timetable is None:
        return len(asset_info)
    total = 0
    for name, uri in asset_info:
        try:
            mapper = timetable.get_partition_mapper(name=name, uri=uri)
            total += len(mapper.to_upstream(partition_key)) if isinstance(mapper, RollupMapper) else 1
        except Exception:
            total += 1
    return total or len(asset_info)


partitioned_dag_runs_router = AirflowRouter(tags=["PartitionedDagRun"])


def _build_response(row, required_count: int) -> PartitionedDagRunResponse:
    return PartitionedDagRunResponse(
        id=row.id,
        dag_id=row.target_dag_id,
        partition_key=row.partition_key,
        created_at=row.created_at.isoformat() if row.created_at else None,
        total_received=row.total_received or 0,
        total_required=required_count,
        state=row.dag_run_state if row.created_dag_run_id else "pending",
        created_dag_run_id=row.dag_run_id,
    )


@partitioned_dag_runs_router.get(
    "/partitioned_dag_runs",
    dependencies=[Depends(requires_access_asset(method="GET"))],
)
def get_partitioned_dag_runs(
    session: SessionDep,
    readable_dags_filter: ReadableDagsFilterDep,
    dag_id: QueryPartitionedDagRunDagIdFilter,
    has_created_dag_run_id: QueryPartitionedDagRunHasCreatedDagRunIdFilter,
) -> PartitionedDagRunCollectionResponse:
    """Return PartitionedDagRuns. Filter by dag_id and/or has_created_dag_run_id."""
    if dag_id.value is not None:
        dag_info = session.execute(
            select(DagModel.timetable_summary).where(DagModel.dag_id == dag_id.value)
        ).one_or_none()

        if dag_info is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Dag with id {dag_id.value} was not found")
        if dag_info.timetable_summary != "Partitioned Asset":
            return PartitionedDagRunCollectionResponse(partitioned_dag_runs=[], total=0)

    # Subquery: count received events per partition (PartitionedAssetKeyLog rows for required assets)
    required_assets_subq = (
        select(DagScheduleAssetReference.asset_id)
        .join(AssetModel, AssetModel.id == DagScheduleAssetReference.asset_id)
        .where(
            DagScheduleAssetReference.dag_id == AssetPartitionDagRun.target_dag_id,
            AssetModel.active.has(),
        )
        .correlate(AssetPartitionDagRun)
    )
    received_subq = (
        select(func.count(PartitionedAssetKeyLog.id))
        .where(
            PartitionedAssetKeyLog.asset_partition_dag_run_id == AssetPartitionDagRun.id,
            PartitionedAssetKeyLog.asset_id.in_(required_assets_subq),
        )
        .correlate(AssetPartitionDagRun)
        .scalar_subquery()
    )

    query = select(
        AssetPartitionDagRun.id,
        AssetPartitionDagRun.target_dag_id,
        AssetPartitionDagRun.partition_key,
        AssetPartitionDagRun.created_at,
        AssetPartitionDagRun.created_dag_run_id,
        DagRun.run_id.label("dag_run_id"),
        DagRun.state.label("dag_run_state"),
        received_subq.label("total_received"),
    ).outerjoin(DagRun, AssetPartitionDagRun.created_dag_run_id == DagRun.id)
    query = apply_filters_to_select(statement=query, filters=[dag_id, has_created_dag_run_id])
    readable_dag_ids = readable_dags_filter.value
    if readable_dag_ids is not None:
        query = query.where(AssetPartitionDagRun.target_dag_id.in_(readable_dag_ids))
    query = query.order_by(AssetPartitionDagRun.created_at.desc())

    if not (rows := session.execute(query).all()):
        return PartitionedDagRunCollectionResponse(partitioned_dag_runs=[], total=0)

    if dag_id.value is not None:
        timetable, asset_info = _load_timetable_and_assets(dag_id.value, session)
        results = [
            _build_response(row, _compute_total_required(timetable, asset_info, row.partition_key))
            for row in rows
        ]
        return PartitionedDagRunCollectionResponse(partitioned_dag_runs=results, total=len(results))

    # No dag_id filter: load timetables and assets for each unique DAG
    unique_dag_ids = list({row.target_dag_id for row in rows})
    dag_timetables_assets: dict[str, tuple[PartitionedAssetTimetable | None, list[tuple[str, str]]]] = {
        did: _load_timetable_and_assets(did, session) for did in unique_dag_ids
    }
    dag_rows = session.execute(
        select(DagModel.dag_id, DagModel.asset_expression).where(DagModel.dag_id.in_(unique_dag_ids))
    ).all()
    asset_expressions = {r.dag_id: r.asset_expression for r in dag_rows}

    results = [
        _build_response(
            row,
            _compute_total_required(
                dag_timetables_assets[row.target_dag_id][0],
                dag_timetables_assets[row.target_dag_id][1],
                row.partition_key,
            ),
        )
        for row in rows
    ]
    return PartitionedDagRunCollectionResponse(
        partitioned_dag_runs=results,
        total=len(results),
        asset_expressions=asset_expressions,
    )


@partitioned_dag_runs_router.get(
    "/pending_partitioned_dag_run/{dag_id}/{partition_key}",
    dependencies=[Depends(requires_access_asset(method="GET")), Depends(requires_access_dag(method="GET"))],
)
def get_pending_partitioned_dag_run(
    dag_id: str,
    partition_key: str,
    session: SessionDep,
) -> PartitionedDagRunDetailResponse:
    """Return full details for pending PartitionedDagRun."""
    partitioned_dag_run = session.execute(
        select(
            AssetPartitionDagRun.id,
            AssetPartitionDagRun.target_dag_id,
            AssetPartitionDagRun.partition_key,
            AssetPartitionDagRun.created_at,
            AssetPartitionDagRun.updated_at,
            DagRun.run_id.label("created_dag_run_id"),
        )
        .outerjoin(DagRun, AssetPartitionDagRun.created_dag_run_id == DagRun.id)
        .where(
            AssetPartitionDagRun.target_dag_id == dag_id,
            AssetPartitionDagRun.partition_key == partition_key,
            AssetPartitionDagRun.created_dag_run_id.is_(None),
        )
    ).one_or_none()

    if partitioned_dag_run is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No PartitionedDagRun for dag={dag_id} partition={partition_key}",
        )

    # Collect received upstream partition keys per asset for this partition run.
    received_keys_by_asset: dict[int, list[str]] = {}
    for row in session.execute(
        select(
            PartitionedAssetKeyLog.asset_id,
            PartitionedAssetKeyLog.source_partition_key,
        ).where(PartitionedAssetKeyLog.asset_partition_dag_run_id == partitioned_dag_run.id)
    ):
        received_keys_by_asset.setdefault(row.asset_id, []).append(row.source_partition_key or "")

    asset_expression_subq = (
        select(DagModel.asset_expression).where(DagModel.dag_id == dag_id).scalar_subquery()
    )
    asset_rows = session.execute(
        select(
            AssetModel.id,
            AssetModel.uri,
            AssetModel.name,
            asset_expression_subq.label("asset_expression"),
        )
        .join(DagScheduleAssetReference, DagScheduleAssetReference.asset_id == AssetModel.id)
        .where(DagScheduleAssetReference.dag_id == dag_id, AssetModel.active.has())
        .order_by(AssetModel.uri)
    ).all()

    # Load serialized DAG to compute required keys for rollup assets
    timetable = None
    serdag = SerializedDagModel.get(dag_id=dag_id, session=session)
    if serdag is not None:
        with suppress(Exception):
            dag = serdag.dag
            if isinstance(dag.timetable, PartitionedAssetTimetable):
                timetable = dag.timetable

    assets = []
    for row in asset_rows:
        received_keys = received_keys_by_asset.get(row.id, [])
        required_keys: list[str] = [partition_key]
        if timetable is not None:
            with suppress(Exception):
                mapper = timetable.get_partition_mapper(name=row.name or "", uri=row.uri or "")
                if isinstance(mapper, RollupMapper):
                    required_keys = sorted(mapper.to_upstream(partition_key))
        received_count = len(received_keys)
        required_count = len(required_keys)
        assets.append(
            PartitionedDagRunAssetResponse(
                asset_id=row.id,
                asset_name=row.name,
                asset_uri=row.uri,
                received=received_count >= required_count and required_count > 0,
                received_count=received_count,
                required_count=required_count,
                received_keys=sorted(received_keys),
                required_keys=required_keys,
            )
        )

    total_received = sum(a.received_count for a in assets)
    total_required = sum(a.required_count for a in assets)
    asset_expression = asset_rows[0].asset_expression if asset_rows else None

    return PartitionedDagRunDetailResponse(
        id=partitioned_dag_run.id,
        dag_id=dag_id,
        partition_key=partition_key,
        created_at=partitioned_dag_run.created_at.isoformat() if partitioned_dag_run.created_at else None,
        updated_at=partitioned_dag_run.updated_at.isoformat() if partitioned_dag_run.updated_at else None,
        created_dag_run_id=partitioned_dag_run.created_dag_run_id,
        assets=assets,
        total_required=total_required,
        total_received=total_received,
        asset_expression=asset_expression,
    )
