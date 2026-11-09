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
Start each task try by forking it from a process prepared for that.

By the time tries start, the run's process runs the Execution API's thread and holds database connections. On
macOS the supervisor therefore starts each try as a new interpreter, because a child forked from a process that
runs threads can crash in the system's Objective-C frameworks, e.g. on a name lookup; importing the task runner
there takes seconds. So the run's process forks this server first, before it starts a thread, opens the
database or imports the Dag file. The server stays single-threaded and forks each try, on every platform: a try
starts in milliseconds, with the run's imports done and everything else fresh.
"""

from __future__ import annotations

import enum
import json
import os
import pkgutil
import select
import signal
import socket
import struct
import sys
import traceback
from contextlib import suppress
from typing import TYPE_CHECKING, NoReturn

import psutil

from airflow.sdk.execution_time.supervisor import (
    ProcessTracker,
    _fork_main,
    _import_task_runner_before_fork,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_INT = struct.Struct("!i")

# psutil reports an exit by a signal as a member of such an enum, which the supervisor names the signal from.
_NegativeSignal = enum.IntEnum("_NegativeSignal", {sig.name: -sig.value for sig in signal.Signals})  # type: ignore[misc]


class ForkServerError(RuntimeError):
    """The fork server is gone."""


class ForkServer:
    """
    The run process's handle on the fork server; it starts tries for the supervisor.

    The server runs one try at a time: it waits for each to end, to report its exit code.
    """

    def __init__(self, pid: int, control: socket.socket) -> None:
        self.pid = pid
        self._control = control

    @classmethod
    def start(cls) -> ForkServer | None:
        """Fork the server from this process, or return None if this process already runs other threads."""
        if psutil.Process().num_threads() > 1:
            return None
        _import_task_runner_before_fork()
        ours, theirs = socket.socketpair()
        pid = os.fork()
        if pid == 0:
            ours.close()
            _serve(theirs)
        theirs.close()
        # The server joins a group of its own too, but may not have run yet.
        with suppress(OSError):
            os.setpgid(pid, pid)
        return cls(pid, ours)

    def launch(
        self,
        target: Callable[[], None],
        requests: socket.socket,
        stdout: socket.socket,
        stderr: socket.socket,
        logs: socket.socket,
        *,
        new_process_group: bool,
    ) -> ProcessTracker:
        """Fork a try running ``target`` with these sockets; see ``ChildLauncher``."""
        request = {
            "target": f"{target.__module__}:{target.__qualname__}",
            "new_process_group": new_process_group,
        }
        status, theirs = socket.socketpair()
        try:
            with theirs:
                socket.send_fds(
                    self._control,
                    [json.dumps(request).encode()],
                    [requests.fileno(), stdout.fileno(), stderr.fileno(), logs.fileno(), theirs.fileno()],
                )
            pid = _read_int(status)
        except OSError:
            pid = None
        if pid is None:
            status.close()
            raise ForkServerError("The process that starts task tries has ended")
        return ForkedTry(pid, status)

    def close(self) -> None:
        """Let the server end, once the try it runs, if any, has ended."""
        self._control.close()


class ForkedTry(ProcessTracker):
    """A try the fork server started; the server, its parent, reports its exit code."""

    ProcessNotFound = ProcessLookupError
    TimeoutExpired = psutil.TimeoutExpired

    def __init__(self, pid: int, status: socket.socket) -> None:
        self._pid = pid
        self._status = status
        self._exit_code: int | None = None

    @property
    def pid(self) -> int:
        return self._pid

    def send_signal(self, s: signal.Signals) -> None:
        # The server reaps the try before it reports; from then on the pid can be another process's.
        if self._exit_code is not None or self._is_reported(0):
            raise ProcessLookupError(self._pid)
        os.kill(self._pid, s)

    def wait(self, timeout: float | None) -> int:
        if self._exit_code is None:
            if not self._is_reported(timeout):
                raise psutil.TimeoutExpired(timeout, self._pid)
            exit_code = _read_int(self._status)
            if exit_code is None:
                raise ForkServerError(f"The process that starts task tries ended while try {self._pid} ran")
            self._status.close()
            self._exit_code = _NegativeSignal(exit_code) if exit_code < 0 else exit_code
        return self._exit_code

    def _is_reported(self, timeout: float | None) -> bool:
        return bool(select.select([self._status], [], [], timeout)[0])


def _read_int(sock: socket.socket) -> int | None:
    data = sock.recv(_INT.size, socket.MSG_WAITALL)
    return _INT.unpack(data)[0] if len(data) == _INT.size else None


def _serve(control: socket.socket) -> NoReturn:
    """Fork a try for each request until the run process closes ``control``."""
    try:
        # The terminal's Ctrl-C is for the run's process, which stops the try that runs.
        with suppress(OSError):
            os.setpgid(0, 0)
        while True:
            message, fds, _, _ = socket.recv_fds(control, 4096, 5)
            if not message:
                os._exit(0)
            _fork_try(control, json.loads(message), fds)
    except BaseException:
        traceback.print_exc()
        os._exit(1)


def _fork_try(control: socket.socket, request: dict, fds: list[int]) -> None:
    requests_fd, stdout_fd, stderr_fd, logs_fd, status_fd = fds
    new_process_group = request["new_process_group"]
    pid = os.fork()
    if pid == 0:
        control.close()
        os.close(status_fd)
        _run_try(request["target"], requests_fd, stdout_fd, stderr_fd, logs_fd, new_process_group)
    # The supervisor sees the try's output end only once no other process holds these.
    for fd in (requests_fd, stdout_fd, stderr_fd):
        os.close(fd)
    if new_process_group:
        # As in the supervisor's own fork: the group exists before the supervisor can signal it.
        with suppress(OSError):
            os.setpgid(pid, pid)
    with socket.socket(fileno=status_fd) as status:
        with suppress(OSError):
            status.sendall(_INT.pack(pid))
        _, wait_status = os.waitpid(pid, 0)
        with suppress(OSError):
            status.sendall(_INT.pack(os.waitstatus_to_exitcode(wait_status)))
    # Closed only now: the end of the try's log wakes the supervisor, which must find the exit code reported.
    os.close(logs_fd)


def _run_try(
    target: str, requests_fd: int, stdout_fd: int, stderr_fd: int, logs_fd: int, new_process_group: bool
) -> NoReturn:
    try:
        if new_process_group:
            with suppress(OSError):
                os.setpgid(0, 0)
        _fork_main(
            socket.socket(fileno=requests_fd),
            socket.socket(fileno=stdout_fd),
            socket.socket(fileno=stderr_fd),
            logs_fd,
            pkgutil.resolve_name(target),
        )
    except BaseException:
        print("Exception in a try's process, exiting with code 124", file=sys.stderr)
        traceback.print_exc()
    # _fork_main ends the process itself; leaving this function would run the server's loop in the try.
    os._exit(124)
