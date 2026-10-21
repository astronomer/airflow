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
"""Exercise the local example's real SQL tools and durable agent without model requests."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from airflow.providers.common.ai.durable.journal import DurableJournal, journal_scope
from airflow.providers.common.ai.example_dags import example_local_agent as example
from airflow.providers.common.ai.toolsets.sql import SQLToolset
from airflow.providers.sqlite.hooks.sqlite import SqliteHook


@patch.object(example.time, "sleep", autospec=True)
@patch.object(example.PydanticAIHook, "get_conn", autospec=True)
@patch.object(SQLToolset, "_get_db_hook", autospec=True)
@patch.object(SqliteHook, "get_uri", autospec=True)
def test_interrupted_write_replays_and_completed_agent_can_repeat_safely(
    get_uri, get_db_hook, get_model, sleep, tmp_path, monkeypatch, memory_storage
):
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
    get_uri.return_value = f"sqlite:///{database}"
    get_db_hook.return_value = SqliteHook(sqlite_conn_id="local_orders_db")
    monkeypatch.setenv("LOCAL_AGENT_PAUSE_SECONDS", "60")
    sleep.side_effect = RuntimeError("interrupted before agent completion")

    def respond(messages, info):
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        queries = [example.READ_ORDERS, example.WRITE_SUMMARY, example.READ_SUMMARY]
        if len(returns) < len(queries):
            return ModelResponse(parts=[ToolCallPart("query", {"sql": queries[len(returns)]})])
        if len(returns) == len(queries):
            return ModelResponse(parts=[ToolCallPart("wait_before_answer", {})])
        return ModelResponse(parts=[TextPart("2 orders, 4600 cents")])

    get_model.return_value = FunctionModel(respond)
    task = example.example_local_agent().get_task("summarize_orders")

    with pytest.raises(RuntimeError, match="interrupted before agent completion"):
        with journal_scope(DurableJournal(memory_storage, clean_up_after_run=True)):
            task.python_callable()

    assert memory_storage.entries
    monkeypatch.delenv("LOCAL_AGENT_PAUSE_SECONDS")
    with journal_scope(DurableJournal(memory_storage, clean_up_after_run=True)):
        assert task.python_callable() == "2 orders, 4600 cents"
    with sqlite3.connect(database) as connection:
        # Identical row values alone cannot distinguish replay from executing the UPDATE twice.
        assert connection.execute("SELECT COUNT(*) FROM writes").fetchone() == (1,)
    assert not memory_storage.entries

    with journal_scope(DurableJournal(memory_storage, clean_up_after_run=True)):
        assert task.python_callable() == "2 orders, 4600 cents"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM writes").fetchone() == (2,)
        assert connection.execute("SELECT * FROM order_summaries").fetchall() == [("orders-demo", 2, 4600)]
    sleep.assert_called_once_with(60)
