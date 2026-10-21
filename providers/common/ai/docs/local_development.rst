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

Getting an agent's prompt and tools right takes many reruns. Run a selected task
directly from its Dag file, or iterate on the agent in a notebook. Use a scripted
model to test tool behavior without spending API credits.

Run one task without Airflow services
-------------------------------------

``airflow tasks run-local`` loads one Python Dag file and runs the selected task
through the normal worker subprocess. It needs no metadata database, scheduler,
API server, Dag processor, or serialized Dag:

.. code-block:: bash

    airflow tasks run-local dags/orders_agent.py run_agent --dag-id orders_agent

Supply both IDs exactly as declared by the Dag. The command runs only the selected
task: it does not run upstream tasks or schedule the Dag. The file can be outside
the configured Dags folder. Its parent directory is the default import root; use
``--bundle-root /path/to/project`` for a nested file that imports shared project
modules. The file must be below that root.

The terminal shows task logs, rendered fields, published XComs, and the final
state. The exit code is zero only when the task reports success and its worker
process exits cleanly. A task with ``do_xcom_push=False`` shows ``no return value
published``. Declared asset outputs are shown as not recorded locally: asset
registry validation is skipped and no downstream asset scheduling happens. A
branch or short-circuit task lists the downstream tasks that would be skipped.

Install
~~~~~~~

.. TODO: confirm the first Airflow release that ships ``airflow tasks run-local``.

The command requires Airflow 3.5 or later. The example below uses Pydantic AI
through Common AI's ``openai`` model extra and ``sql`` toolset extra, with the
SQLite provider for its database:

.. code-block:: bash

    pip install "apache-airflow>=3.5.0" \
        "apache-airflow-providers-common-ai[openai,sql]" \
        apache-airflow-providers-sqlite

For another database, install that database's provider instead. OpenAI Agents
SDK examples also need ``openai-agents`` 0.20.0 or later, which the ``openai``
extra does not install.

Read and write a sandbox database
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This example stands in for an enterprise orders system with a local SQLite file.
It reads the order totals and updates a pre-existing summary row. The write sets
absolute values for a fixed report key, so repeating it with unchanged orders
has the same result. It neither increments totals nor appends another report.

Work in an empty directory. Create the sandbox with the ``sqlite3`` command-line
client:

.. code-block:: bash

    sqlite3 orders.db <<'SQL'
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY,
        amount_cents INTEGER NOT NULL
    );
    INSERT OR IGNORE INTO orders VALUES (1, 1200), (2, 3400);
    CREATE TABLE IF NOT EXISTS order_summaries (
        report_id TEXT PRIMARY KEY,
        order_count INTEGER NOT NULL,
        total_cents INTEGER NOT NULL
    );
    INSERT OR IGNORE INTO order_summaries VALUES ('orders-demo', 0, 0);
    SQL

Supply the database connection as a JSON file and the model connection through
the environment. Replace the model and API key with an endpoint you are permitted
to use:

.. code-block:: bash

    cat > connections.json <<EOF
    {
      "local_orders_db": {
        "conn_type": "sqlite",
        "host": "$PWD/orders.db"
      }
    }
    EOF
    export AIRFLOW_CONN_LOCAL_LLM='{"conn_type":"pydanticai","password":"YOUR_API_KEY","extra":{"model":"openai:gpt-5-mini"}}'

The task deliberately enables ``SQLToolset(allow_writes=True)``; the default is
read-only SQL validation. ``allowed_tables`` limits the exposed tables, but the
prompt's instruction to issue only the summary update is not a database permission.
Use this SQLite sandbox for the demonstration. For an enterprise system, use a
dedicated role whose grants permit only the intended reads and writes: connection
access alone does not authorize every tool action. ``HookToolset`` likewise limits
exposed methods and arguments, but has no general read-only mode: an allowed hook
method can write.

.. exampleinclude:: /../src/airflow/providers/common/ai/example_dags/example_local_agent.py
    :start-after: [START howto_local_agent]
    :end-before: [END howto_local_agent]

The example ships with the provider. Run the installed copy:

.. code-block:: bash

    EXAMPLES=$(python -c 'from airflow.providers.common.ai import example_dags; print(example_dags.__path__[0])')
    airflow tasks run-local "$EXAMPLES/example_local_agent.py" summarize_orders \
        --dag-id example_local_agent --run-id orders-demo-1 \
        --connections connections.json --state-dir state
    echo "$?"
    sqlite3 orders.db 'SELECT * FROM order_summaries;'

With this data the summary row is ``orders-demo|2|4600``. The model's wording can
vary. The terminal shows the published return value, final state ``success``, and
exit code ``0``.

Interrupt and recover the unfinished agent
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Set ``LOCAL_AGENT_PAUSE_SECONDS=60`` and repeat the command with a new run ID, such
as ``orders-demo-recovery``. When the task logs ``Summary written; pausing``, press
Ctrl-C. The command stops the task and the processes it started, allowing a
bounded time for cleanup before it kills what remains. It reports final state
``cancelled``, exits with a non-zero code, and keeps the saved task state.

Unset ``LOCAL_AGENT_PAUSE_SECONDS`` and rerun the exact command with the same Dag
ID, task ID, run ID, and ``--state-dir``. Model and SQL calls that were recorded
successfully and can be replayed return their saved results; the interrupted
pause finishes and the agent publishes its answer. The environment variable changes only the pause
duration, keeping the prompt and tool requests stable.

Durability is not exactly-once execution. Recording happens after execution and
is best effort. A write interrupted after the database commits but before its
result is recorded can run again. Changed requests can stop replay as well. This
is why the example's write must be safe to repeat. In a plain ``@task`` like this
example, a successful agent run clears its recorded steps immediately, even if
the surrounding task later fails. Rerunning a completed agent repeats its calls,
including writes.

Run IDs also identify saved run dates and parameters. A same-run rerun gets a
fresh task-instance identity and incremented try number, but retains the original
manual-run timestamp and configuration. The logical date, ``run_after``, and both
data-interval boundaries are that initial timestamp; this is a zero-length
interval, not one inferred from the Dag's timetable. Omitting ``--params`` reuses
saved configuration; explicitly different parameters require a new run ID.
Run only one attempt for a given Dag, run, and task at a time; concurrent attempts
share recovery state. The default state directory is
``$AIRFLOW_HOME/local-task-state`` (normally ``~/airflow/local-task-state``);
``--state-dir`` selects another location.

Connections, inputs, and limitations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The worker checks a configured secrets backend first, then environment variables,
then the local runner, which reports the missing value and where it looked.
``--connections`` accepts a JSON object mapping IDs to connection objects or URI
strings. ``--variables`` accepts a JSON object mapping names to values. File
entries become environment variables before the Dag is imported; an environment
variable that is already set takes precedence. Connections stored only in a
deployment's metadata database are not available locally. Configure enterprise
secrets backends explicitly; local execution does not inherit a deployment's
credentials or access controls.

``--params '{"region":"west"}'`` supplies Dag run configuration and validated
task parameters. ``--upstream-xcoms '{"producer":{"return_value":42}}'`` supplies
an upstream task's XComs. XComs pushed during the attempt stay in memory. Reading
an upstream XCom that was not supplied behaves like reading a missing XCom in a
deployment: the task gets no value, or the default it passed to ``xcom_pull``.
The command lists each upstream task and key read this way.

Mapped tasks, loop tasks, full Dag execution, run-history queries, automatic
retries, deferral, rescheduling, triggers, human-in-the-loop approval, Variable
writes, asset registry lookups and state, and triggering other Dag runs are
unsupported. An unsupported terminal state, such as deferral, fails the command
even when the worker exits normally. Interactive input and debuggers that need
the task's standard input are also unsupported, because the task runs in a
subprocess. For interactive agent development, iterate in a notebook instead.

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
