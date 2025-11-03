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
Helios - Airflow React Plugin

This plugin serves the Helios React application and integrates it into the Airflow UI.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from airflow.plugins_manager import AirflowPlugin

# Ensure proper MIME types for JavaScript files
mimetypes.add_type("application/javascript", ".cjs")

# Create FastAPI app to serve static files
app = FastAPI()

# Mount the environment-manager React app's dist folder
environment_manager_directory = Path(__file__).parent / "environment-manager" / "dist"
app.mount(
    "/environment-manager",
    StaticFiles(directory=environment_manager_directory, html=True),
    name="environment_manager_static",
)

# Mount the alerts React app's dist folder
alerts_directory = Path(__file__).parent / "alerts" / "dist"
app.mount(
    "/alerts",
    StaticFiles(directory=alerts_directory, html=True),
    name="alerts_static",
)


class HeliosPlugin(AirflowPlugin):
    """Helios Airflow Plugin"""

    name = "Helios"

    # Serve static files
    fastapi_apps = [
        {
            "app": app,
            "url_prefix": "/helios-plugin",
            "name": "Helios Static Server",
        }
    ]

    # Register React applications
    react_apps = [
        {
            "name": "Environment Manager",
            "url_route": "environment-manager",
            "bundle_url": "http://localhost:28080/helios-plugin/environment-manager/main.umd.cjs",
            "destination": "nav",
        },
        {
            "name": "Alerts",
            "url_route": "alerts",
            "bundle_url": "http://localhost:28080/helios-plugin/alerts/main.umd.cjs",
            "destination": "nav",
        },
    ]
