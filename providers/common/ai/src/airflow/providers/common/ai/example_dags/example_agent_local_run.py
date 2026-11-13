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
"""Example Dag: an agent that reads a dev database freely and may make one kind of change to it."""

from __future__ import annotations

# [START howto_agent_local_run]
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.toolsets.function import FunctionToolset

from airflow.providers.common.ai.toolsets.sql import SQLToolset
from airflow.providers.sqlite.hooks.sqlite import SqliteHook
from airflow.sdk import dag, task

TICKETS_CONN_ID = "tickets_db"


@task
def seed_tickets() -> None:
    """Create the dev database's tickets table with three tickets, unless it is already there."""
    SqliteHook(sqlite_conn_id=TICKETS_CONN_ID).run(
        [
            "CREATE TABLE IF NOT EXISTS tickets"
            " (id INTEGER PRIMARY KEY, subject TEXT, status TEXT, customer_reply TEXT)",
            "INSERT OR IGNORE INTO tickets VALUES"
            " (1, 'Password reset email never arrives', 'open', 'Found it in my spam folder, all good now.'),"
            " (2, 'Invoice shows the wrong VAT number', 'open', 'Still wrong on the new invoice.'),"
            " (3, 'CSV export times out', 'closed', NULL)",
        ]
    )


def close_ticket(ticket_id: int) -> str:
    """Close an open ticket."""
    closed = SqliteHook(sqlite_conn_id=TICKETS_CONN_ID).run(
        "UPDATE tickets SET status = 'closed' WHERE id = ? AND status = 'open'",
        parameters=(ticket_id,),
        handler=lambda cursor: cursor.rowcount,
    )
    if not closed:
        raise ModelRetry(f"Ticket {ticket_id} is not open.")
    return f"Closed ticket {ticket_id}."


@dag(tags=["example"])
def example_agent_local_run():
    @task.agent(
        llm_conn_id="pydanticai_default",
        system_prompt=(
            "You triage support tickets. Look the tickets up, then close each open ticket whose "
            "customer says the problem is solved. Leave every other ticket as it is."
        ),
        toolsets=[
            # Reads only the tickets table: the toolset refuses any statement that writes.
            SQLToolset(db_conn_id=TICKETS_CONN_ID, allowed_tables=["tickets"]),
            # The one change the agent may make.
            FunctionToolset(tools=[close_ticket]),
        ],
    )
    def triage_tickets() -> str:
        return "Triage the open tickets and say which ones you closed."

    seed_tickets() >> triage_tickets()


workflow = example_agent_local_run()

if __name__ == "__main__":
    result = workflow.run()
    print(result.output("triage_tickets"))
# [END howto_agent_local_run]
