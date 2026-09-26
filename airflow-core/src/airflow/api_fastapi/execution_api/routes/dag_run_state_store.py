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
from typing import Annotated
from uuid import UUID

from cadwyn import VersionedAPIRouter
from fastapi import HTTPException, Path, Security, status
from sqlalchemy.orm import Session

from airflow._shared.state import DagRunScope
from airflow.api_fastapi.common.db.common import SessionDep
from airflow.api_fastapi.execution_api.datamodels.dag_run_state_store import (
    DagRunStateStorePutBody,
    DagRunStateStoreResponse,
)
from airflow.api_fastapi.execution_api.security import ExecutionAPIRoute, require_auth
from airflow.models.taskinstance import TaskInstance as TI
from airflow.state import get_state_backend

router = VersionedAPIRouter(
    route_class=ExecutionAPIRoute,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Unauthorized"},
        status.HTTP_403_FORBIDDEN: {"description": "Access denied"},
        status.HTTP_404_NOT_FOUND: {"description": "Not found"},
    },
    dependencies=[Security(require_auth, scopes=["ti:self"])],
)


def _get_dag_run_scope_for_ti(task_instance_id: UUID, session: Session) -> DagRunScope:
    """
    Resolve the caller's Dag run scope from its own task instance.

    The scope is never taken from the request: a task can only ever reach the state of the run
    it belongs to.
    """
    ti = session.get(TI, task_instance_id)
    if ti is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "reason": "not_found",
                "message": f"Task instance {task_instance_id} not found",
            },
        )
    return DagRunScope(dag_id=ti.dag_id, run_id=ti.run_id)


def _get_backend():
    backend = get_state_backend()
    if DagRunScope not in backend.supported_scopes:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "reason": "unsupported_scope",
                "message": (
                    f"State backend {type(backend).__name__} does not support DagRunScope. "
                    f"Add it to the backend's supported_scopes once the backend handles it."
                ),
            },
        )
    return backend


@router.get("/{task_instance_id}/{key:path}")
def get_dag_run_state_store(
    task_instance_id: UUID,
    key: Annotated[str, Path(min_length=1)],
    session: SessionDep,
) -> DagRunStateStoreResponse:
    """Get value for a Dag run state store key."""
    scope = _get_dag_run_scope_for_ti(task_instance_id, session)
    value = _get_backend().get(scope, key, session=session)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "reason": "not_found",
                "message": f"Dag run state store key {key!r} not found",
            },
        )
    return DagRunStateStoreResponse(value=json.loads(value))


@router.put("/{task_instance_id}/{key:path}", status_code=status.HTTP_204_NO_CONTENT)
def set_dag_run_state_store(
    task_instance_id: UUID,
    key: Annotated[str, Path(min_length=1)],
    body: DagRunStateStorePutBody,
    session: SessionDep,
) -> None:
    """Set a Dag run state store key, creating or updating the row."""
    scope = _get_dag_run_scope_for_ti(task_instance_id, session)
    _get_backend().set(scope, key, json.dumps(body.value), expires_at=body.expires_at, session=session)


@router.delete("/{task_instance_id}/{key:path}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dag_run_state_store(
    task_instance_id: UUID,
    key: Annotated[str, Path(min_length=1)],
    session: SessionDep,
) -> None:
    """Delete a single Dag run state store key."""
    scope = _get_dag_run_scope_for_ti(task_instance_id, session)
    _get_backend().delete(scope, key, session=session)


@router.delete("/{task_instance_id}", status_code=status.HTTP_204_NO_CONTENT)
def clear_dag_run_state_store(
    task_instance_id: UUID,
    session: SessionDep,
) -> None:
    """Delete every Dag run state store key for the caller's run."""
    scope = _get_dag_run_scope_for_ti(task_instance_id, session)
    _get_backend().clear(scope, session=session)
