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

"""Supervise one task using SDK messages and local services."""

from __future__ import annotations

import os
import signal
import time
from contextlib import suppress
from typing import TYPE_CHECKING, ClassVar

import attrs
import psutil
from pydantic import TypeAdapter

from airflow.sdk.coordinators._subprocess import PopenTracker, _launch_runtime
from airflow.sdk.exceptions import AirflowSecretsBackendAccessDenied, ErrorType
from airflow.sdk.execution_time import comms
from airflow.sdk.execution_time.supervisor import WatchedSubprocess
from airflow.sdk.local_runtime.services import UnsupportedLocalOperation

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Self
    from uuid import UUID

    from structlog.typing import FilteringBoundLogger

    from airflow.sdk.local_runtime.services import LocalTaskServices


@attrs.define(kw_only=True)
class LocalTaskSupervisor(WatchedSubprocess):
    services: LocalTaskServices
    decoder: ClassVar = TypeAdapter(comms.ToSupervisor)
    terminal_state: str | None = attrs.field(default=None, init=False)
    failure: str | None = attrs.field(default=None, init=False)
    _deadline: float | None = attrs.field(default=None, init=False)
    _finished_at: float | None = attrs.field(default=None, init=False)
    _children: set[psutil.Process] = attrs.field(factory=set, init=False)
    # A runtime of another language may show only the type of an error it gets, so the reason is logged here.
    _log_request_errors: bool = False

    @classmethod
    def start_runtime(
        cls,
        *,
        id: UUID,
        command: Sequence[str],
        schema_version: str | None,
        startup_timeout: float,
        execution_timeout: float | None,
        services: LocalTaskServices,
        logger: FilteringBoundLogger,
    ) -> Self:
        """
        Start a task's runtime of another language, which connects back over TCP, as its coordinator does.

        Messages are translated to and from the runtime's ``schema_version``. The runtime may not send
        ``SetExecutionTimeout``, so ``execution_timeout`` starts the clock here; one it sends restarts it.

        :raises TaskLaunchError: when the runtime cannot start, or exits or times out before it connects.
        """
        with _launch_runtime(
            command,
            target_loggers=cls._default_target_loggers(logger, False),
            startup_timeout=startup_timeout,
        ) as runtime:
            process = cls(
                id=id,
                pid=runtime.process.pid,
                stdin=runtime.comm,
                process=PopenTracker(runtime.process),
                process_log=logger,
                subprocess_schema_version=schema_version,
                new_process_group=True,
                services=services,
                log_request_errors=True,
            )
            process._register_pipe_readers(
                runtime.stdout, runtime.stderr, runtime.comm, runtime.logs, data=runtime.drained
            )
            runtime.release()
        # Both connections are accepted, and nothing else may connect.
        cls._close_unused_sockets(runtime.comm_server, runtime.logs_server)
        if execution_timeout:
            process._deadline = time.monotonic() + execution_timeout
        return process

    def _handle_request(self, msg, log, req_id: int) -> None:
        try:
            match msg:
                case comms.SucceedTask():
                    self._remember_children()
                    if msg.task_outlets or msg.outlet_events:
                        raise UnsupportedLocalOperation("--no-db does not publish asset events")
                    self.terminal_state = "success"
                    self._finished_at = time.monotonic()
                    response = None
                case comms.TaskState():
                    self._remember_children()
                    self.terminal_state = msg.state.value
                    self._finished_at = time.monotonic()
                    response = None
                case comms.SetExecutionTimeout():
                    self._deadline = time.monotonic() + msg.timeout_seconds if msg.timeout_seconds else None
                    response = None
                case comms.DeferTask() | comms.RescheduleTask() | comms.AwaitInputTask() | comms.RetryTask():
                    self.terminal_state = "failed"
                    self._finished_at = time.monotonic()
                    raise UnsupportedLocalOperation(
                        f"{type(msg).__name__} is not supported by --no-db; run one synchronous task attempt"
                    )
                case _:
                    response = self.services.handle(msg)
            self.send_msg(response, request_id=req_id)
        except Exception as error:
            self.failure = str(error)
            if self._log_request_errors:
                self.process_log.warning(self.failure)
            error_type = (
                ErrorType.PERMISSION_DENIED
                if isinstance(error, AirflowSecretsBackendAccessDenied)
                else ErrorType.GENERIC_ERROR
            )
            self.send_msg(
                None,
                request_id=req_id,
                error=comms.ErrorResponse(error=error_type, detail={"message": str(error)}),
            )

    @property
    def final_state(self) -> str:
        if self._exit_code != 0 or self.terminal_state is None:
            return "failed"
        return self.terminal_state

    def wait(self) -> int:
        try:
            while self._exit_code is None or self._open_sockets:
                self._remember_children()
                self._service_subprocess(max_wait_time=0.1)
                now = time.monotonic()
                if self._exit_code is None and self._deadline is not None and now >= self._deadline:
                    self.failure = "Task execution timeout exceeded"
                    self.terminal_state = "failed"
                    self.kill(signal.SIGTERM, escalation_delay=1, force=True)
                if self._finished_at is not None and now - self._finished_at > 5 and self._exit_code is None:
                    self.failure = "Task process did not exit after reporting its outcome"
                    self.kill(signal.SIGTERM, escalation_delay=1, force=True)
                if self._process_exit_monotonic and now - self._process_exit_monotonic > 1:
                    self.cleanup_sockets_after_kill()
                    break
            return self._exit_code if self._exit_code is not None else 1
        finally:
            self._remember_children()
            if self._exit_code is None:
                self.kill(signal.SIGTERM, escalation_delay=1, force=True)
            with suppress(ProcessLookupError):
                os.killpg(self.pid, signal.SIGKILL)
            for child in self._children:
                with suppress(psutil.Error):
                    child.kill()
            psutil.wait_procs(self._children, timeout=1)
            self.cleanup_sockets_after_kill()
            self.selector.close()

    def _remember_children(self) -> None:
        with suppress(psutil.Error):
            self._children.update(psutil.Process(self.pid).children(recursive=True))
