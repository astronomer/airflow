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

import pytest
import structlog

from airflow._shared.logging.structlog import LoggerFactory, NamedWriteLogger, logger_name
from airflow.local_run import logs
from airflow.local_run.logs import capture_task_log, configure_local_run_logging, record_startup_events


@pytest.fixture
def console(monkeypatch):
    """
    Logging shaped like Airflow's console setup, restored afterwards.

    Returns the stream of a root console handler, standing in for Airflow's stdlib console handler.
    """
    monkeypatch.setattr(logs, "_startup_events", [])
    saved_config = structlog.get_config()
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_filters = {handler: list(handler.filters) for handler in root.handlers}
    structlog.configure(
        processors=[
            logger_name,
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        logger_factory=LoggerFactory(NamedWriteLogger),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=False,
    )
    stream = io.StringIO()
    root.addHandler(logging.StreamHandler(stream))
    root.setLevel(logging.INFO)
    yield stream
    structlog.configure(**saved_config)
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    for handler, filters in saved_filters.items():
        handler.filters[:] = filters


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

    shown = capsys.readouterr().out + console.getvalue()
    for line in ("internal warning", "hook output", "user log", "migration error", "user record"):
        assert line in shown
    for line in ("internal progress", "migration progress"):
        assert line not in shown


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
def test_console_loggers_are_pinned_to_current_stdout(console, bound):
    factory = LoggerFactory(NamedWriteLogger, io=bound)
    structlog.configure(logger_factory=factory)

    configure_local_run_logging()

    assert factory.io is (sys.stdout if bound is None else bound)


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

    with capture_task_log(path) as attempt:
        try:
            raise ValueError("boom")
        except ValueError as e:
            error = e
            structlog.get_logger("task").exception("Task failed with exception")

    assert attempt.failure is error
    assert "boom" not in capsys.readouterr().out + console.getvalue()
    assert read_events(path) == [("Task failed with exception", "error", "task")]


def test_import_errors_are_left_to_the_run_to_report(console, capsys):
    configure_local_run_logging()

    logging.getLogger("airflow.dag_processing.dagbag.BundleDagBag").error("Error loading DAG")
    structlog.get_logger("airflow.sdk.importers.python_importer").error("Failed to import")
    logging.getLogger("airflow.dag_processing.dagbag.BundleDagBag").warning("DagBag warning")

    shown = capsys.readouterr().out + console.getvalue()
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
