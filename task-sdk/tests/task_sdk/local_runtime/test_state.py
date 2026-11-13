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

import json
from datetime import datetime
from unittest import mock

import pytest
import time_machine

from airflow.sdk.exceptions import LocalRunConfigError
from airflow.sdk.local_runtime.state import LocalStateStore

IDENTITY = {"source": "/project/agent.py", "dag_id": "example", "task_id": "agent"}


def make_store(path=None, *, resume=False, identity=None):
    return LocalStateStore(identity=identity or IDENTITY, run_id="local__test", path=path, resume=resume)


@time_machine.travel("2026-11-13T12:00:00Z", tick=False)
def test_expired_value_is_removed_from_checkpoint(tmp_path):
    path = tmp_path / "state.json"
    with make_store(path) as store:
        store.set("expired", 1, datetime.fromisoformat("2026-11-13T11:59:59+00:00"))
        store.set("live", 2, datetime.fromisoformat("2026-11-13T12:00:01+00:00"))
        store.set("forever", 3, None)
        assert store.get("expired") is None
        assert store.get("live")["value"] == 2
        assert store.get("forever")["value"] == 3
    assert "expired" not in json.loads(path.read_text())["values"]
    assert path.stat().st_mode & 0o777 == 0o600


def test_checkpoint_remains_usable_after_failed_execution(tmp_path):
    path = tmp_path / "state.json"

    def fail():
        with make_store(path) as store:
            store.set("job", "job-123", None)
            raise RuntimeError("task failed")

    with pytest.raises(RuntimeError, match="task failed"):
        fail()
    with make_store(path, resume=True) as store:
        assert store.get("job")["value"] == "job-123"
        store.clear()
    with make_store(path, resume=True) as store:
        assert store.get("job") is None


def test_checkpoint_has_one_writer(tmp_path):
    path = tmp_path / "state.json"
    with make_store(path), pytest.raises(LocalRunConfigError, match="already in use"), make_store(path):
        pass
    with make_store(path):
        pass


def test_resume_requires_existing_checkpoint(tmp_path):
    with (
        pytest.raises(LocalRunConfigError, match="No task state to resume"),
        make_store(tmp_path / "missing.json", resume=True),
    ):
        pass


@pytest.mark.parametrize("operation", ["set", "delete", "clear"])
def test_failed_checkpoint_write_preserves_memory_and_disk(tmp_path, operation):
    @mock.patch(
        "airflow.sdk.local_runtime.state.os.replace", autospec=True, side_effect=OSError("disk error")
    )
    def fail_write(store, mock_replace):
        arguments = {"set": ("value", "new", None), "delete": ("value",), "clear": ()}
        with pytest.raises(OSError, match="disk error"):
            getattr(store, operation)(*arguments[operation])

    path = tmp_path / "checkpoint.json"
    with make_store(path) as store:
        store.set("value", "original", None)
        before = path.read_bytes()
        fail_write(store)
        assert store.get("value")["value"] == "original"
        assert path.read_bytes() == before
        assert not list(tmp_path.glob(".checkpoint.json-*"))


@pytest.mark.parametrize(
    "data",
    [
        "invalid json",
        "{}",
        "[]",
        json.dumps({"version": 2, "identity": IDENTITY, "values": {}}),
        json.dumps({"version": 1, "identity": {**IDENTITY, "task_id": "other"}, "values": {}}),
        json.dumps({"version": 1, "identity": IDENTITY, "values": []}),
        json.dumps({"version": 1, "identity": IDENTITY, "values": {"key": {}}}),
        json.dumps(
            {"version": 1, "identity": IDENTITY, "values": {"key": {"value": 1, "expires_at": "invalid"}}}
        ),
        json.dumps(
            {"version": 1, "identity": IDENTITY, "values": {"key": {"value": 1, "expires_at": "2026-11-13"}}}
        ),
    ],
)
def test_invalid_checkpoint_is_not_overwritten(tmp_path, data):
    path = tmp_path / "state.json"
    path.write_text(data)
    with pytest.raises(LocalRunConfigError, match="Cannot read task state"), make_store(path):
        pass
    assert path.read_text() == data
