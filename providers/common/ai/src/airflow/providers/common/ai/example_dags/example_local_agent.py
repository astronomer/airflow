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
"""Read and update a sandbox orders database with ``airflow tasks run-local``.

See the Common AI local development guide for database setup and the ``local_llm``
and ``local_orders_db`` connections. The task uses Pydantic AI, the provider's
``openai`` and ``sql`` extras, and the SQLite provider. Set
``LOCAL_AGENT_PAUSE_SECONDS=60`` to leave time to interrupt the unfinished agent
after its write; rerun with the same run ID and state directory to recover it.
"""

from __future__ import annotations

import logging
import os
import time

from pydantic_ai import Tool
from pydantic_ai.toolsets import FunctionToolset

from airflow.providers.common.ai.durable import AirflowDurability
from airflow.providers.common.ai.hooks.pydantic_ai import PydanticAIHook
from airflow.providers.common.ai.toolsets.sql import SQLToolset
from airflow.providers.common.compat.sdk import dag, task

log = logging.getLogger(__name__)

# [START howto_local_agent]
READ_ORDERS = "SELECT COUNT(*) AS order_count, COALESCE(SUM(amount_cents), 0) AS total_cents FROM orders"
WRITE_SUMMARY = """
UPDATE order_summaries
SET order_count = (SELECT COUNT(*) FROM orders),
    total_cents = (SELECT COALESCE(SUM(amount_cents), 0) FROM orders)
WHERE report_id = 'orders-demo'
"""
READ_SUMMARY = (
    "SELECT report_id, order_count, total_cents FROM order_summaries WHERE report_id = 'orders-demo'"
)


def wait_before_answer() -> str:
    """Pause after the verified write, before the agent completes, for a cancellation drill."""
    seconds = int(os.environ.get("LOCAL_AGENT_PAUSE_SECONDS", "0"))
    if seconds:
        log.info("Summary written; pausing for %s seconds. Press Ctrl-C to test recovery.", seconds)
        time.sleep(seconds)
    return "Ready to report the saved summary."


@dag(schedule=None, catchup=False, tags=["example", "durable"])
def example_local_agent():
    @task
    def summarize_orders() -> str:
        agent = PydanticAIHook(llm_conn_id="local_llm").create_agent(
            name="local_orders_reporter",
            instructions=(
                "Use the query tool to execute each SQL statement in the prompt exactly, in order, "
                "waiting for each result before the next call. Do not issue any other writes. "
                "After the final SELECT succeeds, call wait_before_answer in a separate turn. "
                "Then report the saved order count and total in cents."
            ),
            toolsets=[
                SQLToolset(
                    db_conn_id="local_orders_db",
                    allowed_tables=["orders", "order_summaries"],
                    allow_writes=True,
                ),
                FunctionToolset(id="cancellation_drill", tools=[Tool(wait_before_answer, sequential=True)]),
            ],
            capabilities=[AirflowDurability()],
        )
        return agent.run_sync(f"Read: {READ_ORDERS}\nWrite: {WRITE_SUMMARY}\nVerify: {READ_SUMMARY}").output

    summarize_orders()


example_local_agent()
# [END howto_local_agent]
