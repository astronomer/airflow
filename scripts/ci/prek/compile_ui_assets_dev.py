#!/usr/bin/env python3
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

import os
import signal
import socket
import subprocess

from common_prek_utils import AIRFLOW_CORE_SOURCES_PATH, AIRFLOW_ROOT_PATH

# NOTE!. This script is executed from a node environment created by a prek hook, and this environment
# Cannot have additional Python dependencies installed. We should not import any of the libraries
# here that are not available in stdlib! You should not import common_prek_utils.py here because
# They are importing the rich library which is not available in the node environment.

if __name__ not in ("__main__", "__mp_main__"):
    raise SystemExit(
        "This file is intended to be executed as an executable program. You cannot use it as a module."
        f"To run this script, run the ./{__file__} command"
    )

UI_CACHE_DIR = AIRFLOW_ROOT_PATH / ".build" / "ui"


UI_DIRECTORY = AIRFLOW_CORE_SOURCES_PATH / "airflow" / "ui"
UI_HASH_FILE = UI_CACHE_DIR / "hash.txt"
UI_ASSET_OUT_FILE = UI_CACHE_DIR / "asset_compile.out"
UI_ASSET_OUT_DEV_MODE_FILE = UI_CACHE_DIR / "asset_compile_dev_mode.out"


SIMPLE_AUTH_MANAGER_UI_DIRECTORY = (
    AIRFLOW_CORE_SOURCES_PATH / "airflow" / "api_fastapi" / "auth" / "managers" / "simple" / "ui"
)
SIMPLE_AUTH_MANAGER_UI_HASH_FILE = UI_CACHE_DIR / "simple-auth-manager-hash.txt"
SIMPLE_AUTH_MANAGER_UI_ASSET_OUT_FILE = UI_CACHE_DIR / "simple_auth_manager_asset_compile.out"
SIMPLE_AUTH_MANAGER_UI_ASSET_OUT_DEV_MODE_FILE = (
    UI_CACHE_DIR / "simple_auth_manager_asset_compile_dev_mode.out"
)

# Sits one below the main UI's floor port. The main UI walks upward from 5173 to give every
# worktree its own dev server, so keeping the auth UI below that floor means an incrementing
# main UI can never take its port, however many worktrees are running.
SIMPLE_AUTH_MANAGER_VITE_DEV_PORT = 5172


def is_port_in_use(port: int) -> bool:
    # Every address family localhost resolves to is checked: a dev server bound only to ::1 still
    # stops another one binding localhost, so probing IPv4 alone would miss a running instance.
    for family, socket_type, proto, _, address in socket.getaddrinfo(
        "localhost", port, type=socket.SOCK_STREAM
    ):
        with socket.socket(family, socket_type, proto) as sock:
            if sock.connect_ex(address) == 0:
                return True
    return False


if __name__ == "__main__":
    UI_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["FORCE_COLOR"] = "true"

    if UI_HASH_FILE.exists():
        # cleanup hash of ui so that next compile-assets recompiles them
        UI_HASH_FILE.unlink()
    UI_ASSET_OUT_FILE.unlink(missing_ok=True)

    if SIMPLE_AUTH_MANAGER_UI_HASH_FILE.exists():
        # cleanup hash of ui so that next compile-assets recompiles them
        SIMPLE_AUTH_MANAGER_UI_HASH_FILE.unlink()
    SIMPLE_AUTH_MANAGER_UI_ASSET_OUT_FILE.unlink(missing_ok=True)

    with open(UI_ASSET_OUT_DEV_MODE_FILE, "w") as f:
        subprocess.run(
            ["pnpm", "install", "--frozen-lockfile", "--config.confirmModulesPurge=false"],
            cwd=os.fspath(UI_DIRECTORY),
            check=True,
            stdout=f,
            stderr=subprocess.STDOUT,
        )

    subprocess.Popen(
        ["pnpm", "dev"],
        cwd=os.fspath(UI_DIRECTORY),
        env=env,
        stdout=open(UI_ASSET_OUT_DEV_MODE_FILE, "a"),
        stderr=subprocess.STDOUT,
    )

    # The login page is the same for every worktree and only one instance can bind the port, so a
    # second breeze reuses the running one instead of fighting it and dying on --strictPort.
    if is_port_in_use(SIMPLE_AUTH_MANAGER_VITE_DEV_PORT):
        print(
            f"Simple auth manager UI already running on port {SIMPLE_AUTH_MANAGER_VITE_DEV_PORT} "
            f"- reusing it instead of starting another one."
        )
    else:
        with open(SIMPLE_AUTH_MANAGER_UI_ASSET_OUT_DEV_MODE_FILE, "w") as f:
            subprocess.run(
                ["pnpm", "install", "--frozen-lockfile", "--config.confirmModulesPurge=false"],
                cwd=os.fspath(SIMPLE_AUTH_MANAGER_UI_DIRECTORY),
                check=True,
                stdout=f,
                stderr=subprocess.STDOUT,
            )

        subprocess.Popen(
            ["pnpm", "dev"],
            cwd=os.fspath(SIMPLE_AUTH_MANAGER_UI_DIRECTORY),
            env=env,
            stdout=open(SIMPLE_AUTH_MANAGER_UI_ASSET_OUT_DEV_MODE_FILE, "a"),
            stderr=subprocess.STDOUT,
        )

    # Keep script alive so child processes stay in the same process group.
    # When breeze exits, kill_process_group() will terminate all processes together.
    signal.pause()
