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

import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("islo")

from islo.errors import NotFoundError

from airflow.providers.common.ai.sandbox.base import (
    SandboxError,
    SandboxFileTooLargeError,
    SandboxSpec,
    SandboxTerminalError,
)
from airflow.providers.common.ai.sandbox.islo import IsloSandboxBackend

_BASE_HOOK_PATH = "airflow.providers.common.ai.sandbox.islo.BaseHook"
_ISLO_PATH = "airflow.providers.common.ai.sandbox.islo.Islo"


def _connection(password="secret-key", host=None, extra=None):
    return SimpleNamespace(password=password, host=host, extra_dejson=extra or {})


def _exec_result(status="completed", exit_code=0, stdout="", stderr="", truncated=False):
    return SimpleNamespace(
        status=status, exit_code=exit_code, stdout=stdout, stderr=stderr, truncated=truncated
    )


def _backend_with_client(**kwargs) -> tuple[IsloSandboxBackend, MagicMock]:
    backend = IsloSandboxBackend(**kwargs)
    client = MagicMock(spec=["sandboxes"])
    client.sandboxes = MagicMock(
        spec=["create_sandbox", "exec_in_sandbox", "get_exec_result", "delete_sandbox"]
    )
    client.sandboxes.exec_in_sandbox.return_value = SimpleNamespace(exec_id="exec-1")
    client.sandboxes.create_sandbox.return_value = SimpleNamespace(name="box-1")
    client.sandboxes.get_exec_result.return_value = _exec_result()
    backend._client = client
    return backend, client


class TestCredentials:
    def test_api_key_comes_from_the_connection_not_the_environment(self):
        backend = IsloSandboxBackend(islo_conn_id="my_islo")

        with (
            patch(_BASE_HOOK_PATH, autospec=True) as hook,
            patch(_ISLO_PATH, autospec=True) as islo,
        ):
            hook.get_connection.return_value = _connection(password=" key ", host="https://compute")
            backend._get_client()

        hook.get_connection.assert_called_once_with("my_islo")
        assert islo.call_args.kwargs["api_key"] == "key"
        assert islo.call_args.kwargs["compute_url"] == "https://compute"

    def test_client_is_resolved_once_and_cached(self):
        backend = IsloSandboxBackend()

        with (
            patch(_BASE_HOOK_PATH, autospec=True) as hook,
            patch(_ISLO_PATH, autospec=True),
        ):
            hook.get_connection.return_value = _connection()
            backend._get_client()
            backend._get_client()

        assert hook.get_connection.call_count == 1

    def test_missing_api_key_is_terminal(self):
        backend = IsloSandboxBackend()

        with patch(_BASE_HOOK_PATH, autospec=True) as hook:
            hook.get_connection.return_value = _connection(password="")
            with pytest.raises(SandboxTerminalError, match="has no password"):
                backend._get_client()

    def test_none_conn_id_defers_to_the_sdk_environment(self):
        backend = IsloSandboxBackend(islo_conn_id=None)

        with patch(_ISLO_PATH, autospec=True) as islo:
            backend._get_client()

        islo.assert_called_once_with()


class TestSpecEnforcement:
    def test_refuses_a_per_domain_egress_allowlist(self):
        backend, _ = _backend_with_client()

        with pytest.raises(SandboxError, match="per-domain egress allowlist"):
            backend.create(spec=SandboxSpec(allow_egress_to=["example.com"]))

    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            (None, False),
            (SandboxSpec(), False),
            (SandboxSpec(block_network=True), False),
            (SandboxSpec(block_network=False), True),
        ],
    )
    def test_block_network_maps_to_internet_enabled(self, spec, expected):
        backend, client = _backend_with_client()

        backend.create(spec=spec)

        assert client.sandboxes.create_sandbox.call_args.kwargs["internet_enabled"] is expected

    def test_refusing_an_egress_allowlist_is_terminal_not_retryable(self):
        # A spec the backend cannot enforce is a configuration fact the model
        # cannot see and cannot fix by trying again.
        backend, _ = _backend_with_client()

        with pytest.raises(SandboxTerminalError):
            backend.create(spec=SandboxSpec(allow_egress_to=["example.com"]))

    def test_env_is_passed_at_creation_not_written_into_a_login_profile(self):
        # The API takes env directly, so there is no second call that could fail
        # and leave a half-provisioned sandbox behind.
        backend, client = _backend_with_client()

        backend.create(spec=SandboxSpec(env={"TOKEN": "s3cret"}))

        assert client.sandboxes.create_sandbox.call_args.kwargs["env"] == {"TOKEN": "s3cret"}
        client.sandboxes.exec_in_sandbox.assert_not_called()


class TestCreate:
    def test_uses_the_server_response_name_not_the_requested_one(self):
        backend, client = _backend_with_client()
        client.sandboxes.create_sandbox.return_value = SimpleNamespace(name="normalised")

        assert backend.create() == "normalised"

    def test_omitted_sizing_is_left_to_the_server(self):
        backend, client = _backend_with_client()

        backend.create()

        kwargs = client.sandboxes.create_sandbox.call_args.kwargs
        assert not {"image", "vcpus", "memory_mb"} & kwargs.keys()

    def test_ttl_is_set_so_an_abandoned_sandbox_is_still_reclaimed(self):
        backend, client = _backend_with_client(delete_after=120)

        backend.create()

        assert client.sandboxes.create_sandbox.call_args.kwargs["lifecycle"].delete_after == 120


class TestRunCommand:
    def test_polls_with_backoff_rather_than_a_flat_interval(self):
        backend, client = _backend_with_client()
        client.sandboxes.get_exec_result.side_effect = [
            _exec_result(status="running"),
            _exec_result(status="running"),
            _exec_result(status="running"),
            _exec_result(stdout="done"),
        ]
        slept: list[float] = []

        with patch("time.sleep", autospec=True, side_effect=slept.append):
            result = backend.run_command("box", "x", timeout=60, max_output_bytes=1024)

        assert result.stdout == "done"
        # Intervals grow; a flat poll would issue far more calls over a long command.
        assert slept == sorted(slept)
        assert slept[-1] > slept[0]

    def test_runs_through_a_login_shell(self):
        backend, client = _backend_with_client()

        backend.run_command("box", "echo hi", timeout=5, max_output_bytes=1024)

        assert client.sandboxes.exec_in_sandbox.call_args.kwargs["command"] == ["sh", "-lc", "echo hi"]

    def test_no_terminal_state_destroys_the_sandbox_and_asks_for_a_fresh_one(self):
        backend, client = _backend_with_client()
        client.sandboxes.get_exec_result.return_value = _exec_result(status="running")

        with patch("time.sleep", autospec=True):
            result = backend.run_command("box", "x", timeout=0.01, max_output_bytes=1024)

        assert result.timed_out
        assert result.sandbox_terminated
        client.sandboxes.delete_sandbox.assert_called_once_with(sandbox_name="box")

    def test_a_delete_failure_during_teardown_does_not_fail_the_call(self):
        backend, client = _backend_with_client()
        client.sandboxes.get_exec_result.return_value = _exec_result(status="running")
        client.sandboxes.delete_sandbox.side_effect = RuntimeError("api down")

        with patch("time.sleep", autospec=True):
            result = backend.run_command("box", "x", timeout=0.01, max_output_bytes=1024)

        assert result.timed_out
        assert result.sandbox_terminated

    def test_server_timeout_status_is_reported_as_a_timeout(self):
        backend, client = _backend_with_client()
        client.sandboxes.get_exec_result.return_value = _exec_result(status="timeout", exit_code=None)

        result = backend.run_command("box", "x", timeout=5, max_output_bytes=1024)

        assert result.timed_out
        assert result.exit_code == -1

    def test_output_is_capped_before_it_reaches_worker_memory(self):
        backend, client = _backend_with_client()
        client.sandboxes.get_exec_result.return_value = _exec_result(stdout="x" * 100)

        result = backend.run_command("box", "x", timeout=5, max_output_bytes=10)

        assert result.stdout == "x" * 10
        assert result.stdout_truncated


class TestFileOperations:
    """Every byte here is guest-controlled, so the cap must be applied guest-side."""

    def test_read_file_bounds_the_transfer_in_the_guest(self):
        backend, client = _backend_with_client()
        client.sandboxes.get_exec_result.return_value = _exec_result(
            stdout="5\n" + base64.b64encode(b"hello").decode()
        )

        backend.read_file("box", "/w/a", max_bytes=100)

        script = client.sandboxes.exec_in_sandbox.call_args.kwargs["command"][2]
        assert "head -c 101 --" in script

    def test_read_file_is_a_single_exec_so_there_is_no_toctou_window(self):
        backend, client = _backend_with_client()
        client.sandboxes.get_exec_result.return_value = _exec_result(
            stdout="5\n" + base64.b64encode(b"hello").decode()
        )

        backend.read_file("box", "/w/a", max_bytes=100)

        assert client.sandboxes.exec_in_sandbox.call_count == 1

    def test_oversized_file_is_refused_even_when_stat_reports_zero(self):
        # A character device or FIFO reports size 0; only the returned byte count
        # reveals that the file exceeded the budget.
        backend, client = _backend_with_client()
        client.sandboxes.get_exec_result.return_value = _exec_result(
            stdout="0\n" + base64.b64encode(b"x" * 11).decode()
        )

        with pytest.raises(SandboxFileTooLargeError):
            backend.read_file("box", "/dev/zero", max_bytes=10)

    def test_read_file_decodes_base64(self):
        backend, client = _backend_with_client()
        client.sandboxes.get_exec_result.return_value = _exec_result(
            stdout="5\n" + base64.b64encode(b"hello").decode()
        )

        assert backend.read_file("box", "/w/a", max_bytes=100) == b"hello"

    def test_write_file_carries_content_through_base64_not_raw_argv(self):
        backend, client = _backend_with_client()

        backend.write_file("box", "/w/a", b"data")

        script = client.sandboxes.exec_in_sandbox.call_args.kwargs["command"][2]
        assert base64.b64encode(b"data").decode() in script
        assert "base64 -d" in script

    def test_list_directory_marks_directories(self):
        backend, client = _backend_with_client()
        client.sandboxes.get_exec_result.return_value = _exec_result(stdout="f a.txt\0d sub\0")

        assert backend.list_directory("box", "/w") == [("a.txt", False), ("sub", True)]

    def test_list_directory_survives_a_filename_containing_a_newline(self):
        backend, client = _backend_with_client()
        client.sandboxes.get_exec_result.return_value = _exec_result(stdout="d new\nline\0f plain.txt\0")

        assert backend.list_directory("box", "/w") == [("new\nline", True), ("plain.txt", False)]

    def test_a_failing_helper_is_recoverable(self):
        backend, client = _backend_with_client()
        client.sandboxes.get_exec_result.return_value = _exec_result(exit_code=1, stderr="no such file")

        with pytest.raises(SandboxError, match="no such file"):
            backend.read_file("box", "/w/missing", max_bytes=100)


class TestDestroy:
    def test_is_idempotent_when_the_sandbox_is_already_gone(self):
        backend, client = _backend_with_client()
        client.sandboxes.delete_sandbox.side_effect = NotFoundError("gone")

        backend.destroy("box")  # must not raise
