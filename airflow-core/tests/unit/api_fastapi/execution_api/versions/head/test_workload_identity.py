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

import time
from datetime import datetime, timezone
from unittest import mock
from uuid import UUID

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError

from airflow.api_fastapi.execution_api.datamodels.token import TIClaims, TIToken
from airflow.api_fastapi.execution_api.routes import workload_identity as wi_route
from airflow.api_fastapi.execution_api.security import (
    CurrentTIToken,
    get_caller_identity_dep,
    require_auth,
    resolve_caller_identity,
)
from airflow.api_fastapi.execution_api.workload_identity import (
    WorkloadCallerIdentity,
    WorkloadIdentityDenied,
    WorkloadIdentityProvider,
    WorkloadIdentityToken,
    get_workload_identity_provider,
)
from airflow.models.dag_version import DagVersion
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.utils.state import TaskInstanceState

from tests_common.test_utils.config import conf_vars

pytestmark = pytest.mark.db_test

PROVIDER = "airflow.api_fastapi.execution_api.routes.workload_identity.get_workload_identity_provider"


class _StubProvider(WorkloadIdentityProvider):
    def __init__(self, *, deny_audience: str | None = None):
        self.deny_audience = deny_audience
        self.calls: list[tuple[WorkloadCallerIdentity, str | None]] = []

    def issue(self, caller, audience):
        self.calls.append((caller, audience))
        if self.deny_audience is not None and audience == self.deny_audience:
            raise WorkloadIdentityDenied(f"{caller.dag_id}.{caller.task_id} may not use {audience}")
        return WorkloadIdentityToken(
            token="signed.jwt.here",
            subject=f"{caller.dag_id}.{caller.task_id}",
            issuer="https://id.example/acme",
            audience=audience,
            expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )


@pytest.fixture
def stub_caller(exec_app):
    """Bypass the DB lookup: the shared ``client`` fixture authenticates as a TI that has no row."""

    async def caller_identity(token=CurrentTIToken) -> WorkloadCallerIdentity:
        return WorkloadCallerIdentity(
            ti_id=str(token.id),
            dag_id="test_dag",
            task_id="test_task",
            run_id="test",
            map_index=-1,
            bundle_name="test_bundle",
        )

    exec_app.dependency_overrides[get_caller_identity_dep] = caller_identity
    yield
    exec_app.dependency_overrides.pop(get_caller_identity_dep, None)


class TestWorkloadIdentityEndpoint:
    def test_501_when_no_provider_configured(self, client, stub_caller):
        with mock.patch(PROVIDER, autospec=True, return_value=None):
            response = client.get("/execution/workload-identity")

        assert response.status_code == 501
        assert response.json()["detail"]["reason"] == "not_configured"

    def test_provider_receives_server_resolved_caller_and_requested_audience(self, client, stub_caller):
        provider = _StubProvider()
        with mock.patch(PROVIDER, autospec=True, return_value=provider):
            response = client.get("/execution/workload-identity", params={"audience": "sts.amazonaws.com"})

        assert response.status_code == 200, response.json()
        assert response.json() == {
            "token": "signed.jwt.here",
            "subject": "test_dag.test_task",
            "issuer": "https://id.example/acme",
            "audience": "sts.amazonaws.com",
            "expires_at": "2030-01-01T00:00:00Z",
        }
        ((caller, audience),) = provider.calls
        assert caller.ti_id == "00000000-0000-0000-0000-000000000000"
        assert caller.bundle_name == "test_bundle"
        assert audience == "sts.amazonaws.com"

    def test_denied_audience_is_403_with_no_token_in_body(self, client, stub_caller):
        provider = _StubProvider(deny_audience="evil.example.com")
        with mock.patch(PROVIDER, autospec=True, return_value=provider):
            response = client.get("/execution/workload-identity", params={"audience": "evil.example.com"})

        assert response.status_code == 403
        assert response.json()["detail"] == {
            "reason": "access_denied",
            "message": "test_dag.test_task may not use evil.example.com",
        }

    def test_slow_provider_is_504_and_never_blocks_other_requests(self, client, stub_caller):
        class _SlowProvider(_StubProvider):
            def issue(self, caller, audience):
                time.sleep(0.5)
                return super().issue(caller, audience)

        with (
            conf_vars({("execution_api", "workload_identity_timeout"): "0.05"}),
            mock.patch(PROVIDER, autospec=True, return_value=_SlowProvider()),
        ):
            response = client.get("/execution/workload-identity")

        assert response.status_code == 504
        assert response.json()["detail"]["reason"] == "provider_timeout"

    def test_saturated_provider_pool_is_503_and_slot_is_released_by_the_thread(self, client, stub_caller):
        provider = _StubProvider()
        for _ in range(wi_route.MAX_INFLIGHT_PROVIDER_CALLS):
            wi_route._inflight.acquire(blocking=False)
        try:
            with mock.patch(PROVIDER, autospec=True, return_value=provider):
                response = client.get("/execution/workload-identity")
        finally:
            for _ in range(wi_route.MAX_INFLIGHT_PROVIDER_CALLS):
                wi_route._inflight.release()

        assert response.status_code == 503
        assert response.json()["detail"]["reason"] == "provider_busy"
        assert provider.calls == []

        # A completed call hands its slot back, so the pool is full again afterwards.
        with mock.patch(PROVIDER, autospec=True, return_value=provider):
            assert client.get("/execution/workload-identity").status_code == 200
        assert wi_route._inflight._value == wi_route.MAX_INFLIGHT_PROVIDER_CALLS

    def test_unknown_task_instance_is_403_before_provider_is_consulted(self, client):
        provider = _StubProvider()
        with mock.patch(PROVIDER, autospec=True, return_value=provider):
            response = client.get("/execution/workload-identity")

        assert response.status_code == 403
        assert response.json()["detail"]["reason"] == "unknown_caller"
        assert provider.calls == []

    def test_route_resolves_a_real_task_instance(self, client, exec_app, dag_maker, session):
        with dag_maker(dag_id="wi_route_dag", serialized=True, session=session):
            EmptyOperator(task_id="t")
        dr = dag_maker.create_dagrun()
        session.commit()
        ti = dr.task_instances[0]
        ti.state = TaskInstanceState.RUNNING
        session.commit()

        async def as_this_ti(request: Request):
            return TIToken(id=ti.id, claims=TIClaims(scope="execution"))

        exec_app.dependency_overrides[require_auth] = as_this_ti
        provider = _StubProvider()
        try:
            with mock.patch(PROVIDER, autospec=True, return_value=provider):
                response = client.get("/execution/workload-identity")
        finally:
            exec_app.dependency_overrides.pop(require_auth, None)

        assert response.status_code == 200, response.json()
        ((caller, _),) = provider.calls
        assert caller.dag_id == "wi_route_dag"
        assert caller.task_id == "t"
        assert caller.bundle_name == "dag_maker"


class TestResolveCallerIdentity:
    def test_resolves_provenance_and_bundle_from_pinned_dag_version(self, dag_maker, session):
        with dag_maker(dag_id="wi_dag", serialized=True, session=session):
            EmptyOperator(task_id="t")
        dr = dag_maker.create_dagrun()
        session.commit()
        ti = dr.task_instances[0]
        ti.state = TaskInstanceState.RUNNING
        session.commit()

        token = TIToken(id=ti.id, claims=TIClaims(scope="execution", jti="jti-123"))
        caller = resolve_caller_identity(token, session)

        assert caller == WorkloadCallerIdentity(
            ti_id=str(ti.id),
            dag_id="wi_dag",
            task_id="t",
            run_id=dr.run_id,
            map_index=-1,
            bundle_name="dag_maker",
            jti="jti-123",
        )

    def test_unknown_task_instance_is_403_not_404(self, session):
        """404 would be read by the SDK client as not found and fall through to other secrets sources."""
        token = TIToken(id=UUID("11111111-1111-1111-1111-111111111111"), claims=TIClaims(scope="execution"))

        with pytest.raises(HTTPException) as exc:
            resolve_caller_identity(token, session)

        assert exc.value.status_code == 403
        assert exc.value.detail["reason"] == "unknown_caller"

    @pytest.mark.parametrize(
        "state", [None, TaskInstanceState.QUEUED, TaskInstanceState.SUCCESS, TaskInstanceState.DEFERRED]
    )
    def test_task_instance_not_running_is_refused(self, dag_maker, session, state):
        """A task token outlives the task; the identity is only for the attempt that is running."""
        with dag_maker(dag_id="wi_not_running", serialized=True, session=session):
            EmptyOperator(task_id="t")
        dr = dag_maker.create_dagrun()
        ti = dr.task_instances[0]
        ti.state = state
        session.commit()

        with pytest.raises(HTTPException) as exc:
            resolve_caller_identity(TIToken(id=ti.id, claims=TIClaims(scope="execution")), session)

        assert exc.value.status_code == 403
        assert exc.value.detail["reason"] == "caller_not_running"

    def test_task_instance_without_pinned_dag_version_is_refused(self, dag_maker, session):
        """A task instance that is not pinned to any Dag version has no bundle to grant on."""
        with dag_maker(dag_id="wi_no_version", serialized=True, session=session):
            EmptyOperator(task_id="t")
        dr = dag_maker.create_dagrun()
        ti = dr.task_instances[0]
        ti.state = TaskInstanceState.RUNNING
        session.commit()
        ti.dag_version_id = None
        session.commit()

        with pytest.raises(HTTPException) as exc:
            resolve_caller_identity(TIToken(id=ti.id, claims=TIClaims(scope="execution")), session)

        assert exc.value.status_code == 403
        assert exc.value.detail == {
            "reason": "unknown_caller",
            "message": "Task instance for this token is not pinned to a Dag bundle",
        }

    def test_task_instance_without_pinned_bundle_is_refused(self, dag_maker, session):
        """An empty bundle must never resolve: a provider rule with a wildcard bundle would match it."""
        with dag_maker(dag_id="wi_unpinned", serialized=True, session=session):
            EmptyOperator(task_id="t")
        dr = dag_maker.create_dagrun()
        ti = dr.task_instances[0]
        ti.state = TaskInstanceState.RUNNING
        session.commit()
        session.get(DagVersion, ti.dag_version_id).bundle_name = None
        session.commit()

        with pytest.raises(HTTPException) as exc:
            resolve_caller_identity(TIToken(id=ti.id, claims=TIClaims(scope="execution")), session)

        assert exc.value.status_code == 403
        assert exc.value.detail == {
            "reason": "unknown_caller",
            "message": "Task instance for this token is not pinned to a Dag bundle",
        }


class TestWorkloadIdentityToken:
    def test_naive_expiry_is_rejected_at_the_provider(self):
        with pytest.raises(ValidationError, match="timezone"):
            WorkloadIdentityToken(token="t", subject="s", issuer="i", expires_at=datetime(2030, 1, 1))


class TestProviderLoading:
    def setup_method(self):
        get_workload_identity_provider.cache_clear()

    def teardown_method(self):
        get_workload_identity_provider.cache_clear()

    def test_unset_means_no_provider(self):
        with conf_vars({("execution_api", "workload_identity_provider"): ""}):
            assert get_workload_identity_provider() is None

    def test_dotted_path_is_instantiated_once(self):
        path = f"{__name__}._StubProvider"
        with conf_vars({("execution_api", "workload_identity_provider"): path}):
            first = get_workload_identity_provider()
            second = get_workload_identity_provider()

        assert isinstance(first, _StubProvider)
        assert first is second
