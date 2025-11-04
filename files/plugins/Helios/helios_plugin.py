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

# Get the plugin base directory
plugin_dir = Path(__file__).parent

# Conditionally mount React app dist folders (only if they exist)
# This allows the plugin to load even if some apps haven't been built yet

environment_manager_directory = plugin_dir / "environment-manager" / "dist"
if environment_manager_directory.exists():
    app.mount(
        "/environment-manager",
        StaticFiles(directory=environment_manager_directory, html=True),
        name="environment_manager_static",
    )

alerts_directory = plugin_dir / "alerts" / "dist"
if alerts_directory.exists():
    app.mount(
        "/alerts",
        StaticFiles(directory=alerts_directory, html=True),
        name="alerts_static",
    )

astro_bar_directory = plugin_dir / "astro-bar" / "dist"
if astro_bar_directory.exists():
    app.mount(
        "/astro-bar",
        StaticFiles(directory=astro_bar_directory, html=True),
        name="astro_bar_static",
    )

# Build the list of React applications (only include apps that are built)
_react_apps = []

# Astro Bar - Dashboard Toolbar
if astro_bar_directory.exists():
    _react_apps.append({
        "name": "Astro Bar",
        "url_route": "astro-bar",
        "bundle_url": "http://localhost:28080/helios-plugin/astro-bar/main.umd.cjs",
        "destination": "dashboard",
    })

# Environment Manager - Navigation Item
if environment_manager_directory.exists():
    _react_apps.append({
        "name": "Environment Manager",
        "url_route": "environment-manager",
        "bundle_url": "http://localhost:28080/helios-plugin/environment-manager/main.umd.cjs",
        "destination": "nav",
    })

# Alerts - Dashboard Widget
if alerts_directory.exists():
    _react_apps.append({
        "name": "Alerts Dashboard",
        "url_route": "alerts",
        "bundle_url": "http://localhost:28080/helios-plugin/alerts/main.umd.cjs",
        "destination": "dashboard",
    })


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

    # Register React applications (only if their dist folders exist)
    react_apps = _react_apps
