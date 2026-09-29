 .. Licensed to the Apache Software Foundation (ASF) under one
    or more contributor license agreements.  See the NOTICE file
    distributed with this work for additional information
    regarding copyright ownership.  The ASF licenses this file
    to you under the Apache License, Version 2.0 (the
    "License"); you may not use this file except in compliance
    with the License.  You may obtain a copy of the License at

 ..   http://www.apache.org/licenses/LICENSE-2.0

 .. Unless required by applicable law or agreed to in writing,
    software distributed under the License is distributed on an
    "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
    KIND, either express or implied.  See the License for the
    specific language governing permissions and limitations
    under the License.

.. _security/workload_identity:

Workload identity
=================

A task that talks to Snowflake, a cloud API or a secrets manager usually authenticates with a
long-lived secret stored in a Connection. Systems that support workload identity federation can
instead trust a short-lived signed token that says *who is calling*, and grant access to that
identity with no stored secret at all. Cloud workload identity does this for the whole worker:
every task on the pod is the same principal. Airflow's workload identity does it per task.

Airflow does not sign these tokens. It cannot: the task's own Execution API token has a per-run
UUID as its subject and an internal issuer, so nothing outside the deployment can trust it, and
the decision of which external identity a task may act as belongs to whoever runs the platform.
What Airflow provides is the contract around that decision:

- The Execution API verifies the task's token and resolves, from its own database, where the
  task comes from: Dag, task, run, map index and the Dag bundle its Dag version is pinned to.
- It passes that provenance to a **workload identity provider** the deployment manager
  configures. The provider maps it to an external identity, decides whether the requested
  audience is allowed, mints and signs the token, and publishes the keys a relying party uses
  to verify it.
- Task code asks for the token with :func:`airflow.sdk.get_workload_identity` or its async
  counterpart :func:`airflow.sdk.aget_workload_identity`. A refusal is a hard error; nothing
  falls back to a stored credential.

With no provider configured the endpoint answers ``501`` and Airflow behaves as before.

Configuring a provider
----------------------

Point ``[execution_api] workload_identity_provider`` at a subclass of
:class:`~airflow.api_fastapi.execution_api.workload_identity.WorkloadIdentityProvider`. It is
instantiated once per API server worker process. ``[execution_api] workload_identity_timeout``
bounds how long a task waits on the provider; past it the task receives ``504``. The provider
call itself cannot be interrupted, so it keeps running until the issuer answers, and at most eight
calls may be in flight per API server process; beyond that the task receives ``503``. Give the
provider's own HTTP client a socket timeout below this value so a dead issuer does not hold those
slots.

.. code-block:: ini

    [execution_api]
    workload_identity_provider = my_platform.identity.VaultProvider
    workload_identity_timeout = 30

A provider implements one method. This example exchanges the caller's provenance for a token
from HashiCorp Vault's identity token backend, which serves its own OIDC discovery document and
JWKS, so any relying party that can trust Vault can trust the task:

.. code-block:: python

    from datetime import datetime, timedelta, timezone

    import hvac

    from airflow.api_fastapi.execution_api.workload_identity import (
        WorkloadCallerIdentity,
        WorkloadIdentityDenied,
        WorkloadIdentityProvider,
        WorkloadIdentityToken,
    )

    # Which Dag bundles may act as which identity. The bundle is the anchor because the
    # deployment manager controls it; Dag ids and task ids are set by Dag authors.
    GRANTS = {"finance": "sf_etl", "growth": "warehouse_reader"}
    ALLOWED_AUDIENCES = {"sf_etl": {"snowflakecomputing.com"}}
    # Vault serves the discovery document for this issuer at <issuer>/.well-known/openid-configuration.
    ISSUER = "https://vault.example.com/v1/identity/oidc"


    class VaultProvider(WorkloadIdentityProvider):
        def __init__(self):
            self.vault = hvac.Client()

        def issue(self, caller: WorkloadCallerIdentity, audience: str | None) -> WorkloadIdentityToken:
            identity = GRANTS.get(caller.bundle_name)
            if identity is None:
                raise WorkloadIdentityDenied(f"bundle {caller.bundle_name!r} is not mapped to an identity")
            if audience and audience not in ALLOWED_AUDIENCES.get(identity, ()):
                raise WorkloadIdentityDenied(f"{identity} may not be used for audience {audience}")
            # One Vault OIDC role per identity; the role fixes the ``sub`` and ``aud`` claims.
            issued = self.vault.secrets.identity.generate_signed_id_token(name=identity)["data"]
            return WorkloadIdentityToken(
                token=issued["token"],
                subject=identity,
                issuer=ISSUER,
                audience=audience,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=issued["ttl"]),
            )

Two rules matter more than the rest of the code. **Refuse rather than widen.** If the caller is
not mapped to an identity, or the identity is not allowed the audience, raise
:class:`~airflow.api_fastapi.execution_api.workload_identity.WorkloadIdentityDenied`. The task
receives a ``403`` with that message, and :func:`airflow.sdk.get_workload_identity` raises;
never substitute a broader identity. **The audience comes from the task.** The Execution API
forwards it unchecked because only the provider knows which audiences an identity may address,
so the provider must check it. A task that can request any audience for an identity can present
that identity to any relying party that trusts the issuer.

The provenance the provider sees is server-resolved and cannot be influenced from a Dag file.
Only a running task instance is resolved: a task token stays valid for a while after the task
ends, and a retry gives the next attempt a new id, so a token for a finished, queued or superseded
attempt is refused. A task instance with no pinned Dag version has no bundle, and is refused before
the provider is called rather than resolved with an empty bundle that a permissive rule would match.

Using the identity from a task
------------------------------

Call :func:`airflow.sdk.get_workload_identity` when a client library takes a token or a token
supplier, or when task code talks to a relying party without a hook:

.. code-block:: python

    from airflow.sdk import get_workload_identity, task


    @task
    def read_from_snowflake():
        import snowflake.connector

        identity = get_workload_identity(audience="snowflakecomputing.com")
        conn = snowflake.connector.connect(
            account="acme-prod",
            authenticator="WORKLOAD_IDENTITY",
            workload_identity_provider="OIDC",
            token=identity.token,
        )
        ...

The Snowflake hook reads the same ``token`` field from the connection extra when the extra sets
``workload_identity_provider``, so a platform whose secrets backend can obtain this token may
also place it in the Connection and leave the task unchanged. Airflow itself does not do that;
this page describes the direct call.

The call goes from the task process to its supervisor and from there to the Execution API with
the task's own token, so task code is never given an Execution API credential. The returned
:class:`airflow.sdk.WorkloadIdentity` keeps the token out of its ``repr`` and the token is
registered with the log masker in both processes, but it is a bearer credential: do not write it
to XCom, files or environment variables. Tokens expire, usually within minutes. Call the
function again rather than holding one across a long task.

What this does not cover
------------------------

- **Revocation of an issued token.** A token is valid until ``expires_at``. Revocation happens
  at the provider, which refuses the next request, and at the relying party. Keep lifetimes
  short.
- **Deferred operators.** Code running in the triggerer has no per-task token and the request is
  not available there. Fetch the identity in the task before deferring, or after resuming.
- **Cross-task isolation on a shared worker.** The token lives in the task process's memory.
  See :ref:`workload-isolation` for what protects that memory from sibling processes and what
  does not.

See also :doc:`/security/jwt_token_authentication` for the task's own Execution API token, which
this does not replace.
