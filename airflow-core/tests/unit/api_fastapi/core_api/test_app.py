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

import contextlib
import inspect
import os
import typing
from unittest import mock

import pytest
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.params import Depends as DependsClass
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from starlette.routing import Mount

from airflow.api_fastapi.app import create_app
from airflow.api_fastapi.core_api.app import (
    VITE_DEV_PORT_COOKIE,
    _parse_vite_dev_port,
    _resolve_vite_dev_origin,
    init_config,
    init_views,
)
from airflow.api_fastapi.core_api.routes.public import authenticated_router
from airflow.api_fastapi.core_api.routes.ui import ui_router
from airflow.api_fastapi.core_api.security import get_user

from tests_common.test_utils.config import conf_vars
from tests_common.test_utils.db import clear_db_jobs

pytestmark = pytest.mark.db_test


def _get_all_api_routes(app):
    """Recursively yield all APIRoutes from the app and its mounted sub-apps."""
    for route in getattr(app, "routes", []):
        if isinstance(route, Mount) and hasattr(route, "app"):
            yield from _get_all_api_routes(route.app)
        if hasattr(route, "endpoint"):
            yield route


class TestStreamingEndpointSessionScope:
    def test_no_streaming_endpoint_uses_function_scoped_depends(self):
        """Streaming endpoints must not use function-scoped generator dependencies.

        FastAPI's ``function_stack`` (used for ``scope="function"`` dependencies)
        is torn down after the route handler returns but *before* the response body
        is sent.  For ``StreamingResponse`` endpoints the response body is produced
        by a generator that runs during sending, so any generator dependency with
        ``scope="function"`` will have its cleanup run before the generator
        executes.  This causes the generator to silently reopen the session via
        autobegin, and the resulting connection is never returned to the pool.
        """
        # These endpoints mention StreamingResponse but only use the session
        # *before* streaming begins — the generator does not capture it.
        # Function scope is correct for them: close the session early rather
        # than hold it open for the entire (potentially long) stream.
        allowed = {
            "airflow.api_fastapi.core_api.routes.public.log.get_log",
            "airflow.api_fastapi.core_api.routes.public.dag_run.wait_dag_run_until_finished",
        }

        app = create_app()
        violations = []
        for route in _get_all_api_routes(app):
            try:
                hints = typing.get_type_hints(route.endpoint, include_extras=True)
            except Exception:
                continue
            returns_streaming = hints.get("return") is StreamingResponse
            if not returns_streaming:
                with contextlib.suppress(OSError, TypeError):
                    returns_streaming = "StreamingResponse" in inspect.getsource(route.endpoint)
            if not returns_streaming:
                continue
            fqn = f"{route.endpoint.__module__}.{route.endpoint.__qualname__}"
            if fqn in allowed:
                continue
            for param_name, hint in hints.items():
                if param_name == "return":
                    continue
                if typing.get_origin(hint) is not typing.Annotated:
                    continue
                for metadata in typing.get_args(hint)[1:]:
                    if isinstance(metadata, DependsClass) and metadata.scope == "function":
                        violations.append(
                            f"{route.endpoint.__module__}.{route.endpoint.__qualname__}"
                            f" parameter '{param_name}'"
                        )

        assert not violations, (
            "Streaming endpoints must not use function-scoped dependencies like "
            "SessionDep — function-scoped cleanup runs before the response body "
            "is streamed, leaking database connections.\n"
            "Do NOT use Annotated[Session, Depends(_get_session)] or other session dependencies "
            "either, as this holds the DB connection open for the entire stream "
            "duration.\n"
            "Instead, use create_session() inside the generator to open/close a "
            "connection for each iteration, releasing it between yields.\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


class TestGzipMiddleware:
    @pytest.fixture(autouse=True)
    def setup(self):
        clear_db_jobs()
        yield
        clear_db_jobs()

    def test_gzip_middleware_should_not_be_chunked(self, test_client) -> None:
        response = test_client.get("/api/v2/monitor/health")
        headers = {k.lower(): v for k, v in response.headers.items()}

        # Ensure we do not reintroduce Transfer-Encoding: chunked
        assert "transfer-encoding" not in headers


class TestRouterLevelDefaultDeny:
    """
    Authentication is enforced as a router-level default on the routers that
    serve user-facing endpoints. A future route added under one of these
    routers cannot accidentally be added without an auth dependency — the
    router-level Depends(get_user) is the defense-in-depth backstop.
    """

    def test_authenticated_router_carries_get_user_dependency(self):
        assert any(
            getattr(dep, "dependency", None) is get_user for dep in authenticated_router.dependencies
        ), (
            "authenticated_router must declare Depends(get_user) at the router level so every "
            "route below /api/v2 (other than the explicit no-auth carve-outs in public_router) "
            "default-denies unauthenticated requests."
        )

    def test_ui_router_carries_get_user_dependency(self):
        assert any(getattr(dep, "dependency", None) is get_user for dep in ui_router.dependencies), (
            "ui_router must declare Depends(get_user) at the router level so every UI endpoint "
            "default-denies unauthenticated requests."
        )


class TestCorsMiddlewareConfig:
    def test_init_config_enables_credentialed_cors_for_explicit_origins(self):
        with conf_vars({("api", "access_control_allow_origins"): "https://example.com"}):
            app = FastAPI()
            init_config(app)

        cors_middlewares = [m for m in app.user_middleware if m.cls is CORSMiddleware]
        assert len(cors_middlewares) == 1
        assert cors_middlewares[0].kwargs["allow_credentials"] is True
        assert cors_middlewares[0].kwargs["allow_origins"] == ["https://example.com"]

    @pytest.mark.parametrize(
        "origins",
        ["*", "https://example.com,*", "*,https://example.com"],
    )
    def test_init_config_rejects_wildcard_origin(self, origins):
        """Wildcard origin is incompatible with credentialed CORS; reject it at startup.

        Browsers refuse any response that combines ``Access-Control-Allow-Origin: *`` with
        ``Access-Control-Allow-Credentials: true``, so silently accepting ``*`` would just ship
        a configuration where every cross-origin request fails. Fail loudly instead.
        """
        from airflow.exceptions import AirflowConfigException

        with conf_vars({("api", "access_control_allow_origins"): origins}):
            app = FastAPI()
            with pytest.raises(AirflowConfigException, match=r"must not contain `\*`"):
                init_config(app)


def _make_request(query: str = "", cookies: dict[str, str] | None = None) -> Request:
    headers = []
    if cookies:
        headers.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": query.encode(),
            "headers": headers,
        }
    )


class TestViteDevPortParsing:
    """
    The parsed port is interpolated into a ``<script src>`` in the dev shell, so anything that is
    not a plain unprivileged port number must be rejected rather than coerced.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            pytest.param("5273", 5273, id="port"),
            pytest.param("1024", 1024, id="lowest-allowed"),
            pytest.param("65535", 65535, id="highest-allowed"),
            pytest.param(None, None, id="absent"),
            pytest.param("", None, id="empty"),
            pytest.param("not-a-port", None, id="non-numeric"),
            pytest.param("80", None, id="privileged-port"),
            pytest.param("70000", None, id="above-range"),
            pytest.param("-1", None, id="negative"),
            pytest.param("http://evil.example.com", None, id="full-origin"),
            pytest.param('5273"></script><script>alert(1)</script>', None, id="markup-injection"),
        ],
    )
    def test_parse_vite_dev_port(self, raw, expected):
        assert _parse_vite_dev_port(raw) == expected


class TestViteDevOriginResolution:
    @pytest.mark.parametrize(
        ("query", "cookies", "env", "expected_origin", "expected_persist"),
        [
            pytest.param("", {}, {}, "http://localhost:5173", None, id="falls-back-to-floor-port"),
            pytest.param(
                "",
                {},
                {"VITE_DEV_PORT": "5174"},
                "http://localhost:5174",
                None,
                id="uses-port-breeze-started-on",
            ),
            pytest.param(
                "vite=5273",
                {},
                {"VITE_DEV_PORT": "5174"},
                "http://localhost:5273",
                5273,
                id="query-overrides-env-and-persists",
            ),
            pytest.param(
                "",
                {VITE_DEV_PORT_COOKIE: "5273"},
                {"VITE_DEV_PORT": "5174"},
                "http://localhost:5273",
                None,
                id="cookie-overrides-env-without-repersisting",
            ),
            pytest.param(
                "vite=5373",
                {VITE_DEV_PORT_COOKIE: "5273"},
                {},
                "http://localhost:5373",
                5373,
                id="query-overrides-cookie",
            ),
            pytest.param(
                "vite=notaport",
                {VITE_DEV_PORT_COOKIE: "5273"},
                {},
                "http://localhost:5273",
                None,
                id="invalid-query-falls-through-to-cookie",
            ),
            pytest.param(
                "vite=notaport",
                {},
                {"VITE_DEV_PORT": "garbage"},
                "http://localhost:5173",
                None,
                id="all-invalid-falls-back-to-floor-port",
            ),
        ],
    )
    def test_resolve_vite_dev_origin(self, query, cookies, env, expected_origin, expected_persist):
        with mock.patch.dict(os.environ, env, clear=False):
            if "VITE_DEV_PORT" not in env:
                os.environ.pop("VITE_DEV_PORT", None)
            origin, persist = _resolve_vite_dev_origin(_make_request(query, cookies))

        assert origin == expected_origin
        assert persist == expected_persist


class TestDevModeShell:
    """
    The dev shell is the only thing the api-server serves in dev mode — every line of the SPA comes
    from a host-side Vite dev server. Templating that server's port lets one breeze backend serve
    the UI from any number of worktrees, each running its own dev server.
    """

    @pytest.fixture
    def dev_mode_client(self):
        app = FastAPI()
        with mock.patch.dict(os.environ, {"DEV_MODE": "true"}):
            os.environ.pop("VITE_DEV_PORT", None)
            init_views(app)
            with TestClient(app) as client:
                yield client

    def test_requested_vite_port_is_rendered_and_persisted(self, dev_mode_client):
        response = dev_mode_client.get("/dags?vite=5273")

        assert 'src="http://localhost:5273/src/main.tsx"' in response.text
        assert dev_mode_client.cookies[VITE_DEV_PORT_COOKIE] == "5273"

    def test_persisted_port_survives_a_reload_without_the_query_parameter(self, dev_mode_client):
        dev_mode_client.get("/dags?vite=5273")

        # Client-side routing reloads the SPA from paths that carry no query string.
        response = dev_mode_client.get("/dags/some_dag/runs")

        assert 'src="http://localhost:5273/src/main.tsx"' in response.text

    def test_rejected_vite_port_is_neither_rendered_nor_persisted(self, dev_mode_client):
        response = dev_mode_client.get("/dags?vite=http://evil.example.com")

        assert "evil.example.com" not in response.text
        assert 'src="http://localhost:5173/src/main.tsx"' in response.text
        assert VITE_DEV_PORT_COOKIE not in dev_mode_client.cookies
