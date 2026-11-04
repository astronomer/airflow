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
Local runs end to end: each test starts the real child process in a temporary project.

The child gets its own environment and SQLite database, so these tests never touch the test database.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import os
import pickle
import re
import signal
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest import mock

import pytest
from alembic.util import CommandError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, scoped_session

from airflow.local_run import runner
from airflow.models.taskinstance import TaskInstance
from airflow.sdk.definitions.local_run import (
    CHILD_MODULE,
    PROTOCOL_VERSION,
    build_child_environment,
    prepare_project_home,
    run_dag_file,
)
from airflow.sdk.exceptions import DagExecutionError, LocalRunError
from airflow.utils.types import DagRunTriggeredByType

PIPELINE = """
from airflow.sdk import dag, task


@task
def numbers():
    return [1, 2, 3]


@task
def double(number: int):
    return number * 2


@task
def total(values):
    return sum(values)


@task
def nothing():
    pass


@dag(schedule=None)
def example():
    total(double.expand(number=numbers()))
    nothing()


workflow = example()
"""


@pytest.fixture
def project(tmp_path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0"\n')
    return tmp_path


def write_dag_file(project: Path, name: str, source: str) -> Path:
    path = project / name
    path.write_text(textwrap.dedent(source))
    return path


def query(project: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(project / ".airflow" / "airflow.db") as conn:
        return conn.execute(sql).fetchall()


def test_runs_are_kept_with_their_outputs(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)

    first = run_dag_file(source)
    second = run_dag_file(source)

    assert first.output("total") == 12
    assert [first.output("double", i) for i in range(3)] == [2, 4, 6]
    assert first.output("nothing") is None
    assert first.run_id != second.run_id
    assert query(project, "SELECT run_id, state FROM dag_run ORDER BY run_after") == [
        (first.run_id, "success"),
        (second.run_id, "success"),
    ]
    assert query(project, "SELECT DISTINCT triggered_by FROM dag_run") == [("TEST",)]


def test_first_run_reports_progress_without_airflow_internals(project, capfd):
    run_dag_file(write_dag_file(project, "pipeline.py", PIPELINE))

    err = capfd.readouterr().err
    for line in (
        f"Creating the project database in {project / '.airflow'} (first run only)",
        "Running Dag 'example' from pipeline.py (run manual__",
        "  ✓ numbers",
        "  ✓ double[2]",
        "  ✓ total",
        "Succeeded in ",
    ):
        assert line in err
    for noise in (
        "MissingGreenlet",
        "XCom not found",
        "Context impl",
        "[DAG TEST]",
        "Task instance state updated",
    ):
        assert noise not in err


def test_task_logs_are_written_where_the_ui_reads_them(project):
    source = write_dag_file(
        project,
        "logged.py",
        """
        from airflow.sdk import dag, task

        @task
        def hello():
            print("hello local log")
            return "hi"

        @dag(schedule=None)
        def logged():
            hello()

        workflow = logged()
        """,
    )

    result = run_dag_file(source)

    log_file = (
        project
        / ".airflow"
        / "logs"
        / "dag_id=logged"
        / f"run_id={result.run_id}"
        / "task_id=hello"
        / "attempt=1.log"
    )
    events = [json.loads(line) for line in log_file.read_text().splitlines()]
    # A deployed task's log: the worker's startup in Pre Execute, the task, then Post Execute. Locally the
    # Dag file is parsed once per run, and that parse fills Pre Execute. Installed listener plugins may log
    # lines of their own in between.
    expected = [
        "::group::Pre Execute",
        "DAG bundles loaded: dags-folder",
        f"Filling up the DagBag from {source}",
        "Local run startup parse complete",
        "::endgroup::",
        "hello local log",
        "Done. Returned value was: hi",
        "::group::Post Execute",
        "Pushing xcom",
        "::endgroup::",
    ]
    assert [e["event"] for e in events if e["event"] in expected] == expected
    by_event = {e["event"]: e for e in events}
    assert by_event["Local run startup parse complete"]["dag_file"] == "logged.py"
    assert isinstance(by_event["Local run startup parse complete"]["dag_file_parse_ms"], int)
    assert by_event["hello local log"]["logger"] == "task.stdout"
    assert {(e["dag_id"], e["task_id"], e["run_id"]) for e in events} == {("logged", "hello", result.run_id)}


def test_structural_edit_rerun_immediately_gets_a_new_dag_version(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    first = run_dag_file(source)
    source.write_text(
        source.read_text().replace(
            "    nothing()\n", "    nothing() >> total.override(task_id='again')([1])\n"
        )
    )

    second = run_dag_file(source)

    assert second.output("again") == 1
    assert query(
        project,
        "SELECT r.run_id, v.version_number FROM dag_run r "
        "JOIN dag_version v ON v.id = r.created_dag_version_id ORDER BY r.run_after",
    ) == [(first.run_id, 1), (second.run_id, 2)]


def test_failed_run_raises_with_result(project, capfd):
    source = write_dag_file(
        project,
        "failing.py",
        """
        from airflow.sdk import dag, task

        @task
        def boom():
            raise ValueError("boom")

        @task
        def after():
            return 1

        @dag(schedule=None)
        def failing():
            boom() >> after()

        workflow = failing()
        """,
    )

    with pytest.raises(DagExecutionError, match="failed tasks: boom") as ctx:
        run_dag_file(source)

    assert ctx.value.result.task_states == {("boom", -1): "failed", ("after", -1): "upstream_failed"}
    with pytest.raises(KeyError, match="task state: upstream_failed"):
        ctx.value.result.output("after")
    out, err = capfd.readouterr()
    assert "  ✗ boom failed\nTraceback (most recent call last):\n" in err
    assert (out + err).count("ValueError: boom") == 1
    assert "Task failed with exception" not in out + err
    assert ": boom. History: " in err


def test_retried_attempt_is_reported_on_one_line(project, capfd):
    source = write_dag_file(
        project,
        "flaky.py",
        """
        from datetime import timedelta
        from pathlib import Path
        from airflow.sdk import dag, task

        @task(retries=1, retry_delay=timedelta(seconds=2))
        def flaky():
            marker = Path(__file__).with_name("attempted")
            if not marker.exists():
                marker.touch()
                raise ConnectionError("try again")
            return "ok"

        @dag(schedule=None)
        def retrying():
            flaky()

        workflow = retrying()
        """,
    )

    assert run_dag_file(source).output("flaky") == "ok"

    out, err = capfd.readouterr()
    # The wait left by the time the line is printed rounds up to whole seconds.
    assert re.search(
        r"  ↻ flaky failed attempt 1 of 2, retrying in [12]s: ConnectionError: try again\n  ✓ flaky\n", err
    )
    for noise in ("Traceback", "Task failed with exception", "No tasks to run"):
        assert noise not in out + err


def test_outputs_are_the_objects_tasks_returned(project, monkeypatch):
    source = write_dag_file(
        project,
        "objects.py",
        """
        import datetime
        from dataclasses import dataclass
        from airflow.sdk import dag, task

        @dataclass
        class Summary:
            rows: int

        @task
        def when():
            return datetime.datetime(2026, 1, 1)

        @task
        def tags():
            return {"a", "b"}

        @task
        def summary():
            return Summary(rows=3)

        @dag(schedule=None)
        def objects():
            when()
            tags()
            summary()

        workflow = objects()
        """,
    )
    # As under ``python objects.py``: the caller has the file imported, under a name of its own.
    spec = importlib.util.spec_from_file_location("callers_objects", source)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "callers_objects", module)
    spec.loader.exec_module(module)

    result = run_dag_file(source)

    assert result.output("when") == datetime.datetime(2026, 1, 1)
    assert result.output("tags") == {"a", "b"}
    assert result.output("summary") == module.Summary(rows=3)


TWO_DAGS = """
from airflow.sdk import dag, task

@task
def t():
    return 1

@dag(schedule=None)
def first():
    t()

@dag(schedule=None)
def second():
    t()

a = first()
b = second()
"""


@pytest.mark.parametrize(
    ("source", "dag_id", "match"),
    [
        pytest.param(
            "import not_a_real_module\n",
            None,
            r"(?s)Importing .*broken\.py failed:.*No module named 'not_a_real_module'",
            id="import-error",
        ),
        pytest.param("from airflow.sdk import dag\n", None, "No Dags found in", id="no-dags"),
        pytest.param(TWO_DAGS, None, r"defines several Dags \(first, second\); choose one", id="several"),
        pytest.param(
            TWO_DAGS,
            "third",
            "does not define Dag 'third' at module level. It defines: first, second",
            id="unknown",
        ),
        pytest.param(
            PIPELINE + "workflow.run()\n",
            None,
            r"Call example\.run\(\) under `if __name__ == \"__main__\":`",
            id="unguarded-run",
        ),
    ],
)
def test_setup_errors_raise_local_run_error(project, source, dag_id, match):
    path = write_dag_file(project, "broken.py", source)

    with pytest.raises(LocalRunError, match=match):
        run_dag_file(path, dag_id=dag_id)


def test_import_failure_is_reported_once(project, capfd):
    path = write_dag_file(project, "broken.py", "import not_a_real_module\n")

    with pytest.raises(LocalRunError, match=r"No module named 'not_a_real_module'$"):
        run_dag_file(path)

    out, err = capfd.readouterr()
    assert "not_a_real_module" not in out + err


def test_dag_id_selection(project):
    path = write_dag_file(project, "two.py", TWO_DAGS)

    assert run_dag_file(path, dag_id="second").dag_id == "second"


def test_dag_id_used_by_another_existing_file_is_refused(project):
    run_dag_file(write_dag_file(project, "pipeline.py", PIPELINE))
    copy = write_dag_file(project, "copy_of_pipeline.py", PIPELINE)

    with pytest.raises(LocalRunError, match="Dag ID 'example' is already used by pipeline.py"):
        run_dag_file(copy)


def test_moved_dag_file_keeps_its_history(project):
    first = run_dag_file(write_dag_file(project, "pipeline.py", PIPELINE))
    (project / "pipeline.py").rename(project / "renamed.py")

    second = run_dag_file(project / "renamed.py")

    assert query(project, "SELECT run_id FROM dag_run ORDER BY run_after") == [
        (first.run_id,),
        (second.run_id,),
    ]


def test_database_from_newer_airflow_is_refused(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    run_dag_file(source)
    with sqlite3.connect(project / ".airflow" / "airflow.db") as conn:
        conn.execute("UPDATE alembic_version SET version_num = 'ffffffffffff'")

    with pytest.raises(LocalRunError, match=r"created by a newer Airflow version \(schema ffffffffffff\)"):
        run_dag_file(source)


def test_interrupted_child_records_a_failed_run(project, tmp_path):
    started = tmp_path / "started"
    source = write_dag_file(
        project,
        "sleepy.py",
        f"""
        import time
        from pathlib import Path
        from airflow.sdk import dag, task

        @task
        def slow():
            Path({str(started)!r}).touch()
            time.sleep(120)

        @task(trigger_rule="all_done")
        def after():
            return 1

        @dag(schedule=None)
        def sleepy():
            slow() >> after()

        workflow = sleepy()
        """,
    )
    home = prepare_project_home(project)
    request = tmp_path / "request.json"
    result_path = tmp_path / "result.pickle"
    request.write_text(
        json.dumps(
            {
                "version": PROTOCOL_VERSION,
                "source": str(source),
                "dag_id": None,
                "run_conf": None,
                "triggered_by": "test",
                "result_path": str(result_path),
            }
        )
    )
    child = subprocess.Popen(
        [sys.executable, "-m", CHILD_MODULE, str(request)],
        env=build_child_environment(os.environ, home=home, root=project),
    )
    deadline = time.monotonic() + 120
    while not started.exists():
        assert child.poll() is None, "child exited before the task started"
        assert time.monotonic() < deadline, "task did not start"
        time.sleep(0.2)

    child.send_signal(signal.SIGINT)

    assert child.wait(timeout=60) == 130
    payload = pickle.loads(result_path.read_bytes())
    assert payload["cancelled"] is True
    assert payload["state"] == "failed"
    assert query(project, "SELECT state FROM dag_run") == [("failed",)]
    # Without stopping, the all_done task would run after the interrupted one.
    assert dict(query(project, "SELECT task_id, state FROM task_instance")) == {
        "slow": "failed",
        "after": "skipped",
    }


@mock.patch.object(runner, "create_dag_run", autospec=True)
@mock.patch.object(runner, "register_dags", autospec=True)
def test_start_run_retries_in_a_new_transaction_when_the_database_is_locked(register, create, tmp_path):
    session = mock.create_autospec(Session, instance=True)
    locked = OperationalError("INSERT INTO dag_run", {}, sqlite3.OperationalError("database is locked"))
    create.side_effect = [locked, (mock.sentinel.scheduler_dag, mock.sentinel.dag_run)]

    with mock.patch.object(runner.settings, "Session", spec=scoped_session, return_value=session):
        started = runner.start_run(
            mock.sentinel.bag,
            mock.sentinel.dag,
            source=tmp_path / "pipeline.py",
            root=tmp_path,
            home=tmp_path,
            bundles=mock.sentinel.bundles,
            run_conf=None,
            triggered_by=DagRunTriggeredByType.TEST,
        )

    assert started == (mock.sentinel.scheduler_dag, mock.sentinel.dag_run)
    assert register.call_count == 2
    session.rollback.assert_called_once_with()


class TestEnsureDatabase:
    @pytest.mark.db_test
    @mock.patch.object(runner, "upgradedb", autospec=True)
    @mock.patch.object(runner, "initdb", autospec=True)
    @mock.patch.object(runner, "_get_script_object", autospec=True)
    @mock.patch.object(runner, "_get_current_revision", autospec=True)
    @pytest.mark.parametrize(
        ("current", "expected_call"),
        [
            pytest.param(None, "initdb", id="new-database"),
            pytest.param("head", None, id="current"),
            pytest.param("older", "upgradedb", id="older"),
        ],
    )
    def test_brings_schema_to_this_version(
        self, get_current, get_script, initdb, upgradedb, tmp_path, current, expected_call
    ):
        get_current.return_value = current
        get_script.return_value.get_heads.return_value = ["head"]

        runner.ensure_database(tmp_path)

        assert initdb.called is (expected_call == "initdb")
        assert upgradedb.called is (expected_call == "upgradedb")

    @pytest.mark.db_test
    @mock.patch.object(runner, "upgradedb", autospec=True)
    @mock.patch.object(runner, "_get_script_object", autospec=True)
    @mock.patch.object(runner, "_get_current_revision", autospec=True, return_value="unknown")
    def test_unknown_revision_is_refused(self, _, get_script, upgradedb, tmp_path):
        get_script.return_value.get_heads.return_value = ["head"]
        get_script.return_value.get_revision.side_effect = CommandError("no such revision")

        with pytest.raises(runner.LocalRunSetupError, match="newer Airflow version"):
            runner.ensure_database(tmp_path)

        upgradedb.assert_not_called()


@pytest.mark.parametrize(
    ("request_overrides", "outcome", "expected_code"),
    [
        pytest.param({"version": 99}, None, 2, id="bad-version"),
        pytest.param({}, KeyboardInterrupt, 130, id="interrupted-before-run"),
        pytest.param({}, runner.LocalRunSetupError("nope"), 2, id="setup-error"),
        pytest.param({}, {"state": "success"}, 0, id="success"),
        pytest.param({}, {"state": "failed"}, 1, id="failed"),
    ],
)
def test_main_exit_codes(tmp_path, request_overrides, outcome, expected_code):
    request = {
        "version": PROTOCOL_VERSION,
        "result_path": str(tmp_path / "result.pickle"),
    } | request_overrides
    (tmp_path / "request.json").write_text(json.dumps(request))
    side_effect = outcome if isinstance(outcome, BaseException) or outcome is KeyboardInterrupt else None
    return_value = {"version": PROTOCOL_VERSION, **outcome} if isinstance(outcome, dict) else None

    with mock.patch.object(
        runner, "execute", autospec=True, side_effect=side_effect, return_value=return_value
    ):
        assert runner.main([str(tmp_path / "request.json")]) == expected_code

    assert pickle.loads((tmp_path / "result.pickle").read_bytes())["version"] == PROTOCOL_VERSION


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(
            {"cancelled": False, "state": "success", "task_states": {}}, "Succeeded in 1.5s", id="success"
        ),
        pytest.param(
            {
                "cancelled": False,
                "state": "failed",
                "task_states": {("b", -1): "failed", ("a", 2): "failed", ("c", -1): "upstream_failed"},
            },
            "Failed in 1.5s: a[2], b",
            id="failed",
        ),
        pytest.param(
            {"cancelled": True, "state": "failed", "task_states": {}}, "Cancelled after 1.5s", id="cancelled"
        ),
    ],
)
def test_summarize_run(payload, expected):
    assert runner.summarize_run(payload, 1.49, Path("/p/.airflow")) == f"{expected}. History: /p/.airflow"


@pytest.mark.parametrize(
    ("state", "cancelled", "retry_in", "expected"),
    [
        pytest.param("success", False, None, "  ✓ load", id="success"),
        pytest.param(
            "up_for_retry",
            False,
            datetime.timedelta(minutes=5),
            "  ↻ load failed attempt 1 of 3, retrying in 5m: ValueError: boom",
            id="retry",
        ),
        pytest.param(
            "up_for_retry",
            False,
            datetime.timedelta(hours=1, minutes=2, seconds=4.2),
            "  ↻ load failed attempt 1 of 3, retrying in 1h 2m 5s: ValueError: boom",
            id="retry-long-wait",
        ),
        pytest.param(
            "up_for_retry",
            False,
            datetime.timedelta(0),
            "  ↻ load failed attempt 1 of 3, retrying: ValueError: boom",
            id="retry-now",
        ),
        pytest.param("failed", True, None, "  ✗ load cancelled", id="cancelled"),
        pytest.param("skipped", False, None, "  · load skipped", id="other"),
    ],
)
def test_report_task(capsys, state, cancelled, retry_in, expected):
    ti = mock.Mock(spec=TaskInstance, task_id="load", map_index=-1, state=state, try_number=1, max_tries=2)

    runner.report_task(ti, ValueError("boom"), cancelled=cancelled, retry_in=retry_in)

    assert capsys.readouterr().err == f"{expected}\n"


def test_report_task_shows_the_failure_that_ended_the_task(capsys):
    ti = mock.Mock(spec=TaskInstance, task_id="load", map_index=3, state="failed")
    try:
        raise ValueError("boom")
    except ValueError as e:
        failure = e

    runner.report_task(ti, failure, cancelled=False)

    err = capsys.readouterr().err
    assert err.startswith("  ✗ load[3] failed\nTraceback (most recent call last):\n")
    assert err.endswith("ValueError: boom\n")


@mock.patch.object(runner.settings, "dispose_async_engine", autospec=True)
@mock.patch.object(runner, "run_requested_dag", autospec=True, side_effect=runner.LocalRunSetupError("nope"))
def test_execute_disposes_async_engine_even_when_setup_fails(_, mock_dispose):
    with pytest.raises(runner.LocalRunSetupError):
        runner.execute({})

    mock_dispose.assert_awaited_once_with()


@mock.patch.object(runner.os, "_exit", autospec=True)
@mock.patch.object(runner.logging, "shutdown", autospec=True)
@mock.patch.object(runner.settings, "dispose_orm", autospec=True)
def test_exit_without_teardown_closes_connections_and_logging_first(mock_dispose, mock_shutdown, mock_exit):
    calls = mock.Mock()
    calls.attach_mock(mock_dispose, "dispose_orm")
    calls.attach_mock(mock_shutdown, "shutdown_logging")
    calls.attach_mock(mock_exit, "exit")

    runner.exit_without_teardown(3)

    assert calls.mock_calls == [mock.call.dispose_orm(), mock.call.shutdown_logging(), mock.call.exit(3)]
