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
import os
import warnings
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from airflow.api_fastapi.auth.tokens import get_signing_key
from airflow.exceptions import AirflowConfigException, AirflowException

log = logging.getLogger(__name__)

_AIRFLOW_PATH = Path(__file__).parents[3]

DEFAULT_VITE_DEV_PORT = 5173
VITE_DEV_PORT_COOKIE = "airflow_vite_dev_port"


def _parse_vite_dev_port(raw: str | None) -> int | None:
    """
    Parse a Vite dev server port, returning ``None`` when it is absent or unusable.

    Only a port number is accepted — never a full origin — because the result is interpolated
    into ``<script src>`` in the dev shell. Restricting the input to an integer in the
    unprivileged range means a caller cannot steer the shell at an arbitrary host or smuggle
    markup into the page.
    """
    if raw is None:
        return None
    try:
        port = int(raw)
    except ValueError:
        return None
    return port if 1024 <= port <= 65535 else None


def _resolve_vite_dev_origin(request: Request) -> tuple[str, int | None]:
    """
    Resolve the Vite dev server the shell should load the SPA from.

    Precedence is ``?vite=<port>`` (an explicit switch), then the cookie set by a previous
    switch, then the port breeze started its own dev server on, then the floor port. The query
    parameter exists so several worktrees can serve one breeze backend: each is a dev server on
    its own port, and the browser picks which one it is looking at.

    Returns the origin along with the port to persist as a cookie, or ``None`` when nothing
    needs persisting.
    """
    from_query = _parse_vite_dev_port(request.query_params.get("vite"))
    port = (
        from_query
        or _parse_vite_dev_port(request.cookies.get(VITE_DEV_PORT_COOKIE))
        or _parse_vite_dev_port(os.environ.get("VITE_DEV_PORT"))
        or DEFAULT_VITE_DEV_PORT
    )
    return f"http://localhost:{port}", from_query


def init_views(app: FastAPI) -> None:
    """Init views by registering the different routers."""
    from airflow.api_fastapi.core_api.routes.public import public_router
    from airflow.api_fastapi.core_api.routes.ui import ui_router

    app.include_router(ui_router)
    app.include_router(public_router)

    dev_mode = os.environ.get("DEV_MODE", str(False)) == "true"

    directory = _AIRFLOW_PATH / ("airflow/ui/dev" if dev_mode else "airflow/ui/dist")

    # During python tests or when the backend is run without having the frontend build
    # those directories might not exist. App should not fail initializing in those scenarios.
    Path(directory).mkdir(exist_ok=True)

    templates = Jinja2Templates(directory=directory)

    if dev_mode:
        app.mount(
            "/static/i18n/locales",
            StaticFiles(directory=_AIRFLOW_PATH / "airflow/ui/public/i18n/locales"),
            name="dev_i18n_static",
        )

    app.mount(
        "/static",
        StaticFiles(
            directory=directory,
            html=True,
        ),
        name="webapp_static_folder",
    )

    @app.get("/health", include_in_schema=False)
    def old_health():
        # If someone has the `/health` endpoint from Airflow 2 set up, we want this to be a 404, not serve the
        # default index.html for the SPA.
        #
        # This is a 404, not a redirect, as setups need correcting to account for this, and a redirect might
        # hide the issue
        return JSONResponse(
            status_code=404,
            content={"error": "Moved in Airflow 3. Please change config to check `/api/v2/monitor/health`"},
        )

    @app.get("/api/v1/{_:path}", include_in_schema=False)
    def old_api(_):
        return JSONResponse(
            status_code=404,
            content={
                "error": "/api/v1 has been removed in Airflow 3, please use its upgraded version /api/v2 instead."
            },
        )

    @app.get("/api/{_:path}", include_in_schema=False)
    def api_not_found(_):
        """Catch all route to handle invalid API endpoints."""
        return JSONResponse(status_code=404, content={"error": "API route not found"})

    @app.get("/{rest_of_path:path}", response_class=HTMLResponse, include_in_schema=False)
    def webapp(request: Request, rest_of_path: str):
        context = {"backend_server_base_url": request.base_url.path}
        port_to_persist = None
        if dev_mode:
            context["vite_dev_origin"], port_to_persist = _resolve_vite_dev_origin(request)

        response = templates.TemplateResponse(
            request,
            "/index.html",
            context,
            media_type="text/html",
        )
        if port_to_persist is not None:
            # Client-side routing means the SPA is reloaded from paths that carry no query
            # string, so the choice has to outlive the URL that made it.
            response.set_cookie(VITE_DEV_PORT_COOKIE, str(port_to_persist), samesite="lax")
        return response


def init_flask_plugins(app: FastAPI) -> None:
    """Integrate Flask plugins (plugins from Airflow 2)."""
    from airflow import plugins_manager

    blueprints, appbuilder_views, appbuilder_menu_links = plugins_manager.get_flask_plugins()

    # If no Airflow 2.x plugin is in the environment, no need to go further
    if not blueprints and not appbuilder_views and not appbuilder_menu_links:
        return

    from fastapi.middleware.wsgi import WSGIMiddleware

    try:
        from airflow.providers.fab.www.app import create_app
    except ImportError:
        raise AirflowException(
            "Some Airflow 2 plugins have been detected in your environment. "
            "To run them with Airflow 3, you must install the FAB provider in your Airflow environment."
        )

    warnings.warn(
        "You have a plugin that is using a FAB view or Flask Blueprint, which was used for the Airflow 2 UI,"
        "and is now deprecated. Please update your plugin to be compatible with the Airflow 3 UI.",
        DeprecationWarning,
        stacklevel=2,
    )

    flask_app = create_app(enable_plugins=True)
    app.mount("/pluginsv2", WSGIMiddleware(flask_app))


def init_config(app: FastAPI) -> None:
    from airflow.configuration import conf

    allow_origins = conf.getlist("api", "access_control_allow_origins")
    allow_methods = conf.getlist("api", "access_control_allow_methods")
    allow_headers = conf.getlist("api", "access_control_allow_headers")

    if "*" in allow_origins:
        # The CORS spec forbids combining `Access-Control-Allow-Origin: *` with
        # `Access-Control-Allow-Credentials: true`, and browsers reject any response that does so
        # (see https://fetch.spec.whatwg.org/#cors-protocol-and-credentials). Airflow's API needs
        # credentialed requests for cookie / Authorization-header auth, so a wildcard origin is
        # never a valid configuration. Fail loudly at startup instead of silently shipping a
        # response shape that no browser will accept.
        raise AirflowConfigException(
            "`[api] access_control_allow_origins` must not contain `*`: the wildcard origin is "
            "incompatible with the credentialed CORS Airflow's API requires, and browsers will "
            "reject every cross-origin response. List the exact origins that need access "
            "(e.g. `https://airflow.mycompany.com`) instead."
        )

    if allow_origins or allow_methods or allow_headers:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=True,
            allow_methods=allow_methods,
            allow_headers=allow_headers,
        )

    app.state.secret_key = get_signing_key("api", "secret_key")


def init_middlewares(app: FastAPI) -> None:
    from airflow.api_fastapi.app import get_auth_manager
    from airflow.api_fastapi.auth.middlewares.refresh_token import JWTRefreshMiddleware
    from airflow.api_fastapi.common.http_access_log import HttpAccessLogMiddleware

    app.add_middleware(JWTRefreshMiddleware)

    for middleware_cls, middleware_kwargs in get_auth_manager().get_fastapi_middlewares():
        app.add_middleware(middleware_cls, **middleware_kwargs)

    # GZipMiddleware must be inside HttpAccessLogMiddleware so that access logs capture
    # the full end-to-end duration including compression time.
    # See https://github.com/apache/airflow/issues/60165
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
    # HttpAccessLogMiddleware must be outermost (added last) so it times the full
    # request lifecycle including all inner middleware.
    app.add_middleware(HttpAccessLogMiddleware)
