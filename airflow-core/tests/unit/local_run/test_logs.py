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

import io
import json
import logging
import sys
import traceback
from pathlib import Path

import pytest
import structlog

import airflow
from airflow._shared.logging.structlog import (
    LoggerFactory,
    NamedWriteLogger,
    logger_name,
    make_filtering_logger,
)
from airflow._shared.module_loading import get_unique_dag_module_name
from airflow.local_run import logs
from airflow.local_run.logs import (
    TASK_FAILED_EVENT,
    TaskFailure,
    capture_task_log,
    configure_local_run_logging,
    read_attempt_failure,
    record_startup_events,
)
from airflow.sdk._shared.secrets_masker import mask_secret, reset_secrets_masker
from airflow.sdk.execution_time.supervisor import forward_to_log, process_log_messages_from_subprocess


@pytest.fixture
def console(monkeypatch, capsys):
    """
    Logging shaped like Airflow's console setup, restored afterwards.

    Its stdlib console handler writes to a stream of its own, standing in for Airflow's on stdout.
    """
    monkeypatch.setattr(logs, "_startup_events", [])
    saved_config = structlog.get_config()
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    renderer = structlog.dev.ConsoleRenderer(colors=False)
    structlog.configure(
        processors=[logger_name, structlog.processors.add_log_level, renderer],
        logger_factory=LoggerFactory(NamedWriteLogger),
        wrapper_class=make_filtering_logger(),
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(io.StringIO())
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
            foreign_pre_chain=[structlog.stdlib.add_logger_name, structlog.processors.add_log_level],
        )
    )
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    yield
    structlog.configure(**saved_config)
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


def read_events(path) -> list[tuple[str, str, str | None]]:
    events = [json.loads(line) for line in path.read_text().splitlines()]
    return [(e["event"], e["level"], e.get("logger")) for e in events]


def test_terminal_hides_airflow_progress_but_not_task_output(console, capsys):
    configure_local_run_logging()

    structlog.get_logger("airflow.models.dagrun").info("internal progress")
    structlog.get_logger("airflow.models.dagrun").warning("internal warning")
    structlog.get_logger("airflow.task.hooks.subprocess").info("hook output")
    structlog.get_logger("my_dag_module").info("user log")
    logging.getLogger("alembic.runtime.migration").info("migration progress")
    logging.getLogger("alembic.runtime.migration").error("migration error")
    logging.getLogger("my.module").info("user record")
    structlog.get_logger("supervisor").info("supervisor progress")
    structlog.get_logger("supervisor").warning("supervisor warning")

    captured = capsys.readouterr()
    assert captured.out == ""
    shown = captured.err
    for line in (
        "internal warning",
        "hook output",
        "user log",
        "migration error",
        "user record",
        "supervisor warning",
    ):
        assert line in shown
    for line in ("internal progress", "migration progress", "supervisor progress"):
        assert line not in shown


def send_lines(reader, *lines: bytes) -> None:
    next(reader)
    for line in lines:
        reader.send(line)


def test_supervised_task_output_is_shown_as_printed(console, capsys):
    configure_local_run_logging()
    supervisor_log = structlog.get_logger("supervisor")

    send_lines(forward_to_log((supervisor_log,), "task.stdout", logging.INFO), b"hello from the task\n")
    send_lines(forward_to_log((supervisor_log,), "task.stderr", logging.ERROR), b"to stderr\n")

    captured = capsys.readouterr()
    assert captured.out == "hello from the task\n"
    assert captured.err == "to stderr\n"


def test_supervised_task_failure_is_left_to_the_runner(console, capsys):
    configure_local_run_logging()
    failure = {"event": TASK_FAILED_EVENT, "level": "error", "logger": "task", "exception": [{}]}

    send_lines(
        process_log_messages_from_subprocess((structlog.get_logger("supervisor"),)),
        json.dumps(failure).encode(),
    )

    captured = capsys.readouterr()
    assert captured.out + captured.err == ""


# What the task runner binds to each of a task's log events.
TASK_CONTEXT = {
    "dag_id": "etl",
    "task_id": "load",
    "map_index": -1,
    "run_id": "manual__2026-11-10T16:00:00+00:00",
    "try_number": 1,
    "ti_id": "019a6c62-d1a0-7658-b737-b6034df6ae45",
    "loc": "etl.py:3",
    "timestamp": "2026-11-10T16:00:01.000000Z",
}


@pytest.mark.parametrize(
    ("event", "shown"),
    [
        pytest.param(
            {"event": "loaded", "level": "info", "logger": get_unique_dag_module_name("/project/etl.py")},
            "  load | etl: loaded",
            id="dag-file-module",
        ),
        pytest.param(
            {"event": "only 3 rows", "level": "warning", "logger": "etl"},
            "  load | etl: warning: only 3 rows",
            id="warning",
        ),
        pytest.param(
            {"event": "loaded", "level": "info", "logger": "etl", "rows": 3},
            "  load | etl: loaded rows=3",
            id="own-fields",
        ),
        pytest.param(
            {
                "event": "from bash",
                "level": "info",
                "logger": "airflow.task.hooks.airflow.providers.standard.hooks.subprocess.SubprocessHook",
                "map_index": 2,
            },
            "  load[2] | SubprocessHook: from bash",
            id="hook-in-mapped-try",
        ),
        pytest.param(
            {"event": "slow to start", "level": "warning", "logger": "task"},
            "  load | warning: slow to start",
            id="task-runner",
        ),
        pytest.param(
            {
                "event": "old option",
                "level": "warning",
                "logger": "py.warnings",
                "category": "UserWarning",
                "filename": str(Path.cwd() / "etl.py"),
                "lineno": 12,
            },
            "  load | etl.py:12: UserWarning: old option",
            id="python-warning",
        ),
    ],
)
def test_supervised_task_log_is_one_short_line_on_stderr(console, capsys, event, shown):
    configure_local_run_logging()

    send_lines(
        process_log_messages_from_subprocess((structlog.get_logger("supervisor"),)),
        json.dumps({**TASK_CONTEXT, **event}).encode(),
    )

    assert capsys.readouterr() == ("", f"{shown}\n")


def test_supervised_task_log_shows_a_logged_traceback_from_the_task_code(console, capsys):
    configure_local_run_logging()
    stack = {
        "exc_type": "KeyError",
        "exc_value": "'missing'",
        "frames": [
            frame(f"{airflow.__path__[0]}/runner.py", "run the task"),
            frame("/project/etl.py", "look"),
        ],
    }
    event = {"event": "lookup failed", "level": "error", "logger": "etl", "exception": [stack]}

    send_lines(
        process_log_messages_from_subprocess((structlog.get_logger("supervisor"),)),
        json.dumps({**TASK_CONTEXT, **event}).encode(),
    )

    assert capsys.readouterr().err.splitlines() == [
        "  load | etl: error: lookup failed",
        "Traceback (most recent call last):",
        '  File "/project/etl.py", line 1, in f',
        "    look",
        "KeyError: 'missing'",
    ]


def test_records_and_warnings_of_the_run_process_go_to_stderr(console, capsys):
    configure_local_run_logging()

    try:
        raise KeyError("missing")
    except KeyError:
        logging.getLogger(get_unique_dag_module_name("/project/etl.py")).exception("lookup failed")
    structlog.get_logger("py.warnings").warning(
        "changelog_url does nothing", category="DeprecationWarning", filename="/elsewhere/app.py", lineno=329
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    first, traceback_start, *_, exception, warning = captured.err.splitlines()
    assert (first, traceback_start, exception) == (
        "etl: error: lookup failed",
        "Traceback (most recent call last):",
        "KeyError: 'missing'",
    )
    assert warning == "/elsewhere/app.py:329: DeprecationWarning: changelog_url does nothing"


@pytest.fixture
def secret():
    """A value the Task SDK masks, as one a task looked up; the supervisor registers those the same way."""
    mask_secret("Pa55w0rd-xyz")
    yield "Pa55w0rd-xyz"
    reset_secrets_masker()


def log_from_supervised_task(secret: str) -> None:
    send_lines(
        process_log_messages_from_subprocess((structlog.get_logger("supervisor"),)),
        json.dumps(
            {**TASK_CONTEXT, "event": f"logged {secret}", "level": "warning", "logger": "etl"}
        ).encode(),
    )


@pytest.mark.parametrize(
    ("log", "shown"),
    [
        pytest.param(log_from_supervised_task, "  load | etl: warning: logged ***", id="supervised-task"),
        pytest.param(
            lambda secret: structlog.get_logger("etl").warning(f"logged {secret}"),
            "etl: warning: logged ***",
            id="event",
        ),
        pytest.param(
            lambda secret: logging.getLogger("etl").warning("logged %s", secret),
            "etl: warning: logged ***",
            id="record",
        ),
    ],
)
@pytest.mark.enable_redact
def test_terminal_masks_secrets(console, capsys, secret, log, shown):
    configure_local_run_logging()

    log(secret)

    assert capsys.readouterr().err == f"{shown}\n"


def test_task_log_gets_what_a_deployed_task_log_has(console, tmp_path):
    configure_local_run_logging()
    path = tmp_path / "attempt=1.log"
    streams = (sys.stdout, sys.stderr)

    with capture_task_log(path):
        structlog.get_logger("task").info("::group::Post Execute")
        structlog.get_logger("airflow.task.operators.python").info("Done. Returned value was: 12")
        structlog.get_logger("airflow.api_fastapi.execution_api.routes").info("Task instance state updated")
        structlog.get_logger("airflow.sdk.definitions.dag").info("[DAG TEST] end task")
        logging.getLogger("my.module").info("user record")
        print("from print")
        print("to stderr", file=sys.stderr)
        sys.stdout.write("unterminated")
    structlog.get_logger("task").info("after the task")

    assert read_events(path) == [
        ("::group::Post Execute", "info", "task"),
        ("Done. Returned value was: 12", "info", "airflow.task.operators.python"),
        ("user record", "info", "my.module"),
        ("from print", "info", "task.stdout"),
        ("to stderr", "error", "task.stderr"),
        ("unterminated", "info", "task.stdout"),
    ]
    assert (sys.stdout, sys.stderr) == streams


def test_task_log_stores_tracebacks_where_the_ui_renders_them(console, tmp_path):
    configure_local_run_logging()
    path = tmp_path / "attempt=1.log"

    with capture_task_log(path):
        try:
            raise ValueError("boom")
        except ValueError:
            structlog.get_logger("task").exception("Task failed with exception")

    (event,) = [json.loads(line) for line in path.read_text().splitlines()]
    assert "exception" not in event
    assert event["error_detail"][0]["exc_type"] == "ValueError"
    assert event["error_detail"][0]["exc_value"] == "boom"


def test_task_log_appends_to_an_existing_attempt_log(console, tmp_path):
    configure_local_run_logging()
    path = tmp_path / "attempt=1.log"
    path.write_text(json.dumps({"event": "before deferral", "level": "info"}) + "\n")

    with capture_task_log(path):
        print("after resuming")

    assert [event for event, _, _ in read_events(path)] == ["before deferral", "after resuming"]


@pytest.mark.parametrize("bound", [None, io.StringIO()])
def test_console_loggers_are_pinned_to_current_stderr(console, bound):
    factory = LoggerFactory(NamedWriteLogger, io=bound)
    structlog.configure(logger_factory=factory)

    configure_local_run_logging()

    assert factory.io is (sys.stderr if bound is None else bound)


def test_startup_lines_fill_each_task_pre_execute_section(console, tmp_path):
    configure_local_run_logging()
    with record_startup_events():
        structlog.get_logger("airflow.dag_processing.bundles.manager").info("DAG bundles loaded: dags-folder")
        logging.getLogger("airflow.dag_processing.dagbag").info("Filling up the DagBag from pipeline.py")
    structlog.get_logger("airflow.models.dagrun").info("not startup")
    first, second = tmp_path / "first.log", tmp_path / "second.log"

    for path in (first, second):
        with capture_task_log(path):
            structlog.get_logger("task").info("::group::Pre Execute")
            structlog.get_logger("task").info("::endgroup::")

    for path in (first, second):
        assert [event for event, _, _ in read_events(path)] == [
            "::group::Pre Execute",
            "DAG bundles loaded: dags-folder",
            "Filling up the DagBag from pipeline.py",
            "::endgroup::",
        ]
        times = [json.loads(line)["timestamp"] for line in path.read_text().splitlines()]
        # The log reader orders lines by time; startup lines must not sort ahead of their section.
        assert times == sorted(times)


def test_task_failure_is_held_back_from_the_terminal(console, capsys, tmp_path):
    configure_local_run_logging()
    path = tmp_path / "attempt=1.log"

    with capture_task_log(path):
        try:
            raise ValueError("boom")
        except ValueError:
            structlog.get_logger("task").exception("Task failed with exception")

    captured = capsys.readouterr()
    assert "boom" not in captured.out + captured.err
    assert read_events(path) == [("Task failed with exception", "error", "task")]
    assert read_attempt_failure(path).summary == "ValueError: boom"


def test_import_errors_are_left_to_the_run_to_report(console, capsys):
    configure_local_run_logging()

    logging.getLogger("airflow.dag_processing.dagbag.BundleDagBag").error("Error loading DAG")
    structlog.get_logger("airflow.sdk.importers.python_importer").error("Failed to import")
    logging.getLogger("airflow.dag_processing.dagbag.BundleDagBag").warning("DagBag warning")

    shown = capsys.readouterr().err
    assert "DagBag warning" in shown
    for line in ("Error loading DAG", "Failed to import"):
        assert line not in shown


def test_startup_lines_are_only_written_inside_pre_execute(console, tmp_path):
    configure_local_run_logging()
    with record_startup_events():
        structlog.get_logger("airflow.dag_processing.bundles.manager").info("DAG bundles loaded: dags-folder")
    path = tmp_path / "attempt=1.log"

    with capture_task_log(path):
        print("no startup section in this log")

    assert [event for event, _, _ in read_events(path)] == ["no startup section in this log"]


def raise_chained(chain: str) -> None:
    try:
        raise KeyError("inner")
    except KeyError as e:
        if chain == "cause":
            raise ValueError("outer") from e
        raise ValueError("outer")


@pytest.mark.parametrize("chain", ["cause", "context"])
def test_attempt_failure_reads_the_traceback_the_supervisor_logged(console, tmp_path, chain):
    configure_local_run_logging()
    path = tmp_path / "attempt=1.log"
    with capture_task_log(path):
        try:
            raise_chained(chain)
        except ValueError as e:
            error = e
            structlog.get_logger("task").exception(TASK_FAILED_EVENT)

    failure = read_attempt_failure(path)

    assert failure is not None
    assert failure.summary == "ValueError: outer"
    # Code lines and caret markers are indented; the rest is what Python prints for the same exception.
    expected = "".join(traceback.format_exception(error)).rstrip()
    assert [line for line in failure.details.splitlines() if not line.startswith("  ")] == [
        line for line in expected.splitlines() if not line.startswith("  ")
    ]
    assert f'  File "{__file__}", line ' in failure.details


@pytest.mark.parametrize(
    ("event", "summary"),
    [
        pytest.param(
            {"event": "Process exited abnormally", "exit_code": 3},
            "Process exited abnormally (exit_code=3)",
            id="exit-code",
        ),
        pytest.param(
            {"event": "Process terminated by signal.", "signal": -9, "signal_name": "SIGKILL"},
            "Process terminated by signal. (signal_name=SIGKILL)",
            id="signal",
        ),
    ],
)
def test_attempt_failure_reads_why_the_process_ended(tmp_path, event, summary):
    path = tmp_path / "attempt=1.log"
    path.write_text(
        "\n".join(json.dumps(e) for e in [{"event": "about to exit", "level": "info"}, event]) + "\n"
    )

    assert read_attempt_failure(path) == TaskFailure(summary=summary, details=summary)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(None, id="no-log"),
        pytest.param(
            json.dumps({"event": "Done. Returned value was: 1", "level": "info"}) + "\nnot json\n",
            id="no-failure",
        ),
    ],
)
def test_attempt_failure_is_none_without_one(tmp_path, content):
    path = tmp_path / "attempt=1.log"
    if content is not None:
        path.write_text(content)

    assert read_attempt_failure(path) is None


def frame(filename: str, line: str) -> dict:
    return {"filename": filename, "lineno": 1, "name": "f", "line": line}


@pytest.mark.parametrize(
    ("frames", "shown", "left_out"),
    [
        pytest.param(
            [
                frame(f"{airflow.__path__[0]}/runner.py", "run the task"),
                frame(f"{airflow.__path__[0]}/operator.py", "call the function"),
                frame("/project/pipeline.py", "task code"),
                frame(f"{airflow.__path__[0]}/hook.py", "hook the task called"),
            ],
            ["task code", "hook the task called"],
            2,
            id="airflow-calling-task-code",
        ),
        pytest.param(
            [
                frame(f"{airflow.__path__[0]}/runner.py", "run the task"),
                frame(f"{airflow.__path__[0]}/bash.py", "raise for the exit code"),
            ],
            ["raise for the exit code"],
            1,
            id="operator-failing",
        ),
    ],
)
def test_attempt_failure_starts_at_the_task_code(tmp_path, frames, shown, left_out):
    path = tmp_path / "attempt=1.log"
    stack = {"exc_type": "ValueError", "exc_value": "boom", "frames": frames}
    path.write_text(
        json.dumps({"event": TASK_FAILED_EVENT, "level": "error", "error_detail": [stack]}) + "\n"
    )

    failure = read_attempt_failure(path)

    assert failure is not None
    assert [line.strip() for line in failure.details.splitlines() if not line.startswith("  File")] == [
        "Traceback (most recent call last):",
        *shown,
        "ValueError: boom",
        f"({left_out} frames of Airflow running the task are left out; the task's log has the full "
        f"traceback: {path})",
    ]


def test_attempt_failure_of_a_run_without_history_does_not_point_to_its_log(tmp_path):
    path = tmp_path / "attempt=1.log"
    frames = [
        frame(f"{airflow.__path__[0]}/runner.py", "run the task"),
        frame("/project/pipeline.py", "code"),
    ]
    stack = {"exc_type": "ValueError", "exc_value": "boom", "frames": frames}
    path.write_text(
        json.dumps({"event": TASK_FAILED_EVENT, "level": "error", "error_detail": [stack]}) + "\n"
    )

    failure = read_attempt_failure(path, log_kept=False)

    assert failure is not None
    assert failure.details.endswith("ValueError: boom\n(1 frames of Airflow running the task are left out)")
