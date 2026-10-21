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
"""Recover real Common AI model and SQL calls across interrupted local CLI processes."""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import textwrap
import time
from contextlib import suppress
from pathlib import Path

import psutil
import pytest

from airflow.providers.common.ai.example_dags import example_local_agent

# Compatibility jobs run provider tests against released Airflow versions without run-local.
pytest.importorskip(
    "airflow.sdk.execution_time.local_runner", reason="airflow tasks run-local is not available"
)


def test_local_command_recovers_recorded_agent_calls(tmp_path):
    database = tmp_path / "orders.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE orders (order_id INTEGER PRIMARY KEY, amount_cents INTEGER NOT NULL);
            INSERT INTO orders VALUES (1, 1200), (2, 3400);
            CREATE TABLE order_summaries (
                report_id TEXT PRIMARY KEY, order_count INTEGER NOT NULL, total_cents INTEGER NOT NULL
            );
            INSERT INTO order_summaries VALUES ('orders-demo', 0, 0);
            CREATE TABLE writes (report_id TEXT);
            CREATE TRIGGER count_writes AFTER UPDATE ON order_summaries
            BEGIN INSERT INTO writes VALUES (NEW.report_id); END;
            """
        )

    dag_file = tmp_path / "local_agent.py"
    dag_file.write_text(
        Path(example_local_agent.__file__).read_text()
        + textwrap.dedent(
            """

            from pathlib import Path
            from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
            from pydantic_ai.models.function import FunctionModel

            def respond(messages, info):
                returns = [
                    part for message in messages for part in message.parts
                    if isinstance(part, ToolReturnPart)
                ]
                with Path(os.environ['LOCAL_TEST_MODEL_CALLS']).open('a') as trace:
                    trace.write(str(len(returns)) + '\\n')
                queries = [READ_ORDERS, WRITE_SUMMARY, READ_SUMMARY]
                if len(returns) < len(queries):
                    return ModelResponse(parts=[ToolCallPart('query', {'sql': queries[len(returns)]})])
                if len(returns) == len(queries):
                    return ModelResponse(parts=[ToolCallPart('wait_before_answer', {})])
                return ModelResponse(parts=[TextPart('2 orders, 4600 cents')])

            def wait_before_answer() -> str:
                "Pause after the recorded SQL write, before the agent completes."
                if os.environ.get('LOCAL_TEST_RESUME') != '1':
                    Path(os.environ['LOCAL_TEST_READY']).write_text(str(os.getpid()))
                    time.sleep(120)
                return 'Ready to report the saved summary.'

            PydanticAIHook.get_conn = lambda self: FunctionModel(respond)
            """
        )
    )
    ready = tmp_path / "ready"
    model_calls = tmp_path / "model-calls"
    output_path = tmp_path / "interrupted.log"
    state_dir = tmp_path / "state"
    environment = os.environ | {
        "AIRFLOW_HOME": str(tmp_path / "airflow"),
        "AIRFLOW__CORE__LOAD_EXAMPLES": "false",
        "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN": f"sqlite:///{tmp_path / 'must_not_exist.db'}",
        "AIRFLOW_CONN_LOCAL_ORDERS_DB": json.dumps({"conn_type": "sqlite", "host": str(database)}),
        "LOCAL_TEST_READY": str(ready),
        "LOCAL_TEST_MODEL_CALLS": str(model_calls),
    }
    environment.pop("_AIRFLOW__AS_LIBRARY", None)
    command = [
        sys.executable,
        "-m",
        "airflow",
        "tasks",
        "run-local",
        str(dag_file),
        "summarize_orders",
        "--dag-id",
        "example_local_agent",
        "--run-id",
        "recover-recorded-calls",
        "--state-dir",
        str(state_dir),
    ]
    task_pid = None
    with output_path.open("w") as output:
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 30
            while not ready.exists() or not ready.read_text():
                if process.poll() is not None or time.monotonic() >= deadline:
                    pytest.fail(f"Agent did not reach its recovery checkpoint:\n{output_path.read_text()}")
                time.sleep(0.05)
            task_pid = int(ready.read_text())
            with sqlite3.connect(database) as connection:
                assert connection.execute("SELECT COUNT(*) FROM writes").fetchone() == (1,)
                assert connection.execute("SELECT * FROM order_summaries").fetchall() == [
                    ("orders-demo", 2, 4600)
                ]
            assert model_calls.read_text().splitlines() == ["0", "1", "2", "3"]

            process.send_signal(signal.SIGINT)
            assert process.wait(timeout=20) == 1, output_path.read_text()
            assert not psutil.pid_exists(task_pid)
        finally:
            with suppress(psutil.NoSuchProcess):
                for descendant in psutil.Process(process.pid).children(recursive=True):
                    with suppress(psutil.NoSuchProcess):
                        descendant.kill()
            if task_pid is not None:
                with suppress(ProcessLookupError):
                    os.killpg(task_pid, signal.SIGKILL)
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)

    state_files = list(state_dir.rglob("state.json"))
    assert len(state_files) == 1
    recorded = json.loads(state_files[0].read_text())
    assert any("_step_" in key for key in recorded)
    assert "Final state: cancelled" in output_path.read_text()

    resumed = subprocess.run(
        command,
        env=environment | {"LOCAL_TEST_RESUME": "1"},
        capture_output=True,
        check=False,
        text=True,
        timeout=45,
    )
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert 'Return value: "2 orders, 4600 cents"' in resumed.stdout
    assert "Final state: success" in resumed.stdout
    assert "(attempt 2)" in resumed.stdout
    assert model_calls.read_text().splitlines() == ["0", "1", "2", "3", "4"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM writes").fetchone() == (1,)
    assert not any("_step_" in key for key in json.loads(state_files[0].read_text()))
    assert not (tmp_path / "must_not_exist.db").exists()
