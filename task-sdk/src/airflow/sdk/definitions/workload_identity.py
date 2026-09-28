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

from datetime import datetime

import attrs


@attrs.define(frozen=True, kw_only=True)
class WorkloadIdentity:
    """
    A short-lived token that identifies the running task to a system outside Airflow.

    Returned by :func:`airflow.sdk.get_workload_identity`. The token is minted by the
    workload identity provider the deployment configures, not by Airflow itself; ``issuer``
    and ``subject`` are what a relying party verifies against. Treat ``token`` like a
    password: keep it in memory, and do not push it to XCom or logs.

    :param token: the signed token, usually a JWT.
    :param subject: the identity the token asserts, the ``sub`` claim.
    :param issuer: who signed it, the ``iss`` claim.
    :param audience: the relying party the token is scoped to, when one was requested.
    :param expires_at: when the token stops being valid. Request a new one after this.
    """

    token: str = attrs.field(repr=False)
    subject: str
    issuer: str
    audience: str | None = None
    expires_at: datetime


def get_workload_identity(*, audience: str | None = None) -> WorkloadIdentity:
    """
    Return a short-lived token that identifies the running task to a system outside Airflow.

    The token is minted by the workload identity provider configured on the API server with
    ``[execution_api] workload_identity_provider`` and is scoped to ``audience`` when one is
    given. Which identity the task receives is decided there, from the task's verified
    provenance; nothing passed here can widen it. Use it from a hook that hands a token
    supplier to a client library, or from task code that talks to a relying party directly.
    A Connection remains the right home for a credential the platform can inject itself.

    Tokens expire, typically within minutes. Call again rather than caching past
    ``expires_at``. From async code use :func:`aget_workload_identity`.

    :raises AirflowRuntimeError: with ``PERMISSION_DENIED`` when the provider refuses the
        task the identity or the audience, and with ``API_SERVER_ERROR`` when no provider is
        configured or it did not answer in time. There is no fallback to another identity.
    """
    # Runtime helpers live in execution_time, which imports this package; same shape as Connection.get.
    from airflow.sdk.execution_time.context import _get_workload_identity

    return _get_workload_identity(audience)


async def aget_workload_identity(*, audience: str | None = None) -> WorkloadIdentity:
    """Async counterpart of :func:`get_workload_identity`, for async operators and hooks."""
    from airflow.sdk.execution_time.context import _aget_workload_identity

    return await _aget_workload_identity(audience)
