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


def _load_timetable(dag_id: str, session) -> PartitionedAssetTimetable | None:
    """Return the PartitionedAssetTimetable for *dag_id*, or None if absent or not partitioned."""
    serdag = SerializedDagModel.get(dag_id=dag_id, session=session)
    if serdag is None:
        return None
    with suppress(Exception):
        if isinstance(serdag.dag.timetable, PartitionedAssetTimetable):
            return serdag.dag.timetable
    return None


def _load_timetable_and_assets(
    dag_id: str, session
) -> tuple[PartitionedAssetTimetable | None, list[tuple[str, str]], dict[int, tuple[str, str]]]:
    """
    Load timetable and active required assets.

    Returns (timetable, [(name, uri), ...], {asset_id: (name, uri)}).
    """
    timetable = _load_timetable(dag_id, session)
    asset_rows = session.execute(
        select(AssetModel.id, AssetModel.name, AssetModel.uri)
        .join(DagScheduleAssetReference, DagScheduleAssetReference.asset_id == AssetModel.id)
        .where(DagScheduleAssetReference.dag_id == dag_id, AssetModel.active.has())
    ).all()
    asset_info = [(r.name, r.uri) for r in asset_rows]
    asset_id_to_info = {r.id: (r.name, r.uri) for r in asset_rows}
    return timetable, asset_info, asset_id_to_info


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
        mapper = timetable.get_partition_mapper(name=name, uri=uri)
        total += len(cast("RollupMapper", mapper).to_upstream(partition_key)) if mapper.is_rollup else 1
    return total


def _compute_received_count(
    received_by_asset: dict[int, set[str]],
    timetable: PartitionedAssetTimetable | None,
    asset_id_to_info: dict[int, tuple[str, str]],
    partition_key: str,
) -> int:
    """
    Count received events using rollup-aware deduplication.

    For rollup assets: count distinct upstream keys that intersect the required set.
    For non-rollup assets: count 1 per asset if any event has been logged — the
    source_partition_key value is irrelevant; having any event satisfies the requirement.
    """
    total = 0
    for asset_id, received_keys in received_by_asset.items():
        if timetable is not None:
            name, uri = asset_id_to_info[asset_id]
            mapper = timetable.get_partition_mapper(name=name, uri=uri)
            if mapper.is_rollup:
                required_keys = frozenset(cast("RollupMapper", mapper).to_upstream(partition_key))
                total += len(received_keys & required_keys)
                continue
        # Non-rollup: any logged event satisfies this asset's requirement.
        total += 1 if received_keys else 0
    return total


partitioned_dag_runs_router = AirflowRouter(tags=["PartitionedDagRun"])


def _build_response(row, required_count: int, received_count: int | None = None) -> PartitionedDagRunResponse:
    return PartitionedDagRunResponse(
        id=row.id,
        dag_id=row.target_dag_id,
        partition_key=row.partition_key,
        created_at=row.created_at.isoformat() if row.created_at else None,
        total_received=received_count if received_count is not None else (row.total_received or 0),
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

    # Subquery for received count per partition (count of required assets that have any log).
    # This matches the non-rollup contract "any event for an asset = that asset is satisfied".
    # Rollup-aware counts are computed in Python in _compute_received_count when dag_id is set.
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
        select(func.count(func.distinct(PartitionedAssetKeyLog.asset_id)))
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
        timetable, asset_info, asset_id_to_info = _load_timetable_and_assets(dag_id.value, session)

        # Batch-fetch all log entries for these APDRs in one query.
        apdr_ids = [row.id for row in rows]
        log_by_apdr: dict[int, dict[int, set[str]]] = {}
        for log_row in session.execute(
            select(
                PartitionedAssetKeyLog.asset_partition_dag_run_id,
                PartitionedAssetKeyLog.asset_id,
                PartitionedAssetKeyLog.source_partition_key,
            ).where(
                PartitionedAssetKeyLog.asset_partition_dag_run_id.in_(apdr_ids),
                PartitionedAssetKeyLog.asset_id.in_(list(asset_id_to_info)),
            )
        ).all():
            log_by_apdr.setdefault(log_row.asset_partition_dag_run_id, {}).setdefault(
                log_row.asset_id, set()
            ).add(log_row.source_partition_key or "")

        results = [
            _build_response(
                row,
                _compute_total_required(timetable, asset_info, row.partition_key),
                _compute_received_count(
                    log_by_apdr.get(row.id, {}), timetable, asset_id_to_info, row.partition_key
                ),
            )
            for row in rows
        ]
        return PartitionedDagRunCollectionResponse(partitioned_dag_runs=results, total=len(results))

    # No dag_id filter: load timetables and assets for each unique Dag.
    # total_received is approximated via SQL for this global view.
    unique_dag_ids = list({row.target_dag_id for row in rows})
    dag_timetables_assets: dict[
        str, tuple[PartitionedAssetTimetable | None, list[tuple[str, str]], dict[int, tuple[str, str]]]
    ] = {did: _load_timetable_and_assets(did, session) for did in unique_dag_ids}
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
    # Use a set to deduplicate: multiple events for the same key count as one.
    received_keys_by_asset: dict[int, set[str]] = {}
    for row in session.execute(
        select(
            PartitionedAssetKeyLog.asset_id,
            PartitionedAssetKeyLog.source_partition_key,
        ).where(PartitionedAssetKeyLog.asset_partition_dag_run_id == partitioned_dag_run.id)
    ):
        received_keys_by_asset.setdefault(row.asset_id, set()).add(row.source_partition_key or "")

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

    timetable = _load_timetable(dag_id, session)

    assets = []
    for row in asset_rows:
        received_keys = sorted(received_keys_by_asset.get(row.id, set()))
        required_keys: list[str] = [partition_key]
        is_rollup = False
        if timetable is not None:
            with suppress(Exception):
                mapper = timetable.get_partition_mapper(name=row.name, uri=row.uri)
                if mapper.is_rollup:
                    required_keys = sorted(cast("RollupMapper", mapper).to_upstream(partition_key))
                    is_rollup = True
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
                received_keys=received_keys,
                required_keys=required_keys,
                is_rollup=is_rollup,
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
