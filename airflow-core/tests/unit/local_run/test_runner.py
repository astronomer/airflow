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
import fcntl
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

import psutil
import pytest
import time_machine
from alembic.util import CommandError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, scoped_session

from airflow.local_run import runner
from airflow.local_run.logs import TaskFailure
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

from tests_common.test_utils.config import conf_vars

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


def test_run_without_history_leaves_the_project_alone(project, capfd):
    result = run_dag_file(write_dag_file(project, "pipeline.py", PIPELINE), keep_history=False)

    assert result.output("total") == 12
    assert result.project_home is None
    assert not (project / ".airflow").exists()
    err = capfd.readouterr().err
    assert "Creating the project database" not in err
    assert re.search(r"Succeeded in \S+ \(\S+ total\)\. No history kept\n", err)


def test_failure_without_history_does_not_point_to_the_deleted_log(project, capfd):
    source = write_dag_file(
        project,
        "failing.py",
        """
        from airflow.sdk import dag, task

        @task
        def boom():
            raise ValueError("boom")

        @dag(schedule=None)
        def failing():
            boom()

        workflow = failing()
        """,
    )

    with pytest.raises(DagExecutionError):
        run_dag_file(source, keep_history=False)

    err = capfd.readouterr().err
    assert re.search(r"\(\d+ frames of Airflow running the task are left out\)\n", err)
    assert "the task's log has the full traceback" not in err


RUN_JOBS = """
SELECT dag_run.dag_id, dag_run.state, job.job_type, job.state FROM dag_run
JOIN job ON job.id = dag_run.creating_job_id ORDER BY dag_run.run_after
"""


def test_run_is_driven_by_a_job_that_ends_with_it(project):
    run_dag_file(write_dag_file(project, "pipeline.py", PIPELINE))

    assert query(project, RUN_JOBS) == [("example", "success", "LocalRunJob", "success")]


def test_job_left_running_after_its_run_finished_is_ended_by_the_next_run(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    run_dag_file(source)
    # As if the process was killed after recording the run's outcome but before ending its job.
    with sqlite3.connect(project / ".airflow" / "airflow.db") as conn:
        conn.execute("UPDATE job SET state = 'running', end_date = NULL")
    ((dag_run_id,),) = query(project, "SELECT id FROM dag_run")
    (project / ".airflow" / "runs" / f"{dag_run_id}.lock").touch()

    run_dag_file(source)

    assert query(project, RUN_JOBS) == [
        ("example", "success", "LocalRunJob", "failed"),
        ("example", "success", "LocalRunJob", "success"),
    ]
    assert not list((project / ".airflow" / "runs").iterdir())


def test_run_from_before_local_runs_recorded_a_job_is_recorded_failed(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    first = run_dag_file(source)
    # As a run started before this change, whose process was killed, looks: no job, and its lock file left.
    with sqlite3.connect(project / ".airflow" / "airflow.db") as conn:
        conn.execute(
            "UPDATE dag_run SET state = 'running', creating_job_id = NULL WHERE run_id = ?", (first.run_id,)
        )
    ((dag_run_id,),) = query(project, f"SELECT id FROM dag_run WHERE run_id = '{first.run_id}'")
    (project / ".airflow" / "runs" / f"{dag_run_id}.lock").touch()

    run_dag_file(source)

    assert query(project, f"SELECT state FROM dag_run WHERE run_id = '{first.run_id}'") == [("failed",)]
    assert not list((project / ".airflow" / "runs").iterdir())


def test_running_run_no_local_process_drives_is_left_alone(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    first = run_dag_file(source)
    # As a run started with `airflow dags trigger` looks while the scheduler runs it.
    with sqlite3.connect(project / ".airflow" / "airflow.db") as conn:
        conn.execute(
            "UPDATE dag_run SET state = 'running', triggered_by = 'CLI', creating_job_id = NULL WHERE run_id = ?",
            (first.run_id,),
        )

    run_dag_file(source)

    assert query(project, f"SELECT state FROM dag_run WHERE run_id = '{first.run_id}'") == [("running",)]


@time_machine.travel("2000-01-01", tick=False)
def test_first_run_reports_progress_without_airflow_internals(project, capfd):
    started = time.monotonic()
    run_dag_file(write_dag_file(project, "pipeline.py", PIPELINE))
    elapsed = time.monotonic() - started

    err = capfd.readouterr().err
    for line in (
        f"Creating the project database in {project / '.airflow'} (first run only)",
        "Running Dag 'example' from pipeline.py (run manual__",
        "  ✓ numbers",
        "  ✓ double[2]",
        "  ✓ total",
    ):
        assert line in err
    # The total also counts the time before the tasks ran, from the call that started the run.
    times = re.search(r"Succeeded in (\d+\.\d)s \((\d+\.\d)s total\)\. History: ", err)
    assert times is not None
    assert float(times[2]) > float(times[1])
    assert float(times[2]) <= elapsed + 0.1
    for noise in (
        "MissingGreenlet",
        "XCom not found",
        "Context impl",
        "[DAG TEST]",
        "Task instance state updated",
    ):
        assert noise not in err


@pytest.mark.parametrize(
    ("debug", "parse_event"),
    [
        pytest.param(False, "Worker startup parse complete", id="supervised"),
        pytest.param(True, "Local run startup parse complete", id="debug"),
    ],
)
def test_task_logs_are_written_where_the_ui_reads_them(project, debug, parse_event):
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

    result = run_dag_file(source, debug=debug)

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
    # A deployed task's log: the worker's startup in Pre Execute, the task, then Post Execute. A supervised
    # try is a worker's task process; in debug mode the run's own parse of the Dag file fills Pre Execute.
    # Installed listener plugins may log lines of their own in between. What the task printed reaches a
    # supervisor separately from its log events, so its place among them can vary.
    expected = [
        "::group::Pre Execute",
        "DAG bundles loaded: dags-folder",
        f"Filling up the DagBag from {source}",
        parse_event,
        "::endgroup::",
        "Done. Returned value was: hi",
        "::group::Post Execute",
        "Pushing xcom",
        "::endgroup::",
    ]
    assert [e["event"] for e in events if e["event"] in expected] == expected
    by_event = {e["event"]: e for e in events}
    assert by_event[parse_event]["bundle_name"] == "dags-folder"
    assert by_event[parse_event]["dag_file"] == "logged.py"
    assert isinstance(by_event[parse_event]["dag_file_parse_ms"], int)
    assert by_event["hello local log"]["logger"] == "task.stdout"
    assert len({e["ti_id"] for e in events}) == 1


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


@pytest.mark.parametrize("debug", [False, True], ids=["supervised", "debug"])
def test_failed_run_raises_with_result(project, capfd, debug):
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

    with pytest.raises(DagExecutionError, match=r"failed tasks: boom \(ValueError: boom\)$") as ctx:
        run_dag_file(source, debug=debug)

    assert ctx.value.result.task_states == {("boom", -1): "failed", ("after", -1): "upstream_failed"}
    assert ctx.value.result.failures == {("boom", -1): "ValueError: boom"}
    with pytest.raises(KeyError, match="task state: upstream_failed"):
        ctx.value.result.output("after")
    out, err = capfd.readouterr()
    # The traceback starts in the Dag file; Airflow's frames that ran the task stay in the task's log.
    assert f'  ✗ boom failed\nTraceback (most recent call last):\n  File "{source}", line ' in err
    assert re.search(
        r"\(\d+ frames of Airflow running the task are left out; the task's log has the full", err
    )
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
        r"  ↻ flaky failed attempt 1 of 2, retrying in [12]s: ConnectionError: try again\n  ✓ flaky \(try 2\)\n",
        err,
    )
    for noise in ("Traceback", "Task failed with exception", "No tasks to run"):
        assert noise not in out + err


@pytest.mark.parametrize(
    ("debug", "expected_state"),
    [
        pytest.param(False, "failed", id="supervised"),
        pytest.param(True, "success", id="debug"),
    ],
)
def test_module_state_starts_fresh_for_each_supervised_try(project, debug, expected_state):
    source = write_dag_file(
        project,
        "counter.py",
        """
        from datetime import timedelta
        from airflow.sdk import dag, task

        ATTEMPTS = 0

        @task(retries=2, retry_delay=timedelta(0))
        def counter():
            global ATTEMPTS
            ATTEMPTS += 1
            if ATTEMPTS < 3:
                raise ValueError(f"attempt {ATTEMPTS} in this process")
            return ATTEMPTS

        @dag(schedule=None)
        def counting():
            counter()

        workflow = counting()
        """,
    )

    try:
        result = run_dag_file(source, debug=debug)
    except DagExecutionError as e:
        result = e.result

    assert result.task_states == {("counter", -1): expected_state}
    assert query(project, "SELECT COUNT(*) FROM task_instance") == [(3,)]


def test_each_try_is_forked_from_the_runs_fork_server(project):
    source = write_dag_file(
        project,
        "family.py",
        """
        import psutil
        from airflow.sdk import dag, task

        @task
        def ancestors():
            return [parent.pid for parent in psutil.Process().parents()[:3]]

        @dag(schedule=None)
        def family():
            ancestors()

        workflow = family()
        """,
    )

    fork_server, run_process, caller = run_dag_file(source).output("ancestors")

    assert caller == os.getpid()
    assert len({fork_server, run_process, caller}) == 3


@mock.patch.dict(os.environ)
@mock.patch.object(runner.ForkServer, "start", autospec=True)
@pytest.mark.parametrize(("new_interpreter", "forks_tries"), [(False, True), (True, False)])
def test_tries_are_forked_unless_a_new_interpreter_is_configured(start, new_interpreter, forks_tries):
    with conf_vars({("core", "execute_tasks_new_python_interpreter"): str(new_interpreter)}):
        fork_server = runner.prepare_supervised_tries()

    assert start.called is forks_tries
    assert (fork_server is start.return_value) is forks_tries


def test_task_that_ends_its_process_fails_only_its_own_try(project, capfd):
    source = write_dag_file(
        project,
        "exits.py",
        """
        import os
        from airflow.sdk import dag, task

        @task
        def crash():
            print("about to exit")
            os._exit(3)

        @task
        def other():
            return 1

        @dag(schedule=None)
        def exits():
            crash()
            other()

        workflow = exits()
        """,
    )

    with pytest.raises(DagExecutionError) as ctx:
        run_dag_file(source)

    assert ctx.value.result.task_states == {("crash", -1): "failed", ("other", -1): "success"}
    assert ctx.value.result.output("other") == 1
    out, err = capfd.readouterr()
    assert "about to exit\n" in out
    assert "  ✗ crash failed\nProcess exited abnormally (exit_code=3)\n" in err


def test_deferred_task_resumes_after_its_trigger(project):
    source = write_dag_file(
        project,
        "deferring.py",
        """
        from datetime import timedelta

        from airflow.providers.standard.triggers.temporal import TimeDeltaTrigger
        from airflow.sdk import BaseOperator, dag


        class Waits(BaseOperator):
            def execute(self, context):
                self.defer(
                    trigger=TimeDeltaTrigger(timedelta(0)), method_name="resume", kwargs={"note": "kept"}
                )

            def resume(self, context, event=None, note=None):
                return [note, event is not None]


        @dag(schedule=None)
        def deferring():
            Waits(task_id="waits")


        workflow = deferring()
        """,
    )

    result = run_dag_file(source)

    assert result.output("waits") == ["kept", True]
    # A triggerer started without --queues, as the project's will be, leaves the trigger to this run.
    assert query(project, "SELECT queue FROM trigger") == [("local-run",)]
    log_file = (
        project / ".airflow" / "logs" / "dag_id=deferring" / f"run_id={result.run_id}" / "task_id=waits"
    )
    events = [json.loads(line) for line in (log_file / "attempt=1.log").read_text().splitlines()]
    loggers = [e.get("logger", "") for e in events]
    # Both process starts, and the trigger between them, log to the one attempt.
    assert [e["event"] for e in events].count("::group::Pre Execute") == 2
    assert any(name.startswith("airflow.providers.standard.triggers") for name in loggers)


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


def test_dag_file_below_the_project_root_imports_from_the_root(project):
    (project / "sub").mkdir()
    write_dag_file(project, "sub/helper.py", "VALUE = 'from helper'\n")
    dag_file = """
        from airflow.sdk import dag, task
        import helper

        @task
        def show():
            return helper.VALUE

        @dag(schedule=None)
        def helped():
            show()

        workflow = helped()
        """
    source = write_dag_file(project, "sub/pipeline.py", dag_file)

    with pytest.raises(
        LocalRunError,
        match=r"'helper' is next to pipeline.py, .* import it as sub\.helper, .*python -m sub\.pipeline",
    ):
        run_dag_file(source)

    write_dag_file(project, "sub/pipeline.py", dag_file.replace("import helper", "from sub import helper"))
    assert run_dag_file(source).output("show") == "from helper"


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


def write_project_secrets_backend(project: Path, backend: str, **backend_kwargs: str) -> None:
    # A JSON string is a TOML string too, but a JSON object is not a TOML table.
    kwargs = ", ".join(f"{key} = {json.dumps(value)}" for key, value in backend_kwargs.items())
    with (project / "pyproject.toml").open("a") as pyproject:
        pyproject.write(f"\n[tool.airflow.secrets]\nbackend = {json.dumps(backend)}\n")
        pyproject.write(f"backend_kwargs = {{ {kwargs} }}\n")


@pytest.mark.parametrize("debug", [False, True], ids=["supervised", "debug"])
def test_project_secrets_backend_is_looked_in_after_the_run_files(project, tmp_path, debug):
    backend_connections = tmp_path / "backend-connections.json"
    backend_connections.write_text(json.dumps({"warehouse": "sqlite://backend", "api": "http://backend"}))
    backend_variables = tmp_path / "backend-variables.json"
    backend_variables.write_text(json.dumps({"region": "eu", "tier": "dev"}))
    write_project_secrets_backend(
        project,
        "airflow.secrets.local_filesystem.LocalFilesystemBackend",
        connections_file_path=str(backend_connections),
        variables_file_path=str(backend_variables),
    )
    run_connections = tmp_path / "run-connections.json"
    run_connections.write_text(json.dumps({"api": "http://run"}))
    run_variables = tmp_path / "run-variables.json"
    run_variables.write_text(json.dumps({"tier": "local"}))
    source = write_dag_file(
        project,
        "secrets.py",
        """
        from airflow.sdk import Connection, Variable, dag, task

        REGION = Variable.get("region")

        @task
        def read():
            return [
                REGION,
                Variable.get("tier"),
                Connection.get("warehouse").host,
                Connection.get("api").host,
            ]

        @dag(schedule=None)
        def secrets():
            read()

        workflow = secrets()
        """,
    )

    result = run_dag_file(source, connections_file=run_connections, variables_file=run_variables, debug=debug)

    assert result.output("read") == ["eu", "local", "backend", "run"]


def test_project_secrets_backend_that_cannot_be_created_stops_the_run(project):
    write_project_secrets_backend(project, "missing_provider.secrets.Backend")
    source = write_dag_file(project, "pipeline.py", PIPELINE)

    with pytest.raises(
        LocalRunError,
        match=r"The secrets backend missing_provider\.secrets\.Backend that pyproject\.toml names could not "
        r"be set up: ModuleNotFoundError: No module named 'missing_provider'",
    ):
        run_dag_file(source)
    assert not (project / ".airflow" / "airflow.db").exists()


GROUPED = """
from airflow.sdk import dag, task, task_group


@task
def extract():
    return 1


@task_group
def transform(value):
    @task
    def add(number):
        return number + 1

    @task
    def scale(number):
        return number * 10

    return scale(add(value))


@task
def load(value):
    return value


@dag(schedule=None)
def grouped():
    load(transform(extract()))


workflow = grouped()
"""

CURRENT_TRIES = """
SELECT task_instance.task_id, task_instance.region_index, task_instance.try_number FROM task_instance
WHERE task_instance.working_set = 1 ORDER BY task_instance.task_id, task_instance.region_index
"""


def test_rerun_runs_the_selected_task_with_the_outputs_its_run_kept(project, capfd):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    first = run_dag_file(source)
    source.write_text(textwrap.dedent(PIPELINE).replace("return sum(values)", "return sum(values) * 10"))
    capfd.readouterr()

    rerun = run_dag_file(source, task_ids=["total"])

    err = capfd.readouterr().err
    assert f"Rerunning total in run {first.run_id}, with the outputs of double, numbers\n" in err
    assert "  ✓ total (try 2)\n" in err
    assert rerun.run_id == first.run_id
    assert rerun.output("total") == 120
    assert rerun.ran == {("total", -1)}
    assert [row for row in query(project, CURRENT_TRIES) if row[2] != 1] == [("total", -1, 2)]
    # The rerun's own job drove the run.
    assert query(project, RUN_JOBS) == [("example", "success", "LocalRunJob", "success")]
    assert query(project, "SELECT COUNT(*) FROM job") == [(2,)]


def test_rerun_of_a_mapped_task_and_what_feeds_it_expands_it_again(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    run_dag_file(source)

    rerun = run_dag_file(source, task_ids=["numbers"], include_downstream=True)

    assert rerun.ran == {("numbers", -1), ("double", 0), ("double", 1), ("double", 2), ("total", -1)}
    assert rerun.output("total") == 12


def test_rerun_after_a_structural_edit_moves_the_run_to_the_new_dag_version(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    run_dag_file(source)
    source.write_text(
        textwrap.dedent(PIPELINE).replace("@dag(schedule=None)", "@dag(schedule=None, tags=['edited'])")
    )

    run_dag_file(source, task_ids=["total"])

    assert query(
        project,
        "SELECT DISTINCT dag_version.version_number FROM dag_run "
        "JOIN dag_version ON dag_version.id = dag_run.created_dag_version_id",
    ) == [(2,)]


@pytest.mark.parametrize(
    ("selection", "expected_ran"),
    [
        pytest.param({"task_ids": [("double", 1)]}, {("double", 1)}, id="one-map-index"),
        pytest.param(
            {"task_ids": ["double"], "include_downstream": True},
            {("double", 0), ("double", 1), ("double", 2), ("total", -1)},
            id="downstream",
        ),
        pytest.param(
            {"task_ids": ["total"], "include_upstream": True},
            {("numbers", -1), ("double", 0), ("double", 1), ("double", 2), ("total", -1)},
            id="upstream",
        ),
    ],
)
def test_rerun_selects_relatives_as_clear_does(project, selection, expected_ran):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    run_dag_file(source)

    rerun = run_dag_file(source, **selection)

    assert rerun.ran == expected_ran
    assert rerun.output("total") == 12


def test_rerun_of_a_task_group_reruns_each_of_its_tasks(project):
    source = write_dag_file(project, "grouped.py", GROUPED)
    run_dag_file(source)

    rerun = run_dag_file(source, task_group_ids=["transform"])

    assert rerun.ran == {("transform.add", -1), ("transform.scale", -1)}
    assert rerun.output("load") == 20


def test_rerun_uses_the_latest_run_that_has_the_inputs(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    first = run_dag_file(source)
    source.write_text(textwrap.dedent(PIPELINE).replace("return number * 2", "raise ValueError('boom')"))
    with pytest.raises(DagExecutionError) as failed:
        run_dag_file(source)

    assert run_dag_file(source, task_ids=["total"]).run_id == first.run_id
    with pytest.raises(LocalRunError, match="lacks the outputs total needs: double did not succeed"):
        run_dag_file(source, task_ids=["total"], run_id=failed.value.result.run_id)


@pytest.fixture(scope="module")
def finished_project(tmp_path_factory) -> Path:
    """A project with one finished run of PIPELINE, for reruns refused before they change anything."""
    project = tmp_path_factory.mktemp("finished")
    (project / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0"\n')
    run_dag_file(write_dag_file(project, "pipeline.py", PIPELINE))
    return project


@pytest.mark.parametrize(
    ("selection", "match"),
    [
        pytest.param(
            {"task_ids": ["totl"]}, "Dag 'example' has no task 'totl'. Did you mean 'total'?", id="task"
        ),
        pytest.param({"task_group_ids": ["nope"]}, "Dag 'example' has no task group 'nope'.$", id="group"),
        pytest.param({"task_ids": [("total", 3)]}, "Task 'total' is not mapped", id="not-mapped"),
        pytest.param(
            {"task_ids": [("double", 7)]}, r"has no map index 7 in run \S+; it has 0, 1, 2", id="map-index"
        ),
        pytest.param(
            {"task_ids": ["total"], "run_id": "nope"}, "Dag 'example' has no run 'nope'", id="run-id"
        ),
    ],
)
def test_rerun_of_what_the_dag_or_run_lacks_is_refused(finished_project, selection, match):
    with pytest.raises(LocalRunError, match=match):
        run_dag_file(finished_project / "pipeline.py", **selection)


SKIPPED_TRIES = """
SELECT task_instance.task_id, task_instance.start_date IS NULL, task_instance_note.content FROM task_instance
LEFT JOIN task_instance_note ON task_instance_note.ti_id = task_instance.id
WHERE task_instance.run_id = '{run_id}' AND task_instance.state = 'skipped' ORDER BY task_instance.task_id
"""


@pytest.mark.parametrize(
    ("task_id", "heading", "expected_ran", "skipped"),
    [
        pytest.param(
            "total",
            "No earlier run has the outputs total needs; running double, numbers first, in run ",
            {("numbers", -1), ("double", 0), ("double", 1), ("double", 2), ("total", -1)},
            ["nothing"],
            id="needs-inputs",
        ),
        pytest.param(
            "numbers",
            "No earlier run to rerun numbers in; running numbers in run ",
            {("numbers", -1)},
            ["double", "nothing", "total"],
            id="no-inputs",
        ),
    ],
)
def test_selection_without_an_earlier_run_runs_in_a_new_run(
    project, capfd, task_id, heading, expected_ran, skipped
):
    result = run_dag_file(write_dag_file(project, "pipeline.py", PIPELINE), task_ids=[task_id])

    assert heading + result.run_id in capfd.readouterr().err
    assert result.ran == expected_ran
    assert result.state == "success"
    # Skipped without a start date, unlike a task the Dag skips itself.
    assert query(project, SKIPPED_TRIES.format(run_id=result.run_id)) == [
        (task, 1, f"Not selected: {task_id} did not need it") for task in skipped
    ]
    assert query(project, "SELECT content FROM dag_run_note") == [(f"Selected: {task_id}",)]


def test_selection_with_a_new_conf_runs_in_a_new_run(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    first = run_dag_file(source)

    result = run_dag_file(source, task_ids=["total"], run_conf={"n": 1})

    assert result.run_id != first.run_id
    assert ("numbers", -1) in result.ran
    assert query(project, f"SELECT conf FROM dag_run WHERE run_id = '{result.run_id}'") == [('{"n": 1}',)]


def test_selection_without_history_runs_in_a_new_run_with_the_tasks_it_needs(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    first = run_dag_file(source)

    result = run_dag_file(source, task_ids=["total"], keep_history=False)

    assert result.run_id != first.run_id
    assert result.ran == {("numbers", -1), ("double", 0), ("double", 1), ("double", 2), ("total", -1)}
    assert query(project, "SELECT run_id FROM dag_run") == [(first.run_id,)]


def test_task_a_selection_left_out_is_not_an_input_of_a_later_rerun(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    first = run_dag_file(source, task_ids=["numbers"])

    # Its upstream ran there, so the left-out task reruns in that run.
    assert run_dag_file(source, task_ids=["nothing"]).run_id == first.run_id
    # double was left out, so that run has no outputs for total.
    assert run_dag_file(source, task_ids=["total"]).run_id != first.run_id


BRANCHING = """
from airflow.sdk import dag, task


@task.branch
def choose():
    return "left"


@task
def left():
    return 1


@task
def right():
    return 2


@task(trigger_rule="none_failed")
def join():
    return "joined"


@dag(schedule=None)
def branching():
    chosen, sides = choose(), [left(), right()]
    chosen >> sides
    sides >> join()


workflow = branching()
"""


def test_side_a_branch_skipped_still_lets_its_join_rerun_in_place(project):
    source = write_dag_file(project, "branching.py", BRANCHING)
    first = run_dag_file(source)
    assert first.task_states[("right", -1)] == "skipped"

    assert run_dag_file(source, task_ids=["join"]).run_id == first.run_id


RESOURCES = """
from airflow.sdk import dag, task


@task
def create():
    return "resource"


@task
def use(resource):
    return resource


@task
def delete():
    pass


@task
def other():
    pass


@dag(schedule=None)
def resources():
    resource = create()
    use(resource) >> delete().as_teardown(setups=resource)
    other()


workflow = resources()
"""


def test_new_run_for_a_selection_runs_the_teardown_of_its_setup(project, capfd):
    result = run_dag_file(write_dag_file(project, "resources.py", RESOURCES), task_ids=["use"])

    # The teardown runs after the selected task, not first.
    assert f"running create first, in run {result.run_id}" in capfd.readouterr().err
    assert result.ran == {("create", -1), ("use", -1), ("delete", -1)}
    assert result.task_states[("other", -1)] == "skipped"


def test_one_map_index_is_refused_in_a_new_run(project):
    with pytest.raises(
        LocalRunError, match="double\\[1\\] can be rerun only in a run where double has expanded"
    ):
        run_dag_file(write_dag_file(project, "pipeline.py", PIPELINE), task_ids=[("double", 1)])


def test_rerun_in_a_run_still_running_or_without_the_task_is_refused(project):
    source = write_dag_file(project, "pipeline.py", PIPELINE)
    first = run_dag_file(source)
    source.write_text(
        textwrap.dedent(PIPELINE)
        .replace("    nothing()\n", "    nothing() >> extra()\n")
        .replace("@dag(schedule=None)", EXTRA + "@dag(schedule=None)")
    )

    with pytest.raises(LocalRunError, match="has no extra: the Dag gained it after that run"):
        run_dag_file(source, task_ids=["extra"], run_id=first.run_id)

    with sqlite3.connect(project / ".airflow" / "airflow.db") as conn:
        conn.execute("UPDATE dag_run SET state = 'running'")
    with pytest.raises(LocalRunError, match="is still running; rerun its tasks once it has finished"):
        run_dag_file(source, task_ids=["total"], run_id=first.run_id)


EXTRA = """
@task
def extra():
    pass


"""


def write_run_request(tmp_path: Path, source: Path, *, debug: bool) -> tuple[Path, Path]:
    """Write a request as the launcher does; return its path and the path the result will be written to."""
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
                "debug": debug,
                "result_path": str(result_path),
                "started_at": time.monotonic(),
            }
        )
    )
    return request, result_path


def start_sleepy_run(project: Path, tmp_path: Path, *, debug: bool) -> tuple[subprocess.Popen, Path, Path]:
    """
    Start a run of a slow task in its own process, as the launcher does, and wait until the task is running.

    Returns the run's process, the file its result will be written to, and the file holding the task's pid.
    """
    started = tmp_path / "started"
    source = write_dag_file(
        project,
        "sleepy.py",
        f"""
        import os
        import time
        from pathlib import Path
        from airflow.sdk import dag, task

        @task
        def slow():
            Path({str(started)!r}).write_text(str(os.getpid()))
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
    child, result_path = start_run(project, tmp_path, source, started, debug=debug)
    return child, result_path, started


def start_run(
    project: Path, tmp_path: Path, source: Path, started: Path, *, debug: bool
) -> tuple[subprocess.Popen, Path]:
    """Start a run in its own process, as the launcher does, and wait until its task writes to ``started``."""
    request, result_path = write_run_request(tmp_path, source, debug=debug)
    child = subprocess.Popen(
        [sys.executable, "-m", CHILD_MODULE, str(request)],
        env=build_child_environment(os.environ, home=prepare_project_home(project), root=project),
    )
    deadline = time.monotonic() + 120
    while not started.exists() or not started.read_text():
        assert child.poll() is None, "child exited before the task started"
        assert time.monotonic() < deadline, "task did not start"
        time.sleep(0.2)
    return child, result_path


@pytest.mark.parametrize("debug", [False, True], ids=["supervised", "debug"])
def test_interrupted_child_records_a_failed_run(project, tmp_path, debug):
    child, result_path, started = start_sleepy_run(project, tmp_path, debug=debug)

    child.send_signal(signal.SIGINT)

    assert child.wait(timeout=60) == 130
    payload = pickle.loads(result_path.read_bytes())
    assert payload["cancelled"] is True
    assert payload["state"] == "failed"
    assert query(project, "SELECT state FROM dag_run") == [("failed",)]
    assert query(project, "SELECT state FROM job") == [("success",)]
    # Without stopping, the all_done task would run after the interrupted one.
    assert dict(query(project, "SELECT task_id, state FROM task_instance")) == {
        "slow": "failed",
        "after": "skipped",
    }
    # A supervised try runs in a process group of its own, which the interrupt did not reach directly.
    with pytest.raises(ProcessLookupError):
        os.kill(int(started.read_text()), 0)


# Each starts a command in a session of its own, which the run's interrupt does not reach.
STARTS_A_COMMAND = {
    # The command holds the try's sockets, so a supervised run waits for it.
    "bash-operator": """
        from airflow.providers.standard.operators.bash import BashOperator
        from airflow.sdk import dag

        @dag(schedule=None)
        def starts_a_command():
            BashOperator(task_id="starts", bash_command="echo $$ > {started}; exec sleep 120")

        workflow = starts_a_command()
        """,
    # Unlike BashOperator's, nothing in the task stops the command when it is killed.
    "detached-process": """
        import subprocess
        import time
        from pathlib import Path
        from airflow.sdk import dag, task

        @task
        def starts():
            command = subprocess.Popen(
                ["sleep", "120"],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            Path({started!r}).write_text(str(command.pid))
            time.sleep(120)

        @dag(schedule=None)
        def starts_a_command():
            starts()

        workflow = starts_a_command()
        """,
}


@pytest.mark.parametrize("starts_a_command", list(STARTS_A_COMMAND.values()), ids=list(STARTS_A_COMMAND))
@pytest.mark.parametrize("debug", [False, True], ids=["supervised", "debug"])
def test_interrupt_stops_the_command_a_task_started(project, tmp_path, starts_a_command, debug):
    started = tmp_path / "started"
    source = write_dag_file(project, "starts_a_command.py", starts_a_command.format(started=str(started)))
    child, result_path = start_run(project, tmp_path, source, started, debug=debug)
    command = psutil.Process(int(started.read_text()))

    child.send_signal(signal.SIGINT)

    assert child.wait(timeout=60) == 130
    assert pickle.loads(result_path.read_bytes())["cancelled"] is True
    command.wait(timeout=10)


BREAKPOINT_DAG = """
from airflow.sdk import dag, task

@task
def stop_here():
    x = 41
    breakpoint()
    return x + 1

@dag(schedule=None)
def stopping():
    stop_here()

workflow = stopping()
"""


def test_breakpoint_in_a_supervised_try_says_how_to_debug(project, monkeypatch):
    monkeypatch.delenv("PYTHONBREAKPOINT", raising=False)
    source = write_dag_file(project, "stopping.py", BREAKPOINT_DAG)

    with pytest.raises(
        DagExecutionError,
        match=r"stop_here \(RuntimeError: breakpoint\(\) needs the task to run in the run's own process.*"
        r"\.run\(debug=True\) or airflow run --debug\.\)$",
    ):
        run_dag_file(source)


def test_breakpoint_hook_of_the_users_own_is_kept(project, monkeypatch):
    monkeypatch.setenv("PYTHONBREAKPOINT", "0")

    assert run_dag_file(write_dag_file(project, "stopping.py", BREAKPOINT_DAG)).output("stop_here") == 42


def test_breakpoint_in_debug_mode_opens_the_debugger(project, tmp_path):
    source = write_dag_file(project, "stopping.py", BREAKPOINT_DAG)
    request, _ = write_run_request(tmp_path, source, debug=True)
    env = build_child_environment(os.environ, home=prepare_project_home(project), root=project)
    env.pop("PYTHONBREAKPOINT", None)

    child = subprocess.run(
        [sys.executable, "-m", CHILD_MODULE, str(request)],
        env=env,
        input="p x * 10\nc\n",
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert child.returncode == 0, child.stderr
    assert "(Pdb) 410" in child.stdout


def test_run_whose_process_ended_early_is_recorded_failed_by_the_next_run(project, capfd):
    source = write_dag_file(
        project,
        "exits.py",
        """
        import os
        from airflow.sdk import dag, task

        @task
        def crash():
            os._exit(3)

        @task
        def other():
            return 1

        @dag(schedule=None)
        def exits():
            crash() >> other()

        workflow = exits()
        """,
    )
    # In debug mode the task runs in the run's process, so ending it ends the run's process too.
    with pytest.raises(LocalRunError, match="exited with code 3 without reporting a result"):
        run_dag_file(source, debug=True)
    ((stuck_run, stuck_state),) = query(project, "SELECT run_id, state FROM dag_run")
    assert stuck_state == "running"

    run_dag_file(write_dag_file(project, "pipeline.py", PIPELINE))

    assert query(project, RUN_JOBS) == [
        ("exits", "failed", "LocalRunJob", "failed"),
        ("example", "success", "LocalRunJob", "success"),
    ]
    assert dict(query(project, "SELECT task_id, state FROM task_instance WHERE dag_id = 'exits'")) == {
        "crash": "failed",
        "other": "skipped",
    }
    expected = f"Recorded run {stuck_run} of Dag 'exits' as failed: its process ended before the run finished"
    assert expected in capfd.readouterr().err
    assert not list((project / ".airflow" / "runs").iterdir())


def test_run_is_recorded_failed_only_once_its_process_is_gone(project, tmp_path):
    child, _, _ = start_sleepy_run(project, tmp_path, debug=True)
    try:
        pipeline = write_dag_file(project, "pipeline.py", PIPELINE)
        run_dag_file(pipeline)
        assert query(project, "SELECT state FROM dag_run WHERE dag_id = 'sleepy'") == [("running",)]

        child.kill()
        child.wait(timeout=60)
        run_dag_file(pipeline)
    finally:
        child.kill()
        child.wait()

    assert query(project, "SELECT state FROM dag_run WHERE dag_id = 'sleepy'") == [("failed",)]


@pytest.mark.parametrize(
    ("exists", "held", "expected"),
    [
        pytest.param(False, False, False, id="missing"),
        pytest.param(True, False, False, id="free"),
        pytest.param(True, True, True, id="held"),
    ],
)
def test_is_run_lock_held(tmp_path, exists, held, expected):
    path = tmp_path / "1.lock"
    if exists:
        path.touch()
    with open(path if exists else tmp_path / "other", "w") as holder:
        if held:
            fcntl.flock(holder, fcntl.LOCK_EX)

        assert runner.is_run_lock_held(path) is expected


@mock.patch.object(runner, "lock_run", autospec=True)
@mock.patch.object(runner, "fail_abandoned_runs", autospec=True, return_value=[])
@mock.patch.object(runner, "create_dag_run", autospec=True)
@mock.patch.object(runner, "register_dags", autospec=True)
def test_start_run_retries_in_a_new_transaction_when_the_database_is_locked(
    register, create, fail_abandoned, lock, tmp_path
):
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
    assert fail_abandoned.call_count == 2
    lock.assert_called_once_with(tmp_path, mock.sentinel.dag_run)
    session.rollback.assert_called_once_with()


class TestEnsureDatabase:
    @pytest.mark.db_test
    @mock.patch.object(runner, "upgradedb", autospec=True)
    @mock.patch.object(runner, "initdb", autospec=True)
    @mock.patch.object(runner, "_get_script_object", autospec=True)
    @mock.patch.object(runner, "read_schema_revision", autospec=True)
    @pytest.mark.parametrize(
        ("current", "expected_call", "reads_migrations"),
        [
            pytest.param(None, "initdb", False, id="new-database"),
            pytest.param(runner.get_newest_revision(), None, False, id="newest"),
            pytest.param("head", None, True, id="head-missing-from-revision-map"),
            pytest.param("older", "upgradedb", True, id="older"),
        ],
    )
    def test_brings_schema_to_this_version(
        self, read_revision, get_script, initdb, upgradedb, tmp_path, current, expected_call, reads_migrations
    ):
        read_revision.return_value = current
        get_script.return_value.get_heads.return_value = ["head"]

        runner.ensure_database(tmp_path)

        assert initdb.called is (expected_call == "initdb")
        assert upgradedb.called is (expected_call == "upgradedb")
        assert get_script.called is reads_migrations

    @pytest.mark.db_test
    @mock.patch.object(runner, "upgradedb", autospec=True)
    @mock.patch.object(runner, "_get_script_object", autospec=True)
    @mock.patch.object(runner, "read_schema_revision", autospec=True, return_value="unknown")
    def test_unknown_revision_is_refused(self, _, get_script, upgradedb, tmp_path):
        get_script.return_value.get_heads.return_value = ["head"]
        get_script.return_value.get_revision.side_effect = CommandError("no such revision")

        with pytest.raises(runner.LocalRunSetupError, match="newer Airflow version"):
            runner.ensure_database(tmp_path)

        upgradedb.assert_not_called()


def test_newest_revision_is_the_migrations_head():
    assert runner._get_script_object().get_heads() == [runner.get_newest_revision()]


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
            {"cancelled": False, "state": "success", "task_states": {}},
            "Succeeded in 1.5s (4.2s total)",
            id="success",
        ),
        pytest.param(
            {
                "cancelled": False,
                "state": "failed",
                "task_states": {("b", -1): "failed", ("a", 2): "failed", ("c", -1): "upstream_failed"},
            },
            "Failed in 1.5s (4.2s total): a[2], b",
            id="failed",
        ),
        pytest.param(
            {"cancelled": True, "state": "failed", "task_states": {}},
            "Cancelled after 1.5s (4.2s total)",
            id="cancelled",
        ),
    ],
)
def test_summarize_run(payload, expected):
    summary = runner.summarize_run(payload, 1.49, 4.16, Path("/p/.airflow"))

    assert summary == f"{expected}. History: /p/.airflow"


def test_summarize_run_links_to_the_run_while_the_ui_runs():
    payload = {"cancelled": False, "state": "success", "task_states": {}}
    run_url = "http://127.0.0.1:8080/dags/example/runs/manual__1"

    summary = runner.summarize_run(payload, 1.49, 4.16, Path("/p/.airflow"), run_url=run_url)

    assert summary == f"Succeeded in 1.5s (4.2s total). View it at {run_url}"


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
        pytest.param("up_for_retry", True, None, "  ✗ load cancelled", id="cancelled-with-retries-left"),
        pytest.param("skipped", False, None, "  · load skipped", id="other"),
    ],
)
def test_report_task(capsys, state, cancelled, retry_in, expected):
    ti = mock.Mock(spec=TaskInstance, task_id="load", map_index=-1, try_number=1, max_tries=2)
    failure = TaskFailure(summary="ValueError: boom", details="Traceback ...")

    runner.report_task(ti, state, failure, cancelled=cancelled, retry_in=retry_in)

    assert capsys.readouterr().err == f"{expected}\n"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        pytest.param("success", "  ✓ load (try 2)", id="success"),
        pytest.param("failed", "  ✗ load (try 2) failed", id="failed"),
        pytest.param(
            "up_for_retry", "  ↻ load failed attempt 2 of 3, retrying: ValueError: boom", id="retry"
        ),
    ],
)
def test_report_task_numbers_a_later_try(capsys, state, expected):
    ti = mock.Mock(spec=TaskInstance, task_id="load", map_index=-1, try_number=2, max_tries=2)
    failure = TaskFailure(summary="ValueError: boom", details="Traceback ...")

    runner.report_task(ti, state, failure, cancelled=False, retry_in=datetime.timedelta(0))

    assert capsys.readouterr().err.splitlines()[0] == expected


def test_report_task_shows_the_failure_that_ended_the_task(capsys):
    ti = mock.Mock(spec=TaskInstance, task_id="load", map_index=3, try_number=1)
    failure = TaskFailure(
        summary="ValueError: boom", details="Traceback (most recent call last):\nValueError: boom"
    )

    runner.report_task(ti, "failed", failure, cancelled=False)

    assert (
        capsys.readouterr().err
        == "  ✗ load[3] failed\nTraceback (most recent call last):\nValueError: boom\n"
    )


@mock.patch.object(runner.settings, "dispose_async_engine", autospec=True)
@mock.patch.object(runner, "configure_local_run_logging", autospec=True)
@mock.patch.object(runner, "prepare_supervised_tries", autospec=True)
@mock.patch.object(runner, "run_requested_dag", autospec=True, side_effect=runner.LocalRunSetupError("nope"))
@pytest.mark.parametrize(("debug", "forks_tries"), [(False, True), (True, False)])
def test_execute_ends_fork_server_and_disposes_async_engine_even_when_setup_fails(
    _, prepare, configure_logging, mock_dispose, debug, forks_tries
):
    with pytest.raises(runner.LocalRunSetupError):
        runner.execute({"debug": debug})

    assert prepare.called is forks_tries
    assert prepare.return_value.close.called is forks_tries
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
