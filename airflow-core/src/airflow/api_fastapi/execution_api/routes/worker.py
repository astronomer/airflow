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

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from airflow.api_fastapi.execution_api.deps import JWTBearerWorker

log = logging.getLogger(__name__)

router = APIRouter()

# JWT validation for worker registration - accepts string subjects
JWTBearerWorkerDep = Depends(JWTBearerWorker())


class ProviderInfo(BaseModel):
    """Schema for provider metadata."""

    name: str
    version: str


class WorkerProviderRegistration(BaseModel):
    """Schema for worker provider registration request."""

    worker_id: str
    executor_type: str
    providers: list[ProviderInfo]


@router.post("/register-providers")
def register_worker_providers(
    request: WorkerProviderRegistration,
    token_claims: dict = JWTBearerWorkerDep,
) -> dict:
    """
    Register worker's installed providers with the API server.

    Called by Celery/K8s workers on boot with list of installed providers.
    JWT token authenticates the worker.
    """
    log.info(
        f"Received provider registration from worker {request.worker_id} "
        f"({request.executor_type}) with {len(request.providers)} providers"
    )

    # Validate token subject matches worker_id pattern
    expected_subject = f"worker:{request.worker_id}"
    actual_subject = token_claims.get("sub")

    if actual_subject != expected_subject:
        log.warning(
            f"Token subject mismatch: expected '{expected_subject}', got '{actual_subject}' "
            f"for worker {request.worker_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token subject does not match worker_id",
        )

    try:
        from airflow.api_fastapi.execution_api.services.provider_metadata_fetcher import (
            provider_metadata_fetcher,
        )
        from airflow.api_fastapi.execution_api.services.worker_inventory import worker_inventory

        provider_dicts = [p.model_dump() for p in request.providers]

        # Register providers in inventory
        worker_inventory.register(
            worker_id=request.worker_id,
            executor_type=request.executor_type,
            providers=provider_dicts,
        )

        # Kick off background fetch of provider.yaml connection metadata
        # for any providers not already cached at this version
        provider_metadata_fetcher.fetch_many_in_background(provider_dicts)

        log.info(f"Successfully registered {len(request.providers)} providers for worker {request.worker_id}")

        return {
            "status": "success",
            "worker_id": request.worker_id,
            "registered_providers": len(request.providers),
        }

    except Exception as e:
        log.error(f"Failed to register providers for worker {request.worker_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register providers: {str(e)}",
        )
