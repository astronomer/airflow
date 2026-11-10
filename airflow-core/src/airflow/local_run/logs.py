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

What a task prints goes to stdout and stderr as printed. Log events go to stderr, as Python's own logging
does, one short line each that names the task, so that stdout stays the script's.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

import structlog

import airflow
from airflow._shared.module_loading import UNUSUAL_MODULE_PREFIX
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

# Which run and try a task's event belongs to, and where in Airflow it was logged: the task's log keeps them,
# the terminal names the task instead.
_TERMINAL_HIDDEN_FIELDS = (
    "dag_id",
    "task_id",
    "run_id",
    "map_index",
    "try_number",
    "ti_id",
    "timestamp",
    "loc",
    "filename",
    "lineno",
    "func_name",
)

# Airflow imports a Dag file under its file name with this prefix, so a logger named after the file's module
# would show it.
_DAG_MODULE_PREFIX = re.compile(rf"{UNUSUAL_MODULE_PREFIX}[0-9a-f]{{40}}_")

# Hooks and operators log as ``airflow.task.hooks.<module>.<class>``; the class names them well enough.
_TASK_LOGGER_PREFIXES = ("airflow.task.hooks.", "airflow.task.operators.")

# Airflow's task runner and the task supervisor: the task's name already says where their events came from.
_UNNAMED_LOGGERS = ("task", "supervisor")

_LEVELS = logging.getLevelNamesMapping()

# Writes the log file of the task that is running, if any.
_task_log: Any = None


@dataclass(frozen=True)
class TaskFailure:
    """Why a task attempt failed, as the terminal shows it."""

    # One line, for an attempt that will be retried.
    summary: str
    # For the attempt that fails the task, e.g. a traceback.
    details: str


# This run's startup lines (bundle loading, Dag file parsing). A worker logs its own startup inside each
# task's Pre Execute section; a local run parses once, so the same lines go into every task's section.
_startup_events: list[tuple[str, dict[str, Any]]] = []
_recording_startup = False


def configure_local_run_logging() -> None:
    """Route this process's log output: short on stderr, complete in the running task's log file."""
    # Airflow's console loggers pick a stream up when each one is created; pinned now, loggers first used
    # while a task's printed output is being copied cannot write through that copy into the file.
    factory = structlog.get_config()["logger_factory"]
    if getattr(factory, "io", sys.stderr) is None:
        factory.io = sys.stderr
    # Cached loggers hold this very list, so the router and renderer replace Airflow's renderer in place.
    processors = structlog.get_config()["processors"]
    processors[-1:] = [_route_event, render_for_terminal]
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(_is_shown_on_console)
        # Airflow's console handler, which renders records the way its console loggers render events.
        if type(handler) is logging.StreamHandler and isinstance(
            formatter := handler.formatter, structlog.stdlib.ProcessorFormatter
        ):
            handler.setStream(sys.stderr)
            formatter.processors = [*formatter.processors[:-1], render_for_terminal]
    root.addHandler(_CopyRecordsToTaskLog())


def render_for_terminal(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> str:
    """
    Render a log event as the terminal shows it: the task, where the event came from, and the message.

    A Python warning reads as Python prints one. Tracebacks follow on the lines after.
    """
    fields = dict(structlog.processors.format_exc_info(logger, method_name, event_dict))
    message = str(fields.pop("event", ""))
    level = str(fields.pop("level", method_name))
    name = str(fields.pop("logger", None) or "")
    task_id, map_index = fields.get("task_id"), fields.get("map_index", -1)
    if name == "py.warnings":
        where = f"{_describe_path(Path(str(fields.pop('filename', ''))))}:{fields.pop('lineno', '')}"
        line = f"{where}: {fields.pop('category', 'Warning')}: {message}"
    else:
        line = f"{level}: {message}" if _LEVELS.get(level.upper(), 0) >= logging.WARNING else message
        if source := _get_display_name(name):
            line = f"{source}: {line}"
    for field in _TERMINAL_HIDDEN_FIELDS:
        fields.pop(field, None)
    details = [str(text) for key in ("exception", "stack") if (text := fields.pop(key, None))]
    if stacks := fields.pop("error_detail", None):
        details.append(_format_stacks(stacks)[0] if isinstance(stacks, list) else str(stacks))
    line += "".join(f" {key}={value}" for key, value in fields.items())
    if task_id:
        line = f"  {get_task_label(str(task_id), map_index if isinstance(map_index, int) else -1)} | {line}"
    return "\n".join([line, *details])


def get_task_label(task_id: str, map_index: int) -> str:
    """Return how the terminal names a task, or one mapped try of it."""
    return task_id if map_index < 0 else f"{task_id}[{map_index}]"


def _get_display_name(logger_name: str) -> str:
    if logger_name in _UNNAMED_LOGGERS:
        return ""
    if logger_name.startswith(_TASK_LOGGER_PREFIXES):
        return logger_name.rpartition(".")[2]
    return _DAG_MODULE_PREFIX.sub("", logger_name)


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
def capture_task_log(path: Path) -> Iterator[None]:
    """Write the running task's log to ``path`` as JSON lines, as a deployed task's supervisor does."""
    global _task_log
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
        sys.stdout, sys.stderr = stdout, stderr  # type: ignore[assignment]
        try:
            yield
        finally:
            sys.stdout, sys.stderr = stdout.stream, stderr.stream
            stdout.emit_pending()
            stderr.emit_pending()
            _task_log = None


def read_attempt_failure(path: Path) -> TaskFailure | None:
    """
    Return why the attempt logged in ``path`` failed, if the log says.

    The traceback starts where Airflow handed over to code of the task's own; the log keeps every frame.
    """
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
                details, left_out = _format_stacks(stacks)
                if left_out:
                    details += (
                        f"\n({left_out} frames of Airflow running the task are left out; the task's log has "
                        f"the full traceback: {_describe_path(path)})"
                    )
                failure = TaskFailure(summary=_format_exception_only(stacks[0]), details=details)
            elif message.startswith(PROCESS_EXIT_EVENTS):
                detail = ", ".join(
                    f"{key}={event[key]}" for key in ("exit_code", "signal_name") if key in event
                )
                summary = f"{message} ({detail})" if detail else message
                failure = TaskFailure(summary=summary, details=summary)
    return failure


def _format_stacks(stacks: list[dict[str, Any]]) -> tuple[str, int]:
    """
    Render a structured traceback the way Python prints the exception, and count the frames left out.

    The log holds the raised exception first, then each exception it was raised from or while handling.
    """
    text, left_out = _format_stack(stacks[-1])
    for inner, outer in zip(reversed(stacks), reversed(stacks[:-1])):
        if inner.get("is_cause"):
            text += "\nThe above exception was the direct cause of the following exception:\n\n"
        else:
            text += "\nDuring handling of the above exception, another exception occurred:\n\n"
        outer_text, outer_left_out = _format_stack(outer)
        text += outer_text
        left_out += outer_left_out
    return text.rstrip(), left_out


def _format_stack(stack: dict[str, Any]) -> tuple[str, int]:
    lines = []
    frames = _drop_frames_leading_to_task_code(stack.get("frames") or [])
    if frames:
        lines.append("Traceback (most recent call last):")
        for frame in frames:
            lines.append(
                f'  File "{frame.get("filename")}", line {frame.get("lineno")}, in {frame.get("name")}'
            )
            if code := (frame.get("line") or "").strip():
                lines.append(f"    {code}")
    lines.append(_format_exception_only(stack))
    lines.extend(stack.get("exc_notes") or ())
    return "\n".join(lines) + "\n", len(stack.get("frames") or []) - len(frames)


def _drop_frames_leading_to_task_code(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Drop the frames of Airflow code that lead to the first frame of other code, e.g. the Dag file's.

    Airflow frames below that one stay: they show what the task's code called. When every frame is Airflow's,
    as for a failing operator, the frame that raised stays.
    """
    for index, frame in enumerate(frames):
        if not _is_airflow_code(str(frame.get("filename", ""))):
            return frames[index:]
    return frames[-1:]


def _is_airflow_code(filename: str) -> bool:
    return any(Path(filename).is_relative_to(directory) for directory in _get_airflow_directories())


@functools.cache
def _get_airflow_directories() -> tuple[Path, ...]:
    # One directory per installed distribution of the ``airflow`` namespace, e.g. core, the SDK, providers.
    return tuple(Path(directory) for directory in airflow.__path__)


def _describe_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


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
        # The runner reports the failure from the task's log, once it knows whether the task will retry.
        raise structlog.DropEvent
    if not _is_on_console(name, _LEVELS[str(event_dict.get("level", method_name)).upper()]):
        raise structlog.DropEvent
    return event_dict


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
