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

from datetime import datetime, timezone
from unittest import mock

import httpx
import pytest

from airflow.sdk import WorkloadIdentity, aget_workload_identity, get_workload_identity
from airflow.sdk.api.client import Client, WorkloadIdentityOperations
from airflow.sdk.api.datamodels._generated import WorkloadIdentityResponse
from airflow.sdk.exceptions import AirflowRuntimeError, ErrorType
from airflow.sdk.execution_time.comms import ErrorResponse, GetWorkloadIdentity, WorkloadIdentityResult
from airflow.sdk.execution_time.request_handlers import handle_get_workload_identity

ISSUED = WorkloadIdentityResponse(
    token="header.payload.signature",
    subject="sf_etl",
    issuer="https://id.example/acme",
    audience="acme.snowflakecomputing.com",
    expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
)

EXPECTED = WorkloadIdentity(
    token="header.payload.signature",
    subject="sf_etl",
    issuer="https://id.example/acme",
    audience="acme.snowflakecomputing.com",
    expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
)


def _client(handler) -> Client:
    return Client(base_url="test://server", token="", transport=httpx.MockTransport(handler))


class TestWorkloadIdentityOperations:
    def test_get_passes_audience_and_parses_response(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=ISSUED.model_dump(mode="json"))

        result = _client(handler).workload_identity.get("acme.snowflakecomputing.com")

        assert isinstance(result, WorkloadIdentityResponse)
        assert result.token == "header.payload.signature"
        assert seen[0].url.path.endswith("/workload-identity")
        assert seen[0].url.params["audience"] == "acme.snowflakecomputing.com"

    def test_get_without_audience_sends_no_query(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "audience" not in request.url.params
            return httpx.Response(200, json=ISSUED.model_dump(mode="json"))

        assert isinstance(_client(handler).workload_identity.get(), WorkloadIdentityResponse)

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_denied_returns_permission_denied_with_server_message(self, status_code):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code, json={"detail": {"reason": "access_denied", "message": "not entitled"}}
            )

        result = _client(handler).workload_identity.get("evil.example.com")

        assert isinstance(result, ErrorResponse)
        assert result.error == ErrorType.PERMISSION_DENIED
        assert result.detail == {
            "audience": "evil.example.com",
            "status_code": status_code,
            "message": "not entitled",
        }

    @pytest.mark.parametrize(("status_code", "reason"), [(501, "not_configured"), (504, "provider_timeout")])
    def test_unavailable_is_returned_once_without_retry(self, status_code, reason):
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(status_code, json={"detail": {"reason": reason, "message": "no"}})

        result = _client(handler).workload_identity.get()

        assert calls == 1
        assert isinstance(result, ErrorResponse)
        assert result.error == ErrorType.API_SERVER_ERROR
        assert result.detail == {"audience": None, "status_code": status_code, "message": "no"}

    def test_other_server_errors_raise(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": {"message": "boom"}})

        with pytest.raises(httpx.HTTPStatusError):
            _client(handler).workload_identity.get()


class TestHandleGetWorkloadIdentity:
    def test_masks_token_and_returns_result(self):
        client = mock.create_autospec(Client, instance=True)
        ops = mock.create_autospec(WorkloadIdentityOperations, instance=True)
        ops.get.return_value = ISSUED
        type(client).workload_identity = mock.PropertyMock(return_value=ops)

        with mock.patch("airflow.sdk.execution_time.request_handlers.mask_secret", autospec=True) as mask:
            resp, dump_opts = handle_get_workload_identity(
                client, GetWorkloadIdentity(audience="acme.snowflakecomputing.com")
            )

        ops.get.assert_called_once_with("acme.snowflakecomputing.com")
        mask.assert_called_once_with("header.payload.signature")
        assert isinstance(resp, WorkloadIdentityResult)
        assert resp.subject == "sf_etl"
        assert resp.token == "header.payload.signature"
        assert dump_opts == {"exclude_unset": True}

    def test_error_response_passes_through(self):
        client = mock.create_autospec(Client, instance=True)
        ops = mock.create_autospec(WorkloadIdentityOperations, instance=True)
        error = ErrorResponse(error=ErrorType.PERMISSION_DENIED, detail={"audience": "evil.example.com"})
        ops.get.return_value = error
        type(client).workload_identity = mock.PropertyMock(return_value=ops)

        resp, dump_opts = handle_get_workload_identity(
            client, GetWorkloadIdentity(audience="evil.example.com")
        )

        assert resp is error
        assert dump_opts == {}


class TestGetWorkloadIdentity:
    def test_returns_identity_and_masks_token_in_the_task_process(self, mock_supervisor_comms):
        mock_supervisor_comms.send.return_value = WorkloadIdentityResult.from_response(ISSUED)

        with mock.patch("airflow.sdk.execution_time.context.mask_secret", autospec=True) as mask:
            result = get_workload_identity(audience="acme.snowflakecomputing.com")

        mock_supervisor_comms.send.assert_called_once_with(
            GetWorkloadIdentity(audience="acme.snowflakecomputing.com")
        )
        mask.assert_called_once_with("header.payload.signature")
        assert result == EXPECTED

    def test_token_is_not_in_repr(self, mock_supervisor_comms):
        mock_supervisor_comms.send.return_value = WorkloadIdentityResult.from_response(ISSUED)

        result = get_workload_identity()

        assert "header.payload.signature" not in repr(result)

    def test_denied_raises_permission_denied_after_a_single_request(self, mock_supervisor_comms):
        mock_supervisor_comms.send.return_value = ErrorResponse(
            error=ErrorType.PERMISSION_DENIED,
            detail={"audience": "evil.example.com", "status_code": 403, "message": "not entitled"},
        )

        with pytest.raises(AirflowRuntimeError, match="PERMISSION_DENIED.*not entitled"):
            get_workload_identity(audience="evil.example.com")

        mock_supervisor_comms.send.assert_called_once()

    def test_not_configured_raises_api_server_error(self, mock_supervisor_comms):
        mock_supervisor_comms.send.return_value = ErrorResponse(
            error=ErrorType.API_SERVER_ERROR, detail={"audience": None, "status_code": 501, "message": "no"}
        )

        with pytest.raises(AirflowRuntimeError, match="API_SERVER_ERROR"):
            get_workload_identity()

    @pytest.mark.asyncio
    async def test_async_twin_uses_asend_and_async_masking(self, mock_supervisor_comms):
        mock_supervisor_comms.asend.return_value = WorkloadIdentityResult.from_response(ISSUED)

        with mock.patch("airflow.sdk.execution_time.context.amask_secret", autospec=True) as amask:
            result = await aget_workload_identity(audience="acme.snowflakecomputing.com")

        mock_supervisor_comms.asend.assert_called_once_with(
            GetWorkloadIdentity(audience="acme.snowflakecomputing.com")
        )
        amask.assert_awaited_once_with("header.payload.signature")
        assert result == EXPECTED

    @pytest.mark.asyncio
    async def test_async_twin_denied_raises(self, mock_supervisor_comms):
        mock_supervisor_comms.asend.return_value = ErrorResponse(
            error=ErrorType.PERMISSION_DENIED, detail={"audience": "evil.example.com", "status_code": 403}
        )

        with pytest.raises(AirflowRuntimeError, match="PERMISSION_DENIED"):
            await aget_workload_identity(audience="evil.example.com")
