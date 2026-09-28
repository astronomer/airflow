#
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

import functools
import logging
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, status

from airflow.api_fastapi.execution_api.datamodels.workload_identity import WorkloadIdentityResponse
from airflow.api_fastapi.execution_api.security import get_caller_identity_dep
from airflow.api_fastapi.execution_api.workload_identity import (
    WorkloadCallerIdentity,
    WorkloadIdentityDenied,
    get_workload_identity_provider,
)
from airflow.configuration import conf

router = APIRouter()

log = logging.getLogger(__name__)

# Provider calls go to an external issuer. They run on their own small pool rather than the
# request threadpool every other route shares, so a slow issuer cannot starve heartbeats.
_PROVIDER_LIMITER = anyio.CapacityLimiter(8)


@router.get(
    "/workload-identity",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Unauthorized"},
        status.HTTP_403_FORBIDDEN: {"description": "Task is not allowed the requested identity or audience"},
        status.HTTP_501_NOT_IMPLEMENTED: {"description": "No workload identity provider is configured"},
        status.HTTP_504_GATEWAY_TIMEOUT: {
            "description": "The workload identity provider did not answer in time"
        },
    },
)
async def get_workload_identity(
    caller: Annotated[WorkloadCallerIdentity, Depends(get_caller_identity_dep)],
    audience: Annotated[str | None, Query()] = None,
) -> WorkloadIdentityResponse:
    """
    Mint a workload identity token for the calling task instance.

    The token is not the task's own Execution API token. Which identity it carries, and
    whether ``audience`` is allowed for it, is decided by the configured provider from the
    caller identity the server resolved; nothing in the request can widen it.
    """
    provider = get_workload_identity_provider()
    if provider is None:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "reason": "not_configured",
                "message": "No workload identity provider is configured on this deployment",
            },
        )
    timeout = conf.getfloat("execution_api", "workload_identity_timeout")
    try:
        with anyio.fail_after(timeout):
            # abandon_on_cancel lets the deadline return to the task while the provider call
            # finishes on its own pool; without it the timeout waits for the thread.
            issued = await anyio.to_thread.run_sync(
                functools.partial(provider.issue, caller, audience),
                abandon_on_cancel=True,
                limiter=_PROVIDER_LIMITER,
            )
    except WorkloadIdentityDenied as exc:
        log.info(
            "Workload identity denied for task %s (%s.%s, audience=%s): %s",
            caller.ti_id,
            caller.dag_id,
            caller.task_id,
            audience,
            exc,
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"reason": "access_denied", "message": str(exc)},
        )
    except TimeoutError:
        log.warning(
            "Workload identity provider did not answer within %ss for task %s (%s.%s, audience=%s)",
            timeout,
            caller.ti_id,
            caller.dag_id,
            caller.task_id,
            audience,
        )
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "reason": "provider_timeout",
                "message": f"Workload identity provider did not answer within {timeout} seconds",
            },
        )
    return WorkloadIdentityResponse.model_validate(issued)
