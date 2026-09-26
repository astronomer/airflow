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

import json

from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from airflow.api_fastapi.auth.managers.models.resource_details import DagAccessEntity
from airflow.api_fastapi.common.db.common import SessionDep, paginated_select
from airflow.api_fastapi.common.parameters import QueryLimit, QueryOffset
from airflow.api_fastapi.common.router import AirflowRouter
from airflow.api_fastapi.core_api.datamodels.dag_run_state_store import (
    DagRunStateStoreCollectionResponse,
    DagRunStateStoreResponse,
)
from airflow.api_fastapi.core_api.openapi.exceptions import create_openapi_http_exception_doc
from airflow.api_fastapi.core_api.security import requires_access_dag
from airflow.models.dag_run_state_store import DagRunStateStoreModel
from airflow.models.dagrun import DagRun

dag_run_state_store_router = AirflowRouter(
    tags=["Dag Run State Store"],
    prefix="/dags/{dag_id}/dagRuns/{dag_run_id}/state-store",
)

_COLUMNS = (
    DagRunStateStoreModel.key,
    DagRunStateStoreModel.value,
    DagRunStateStoreModel.updated_at,
    DagRunStateStoreModel.expires_at,
)


def _require_dag_run(dag_id: str, dag_run_id: str, session: SessionDep) -> None:
    exists = session.scalar(
        select(DagRun.id).where(DagRun.dag_id == dag_id, DagRun.run_id == dag_run_id).limit(1)
    )
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dag run not found for dag_id={dag_id!r}, run_id={dag_run_id!r}",
        )


@dag_run_state_store_router.get(
    "",
    responses=create_openapi_http_exception_doc([status.HTTP_404_NOT_FOUND]),
    dependencies=[Depends(requires_access_dag(method="GET", access_entity=DagAccessEntity.RUN))],
)
def list_dag_run_state_store(
    dag_id: str,
    dag_run_id: str,
    limit: QueryLimit,
    offset: QueryOffset,
    session: SessionDep,
) -> DagRunStateStoreCollectionResponse:
    """List all Dag run state store entries for a Dag run."""
    _require_dag_run(dag_id, dag_run_id, session)
    base = (
        select(*_COLUMNS)
        .where(
            DagRunStateStoreModel.dag_id == dag_id,
            DagRunStateStoreModel.run_id == dag_run_id,
        )
        .order_by(DagRunStateStoreModel.key.asc())
    )
    paginated, total_entries = paginated_select(
        statement=base,
        filters=None,
        order_by=None,
        offset=offset,
        limit=limit,
        session=session,
    )
    entries = [
        DagRunStateStoreResponse(
            key=r.key, value=json.loads(r.value), updated_at=r.updated_at, expires_at=r.expires_at
        )
        for r in session.execute(paginated).all()
    ]
    return DagRunStateStoreCollectionResponse(dag_run_state_store=entries, total_entries=total_entries)


@dag_run_state_store_router.get(
    "/{key:path}",
    responses=create_openapi_http_exception_doc([status.HTTP_404_NOT_FOUND]),
    dependencies=[Depends(requires_access_dag(method="GET", access_entity=DagAccessEntity.RUN))],
)
def get_dag_run_state_store(
    dag_id: str,
    dag_run_id: str,
    key: str,
    session: SessionDep,
) -> DagRunStateStoreResponse:
    """Get a single Dag run state store entry."""
    _require_dag_run(dag_id, dag_run_id, session)
    row = session.execute(
        select(*_COLUMNS).where(
            DagRunStateStoreModel.dag_id == dag_id,
            DagRunStateStoreModel.run_id == dag_run_id,
            DagRunStateStoreModel.key == key,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dag run state store key {key!r} not found",
        )
    return DagRunStateStoreResponse(
        key=row.key, value=json.loads(row.value), updated_at=row.updated_at, expires_at=row.expires_at
    )
