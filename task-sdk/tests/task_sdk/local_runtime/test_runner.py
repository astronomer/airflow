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

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import textwrap
import time
from contextlib import closing, suppress
from pathlib import Path
from unittest import mock

import psutil
import pytest

from airflow.sdk.exceptions import LocalRunConfigError, LocalRunUsageError
from airflow.sdk.execution_time.coordinator import BaseCoordinator, CoordinatorManager
from airflow.sdk.local_runtime import runner


@pytest.fixture
def project(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "pipeline.py").write_text(
        textwrap.dedent(
            """
            from airflow.sdk import dag, task, get_current_context

            @task
            def produce():
                raise RuntimeError("Upstream task must never execute")

            @task(retries=3)
            def consume(value):
                context = get_current_context()
                store = context["task_state_store"]
                previous = store.get("count", 0)
                store.set("count", previous + 1)
                return {"value": value, "count": previous + 1, "run_id": context["run_id"]}

            @dag(schedule=None)
            def sample():
                consume(produce())

            sample()
            """
        )
    )
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        textwrap.dedent(
            """
            import builtins
            import os
            import sys
            import sqlalchemy
            import sqlite3

            def forbidden(*args, **kwargs):
                raise AssertionError("Database or Execution API construction is forbidden")

            sqlalchemy.create_engine = forbidden
            sqlalchemy.engine.create_engine = forbidden
            original_connect = sqlite3.connect

            def connect(database, *args, **kwargs):
                if str(database).removeprefix("file:") == os.environ.get("NO_DB_TEST_TOOL_DATABASE"):
                    return original_connect(database, *args, **kwargs)
                return forbidden()

            sqlite3.connect = connect
            original_import = builtins.__import__

            def guarded_import(name, *args, **kwargs):
                result = original_import(name, *args, **kwargs)
                client_module = sys.modules.get("airflow.sdk.api.client")
                if client_module is not None and hasattr(client_module, "Client"):
                    client_module.Client.__init__ = forbidden
                api_module = sys.modules.get("airflow.api_fastapi.execution_api.app")
                if api_module is not None and hasattr(api_module, "InProcessExecutionAPI"):
                    api_module.InProcessExecutionAPI.__init__ = forbidden
                return result

            builtins.__import__ = guarded_import
            """
        )
    )
    return tmp_path


def run_cli(project, *arguments, timeout=45, module=None, no_db_flag="--no-db", as_script=False):
    env = {
        **os.environ,
        "PYTHONPATH": str(project / "guard") + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "AIRFLOW_HOME": str(project / "ambient"),
        "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN": "invalid-metadata-url",
        "AIRFLOW__CORE__EXECUTION_API_SERVER_URL": "http://production.invalid/execution/",
    }
    # The SDK test harness suppresses package initialization; a CLI test must exercise it.
    env.pop("_AIRFLOW__AS_LIBRARY", None)
    source = str(project / "pipeline.py")
    if as_script:
        command = [sys.executable, source]
    elif module:
        command = [sys.executable, "-m", module, "run", source]
    else:
        command = [str(Path(sys.executable).with_name("airflow")), "run", source]
    return subprocess.run(
        [*command, no_db_flag, *arguments],
        env=env,
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


@pytest.mark.parametrize(
    ("module", "flag"),
    [
        (None, "--no-db"),
        (None, "--no-d"),
        ("airflow", "--no-db"),
        ("airflow", "--no-d"),
        ("airflow.__main__", "--no-db"),
    ],
)
def test_selected_task_runs_without_database_or_api(project, module, flag):
    result = run_cli(project, "--task", "consume", "--input", "produce=3", module=module, no_db_flag=flag)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "'value': 3" in result.stdout
    assert "'count': 1" in result.stdout
    assert "Upstream task must never execute" not in result.stdout + result.stderr
    assert not (project / ".airflow").exists()
    assert not (project / "ambient").exists()
    assert not list(project.rglob("airflow.db"))


def test_dag_file_run_as_a_script_runs_without_database_or_api(project):
    source = project / "pipeline.py"
    source.write_text(
        source.read_text().replace(
            "\nsample()\n",
            '\nworkflow = sample()\n\nif __name__ == "__main__":\n    print(workflow.run().output("consume"))\n',
        )
    )

    result = run_cli(project, "--task", "consume", "--input", "produce=3", as_script=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "'value': 3" in result.stdout
    assert not (project / "ambient").exists()
    assert not list(project.rglob("airflow.db"))


@pytest.mark.parametrize("run_conf", [None, {}, {"limit": 7}])
def test_default_conf_is_a_mapping(project, run_conf):
    write_task(project, "return get_current_context()['dag_run'].conf.get('limit', 42)")
    arguments = ["--conf", json.dumps(run_conf)] if run_conf is not None else []
    result = run_cli(project, "--task", "check", *arguments)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"check = {(run_conf or {}).get('limit', 42)}" in result.stdout


@pytest.mark.parametrize("read_during_task", [False, True])
def test_source_defined_output_class_is_allowed_only_after_execution(project, read_during_task):
    (project / "pipeline.py").write_text(
        textwrap.dedent(
            f"""
            from dataclasses import dataclass
            from airflow.sdk import dag, task, get_current_context
            @dataclass
            class Summary:
                value: int
            @dag(schedule=None)
            def sample():
                @task
                def check():
                    value = Summary(42)
                    if {read_during_task}:
                        ti = get_current_context()["ti"]
                        ti.xcom_push(key="custom", value=value)
                        return ti.xcom_pull(task_ids=ti.task_id, key="custom")
                    return value
                check()
            sample()
            """
        )
    )
    result = run_cli(project, "--task", "check")
    assert result.returncode == (1 if read_during_task else 0), result.stdout + result.stderr
    if read_during_task:
        assert "was not found in allow list" in result.stderr
    else:
        assert "check = Summary(value=42)" in result.stdout


@pytest.mark.parametrize("dag_id", [None, "missing"])
def test_empty_dag_file_is_a_file_error(project, dag_id):
    (project / "pipeline.py").write_text("")
    arguments = ["--dag-id", dag_id] if dag_id else []
    result = run_cli(project, "--task", "check", *arguments)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "No Dags found" in result.stderr
    assert "module level" in result.stderr


def write_task(project, body, *, arguments="", dependencies="", decorator=""):
    source = (
        "from airflow.sdk import dag, task, get_current_context, Connection, Variable\n"
        "@task\n"
        "def upstream():\n"
        "    raise RuntimeError('Upstream task must never execute')\n"
        f"@task({decorator})\n"
        f"def check({arguments}):\n"
        + textwrap.indent(textwrap.dedent(body).strip(), "    ")
        + "\n@dag(schedule=None)\n"
        "def sample():\n" + textwrap.indent(dependencies or "check()", "    ") + "\nsample()\n"
    )
    (project / "pipeline.py").write_text(source)


def test_output_is_shown_in_full_up_to_a_line(project):
    write_task(project, "return 'Closed ticket 1; ticket 2 is still broken, so it stays open.'")

    result = run_cli(project, "--task", "check")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "check = 'Closed ticket 1; ticket 2 is still broken, so it stays open.'" in result.stdout


def test_explicit_null_input_is_present(project):
    result = run_cli(project, "--task", "consume", "--input", "produce=null")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "'value': None" in result.stdout


@pytest.mark.parametrize("provided", [False, True])
def test_dynamic_xcom_requires_explicit_input(project, provided):
    write_task(
        project,
        "return get_current_context()['ti'].xcom_pull(task_ids='upstream')",
        dependencies="upstream() >> check()",
    )
    options = ["--input", "upstream=7"] if provided else []
    result = run_cli(project, "--task", "check", *options)
    assert result.returncode == (0 if provided else 1), result.stdout + result.stderr
    assert ("check = 7" if provided else "No input for 'upstream'") in result.stdout + result.stderr, (
        result.stdout + result.stderr
    )


def test_connections_variables_templates_and_masked_tool_logs(project):
    (project / "connections.json").write_text(
        '{"warehouse": {"conn_type": "http", "host": "example.test", "password": "local-test-secret-987"}}'
    )
    (project / "variables.json").write_text('{"region": "eu"}')
    write_task(
        project,
        """
        import structlog
        connection = Connection.get("warehouse")
        print(connection.password)
        structlog.get_logger("airflow.providers.common.ai.tools").info("::group::Tool call: inspect", result="ok")
        return {"host": connection.host, "region": Variable.get("region"), "rendered": rendered}
        """,
        arguments="rendered",
        dependencies='check("{{ var.value.region }}-{{ params.suffix }}")',
    )
    result = run_cli(
        project,
        "--task",
        "check",
        "--connections-file",
        str(project / "connections.json"),
        "--variables-file",
        str(project / "variables.json"),
        "--conf",
        '{"suffix": "ready"}',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "eu-ready" in result.stdout
    assert "Tool call: inspect" in result.stdout + result.stderr
    assert "local-test-secret-987" not in result.stdout + result.stderr


def test_terminal_shows_the_whole_task_log(project):
    write_task(
        project,
        """
        import structlog
        operator_log = structlog.get_logger("airflow.task.operators.example.ExampleOperator")
        operator_log.info("::group::Tool call: inspect")
        structlog.get_logger("airflow.task.hooks.example.ExampleHook").info("Running statement: SELECT 1")
        operator_log.info("Tool inspect returned in 0.01s")
        operator_log.info("::endgroup::")
        print("printed by the task")
        return 7
        """,
    )
    result = run_cli(project, "--task", "check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "check | Tool call: inspect\n"
        "  check |   ExampleHook: Running statement: SELECT 1\n"
        "  check |   Tool inspect returned in 0.01s\n"
    ) in result.stderr
    assert "check | _PythonDecoratedOperator: Done. Returned value was: 7" in result.stderr
    assert "printed by the task" in result.stdout + result.stderr
    for hidden in (
        "::group::",
        "::endgroup::",
        "Pre Execute",
        "Pushing xcom",
        "Filling up the DagBag",
    ):
        assert hidden not in result.stdout + result.stderr


def test_async_state_operations_and_clear(project):
    write_task(
        project,
        """
        import asyncio
        async def exercise():
            store = get_current_context()["task_state_store"]
            await store.aset("value", {"n": 4})
            value = await store.aget("value")
            await store.adelete("value")
            missing = await store.aget("value", "missing")
            await store.aset("other", 5)
            await store.aclear()
            return [value, missing, await store.aget("other", "cleared")]
        return asyncio.run(exercise())
        """,
    )
    result = run_cli(project, "--task", "check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[{'n': 4}, 'missing', 'cleared']" in result.stdout


def test_failure_runs_one_attempt(project):
    write_task(
        project,
        """
        from pathlib import Path
        with Path("attempts.txt").open("a") as stream:
            stream.write("attempt\\n")
        raise ValueError("expected-task-failure")
        """,
        decorator="retries=3",
    )
    result = run_cli(project, "--task", "check")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "expected-task-failure" in result.stdout + result.stderr
    assert (project / "attempts.txt").read_text() == "attempt\n"


def test_historical_context_fails_at_use(project):
    write_task(project, 'return str(get_current_context()["prev_start_date_success"])')
    result = run_cli(project, "--task", "check")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "GetPrevSuccessfulDagRun is not supported" in result.stdout + result.stderr


def test_parse_error_is_distinct(project):
    (project / "pipeline.py").write_text("raise ValueError('expected-import-failure')\n")
    result = run_cli(project, "--task", "check")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "expected-import-failure" in result.stderr


def test_missing_input_fails_without_running_upstream(project):
    result = run_cli(project, "--task", "consume")

    assert result.returncode == 2, result.stdout + result.stderr
    assert "No input for 'produce'" in result.stderr
    assert "Upstream task must never execute" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--task", "consume", "--task", "produce"],
        ["--task", "consume[0]"],
        ["--task", "consume", "--upstream"],
        ["--task", "consume", "--downstream"],
        ["--task", "consume", "--group", "group"],
        ["--task", "consume", "--run-id", "old"],
        ["--task", "consume", "--debug"],
        ["--task", "consume", "--keep-task-state"],
    ],
)
def test_invalid_selection(project, arguments):
    result = run_cli(project, *arguments)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "--no-db" in result.stderr


def test_explicit_checkpoint_resume_and_default_reset(project):
    state = project / "checkpoint.json"
    arguments = ["--task", "consume", "--input", "produce=3", "--state-file", str(state)]
    first = run_cli(project, *arguments)
    resumed = run_cli(project, *arguments, "--keep-task-state")
    fresh = run_cli(project, *arguments)

    for result in (first, resumed, fresh):
        assert result.returncode == 0, result.stdout + result.stderr
    assert "'count': 1" in first.stdout
    assert "'count': 2" in resumed.stdout
    assert "'count': 1" in fresh.stdout
    assert not list(project.rglob("airflow.db"))


def test_execution_timeout_does_not_retry(project):
    write_task(
        project,
        "import time; time.sleep(60)",
        decorator="execution_timeout=__import__('datetime').timedelta(seconds=0.2), retries=3",
    )
    result = run_cli(project, "--task", "check")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "timeout" in (result.stdout + result.stderr).lower()


@pytest.mark.parametrize("interrupt", [None, "cli", "terminal"])
def test_owned_processes_are_cleaned_up(project, interrupt):
    write_task(
        project,
        f"""
        import json
        import os
        import signal
        import subprocess
        import sys
        import time
        from pathlib import Path
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        Path("pids.ready").write_text(json.dumps([os.getpid(), child.pid]))
        Path("pids.ready").replace("pids.json")
        {"time.sleep(60)" if interrupt else 'return "finished"'}
        """,
    )
    process = subprocess.Popen(
        [
            str(Path(sys.executable).with_name("airflow")),
            "run",
            str(project / "pipeline.py"),
            "--no-db",
            "--task",
            "check",
        ],
        cwd=project,
        env={**os.environ, "AIRFLOW_HOME": str(project / "ambient")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    pids = []
    try:
        deadline = time.monotonic() + 30
        while not (project / "pids.json").exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if (project / "pids.json").exists():
            pids = json.loads((project / "pids.json").read_text())
        if interrupt == "terminal":
            os.killpg(process.pid, signal.SIGINT)
        elif interrupt == "cli":
            process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == (130 if interrupt else 0), stdout + stderr
        assert len(pids) == 2
        for pid in pids:
            assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        for pid in pids:
            with suppress(psutil.NoSuchProcess):
                psutil.Process(pid).kill()


@pytest.mark.parametrize("valid", [False, True])
def test_multiple_output_input(project, valid):
    (project / "pipeline.py").write_text(
        textwrap.dedent(
            """
            from airflow.sdk import dag, task
            @task(multiple_outputs=True)
            def upstream():
                raise RuntimeError("Upstream task must never execute")
            @task
            def consume(value):
                return value + 1
            @dag(schedule=None)
            def sample():
                consume(upstream()["number"])
            sample()
            """
        )
    )
    result = run_cli(
        project, "--task", "consume", "--input", 'upstream={"number": 6}' if valid else "upstream=6"
    )
    assert result.returncode == (0 if valid else 2), result.stdout + result.stderr
    assert ("consume = 7" if valid else "must be a JSON object") in result.stdout + result.stderr


def test_invalid_params_are_usage_errors(project):
    (project / "pipeline.py").write_text(
        textwrap.dedent(
            """
            from airflow.sdk import dag, task, Param
            @dag(schedule=None, params={"count": Param(1, type="integer")})
            def sample():
                @task
                def check():
                    raise RuntimeError("Must reject parameters before executing")
                check()
            sample()
            """
        )
    )
    result = run_cli(project, "--task", "check", "--conf", '{"count": "bad"}')
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Invalid input for param count" in result.stderr


def test_deferral_fails_without_waiting(project):
    write_task(
        project,
        """
        from datetime import timedelta
        from airflow.exceptions import TaskDeferred
        from airflow.providers.standard.triggers.temporal import TimeDeltaTrigger
        raise TaskDeferred(trigger=TimeDeltaTrigger(timedelta(hours=1)), method_name="execute_complete")
        """,
    )
    result = run_cli(project, "--task", "check")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "DeferTask is not supported by --no-db" in result.stdout + result.stderr


def test_agent_tools_use_development_database_without_metadata_database(project, monkeypatch):
    pytest.importorskip("airflow.providers.common.ai")
    pytest.importorskip("airflow.providers.sqlite")
    database = project / "tickets.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE tickets (id INTEGER PRIMARY KEY, status TEXT, customer_reply TEXT)")
        conn.executemany(
            "INSERT INTO tickets VALUES (?, ?, ?)",
            [(1, "open", "Solved now"), (2, "open", "Still broken"), (3, "closed", None)],
        )
        conn.commit()
    monkeypatch.setenv("NO_DB_TEST_TOOL_DATABASE", str(database))
    monkeypatch.setenv("AIRFLOW_CONN_TICKETS_DB", json.dumps({"conn_type": "sqlite", "host": str(database)}))
    monkeypatch.setenv(
        "AIRFLOW_CONN_PYDANTICAI_DEFAULT",
        json.dumps({"conn_type": "pydanticai", "extra": {"model": "openai:gpt-5"}}),
    )
    (project / "pipeline.py").write_text(
        textwrap.dedent(
            """
            from unittest import mock
            from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
            from pydantic_ai.models.function import FunctionModel
            from airflow.providers.common.ai.example_dags.example_agent_local_run import workflow
            from airflow.providers.common.ai.hooks.pydantic_ai import PydanticAIHook
            steps = [
                ToolCallPart("query", {"sql": "SELECT id, status, customer_reply FROM tickets WHERE status = 'open'"}),
                ToolCallPart("query", {"sql": "UPDATE tickets SET status = 'closed'"}),
                ToolCallPart("close_ticket", {"ticket_id": 1}),
            ]
            def triage(messages, info):
                answered = [p for m in messages for p in m.parts if isinstance(p, (ToolReturnPart, RetryPromptPart))]
                if len(answered) < len(steps):
                    return ModelResponse(parts=[steps[len(answered)]])
                return ModelResponse(parts=[TextPart("Closed ticket 1.")])
            mock.patch.object(PydanticAIHook, "get_conn", autospec=True, return_value=FunctionModel(triage)).start()
            """
        )
    )

    result = run_cli(project, "--task", "triage_tickets", timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Closed ticket 1." in result.stdout
    assert "triage_tickets | Tool call: close_ticket\n" in result.stderr
    assert "::group::" not in result.stdout + result.stderr
    with closing(sqlite3.connect(database)) as conn:
        assert dict(conn.execute("SELECT id, status FROM tickets")) == {1: "closed", 2: "open", 3: "closed"}
    assert not list(project.rglob("airflow.db"))


# A runtime of another language, as far as its supervisor can tell: it speaks the task protocol over TCP. It
# records the context it starts with, reads each argument, a connection, a missing variable and its task
# state, and returns what it read. An argument named "pull" names a task whose output it reads when it runs.
FAKE_RUNTIME = """
import json
import socket
import sys
from datetime import datetime, timezone

import msgspec


def connect(flag):
    host, port = next(arg for arg in sys.argv if arg.startswith(flag)).removeprefix(flag).rsplit(":", 1)
    return socket.create_connection((host, int(port)))


comm = connect("--comm=")
logs = connect("--logs=")
requests = 0


def read_exactly(size):
    data = b""
    while len(data) < size:
        if not (chunk := comm.recv(size - len(data))):
            raise EOFError
        data += chunk
    return data


def read_frame():
    frame = msgspec.msgpack.decode(read_exactly(int.from_bytes(read_exactly(4), "big")))
    return frame + [None] * (3 - len(frame))


def call(body):
    global requests
    requests += 1
    payload = msgspec.msgpack.encode([requests, body])
    comm.sendall(len(payload).to_bytes(4, "big") + payload)
    return read_frame()[1:]


def now():
    return datetime.now(timezone.utc).isoformat()


def pull(task_id):
    result, error = call({"type": "GetXCom", "key": "return_value", "task_id": task_id, **coordinate})
    if error:
        call({"type": "TaskState", "state": "failed", "end_date": now()})
        sys.exit(1)
    return result["value"]


startup = read_frame()[1]
ti = startup["ti"]
coordinate = {"dag_id": ti["dag_id"], "run_id": ti["run_id"]}
with open("startup.json", "w") as file:
    json.dump(startup["ti_context"], file, default=str)
record = {"event": "fake runtime started", "level": "info", "logger": "fake.runtime", "timestamp": now()}
logs.sendall((json.dumps(record) + "\\n").encode())
arguments = {}
for binding in startup["ti_context"]["arg_bindings"]:
    if binding["kind"] == "xcom":
        arguments[binding["name"]] = pull(binding["task_id"])
    elif binding["name"] == "pull" and binding["value"]:
        arguments[binding["name"]] = pull(binding["value"])
    else:
        arguments[binding["name"]] = binding["value"]
connection = call({"type": "GetConnection", "conn_id": "fake_conn"})[0]
variable = call({"type": "GetVariable", "key": "missing"})[0]
call({"type": "SetTaskStateStore", "ti_id": ti["id"], "key": "seen", "value": arguments, "expires_at": None})
state = call({"type": "GetTaskStateStore", "ti_id": ti["id"], "key": "seen"})[0]
output = {"arguments": state["value"], "host": connection["host"], "variable": variable["error"]}
call({"type": "SetXCom", "key": "return_value", "value": output, "task_id": ti["task_id"], **coordinate})
call({"type": "SucceedTask", "end_date": now()})
"""

FAKE_COORDINATORS = """
import sys
from pathlib import Path

from airflow.sdk.coordinators._subprocess import SubprocessCoordinator


class FakeRuntimeCoordinator(SubprocessCoordinator):
    def _build_execute_task_command(self, *, what):
        return [sys.executable, str(Path(__file__).with_name("fake_runtime.py"))], None


class MissingRuntimeCoordinator(SubprocessCoordinator):
    def _build_execute_task_command(self, *, what):
        return [str(Path(__file__).with_name("no_such_runtime"))], None
"""


def write_stub_project(project, *, coordinator="FakeRuntimeCoordinator", call="consume(produce())"):
    (project / "pyproject.toml").write_text(
        "[tool.airflow.sdk]\n"
        f'coordinators = {{ fake = {{ classpath = "fake_coordinators.{coordinator}" }} }}\n'
        'queue_to_coordinator = { fake = "fake" }\n'
    )
    (project / "guard" / "fake_runtime.py").write_text(FAKE_RUNTIME)
    (project / "guard" / "fake_coordinators.py").write_text(FAKE_COORDINATORS)
    (project / "connections.json").write_text(
        json.dumps({"fake_conn": {"conn_type": "http", "host": "example.com"}})
    )
    (project / "pipeline.py").write_text(
        textwrap.dedent(
            f"""
            from datetime import timedelta

            from airflow.sdk import dag, task

            @task
            def produce():
                raise RuntimeError("Upstream task must never execute")

            @task.stub(queue="fake", execution_timeout=timedelta(minutes=5))
            def consume(value=None, greeting="hello", pull=None): ...

            @dag(schedule=None)
            def sample():
                {call}

            sample()
            """
        )
    )


def test_stub_runs_in_its_runtime_with_local_services(project):
    write_stub_project(project)

    result = run_cli(
        project, "--task", "consume", "--input", "produce=3", "--connections-file", "connections.json"
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "consume | fake.runtime: fake runtime started" in output
    assert (
        "consume = {'arguments': {'greeting': 'hello', 'pull': None, 'value': 3}, 'host': 'example.com', "
        "'variable': 'VARIABLE_NOT_FOUND'}" in output
    )
    context = json.loads((project / "startup.json").read_text())
    assert context["execution_timeout"] == 300
    assert [
        {key: value for key, value in binding.items() if value is not None}
        for binding in context["arg_bindings"]
    ] == [
        {"name": "value", "kind": "xcom", "task_id": "produce"},
        {"name": "greeting", "kind": "literal", "value": "hello", "from_default": True},
        {"name": "pull", "kind": "literal", "from_default": True},
    ]


def test_stub_whose_runtime_reads_a_missing_input_fails_with_the_reason(project):
    write_stub_project(project, call='produce() >> consume(pull="produce")')

    result = run_cli(project, "--task", "consume")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "No input for 'produce', key 'return_value'. Supply --input produce=JSON" in result.stderr


def test_stub_whose_runtime_cannot_start_fails_with_the_reason(project):
    write_stub_project(project, coordinator="MissingRuntimeCoordinator")

    result = run_cli(project, "--task", "consume", "--input", "produce=3")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Cannot launch the task's runtime reason=The runtime cannot start" in result.stderr


def test_stub_on_a_queue_without_a_runtime_is_refused(project):
    write_stub_project(project)
    (project / "pyproject.toml").write_text("")

    result = run_cli(project, "--task", "consume", "--input", "produce=3")

    assert result.returncode == 2, result.stdout + result.stderr
    assert (
        "Task 'consume' is a stub, and no runtime runs its queue 'fake': map the queue to one in "
        "queue_to_coordinator of [tool.airflow.sdk] in pyproject.toml"
    ) in result.stderr


@mock.patch.object(runner, "get_coordinator_manager", autospec=True)
def test_project_coordinators_that_cannot_be_used_are_a_config_error(get_manager):
    get_manager.side_effect = ValueError(
        "[sdk] queue_to_coordinator references invalid coordinator key: 'ts'"
    )

    with pytest.raises(
        LocalRunConfigError, match=r"\[tool\.airflow\.sdk\] in pyproject\.toml cannot be used"
    ):
        runner.find_task_runtime(mock.NonCallableMock(queue="typescript"))


@mock.patch.object(runner, "get_coordinator_manager", autospec=True)
def test_coordinator_that_starts_no_runtime_process_is_refused(get_manager):
    get_manager.return_value = manager = mock.create_autospec(CoordinatorManager, instance=True)
    manager.for_queue.return_value = mock.create_autospec(BaseCoordinator, instance=True)

    with pytest.raises(LocalRunUsageError, match="--no-db cannot run queue 'typescript'"):
        runner.find_task_runtime(mock.NonCallableMock(queue="typescript"))


TS_EXAMPLE = Path(__file__).parents[4] / "ts-sdk" / "example"


def test_typescript_stub_runs_on_node(project):
    bundle = TS_EXAMPLE / "dist" / "bundle.min.mjs"
    if not bundle.is_file():
        pytest.skip(f"{bundle} is not built; ts-sdk/example/README.md says how to build it")
    node = shutil.which("node")
    version = subprocess.check_output([node, "--version"], text=True).strip() if node else "none"
    if not node or int(version.removeprefix("v").split(".")[0]) < 22:
        pytest.skip(f"The TypeScript SDK needs Node 22 or later on PATH, not {version}")
    (project / "pyproject.toml").write_text(
        "[tool.airflow.sdk]\n"
        'coordinators = { ts = { classpath = "airflow.sdk.coordinators.node.NodeCoordinator" } }\n'
        'queue_to_coordinator = { typescript = "ts" }\n'
    )
    shutil.copy(TS_EXAMPLE / "dags" / "typescript_example.py", project / "pipeline.py")
    (project / "dist").mkdir()
    shutil.copy(bundle, project / "dist")

    result = run_cli(project, "--task", "build_message", "--input", 'python_start="hi"')

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(
        r"build_message = \{'message': 'hello from TypeScript; upstream=hi', 'upstream': 'hi'\}",
        result.stdout,
    ), result.stdout + result.stderr
