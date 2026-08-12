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

import inspect

import pytest

from airflow.providers.common.ai.sandbox.base import (
    SandboxBackend,
    SandboxError,
    SandboxExecResult,
    SandboxFileTooLargeError,
    SandboxSpec,
    SandboxTerminalError,
    _new_sandbox_name,
    _validate_positive_finite,
)


class TestValidation:
    @pytest.mark.parametrize("bad", [0, -1, float("inf"), float("-inf"), float("nan")])
    def test_rejects_non_positive_or_non_finite(self, bad):
        with pytest.raises(ValueError, match="thing must be a positive finite number"):
            _validate_positive_finite(bad, "thing")

    @pytest.mark.parametrize("good", [1, 0.5, 3600])
    def test_accepts_positive_finite(self, good):
        _validate_positive_finite(good, "thing")


class TestSandboxName:
    def test_is_prefixed_for_operator_cleanup(self):
        assert _new_sandbox_name().startswith("airflow-sandbox-")

    def test_is_unique_per_call(self):
        assert len({_new_sandbox_name() for _ in range(100)}) == 100


class TestSandboxSpec:
    def test_defaults_deny_egress_and_inject_nothing(self):
        # The safe starting point: a sandbox that cannot phone home and carries
        # none of the worker's environment.
        spec = SandboxSpec()

        assert spec.block_network is True
        assert spec.env is None
        assert spec.allow_egress_to is None

    def test_is_frozen_so_a_backend_cannot_mutate_the_authors_intent(self):
        spec = SandboxSpec()

        with pytest.raises(AttributeError):
            spec.block_network = False  # type: ignore[misc]


class TestSandboxExecResult:
    def test_defaults_are_the_success_case(self):
        result = SandboxExecResult(exit_code=0, stdout="", stderr="")

        assert not result.timed_out
        assert not result.stdout_truncated
        assert not result.stderr_truncated
        assert not result.sandbox_terminated


class TestErrorHierarchy:
    def test_terminal_is_a_sandbox_error(self):
        # The toolset catches SandboxTerminalError first, so ordering matters.
        assert issubclass(SandboxTerminalError, SandboxError)

    def test_file_too_large_is_recoverable(self):
        assert issubclass(SandboxFileTooLargeError, SandboxError)
        assert not issubclass(SandboxFileTooLargeError, SandboxTerminalError)

    def test_file_too_large_carries_the_numbers_for_the_message(self):
        e = SandboxFileTooLargeError("/w/big", 100, 10)

        assert (e.path, e.size_bytes, e.max_bytes) == ("/w/big", 100, 10)
        assert "/w/big" in str(e)


class TestBackendContract:
    def test_cannot_be_instantiated_without_implementing_everything(self):
        with pytest.raises(TypeError):
            SandboxBackend()  # type: ignore[abstract]

    def test_operation_methods_are_named_after_their_tools(self):
        # The mapping from a model-facing tool to the backend call behind it is
        # deliberately literal; renaming one without the other breaks that.
        for name in ("run_command", "read_file", "write_file", "list_directory"):
            assert getattr(SandboxBackend, name).__isabstractmethod__

    def test_create_takes_the_spec_as_a_keyword_only_argument(self):
        sig = inspect.signature(SandboxBackend.create)

        assert sig.parameters["spec"].kind is inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["spec"].default is None
