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
Logging for a local run: a quiet terminal, and a full log file per task attempt.

A deployed task's supervisor writes the task log from the task process's output, and so does a local run's,
which forwards that output here as well. In debug mode tasks run in the run's own process, so while a task
runs its log events, log records and printed output are also written to its log file, the same as a
deployed task's log. Either way the terminal shows the task's own output, hook output, warnings and
errors, but not Airflow's progress lines; the runner prints a summary instead.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

import structlog

from airflow.sdk.log import logging_processors

if TYPE_CHECKING:
    from structlog.typing import EventDict, WrappedLogger

# Lowest level shown on the terminal, by logger-name prefix; the longest matching prefix wins.
CONSOLE_LEVELS = {
    "airflow": logging.WARNING,
    "airflow.task.hooks": logging.INFO,
    "task": logging.WARNING,
    "supervisor": logging.WARNING,
    "alembic": logging.WARNING,
    "sqlalchemy": logging.WARNING,
}

# Running in this process, but not part of a deployed task's log: the Execution API's server side and the
# local run loop.
NOT_TASK_LOGGERS = ("airflow.api_fastapi", "airflow.sdk.definitions.dag")

# Their errors are about importing the Dag file, which the run reports once, from the DagBag's import errors.
IMPORT_ERROR_LOGGERS = ("airflow.dag_processing.dagbag", "airflow.sdk.importers")

PRE_EXECUTE_GROUP = "::group::Pre Execute"

# What the task runner logs, with the exception, when a task attempt fails.
TASK_FAILED_EVENT = "Task failed with exception"

# What a supervised task printed, as its supervisor forwards it; shown as printed.
OUTPUT_LOGGERS = {"task.stdout": "stdout", "task.stderr": "stderr"}

# What the supervisor logs when a task's process ends without the task runner reporting a failure.
PROCESS_EXIT_EVENTS = ("Process exited abnormally", "Process terminated by signal")

_LEVELS = logging.getLevelNamesMapping()

# Writes the log file of the task that is running, if any.
_task_log: Any = None


@dataclass
class TaskAttempt:
    """What the terminal held back while a task attempt ran in this process."""

    # Shown only once it is known whether the task will retry.
    failure: BaseException | None = None


@dataclass(frozen=True)
class TaskFailure:
    """Why a task attempt failed, as the terminal shows it."""

    # One line, for an attempt that will be retried.
    summary: str
    # For the attempt that fails the task, e.g. a traceback.
    details: str

    @classmethod
    def from_exception(cls, error: BaseException) -> TaskFailure:
        return cls(
            summary="".join(traceback.format_exception_only(error)).strip(),
            details="".join(traceback.format_exception(error)).rstrip(),
        )


_attempt: TaskAttempt | None = None

# This run's startup lines (bundle loading, Dag file parsing). A worker logs its own startup inside each
# task's Pre Execute section; a local run parses once, so the same lines go into every task's section.
_startup_events: list[tuple[str, dict[str, Any]]] = []
_recording_startup = False


def configure_local_run_logging() -> None:
    """Route this process's log output: quiet on the terminal, complete in the running task's log file."""
    # Airflow's console loggers pick ``sys.stdout`` up when each one is created; pinned now, loggers first
    # used while a task's printed output is being copied cannot write through that copy into the file.
    factory = structlog.get_config()["logger_factory"]
    if getattr(factory, "io", sys.stdout) is None:
        factory.io = sys.stdout
    # Cached loggers hold this very list, so the router is inserted in place, ahead of the renderer.
    processors = structlog.get_config()["processors"]
    processors.insert(len(processors) - 1, _route_event)
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(_is_shown_on_console)
    root.addHandler(_CopyRecordsToTaskLog())


@contextmanager
def record_startup_events() -> Iterator[None]:
    """Keep the task-log lines emitted inside this block, for each task's Pre Execute section."""
    global _recording_startup
    _recording_startup = True
    try:
        yield
    finally:
        _recording_startup = False


@contextmanager
def capture_task_log(path: Path) -> Iterator[TaskAttempt]:
    """Write the running task's log to ``path`` as JSON lines, as a deployed task's supervisor does."""
    global _task_log, _attempt
    path.parent.mkdir(parents=True, exist_ok=True)
    *processors_to_json, write_json = logging_processors(json_output=True)
    with path.open("ab") as log_file:
        task_log = structlog.wrap_logger(
            structlog.BytesLogger(log_file),
            processors=[*processors_to_json, _rename_exception_for_ui, write_json],
        )
        stdout = _LineTee(sys.stdout, lambda line: task_log.info(line, logger="task.stdout"))
        stderr = _LineTee(sys.stderr, lambda line: task_log.error(line, logger="task.stderr"))
        _task_log = task_log
        _attempt = attempt = TaskAttempt()
        sys.stdout, sys.stderr = stdout, stderr  # type: ignore[assignment]
        try:
            yield attempt
        finally:
            sys.stdout, sys.stderr = stdout.stream, stderr.stream
            stdout.emit_pending()
            stderr.emit_pending()
            _task_log = None
            _attempt = None


def read_attempt_failure(path: Path) -> TaskFailure | None:
    """Return why the attempt whose supervisor wrote the log at ``path`` failed, if it says."""
    failure = None
    with suppress(OSError), path.open() as log_file:
        for line in log_file:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            message = str(event.get("event", ""))
            if message == TASK_FAILED_EVENT and event.get("error_detail"):
                stacks = event["error_detail"]
                failure = TaskFailure(
                    summary=_format_exception_only(stacks[0]), details=_format_stacks(stacks)
                )
            elif message.startswith(PROCESS_EXIT_EVENTS):
                detail = ", ".join(
                    f"{key}={event[key]}" for key in ("exit_code", "signal_name") if key in event
                )
                summary = f"{message} ({detail})" if detail else message
                failure = TaskFailure(summary=summary, details=summary)
    return failure


def _format_stacks(stacks: list[dict[str, Any]]) -> str:
    """
    Render a structured traceback the way Python prints the exception.

    The supervisor logs the raised exception first, then each exception it was raised from or while handling.
    """
    text = _format_stack(stacks[-1])
    for inner, outer in zip(reversed(stacks), reversed(stacks[:-1])):
        if inner.get("is_cause"):
            text += "\nThe above exception was the direct cause of the following exception:\n\n"
        else:
            text += "\nDuring handling of the above exception, another exception occurred:\n\n"
        text += _format_stack(outer)
    return text.rstrip()


def _format_stack(stack: dict[str, Any]) -> str:
    lines = []
    if frames := stack.get("frames"):
        lines.append("Traceback (most recent call last):")
        for frame in frames:
            lines.append(
                f'  File "{frame.get("filename")}", line {frame.get("lineno")}, in {frame.get("name")}'
            )
            if code := (frame.get("line") or "").strip():
                lines.append(f"    {code}")
    lines.append(_format_exception_only(stack))
    lines.extend(stack.get("exc_notes") or ())
    return "\n".join(lines) + "\n"


def _format_exception_only(stack: dict[str, Any]) -> str:
    value = stack.get("exc_value")
    return f"{stack.get('exc_type')}: {value}" if value else str(stack.get("exc_type"))


def _is_within(logger_name: str, prefix: str) -> bool:
    return logger_name == prefix or logger_name.startswith(f"{prefix}.")


def _console_level(logger_name: str) -> int:
    matches = [prefix for prefix in CONSOLE_LEVELS if _is_within(logger_name, prefix)]
    return CONSOLE_LEVELS[max(matches, key=len)] if matches else logging.NOTSET


def _is_on_console(logger_name: str, level: int) -> bool:
    if level >= logging.ERROR and any(_is_within(logger_name, prefix) for prefix in IMPORT_ERROR_LOGGERS):
        return False
    return level >= _console_level(logger_name)


def _belongs_in_task_log(logger_name: str) -> bool:
    return not any(_is_within(logger_name, prefix) for prefix in NOT_TASK_LOGGERS)


def _route_event(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    name = event_dict.get("logger") or ""
    if (stream := OUTPUT_LOGGERS.get(name)) is not None:
        print(event_dict.get("event", ""), file=getattr(sys, stream), flush=True)
        raise structlog.DropEvent
    if _belongs_in_task_log(name):
        _copy_to_task_log(method_name, event_dict)
    if name == "task" and event_dict.get("event") == TASK_FAILED_EVENT:
        # The runner reports the failure once it knows whether the task will retry.
        if _attempt is not None:
            _attempt.failure = _get_exception(event_dict.get("exc_info"))
        raise structlog.DropEvent
    if not _is_on_console(name, _LEVELS[str(event_dict.get("level", method_name)).upper()]):
        raise structlog.DropEvent
    return event_dict


def _get_exception(exc_info: Any) -> BaseException | None:
    if isinstance(exc_info, BaseException):
        return exc_info
    if isinstance(exc_info, tuple):
        return exc_info[1]
    return sys.exc_info()[1] if exc_info else None


def _copy_to_task_log(method_name: str, event_dict: Mapping[str, Any]) -> None:
    if _recording_startup:
        _startup_events.append((method_name, dict(event_dict)))
    if _task_log is None:
        return
    _write_to_task_log(method_name, event_dict)
    if event_dict.get("event") == PRE_EXECUTE_GROUP and event_dict.get("logger") == "task":
        for startup_method, startup_event in _startup_events:
            # The log reader orders lines by time, so a startup line keeps its place in the section only
            # with the time it is written here.
            _write_to_task_log(startup_method, {k: v for k, v in startup_event.items() if k != "timestamp"})


def _write_to_task_log(method_name: str, event_dict: Mapping[str, Any]) -> None:
    fields = dict(event_dict)
    event = fields.pop("event", "")
    getattr(_task_log, method_name, _task_log.info)(event, **fields)


def _is_shown_on_console(record: logging.LogRecord) -> bool:
    return _is_on_console(record.name, record.levelno)


def _rename_exception_for_ui(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Store a traceback as ``error_detail``, which the UI renders, as the task supervisor does."""
    if (exception := event_dict.pop("exception", None)) is not None:
        event_dict["error_detail"] = exception
    return event_dict


class _CopyRecordsToTaskLog(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if not _belongs_in_task_log(record.name):
            return
        event_dict: dict[str, Any] = {
            "event": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            event_dict["exc_info"] = record.exc_info
        _copy_to_task_log(record.levelname.lower(), event_dict)


class _LineTee:
    """Write through to ``stream`` and hand each complete line to ``emit``."""

    def __init__(self, stream: TextIO, emit: Callable[[str], None]) -> None:
        self.stream = stream
        self._emit = emit
        self._pending = ""

    def write(self, text: str) -> int:
        written = self.stream.write(text)
        *lines, self._pending = (self._pending + text).split("\n")
        for line in lines:
            self._emit(line)
        return written

    def emit_pending(self) -> None:
        if self._pending:
            self._emit(self._pending)
            self._pending = ""

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)
