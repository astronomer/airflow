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
"""
Execution API routes for asset state.

Per-task asset registration checks (i.e. enforcing that the requesting task
references the asset as inlet or outlet) are intentionally not implemented
here. AIP-103 sketches a write/read asymmetry but explicitly defers the
precise authorization rules to AIP-93 as mentioned in AIP-103.
"""

from __future__ import annotations

from typing import Annotated

from cadwyn import VersionedAPIRouter
from fastapi import HTTPException, Path, status

from airflow._shared.state import AssetScope
from airflow.api_fastapi.common.db.common import SessionDep
from airflow.api_fastapi.execution_api.datamodels.asset_state import (
    AssetStatePutBody,
    AssetStateResponse,
)
from airflow.models.asset import AssetModel
from airflow.state import get_state_backend

# TODO(AIP-103): enforce that the requesting task is registered with the asset
# (via task_inlet_asset_reference or task_outlet_asset_reference) before
# allowing reads/writes. Currently any task with a valid execution token can
# access any asset's state — the same gap exists in /assets and /asset-events.
# Proper fix is a unified asset-registration check across all asset routes,
# not just here.
router = VersionedAPIRouter(
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Unauthorized"},
        status.HTTP_404_NOT_FOUND: {"description": "Not found"},
    },
)


@router.get("/{asset_id}/{key}")
def get_asset_state(
    asset_id: int,
    key: Annotated[str, Path(min_length=1)],
) -> AssetStateResponse:
    """Get an asset state."""
    value = get_state_backend().get(AssetScope(asset_id=asset_id), key)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "reason": "not_found",
                "message": f"Asset state key {key!r} not found",
            },
        )
    return AssetStateResponse(value=value)


@router.put("/{asset_id}/{key}", status_code=status.HTTP_204_NO_CONTENT)
def set_asset_state(
    asset_id: int,
    key: Annotated[str, Path(min_length=1)],
    body: AssetStatePutBody,
    session: SessionDep,
) -> None:
    """Set an asset state."""
    if session.get(AssetModel, asset_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"reason": "not_found", "message": f"Asset {asset_id} not found"},
        )
    get_state_backend().set(AssetScope(asset_id=asset_id), key, body.value)


@router.delete("/{asset_id}/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset_state(
    asset_id: int,
    key: Annotated[str, Path(min_length=1)],
) -> None:
    """Delete an asset state."""
    get_state_backend().delete(AssetScope(asset_id=asset_id), key)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def clear_asset_state(
    asset_id: int,
) -> None:
    """Delete all state keys for an asset."""
    get_state_backend().clear(AssetScope(asset_id=asset_id))
