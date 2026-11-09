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

import sqlite3
import textwrap

import pytest

from airflow.sdk.definitions.local_run import run_dag_file
from airflow.sdk.exceptions import DagExecutionError


@pytest.mark.parametrize(
    ("event", "retries", "expected_state", "output"),
    [
        ("TaskSuccessEvent", 0, "success", None),
        ("TaskSkippedEvent", 0, "skipped", None),
        ("TaskFailedEvent", 0, "failed", None),
        ("TaskFailedEvent", 1, "success", "retried"),
    ],
)
def test_terminal_trigger_events_do_not_resume_the_finished_attempt(
    tmp_path, event, retries, expected_state, output
):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "terminal-trigger"\nversion = "0"\n')
    source = tmp_path / "pipeline.py"
    source.write_text(
        textwrap.dedent(
            f"""
            from datetime import timedelta
            from pathlib import Path
            from airflow.sdk import BaseOperator, dag
            from airflow.triggers.base import BaseTrigger, {event}


            class TerminalTrigger(BaseTrigger):
                def serialize(self):
                    return (f"{{__name__}}.TerminalTrigger", {{}})

                async def run(self):
                    yield {event}()


            class DeferredTask(BaseOperator):
                def execute(self, context):
                    if context["ti"].try_number > 1:
                        return "retried"
                    self.defer(trigger=TerminalTrigger(), method_name="resume")

                def resume(self, context, event=None):
                    Path(__file__).with_suffix(".resumed").touch()
                    return "incorrectly resumed"


            @dag(schedule=None)
            def terminal_trigger():
                DeferredTask(task_id="deferred", retries={retries}, retry_delay=timedelta(0))


            workflow = terminal_trigger()
            """
        )
    )

    if expected_state == "failed":
        with pytest.raises(DagExecutionError) as exc:
            run_dag_file(source)
        result = exc.value.result
    else:
        result = run_dag_file(source)

    assert result.task_states == {("deferred", -1): expected_state}
    assert not source.with_suffix(".resumed").exists()
    if output is not None:
        assert result.output("deferred") == output
    if retries:
        with sqlite3.connect(tmp_path / ".airflow" / "airflow.db") as connection:
            attempts = connection.execute(
                "SELECT try_number, working_set FROM task_instance ORDER BY try_number"
            ).fetchall()
        assert attempts == [(1, None), (2, 1)]


def test_trigger_deadline_resumes_through_task_failure(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "trigger-timeout"\nversion = "0"\n')
    source = tmp_path / "pipeline.py"
    source.write_text(
        textwrap.dedent(
            """
            import asyncio
            from datetime import timedelta
            from pathlib import Path
            from airflow.sdk import BaseOperator, dag
            from airflow.triggers.base import BaseTrigger, TriggerEvent


            class LateTrigger(BaseTrigger):
                def serialize(self):
                    return (f"{__name__}.LateTrigger", {})

                async def run(self):
                    await asyncio.sleep(1)
                    yield TriggerEvent({"ok": True})

                async def cleanup(self):
                    Path(__file__).with_suffix(".cleaned").touch()


            class DeferredTask(BaseOperator):
                def execute(self, context):
                    self.defer(
                        trigger=LateTrigger(), method_name="resume", timeout=timedelta(milliseconds=1)
                    )

                def resume(self, context, event=None):
                    return "incorrectly resumed"


            @dag(schedule=None)
            def trigger_timeout():
                DeferredTask(task_id="deferred", retries=0)


            workflow = trigger_timeout()
            """
        )
    )

    with pytest.raises(DagExecutionError) as exc:
        run_dag_file(source)

    assert exc.value.result.task_states == {("deferred", -1): "failed"}
    assert "Trigger timeout" in exc.value.result.failures[("deferred", -1)]
    assert source.with_suffix(".cleaned").exists()
