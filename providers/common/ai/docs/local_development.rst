 .. Licensed to the Apache Software Foundation (ASF) under one
    or more contributor license agreements.  See the NOTICE file
    distributed with this work for additional information
    regarding copyright ownership.  The ASF licenses this file
    to you under the Apache License, Version 2.0 (the
    "License"); you may not use this file except in compliance
    with the License.  You may obtain a copy of the License at

 ..   http://www.apache.org/licenses/LICENSE-2.0

 .. Unless required by applicable law or agreed to in writing,
    software distributed under the License is distributed on an
    "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
    KIND, either express or implied.  See the License for the
    specific language governing permissions and limitations
    under the License.

.. _howto/local_development:

Develop and test AI tasks locally
=================================

Getting an agent's prompt and tools right takes many reruns. Do them in a
notebook, with no Airflow running, then run the finished Dag on your machine against
a development database, and test it without an API key.

Iterate in a notebook
---------------------

``AgentOperator`` builds its agent from a
:class:`~airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook` and the
toolsets you pass it. Build the same agent yourself and call it directly. Hooks
read connections from ``AIRFLOW_CONN_<ID>`` environment variables, so no
scheduler, metadata database, or ``airflow db migrate`` is involved:

.. code-block:: bash

    export AIRFLOW_CONN_MY_LLM='{"conn_type": "pydanticai", "password": "sk-...", "extra": {"model": "openai:gpt-5"}}'
    export AIRFLOW_CONN_ORDERS_DB='{"conn_type": "sqlite", "host": "/tmp/orders.db"}'

.. code-block:: python

    from airflow.providers.common.ai.hooks.pydantic_ai import PydanticAIHook
    from airflow.providers.common.ai.toolsets.sql import SQLToolset

    agent = PydanticAIHook.get_hook("my_llm").create_agent(
        instructions="You answer questions about the orders database.",
        toolsets=[SQLToolset(db_conn_id="orders_db", allowed_tables=["orders"])],
    )
    result = agent.run_sync("How many orders are there?")
    print(result.output)

Change the instructions, tools, or prompt and rerun the cell. To talk to the agent
instead, pydantic-ai's ``agent.to_cli_sync()`` opens a chat in the terminal (it
needs the ``pydantic-ai-slim[cli]`` extra).

When the answers look right, copy the arguments into the task. ``instructions``
becomes ``system_prompt``, the connection ID goes in ``llm_conn_id``, ``toolsets``
and ``output_type`` keep their names, and any other agent argument, such as
``retries``, goes in ``agent_params``.

.. code-block:: python

    # dags/orders_report.py
    from airflow.providers.common.ai.toolsets.sql import SQLToolset
    from airflow.sdk import dag, task


    @dag(schedule=None)
    def orders_report():
        @task.agent(
            llm_conn_id="my_llm",
            system_prompt="You answer questions about the orders database.",
            toolsets=[SQLToolset(db_conn_id="orders_db", allowed_tables=["orders"])],
        )
        def orders_question() -> str:
            return "How many orders are there?"

        orders_question()


    orders_report()

To keep prompt data on your machine while iterating, point ``my_llm`` at a model
you serve yourself; see :ref:`howto/self_hosted_models`.

Run the Dag on your machine
---------------------------

On an Airflow version that runs Dags locally (see
:doc:`apache-airflow:howto/run-dags-locally`), you run a Dag file the way you run a
Python script, and Airflow's UI shows each run, including every tool call the agent
made. Point the agent at a development copy of what it works on, and give it only the
changes it needs.

This Dag has an agent work through support tickets in a SQLite database in the
project. It may read the ``tickets`` table as it likes, and the one change it can make
is to close an open ticket:

.. exampleinclude:: /../../ai/src/airflow/providers/common/ai/example_dags/example_agent_local_run.py
    :language: python
    :start-after: [START howto_agent_local_run]
    :end-before: [END howto_agent_local_run]

Two toolsets decide what the agent can do:

* ``SQLToolset`` gives it ``list_tables``, ``get_schema``, ``query`` and
  ``check_query``, on the ``tickets`` table only. It is read-only unless you pass
  ``allow_writes=True``: it refuses a ``query`` that writes, and tells the model why.
  See :doc:`toolsets/sql`.
* ``close_ticket`` is the one change the Dag permits. In a ``FunctionToolset`` a plain
  function is a tool: the model reads its docstring as the tool's description and may
  pass only the arguments in its signature, so it chooses which ticket to close, not
  the statement that closes it. For a ticket that is not open the function raises
  ``ModelRetry``, which the model reads and can act on.

``seed_tickets`` is not a tool. It creates the table and three tickets on the first run,
so that the agent has something to work on; delete ``tickets.db`` to start over.

``HookToolset(SqliteHook(...), allowed_methods=["run"])`` would offer the hook's ``run``
method, which runs any statement the model writes. An approval gate
(:doc:`tool_approval`) works in a local run that keeps its history: the task waits as
``awaiting_input`` until you answer on the **Required Actions** page of
``airflow standalone --project``. A run with ``--no-history`` has no page to answer
from, and waits until you press Ctrl-C.

Create a project, as :doc:`apache-airflow:howto/run-dags-locally` describes, and add
the provider with the ``sql`` extra, which ``SQLToolset`` needs, and the SQLite
provider. Swap ``openai`` for your model vendor's extra (see :doc:`model_providers`):

.. code-block:: bash

    uvx --from apache-airflow-core airflow bootstrap tickets
    cd tickets
    uv add "apache-airflow-providers-common-ai[sql,openai]" apache-airflow-providers-sqlite

Save the Dag as ``triage.py``, and give the run its two connections. The database's
connection needs no credentials: ``tickets.db`` is relative to the directory you run the Dag
from, and SQLite creates the file on the first run. The model's connection holds your
key, as in :doc:`quickstart`:

.. code-block:: bash

    export AIRFLOW_CONN_TICKETS_DB='{"conn_type": "sqlite", "host": "tickets.db"}'
    export AIRFLOW_CONN_PYDANTICAI_DEFAULT='{"conn_type": "pydanticai", "password": "sk-...", "extra": {"model": "openai:gpt-5"}}'

To keep the key out of your shell, put the connection in a secrets backend that the
project names in its ``pyproject.toml`` instead; see
:doc:`apache-airflow:howto/run-dags-locally`.

Run the Dag:

.. code-block:: bash

    uv run triage.py

The terminal shows a line for each task, the statements the database hook runs, each
tool call the agent makes, a summary of the model's run with its token counts, and then
the agent's answer. This output is from a stand-in model, with the seed's rows
shortened; your model writes its own query and answer:

.. code-block:: text

    Running Dag 'example_agent_local_run' from triage.py (run manual__2026-11-13T14:38:27.132303+00:00)
      seed_tickets | SqliteHook: Running statement: CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY, subject TEXT, status TEXT, customer_reply TEXT), parameters: None
      seed_tickets | SqliteHook: Running statement: INSERT OR IGNORE INTO tickets VALUES (1, ...), (2, ...), (3, ...), parameters: None
      seed_tickets | SqliteHook: Rows affected: 3
      ✓ seed_tickets
      triage_tickets | Tool call: query
      triage_tickets | SqliteHook: Running statement: SELECT id, status, customer_reply FROM tickets WHERE status = 'open', parameters: None
      triage_tickets | Tool call: query
      triage_tickets | Tool call: close_ticket
      triage_tickets | SqliteHook: Running statement: UPDATE tickets SET status = 'closed' WHERE id = ? AND status = 'open', parameters: (1,)
      triage_tickets | SqliteHook: Rows affected: 1
      triage_tickets | LLM run complete: model=function:triage:, requests=4, tool_calls=2, input_tokens=415, output_tokens=103, total_tokens=518
      ✓ triage_tickets
    Succeeded in 9.0s (17.7s total). History: /path/to/tickets/.airflow
    Closed ticket 1; ticket 2 is still open.

``uv run airflow run triage.py`` runs it too, and takes ``--no-history``, ``--debug``
and ``--connections-file`` like any local run.

The terminal names each tool call as it starts, but not how long the call took or how
it ended: the second ``query`` call above is a write the toolset refused. To see what
happened in each call, start the UI on the project's history:

.. code-block:: bash

    uv run airflow standalone --project

Open the run, select ``triage_tickets``, and look at its **Logs** tab. Each tool call is
a collapsed group named after the tool, such as ``Tool call: query``, which holds how
long the call took, the statement the hook ran, or why the call was refused:

.. code-block:: text

    Tool query requested ModelRetry after 0.00s: The query tool failed: Statement type 'Update' is not allowed. Allowed types: Select, Union, Intersect, Except, Describe, Show

The last group, ``LLM run complete``, holds the token counts and the order of the calls,
such as ``Tool call sequence: query -> query -> close_ticket``. The arguments the model
passed are logged at DEBUG, so the log does not show them. A run with ``--no-history``
deletes the task log with the rest of its history, so the terminal is the only place
its tool calls show.

Test an agent task without calling a model
------------------------------------------

Script the model's replies with pydantic-ai's
`FunctionModel <https://pydantic.dev/docs/ai/guides/testing/>`__ and patch
``PydanticAIHook.get_conn``, which is where ``AgentOperator`` and ``@task.agent``
get their model. ``dag.test()`` then runs the real task, including template rendering,
toolset calls against your test database and XCom, without network access:

.. code-block:: python

    # tests/test_orders_report.py
    from unittest import mock

    import pydantic_ai.models
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel

    from airflow.providers.common.ai.hooks.pydantic_ai import PydanticAIHook

    from orders_report import orders_report  # dags/orders_report.py from above

    # Fail the test instead of calling a real model by accident.
    pydantic_ai.models.ALLOW_MODEL_REQUESTS = False


    def scripted_model(messages, info):
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart("query", {"sql": "SELECT COUNT(*) AS n FROM orders"})])
        return ModelResponse(parts=[TextPart(f"Result: {returns[-1].content}")])


    def test_report_counts_orders():
        with mock.patch.object(
            PydanticAIHook, "get_conn", autospec=True, return_value=FunctionModel(scripted_model)
        ):
            dag_run = orders_report().test()

        assert dag_run.state == "success"

The first reply calls the ``query`` tool, which runs against the test database
behind ``orders_db``; the second turns the tool result into the answer. The task
still looks up ``my_llm``, so define it in the test environment too; it needs no
key:

.. code-block:: bash

    export AIRFLOW_CONN_MY_LLM='{"conn_type": "pydanticai", "extra": {"model": "openai:gpt-5"}}'

``dag.test()`` needs a metadata database, so run ``airflow db migrate`` once in the
test environment. It also looks the Dag up in your Dags folder, so import the Dag
from its file instead of defining it in the test, and put the Dags folder on the
import path (pytest's ``pythonpath`` setting).

Setting a ``pydanticai`` connection's model to ``test`` swaps in pydantic-ai's
``TestModel`` instead, with no patching. It calls *every* tool once with generated
arguments, against your real connections. That suits ``@task.llm`` and agents whose
tools accept any input, but a ``SQLToolset`` rejects the generated SQL until its
retries run out, and the task fails.

Check the answers themselves
----------------------------

The test above scripts the model's replies, so it can't tell you whether a changed
prompt still gives good answers. For that, run a set of cases with expected
outcomes against the notebook agent from the first section, using a real model and
a library such as `pydantic-evals <https://pydantic.dev/docs/ai/evals/evals/>`__,
before you ship the change.

To check the answers in every run instead, follow each step with a task that checks its
output and fails when a check does, as
:doc:`use_cases/rank_renewals_by_churn_risk` does for an agent that works in four steps.
