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
"""islo.dev microVM backend for :class:`~airflow.providers.common.ai.toolsets.sandbox.SandboxToolset`."""

from __future__ import annotations

import base64
import binascii
import math
import shlex
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any

# The missing-``islo`` case is turned into AirflowOptionalProviderFeatureException by
# the package __init__'s lazy import, so import the SDK plainly here.
from islo import Islo
from islo.errors import NotFoundError

from airflow.providers.common.ai.sandbox.base import (
    SandboxBackend,
    SandboxError,
    SandboxExecResult,
    SandboxFileTooLargeError,
    SandboxTerminalError,
    _new_sandbox_name,
    _validate_positive_finite,
)
from airflow.providers.common.compat.sdk import BaseHook

if TYPE_CHECKING:
    from airflow.providers.common.ai.sandbox.base import SandboxSpec

_TERMINAL_EXEC_STATUSES = frozenset({"completed", "failed", "timeout"})
# Poll quickly at first so a fast command returns promptly, then back off. A flat
# 200ms interval would issue up to 1,500 API calls for a single five-minute command.
_POLL_INITIAL = 0.2
_POLL_MAX = 2.0
_POLL_BACKOFF = 1.5
_POLL_GRACE = 5.0
_FILE_OP_TIMEOUT = 120.0
# Helpers return a status or a listing, never bulk content, so a small cap bounds
# what a hostile guest can push into worker memory.
_HELPER_OUTPUT_CAP = 1024 * 1024


class IsloSandboxBackend(SandboxBackend):
    """
    Sandbox backend that runs agent commands in an `islo.dev <https://islo.dev>`__ microVM.

    Hardware-level isolation with no local Docker daemon, so unlike the ``sbx``
    backend this works from a worker running in a container. Credentials come from
    an Airflow connection, resolved lazily on first use, so the API key lives in
    the configured secrets backend rather than the worker environment.

    Connection fields: ``password`` is the islo API key (required), ``host`` the
    compute URL (optional), and the extra may set ``base_url`` and ``timeout``
    (request timeout in seconds).

    File operations go through the command channel using ``base64``, because the
    per-sandbox command API is the surface this adapter is verified against. The
    template image therefore needs ``base64``, ``stat`` and ``ls``.

    :param islo_conn_id: Airflow connection ID for islo. ``None`` lets the SDK
        resolve credentials from its own environment variables (``ISLO_API_KEY``).
    :param image: Sandbox image. ``None`` (default) uses the server default.
    :param vcpus: Number of virtual CPUs. ``None`` uses the server default.
    :param memory_mb: Memory in MB. ``None`` uses the server default.
    :param delete_after: Server-side TTL in seconds after which the sandbox is
        deleted even if the worker never got to destroy it, for example because it
        was killed mid-run. Default ``3600``.
    """

    name = "islo"

    def __init__(
        self,
        islo_conn_id: str | None = "islo_default",
        *,
        image: str | None = None,
        vcpus: int | None = None,
        memory_mb: int | None = None,
        delete_after: int = 3600,
    ) -> None:
        _validate_positive_finite(delete_after, "delete_after")
        if vcpus is not None:
            _validate_positive_finite(vcpus, "vcpus")
        if memory_mb is not None:
            _validate_positive_finite(memory_mb, "memory_mb")
        if image == "":
            raise ValueError("image must not be empty.")
        self._islo_conn_id = islo_conn_id
        self._image = image
        self._vcpus = vcpus
        self._memory_mb = memory_mb
        self._delete_after = delete_after
        self._client: Islo | None = None

    def _get_client(self) -> Islo:
        if self._client is not None:
            return self._client
        if self._islo_conn_id is None:
            self._client = Islo()
            return self._client
        conn = BaseHook.get_connection(self._islo_conn_id)
        api_key = (conn.password or "").strip()
        if not api_key:
            raise SandboxTerminalError(
                f"Connection {self._islo_conn_id!r} has no password; set it to the islo API key."
            )
        kwargs: dict[str, Any] = {"api_key": api_key}
        if conn.host:
            kwargs["compute_url"] = conn.host
        extra = conn.extra_dejson
        if extra.get("base_url"):
            kwargs["base_url"] = extra["base_url"]
        if extra.get("timeout") is not None:
            request_timeout = float(extra["timeout"])
            _validate_positive_finite(request_timeout, "connection extra timeout")
            kwargs["timeout"] = request_timeout
        self._client = Islo(**kwargs)
        return self._client

    def create(self, *, spec: SandboxSpec | None = None) -> str:
        from islo.types import LifecyclePolicy

        if spec is not None and spec.allow_egress_to:
            raise SandboxTerminalError(
                "The islo backend cannot apply a per-domain egress allowlist; it can only turn "
                "outbound access on or off. Drop allow_egress_to, or use a backend with "
                "per-domain network rules."
            )
        # Pass only the kwargs that were set; the SDK treats absent kwargs as "omit"
        # and the server fills in its defaults.
        kwargs: dict[str, Any] = {}
        if self._image is not None:
            kwargs["image"] = self._image
        if self._vcpus is not None:
            kwargs["vcpus"] = self._vcpus
        if self._memory_mb is not None:
            kwargs["memory_mb"] = self._memory_mb
        # No spec means the toolset's default, which blocks egress.
        kwargs["internet_enabled"] = False if spec is None else not spec.block_network
        if spec is not None and spec.env:
            # The API takes environment directly, so there is no need to write a
            # login profile and no half-provisioned sandbox to clean up if that
            # write were to fail.
            kwargs["env"] = dict(spec.env)
        sandbox = self._get_client().sandboxes.create_sandbox(
            name=_new_sandbox_name(),
            lifecycle=LifecyclePolicy(delete_after=self._delete_after),
            **kwargs,
        )
        # The server may normalize the name; the response is authoritative.
        return sandbox.name

    def _await_exec(
        self, sandbox: str, exec_id: str, *, deadline: float, max_output_bytes: int | None
    ) -> Any:
        """Poll one exec to a terminal state, backing off between attempts."""
        client = self._get_client()
        interval = _POLL_INITIAL
        while time.monotonic() < deadline:
            result = client.sandboxes.get_exec_result(sandbox, exec_id)
            if result.status in _TERMINAL_EXEC_STATUSES:
                return result
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
            interval = min(interval * _POLL_BACKOFF, _POLL_MAX)
        return None

    def run_command(
        self, sandbox: str, command: str, *, timeout: float, max_output_bytes: int
    ) -> SandboxExecResult:
        _validate_positive_finite(timeout, "timeout")
        client = self._get_client()
        # ``timeout_secs`` is only a client-side hint to the islo API, not
        # server-enforced, so the real bound is the poll deadline below: if no
        # terminal result arrives in time we delete the microVM ourselves.
        response = client.sandboxes.exec_in_sandbox(
            sandbox, command=["sh", "-lc", command], timeout_secs=max(1, math.ceil(timeout))
        )
        result = self._await_exec(
            sandbox,
            response.exec_id,
            deadline=time.monotonic() + timeout + _POLL_GRACE,
            max_output_bytes=max_output_bytes,
        )
        if result is None:
            # No terminal result within the deadline. Delete the microVM so the
            # command cannot continue in a sandbox later calls will reuse, then tell
            # the toolset to provision a fresh one. A transient delete failure must
            # not fail the task; the server-side TTL is the backstop.
            with suppress(Exception):
                self.destroy(sandbox)
            return SandboxExecResult(
                exit_code=-1, stdout="", stderr="", timed_out=True, sandbox_terminated=True
            )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        # Bound what reaches worker memory, mirroring the streaming cap the sbx
        # backend applies while draining.
        out_trunc = len(stdout) > max_output_bytes
        err_trunc = len(stderr) > max_output_bytes
        return SandboxExecResult(
            exit_code=result.exit_code if result.exit_code is not None else -1,
            stdout=stdout[:max_output_bytes],
            stderr=stderr[:max_output_bytes],
            timed_out=result.status == "timeout",
            stdout_truncated=out_trunc or bool(getattr(result, "truncated", False)),
            stderr_truncated=err_trunc,
        )

    def _file_helper(
        self, sandbox: str, script: str, *, max_output_bytes: int, stdin: bytes | None = None
    ) -> bytes:
        """
        Run a helper command, capping what it can return.

        Every byte here is guest-controlled, so the cap is not a nicety: a path
        like ``/dev/zero`` or a FIFO the agent made itself streams without end,
        and an uncapped read would exhaust worker memory.
        """
        client = self._get_client()
        if stdin is not None:
            # The exec API takes no stdin, so carry the payload in the command
            # itself, decoded by the shell.
            payload = base64.b64encode(stdin).decode()
            script = f"printf %s {shlex.quote(payload)} | base64 -d | {script}"
        response = client.sandboxes.exec_in_sandbox(
            sandbox, command=["sh", "-c", script], timeout_secs=math.ceil(_FILE_OP_TIMEOUT)
        )
        result = self._await_exec(
            sandbox,
            response.exec_id,
            deadline=time.monotonic() + _FILE_OP_TIMEOUT + _POLL_GRACE,
            max_output_bytes=None,
        )
        if result is None:
            raise SandboxError("The sandbox did not respond to a file operation in time.")
        if result.exit_code:
            raise SandboxError((result.stderr or "").strip() or "command failed")
        return (result.stdout or "")[:max_output_bytes].encode()

    def read_file(self, sandbox: str, path: str, *, max_bytes: int) -> bytes:
        quoted = shlex.quote(path)
        # One exec, with the cap enforced guest-side by `head -c`. Checking the
        # size in a separate call would be both a TOCTOU window and useless
        # against anything `stat` reports as zero-length -- character devices,
        # FIFOs, procfs -- which stream unboundedly when read.
        script = (
            f"stat -Lc %s -- {quoted} 2>/dev/null || echo 0; head -c {max_bytes + 1} -- {quoted} | base64"
        )
        raw = self._file_helper(sandbox, script, max_output_bytes=max_bytes * 2 + 4096)
        reported, _, encoded = raw.partition(b"\n")
        try:
            data = base64.b64decode(encoded, validate=False)
        except (binascii.Error, ValueError) as e:
            raise SandboxError(f"Could not decode {path!r} from the sandbox.") from e
        if len(data) > max_bytes:
            # `head` handed back the sentinel byte, so the file is over budget.
            # A streaming source reports 0, in which case the true size is
            # unknown but irrelevant.
            try:
                size = int(reported.strip())
            except ValueError:
                size = 0
            raise SandboxFileTooLargeError(path, max(size, len(data)), max_bytes)
        return data

    def write_file(self, sandbox: str, path: str, content: bytes) -> None:
        quoted = shlex.quote(path)
        self._file_helper(
            sandbox,
            f'(mkdir -p -- "$(dirname -- {quoted})" && cat > {quoted})',
            max_output_bytes=_HELPER_OUTPUT_CAP,
            stdin=content,
        )

    def list_directory(self, sandbox: str, path: str) -> list[tuple[str, bool]]:
        quoted = shlex.quote(path)
        # NUL-separated: a filename may legally contain a newline, and the agent
        # can create one itself, which a line-based listing would split into two
        # entries that neither it nor the model can then open.
        listing = self._file_helper(
            sandbox,
            f"find -- {quoted} -maxdepth 1 -mindepth 1 -printf '%y %f\\0'",
            max_output_bytes=_HELPER_OUTPUT_CAP,
        )
        entries: list[tuple[str, bool]] = []
        for record in listing.split(b"\0"):
            if not record:
                continue
            kind, _, raw_name = record.partition(b" ")
            name = raw_name.decode(errors="replace")
            if not name:
                continue
            # find's %y is a single type character: 'd' for a directory.
            entries.append((name, kind == b"d"))
        return entries

    def destroy(self, sandbox: str) -> None:
        # Already-gone is fine -- destroy is idempotent.
        with suppress(NotFoundError):
            self._get_client().sandboxes.delete_sandbox(sandbox_name=sandbox)
