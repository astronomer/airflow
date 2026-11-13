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
"""``example_agent_local_run``: the agent reads the tickets, is refused a write, and closes the solved one."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from unittest import mock

import pytest

pytest.importorskip("airflow.providers.sqlite")

from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from airflow.providers.common.ai.example_dags import example_agent_local_run as example
from airflow.providers.common.ai.hooks.pydantic_ai import PydanticAIHook

STEPS = [
    ToolCallPart("query", {"sql": "SELECT id, status, customer_reply FROM tickets WHERE status = 'open'"}),
    ToolCallPart("query", {"sql": "UPDATE tickets SET status = 'closed'"}),
    ToolCallPart("close_ticket", {"ticket_id": 1}),
]


def triage(messages, info: AgentInfo) -> ModelResponse:
    answered = [p for m in messages for p in m.parts if isinstance(p, (ToolReturnPart, RetryPromptPart))]
    if len(answered) < len(STEPS):
        return ModelResponse(parts=[STEPS[len(answered)]])
    return ModelResponse(parts=[TextPart("Closed ticket 1.")])


@pytest.mark.db_test
@mock.patch.object(PydanticAIHook, "get_conn", autospec=True, return_value=FunctionModel(triage))
def test_agent_closes_the_solved_ticket_and_nothing_else(mock_get_conn, tmp_path, monkeypatch):
    database = tmp_path / "tickets.db"
    monkeypatch.setenv("AIRFLOW_CONN_TICKETS_DB", json.dumps({"conn_type": "sqlite", "host": str(database)}))
    monkeypatch.setenv(
        "AIRFLOW_CONN_PYDANTICAI_DEFAULT",
        json.dumps({"conn_type": "pydanticai", "extra": {"model": "openai:gpt-5"}}),
    )

    dag_run = example.workflow.test()

    assert dag_run.state == "success"
    with closing(sqlite3.connect(database)) as conn:
        statuses = dict(conn.execute("SELECT id, status FROM tickets"))
    assert statuses == {1: "closed", 2: "open", 3: "closed"}
