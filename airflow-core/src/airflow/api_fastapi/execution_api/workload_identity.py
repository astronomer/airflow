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
"""
Pluggable workload identity provider for the Execution API.

A task instance authenticates to the Execution API with a token that names only itself.
Systems outside Airflow (Snowflake, a cloud IAM, a secrets manager) cannot trust that token:
its subject is a per-run UUID and its issuer is internal. A *workload identity* is a second,
short-lived token that such a system can verify, minted for the task by a provider the
deployment configures with ``[execution_api] workload_identity_provider``.

Airflow's part is fixed and small. The Execution API verifies the task's own token, resolves
where the task comes from (:class:`WorkloadCallerIdentity`) and hands that to the provider.
Everything else is the provider's: which external identity the task runs as, whether the
requested audience is allowed for it, how the token is signed and where its public keys are
published. When no provider is configured the endpoint answers 501 and nothing changes.
"""

from __future__ import annotations

import abc
import functools
from dataclasses import dataclass

from pydantic import AwareDatetime, BaseModel

from airflow.configuration import conf


@dataclass(frozen=True)
class WorkloadCallerIdentity:
    """
    The verified provenance of the task instance making an Execution API request.

    Every field is read by the server from its own database after the caller's token has
    been validated. Nothing here comes from the request body, query string or Dag code, so a
    provider can build authorization rules on it.

    :param ti_id: the task-instance id, the ``sub`` of the caller's token.
    :param dag_id: the Dag the task instance belongs to.
    :param task_id: the task within that Dag.
    :param run_id: the Dag run the task instance belongs to.
    :param map_index: the map index, ``-1`` for unmapped tasks.
    :param bundle_name: the Dag bundle of the Dag version the run is pinned to. Bundles are
        configured by the deployment manager, not the Dag author, which makes them the
        anchor a provider can grant identities to.
    :param jti: the caller token's JWT id when present, for audit correlation.
    """

    ti_id: str
    dag_id: str
    task_id: str
    run_id: str
    map_index: int
    bundle_name: str
    jti: str | None = None


class WorkloadIdentityToken(BaseModel):
    """
    A minted workload identity token for one task instance.

    ``expires_at`` must be timezone-aware; a naive value is rejected here, at the provider,
    rather than surfacing to the task as an unparsable server response.
    """

    token: str
    subject: str
    issuer: str
    audience: str | None = None
    expires_at: AwareDatetime


class WorkloadIdentityDenied(Exception):
    """Raised by a provider when the caller may not have the requested identity or audience."""


class WorkloadIdentityProvider(abc.ABC):
    """
    Mint a workload identity token for a task instance.

    The provider is the sole authority over what a caller may receive. The Execution API
    forwards ``audience`` from the task unchecked, so a provider must decide for itself
    whether the identity it maps the caller to is allowed that audience, and raise
    :class:`WorkloadIdentityDenied` when it is not. A deny is returned to the task as a
    403 and the task-side helper raises; there is no fallback to another identity.
    """

    @abc.abstractmethod
    def issue(self, caller: WorkloadCallerIdentity, audience: str | None) -> WorkloadIdentityToken:
        """
        Return a token for ``caller``, scoped to ``audience`` when one was requested.

        Raise :class:`WorkloadIdentityDenied` when ``caller`` is not mapped to an identity, or
        the identity is not allowed ``audience``. Never substitute a different identity.
        """


@functools.cache
def get_workload_identity_provider() -> WorkloadIdentityProvider | None:
    """Return the configured provider, or ``None`` when no workload identity is available."""
    provider_cls = conf.getimport("execution_api", "workload_identity_provider", fallback=None)
    if provider_cls is None:
        return None
    return provider_cls()
