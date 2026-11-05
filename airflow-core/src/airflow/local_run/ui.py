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
Find the UI serving a project's history.

``airflow standalone --project`` records the address of the server it starts in ``.airflow/ui.json``.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from urllib.parse import quote, urlsplit

UI_FILE_NAME = "ui.json"

# Long enough for a loopback connection on a busy machine; a run waits this long when the server hangs.
CONNECT_TIMEOUT_SECONDS = 0.5


def get_ui_file(home: Path) -> Path:
    return home / UI_FILE_NAME


def write_ui_file(home: Path, url: str) -> None:
    path = get_ui_file(home)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"url": url, "pid": os.getpid()}))
    os.replace(tmp, path)


def remove_ui_file(home: Path) -> None:
    """Remove the record if this process wrote it; another server may have replaced it since."""
    if read_ui_record(home).get("pid") == os.getpid():
        get_ui_file(home).unlink(missing_ok=True)


def read_ui_record(home: Path) -> dict:
    try:
        record = json.loads(get_ui_file(home).read_text())
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def read_live_ui_url(home: Path) -> str | None:
    """
    Return the URL of the UI serving ``home``, or ``None`` when no recorded server is still serving.

    A server that was killed leaves its record behind, and its port may since serve something else, so both
    its process and its port are checked.
    """
    record = read_ui_record(home)
    url, pid = record.get("url"), record.get("pid")
    if not isinstance(url, str) or not isinstance(pid, int) or not is_process_alive(pid):
        return None
    address = urlsplit(url)
    try:
        with socket.create_connection((address.hostname, address.port), timeout=CONNECT_TIMEOUT_SECONDS):
            pass
    except (OSError, ValueError):
        return None
    return url


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    # The server runs as this user, so a process of another user's that has its pid is not the server.
    except (ProcessLookupError, PermissionError):
        return False
    return True


def build_run_url(ui_url: str, dag_id: str, run_id: str) -> str:
    """Return the UI page of a Dag run, e.g. ``http://127.0.0.1:8080/dags/example/runs/manual__...``."""
    # ``:`` and ``+`` are valid in a path and keep a run ID with a timestamp readable in a terminal.
    return f"{ui_url.rstrip('/')}/dags/{quote(dag_id, safe='')}/runs/{quote(run_id, safe=':+')}"
