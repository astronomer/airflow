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
import subprocess
from unittest.mock import patch

import pytest

from airflow.providers.common.ai.sandbox.base import (
    SandboxError,
    SandboxFileTooLargeError,
    SandboxSpec,
    SandboxTerminalError,
)
from airflow.providers.common.ai.sandbox.sbx import _KILL_AFTER, SbxSandboxBackend


def _completed(returncode=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def backend():
    return SbxSandboxBackend(host_network_policy="deny-all")


class TestInit:
    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"image": ""}, "image"),
            ({"memory": ""}, "memory"),
            ({"sbx_path": ""}, "sbx_path"),
            ({"cpus": 0}, "cpus"),
            ({"create_timeout": -1}, "create_timeout"),
            ({"host_network_policy": "nope"}, "host_network_policy"),
        ],
    )
    def test_rejects_invalid_configuration(self, kwargs, match):
        with pytest.raises(ValueError, match=match):
            SbxSandboxBackend(**kwargs)


class TestSpecEnforcement:
    """A backend must refuse a restriction it cannot actually apply."""

    def test_refuses_a_per_domain_egress_allowlist(self, backend):
        # sbx governs egress with a host-level policy, so a per-sandbox
        # allowlist would be silently ignored.
        with pytest.raises(SandboxError, match="per-sandbox egress allowlist"):
            backend.create(spec=SandboxSpec(allow_egress_to=["example.com"]))

    def test_refuses_no_egress_when_the_host_policy_is_undeclared(self):
        with pytest.raises(SandboxError, match="host policy has not been declared"):
            SbxSandboxBackend().create(spec=SandboxSpec(block_network=True))

    def test_refuses_no_egress_when_the_host_policy_allows_it(self):
        with pytest.raises(SandboxError, match="host policy has not been declared"):
            SbxSandboxBackend(host_network_policy="allow-all").create(spec=SandboxSpec())

    def test_accepts_an_acknowledged_open_network(self):
        undeclared = SbxSandboxBackend()
        with (
            patch("shutil.which", autospec=True, return_value="/usr/bin/sbx"),
            patch.object(undeclared, "_run_cli", autospec=True, return_value=_completed()),
        ):
            name = undeclared.create(spec=SandboxSpec(block_network=False))

        assert name.startswith("airflow-sandbox-")


class TestCreate:
    def test_missing_binary_is_terminal_and_says_why(self):
        with patch("shutil.which", autospec=True, return_value=None):
            with pytest.raises(SandboxTerminalError, match="was not found on PATH"):
                SbxSandboxBackend().create()

    def test_failed_create_cleans_up_the_partial_sandbox(self, backend):
        calls = []

        def fake_run_cli(args, *, timeout, stdin=None):
            calls.append(args)
            return _completed(returncode=1, stderr=b"nope")

        with (
            patch("shutil.which", autospec=True, return_value="/usr/bin/sbx"),
            patch.object(backend, "_run_cli", autospec=True, side_effect=fake_run_cli),
        ):
            with pytest.raises(SandboxTerminalError, match="sbx create' failed"):
                backend.create()

        assert calls[0][0] == "create"
        assert calls[1][:2] == ["rm", "-f"]

    def test_env_is_applied_through_the_login_profile(self, backend):
        seen = []

        with (
            patch("shutil.which", autospec=True, return_value="/usr/bin/sbx"),
            patch.object(backend, "_run_cli", autospec=True, return_value=_completed()),
            patch.object(
                backend,
                "_exec_capped_bytes",
                autospec=True,
                side_effect=lambda args, **kw: (
                    seen.append((args, kw.get("stdin"))) or (0, bytearray(), bytearray(), False, False)
                ),
            ),
        ):
            backend.create(spec=SandboxSpec(env={"TOKEN": "s3cret"}, block_network=True))

        profile_call = next(c for c in seen if "/etc/profile" in " ".join(c[0]))
        assert b"export TOKEN=s3cret" in profile_call[1]

    def test_env_values_are_shell_quoted(self, backend):
        seen = []

        with (
            patch("shutil.which", autospec=True, return_value="/usr/bin/sbx"),
            patch.object(backend, "_run_cli", autospec=True, return_value=_completed()),
            patch.object(
                backend,
                "_exec_capped_bytes",
                autospec=True,
                side_effect=lambda args, **kw: (
                    seen.append((args, kw.get("stdin"))) or (0, bytearray(), bytearray(), False, False)
                ),
            ),
        ):
            backend.create(spec=SandboxSpec(env={"X": "a b; rm -rf /"}))

        profile_call = next(c for c in seen if "/etc/profile" in " ".join(c[0]))
        assert b"'a b; rm -rf /'" in profile_call[1]

    def test_a_failed_env_application_does_not_orphan_the_microvm(self, backend):
        # sbx has no server-side TTL, so anything left behind here survives until
        # an operator notices it.
        calls = []

        def fake_run_cli(args, *, timeout, stdin=None):
            calls.append(args)
            return _completed()

        with (
            patch("shutil.which", autospec=True, return_value="/usr/bin/sbx"),
            patch.object(backend, "_run_cli", autospec=True, side_effect=fake_run_cli),
            patch.object(
                backend, "_exec_capped_bytes", autospec=True, side_effect=subprocess.TimeoutExpired("sbx", 1)
            ),
        ):
            with pytest.raises(subprocess.TimeoutExpired):
                backend.create(spec=SandboxSpec(env={"A": "1"}, block_network=True))

        assert calls[0][0] == "create"
        assert ["rm", "-f"] in [c[:2] for c in calls]
        assert backend._workspaces == {}

    def test_a_non_string_env_value_does_not_orphan_the_microvm(self, backend):
        # SandboxSpec.env is typed Mapping[str, str] but nothing validates it, and
        # shlex.quote raises TypeError on an int.
        calls = []

        def fake_run_cli(args, *, timeout, stdin=None):
            calls.append(args)
            return _completed()

        with (
            patch("shutil.which", autospec=True, return_value="/usr/bin/sbx"),
            patch.object(backend, "_run_cli", autospec=True, side_effect=fake_run_cli),
        ):
            with pytest.raises(TypeError):
                backend.create(spec=SandboxSpec(env={"PORT": 8080}, block_network=True))  # type: ignore[dict-item]

        assert ["rm", "-f"] in [c[:2] for c in calls]
        assert backend._workspaces == {}


class TestRunCommand:
    @pytest.mark.parametrize(
        ("returncode", "elapsed", "expected"),
        [
            (124, 0.0, True),  # SIGTERM path: timeout's own exit code
            (137, 100.0, True),  # SIGKILL escalation, after the kill-after point
            (137, 1.0, False),  # fast 137 is an OOM kill, not a timeout
            (0, 0.0, False),
            (1, 0.0, False),
        ],
    )
    def test_timeout_classification(self, backend, returncode, elapsed, expected):
        times = iter([0.0, elapsed])
        with (
            patch.object(
                backend, "_exec_capped", autospec=True, return_value=(returncode, "", "", False, False)
            ),
            patch("time.monotonic", autospec=True, side_effect=lambda: next(times)),
        ):
            result = backend.run_command("box", "x", timeout=10, max_output_bytes=1024)

        assert result.timed_out is expected

    def test_137_between_the_budget_and_the_kill_point_is_not_a_timeout(self, backend):
        # GNU timeout only escalates to SIGKILL at budget + --kill-after, so a
        # 137 arriving before that cannot be escalation.
        times = iter([0.0, 10 + _KILL_AFTER - 1])
        with (
            patch.object(backend, "_exec_capped", autospec=True, return_value=(137, "", "", False, False)),
            patch("time.monotonic", autospec=True, side_effect=lambda: next(times)),
        ):
            result = backend.run_command("box", "x", timeout=10, max_output_bytes=1024)

        assert result.timed_out is False

    def test_hung_cli_destroys_the_sandbox_and_asks_for_a_fresh_one(self, backend):
        with (
            patch.object(
                backend, "_exec_capped", autospec=True, side_effect=subprocess.TimeoutExpired("sbx", 1)
            ),
            patch.object(backend, "destroy", autospec=True) as destroy,
        ):
            result = backend.run_command("box", "x", timeout=1, max_output_bytes=1024)

        destroy.assert_called_once_with("box")
        assert result.timed_out
        assert result.sandbox_terminated

    def test_command_runs_through_a_login_shell_under_gnu_timeout(self, backend):
        with patch.object(
            SbxSandboxBackend, "_exec_capped", return_value=(0, "", "", False, False)
        ) as exec_capped:
            backend.run_command("box", "echo hi", timeout=5, max_output_bytes=1024)

        args = exec_capped.call_args[0][0]
        assert args[:3] == ["exec", "box", "timeout"]
        assert args[-3:] == ["sh", "-lc", "echo hi"]

    def test_per_stream_truncation_flags_are_carried_through(self, backend):
        with patch.object(SbxSandboxBackend, "_exec_capped", return_value=(0, "a", "b", True, False)):
            result = backend.run_command("box", "x", timeout=5, max_output_bytes=1024)

        assert result.stdout_truncated
        assert not result.stderr_truncated


class TestFileOperations:
    """Every byte here is guest-controlled, so the cap must be guest-side."""

    def test_read_file_bounds_the_transfer_in_the_guest(self, backend):
        # head -c is what stops /dev/zero, a FIFO, or anything else stat reports
        # as zero-length from streaming into worker memory.
        with patch.object(backend, "_file_helper", autospec=True, return_value=bytearray(b"5\n")) as helper:
            with patch("base64.b64decode", autospec=True, return_value=b"hello"):
                backend.read_file("box", "/w/a", max_bytes=100)

        script = helper.call_args[0][1]
        assert "head -c 101 --" in script
        assert helper.call_args.kwargs["max_output_bytes"] <= 100 * 2 + 4096

    def test_read_file_is_a_single_exec_so_there_is_no_toctou_window(self, backend):
        with patch.object(backend, "_file_helper", autospec=True, return_value=bytearray(b"5\n")) as helper:
            with patch("base64.b64decode", autospec=True, return_value=b"hello"):
                backend.read_file("box", "/w/a", max_bytes=100)

        assert helper.call_count == 1

    def test_oversized_file_is_refused_even_when_stat_reports_zero(self, backend):
        # A character device or FIFO reports size 0; only the returned byte count
        # reveals that the file exceeded the budget.
        payload = b"1\n" + base64.b64encode(b"x" * 11)
        with patch.object(backend, "_file_helper", autospec=True, return_value=bytearray(payload)):
            with pytest.raises(SandboxFileTooLargeError):
                backend.read_file("box", "/dev/zero", max_bytes=10)

    def test_read_file_decodes_base64(self, backend):
        payload = b"5\n" + base64.b64encode(b"hello")
        with patch.object(backend, "_file_helper", autospec=True, return_value=bytearray(payload)):
            assert backend.read_file("box", "/w/a", max_bytes=100) == b"hello"

    def test_write_file_sends_content_on_stdin_not_argv(self, backend):
        # Keeps a large file from blowing the command-line length limit.
        with patch.object(backend, "_file_helper", autospec=True, return_value=bytearray()) as helper:
            backend.write_file("box", "/w/a", b"data")

        assert helper.call_args.kwargs["stdin"] == base64.b64encode(b"data")

    def test_paths_are_shell_quoted(self, backend):
        with patch.object(backend, "_file_helper", autospec=True, return_value=bytearray()) as helper:
            backend.write_file("box", "/w/a b; rm -rf /", b"x")

        assert "'/w/a b; rm -rf /'" in helper.call_args[0][1]

    def test_list_directory_marks_directories(self, backend):
        listing = bytearray(b"f a.txt\0d sub\0")
        with patch.object(backend, "_file_helper", autospec=True, return_value=listing):
            assert backend.list_directory("box", "/w") == [("a.txt", False), ("sub", True)]

    def test_list_directory_survives_a_filename_containing_a_newline(self, backend):
        # A line-based listing would split this into two entries, neither of
        # which the model could then open. The agent can create such a name.
        listing = bytearray(b"d new\nline\0f plain.txt\0")
        with patch.object(backend, "_file_helper", autospec=True, return_value=listing):
            assert backend.list_directory("box", "/w") == [("new\nline", True), ("plain.txt", False)]

    def test_stdin_payloads_pass_the_interactive_flag(self, backend):
        # `sbx exec` mirrors `docker exec`, where -i keeps STDIN open even when it
        # is not attached. Piping through subprocess attaches it anyway, so this
        # guards the case where the worker itself has no stdin.
        with patch.object(
            backend,
            "_exec_capped_bytes",
            autospec=True,
            return_value=(0, bytearray(), bytearray(), False, False),
        ) as exec_capped:
            backend.write_file("box", "/w/a", b"data")

        assert exec_capped.call_args[0][0][:3] == ["exec", "-i", "box"]

    def test_no_payload_means_no_interactive_flag(self, backend):
        # Nothing to send, so keeping stdin open would only invite the CLI to
        # wait on input that never arrives.
        with patch.object(
            backend,
            "_exec_capped_bytes",
            autospec=True,
            return_value=(0, bytearray(b"f a.txt\0"), bytearray(), False, False),
        ) as exec_capped:
            backend.list_directory("box", "/w")

        assert exec_capped.call_args[0][0][:2] == ["exec", "box"]

    def test_file_helper_caps_what_the_guest_can_return(self, backend):
        with patch.object(
            backend,
            "_exec_capped_bytes",
            autospec=True,
            return_value=(0, bytearray(b"ok"), bytearray(), False, False),
        ) as exec_capped:
            backend._file_helper("box", "echo ok", max_output_bytes=123)

        assert exec_capped.call_args.kwargs["max_output_bytes"] == 123

    def test_helper_failure_is_recoverable_not_terminal(self, backend):
        with patch.object(
            backend,
            "_exec_capped_bytes",
            autospec=True,
            return_value=(1, bytearray(), bytearray(b"no such file"), False, False),
        ):
            with pytest.raises(SandboxError, match="no such file"):
                backend.read_file("box", "/w/missing", max_bytes=100)


class TestDestroy:
    def test_is_idempotent_when_the_sandbox_is_already_gone(self, backend):
        with patch.object(backend, "_run_cli", autospec=True, return_value=_completed(returncode=1)):
            backend.destroy("box")  # must not raise

    def test_removes_the_workspace_even_if_the_cli_times_out(self, backend, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        backend._workspaces["box"] = str(workspace)

        with patch.object(
            backend, "_run_cli", autospec=True, side_effect=subprocess.TimeoutExpired("sbx", 1)
        ):
            backend.destroy("box")

        assert not workspace.exists()
