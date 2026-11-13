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

Rank renewals by churn risk, checking each step
===============================================

An account team wants to know which customers up for renewal this quarter are most likely to
leave. The evidence is spread over three systems: renewals in the CRM, support incidents in the
warehouse, and SLA commitments in the customers' contracts. This Dag has an agent gather each
piece in turn and a model rank the customers from what they found.

Each step can be wrong in a way that spoils every step after it. An agent can report a renewal
from next quarter, or quote a contract clause that the contract does not contain. So each step
is followed by an evaluation task that checks its output before the next step runs. A failed
check fails that task and stops the run there, and its message says which check failed and on
which customers.

The Dag runs on your machine with no credentials: SQLite files stand in for the CRM and the
warehouse, and a folder of text files for the contracts. Moving it to the real systems means
changing connections and one toolset, as `Move to the real systems`_ shows.

What this demonstrates
----------------------

* An evaluation after each step as a plain ``@task``. It checks the step's output against the
  earlier steps and against the contracts, logs ``PASS`` or ``FAIL`` for each check, returns
  the results as its XCom, and raises ``EvaluationFailed`` when a check fails, so the tasks
  after it end ``upstream_failed``.
* :doc:`../structured_output` as the first check. A field constraint such as a score between
  0 and 100 is checked as the model answers, and the model is asked again until it passes.
* An LLM judge, a ``@task.llm`` whose verdicts the last evaluation takes into account.
* One read-only toolset per agent step: ``SQLToolset`` for each database and
  ``ObjectStorageToolset`` for the contracts. The ranking and the judge get no tools.
* Running one step, or one evaluation, on its own with ``airflow run --task`` and ``--input``.

The Dag
-------

Four steps, each followed by its evaluation:

.. exampleinclude:: /../../ai/src/airflow/providers/common/ai/example_dags/example_agent_churn_analysis.py
    :language: python
    :start-after: [START howto_agent_churn_analysis_dag]
    :end-before: [END howto_agent_churn_analysis_dag]

Each step reads the outputs of the steps before it, and waits with ``>>`` for the evaluation
of the step before it to pass. An evaluation returns a record of its checks, not the step's
data, so the next step reads the step's output itself.

``seed_stand_ins`` writes the local stand-ins on every run, with renewal dates in the run's
quarter. It goes when the connections point at the real systems.

One step and its evaluation
---------------------------

The SLA step has an agent read the contracts of the customers with incidents. Its evaluation
checks that every SLA belongs to one of those customers, and that every quote is in its
contract word for word:

.. exampleinclude:: /../../ai/src/airflow/providers/common/ai/example_dags/example_agent_churn_analysis.py
    :language: python
    :start-after: [START howto_agent_churn_analysis_step]
    :end-before: [END howto_agent_churn_analysis_step]

The output types do the checks that need only the step's own answer. A ``contract_file`` must
be a plain file name, since the evaluation opens it, and a ``score`` must be between 0 and 100.
Pydantic AI sends a failed constraint back to the model, which answers again within the same
task:

.. exampleinclude:: /../../ai/src/airflow/providers/common/ai/example_dags/example_agent_churn_analysis.py
    :language: python
    :start-after: [START howto_agent_churn_analysis_output_types]
    :end-before: [END howto_agent_churn_analysis_output_types]

Checks that need another step's output, or the contracts, can't run inside the step. They go
in the evaluation task, which every evaluation builds with one helper:

.. exampleinclude:: /../../ai/src/airflow/providers/common/ai/example_dags/example_agent_churn_analysis.py
    :language: python
    :start-after: [START howto_agent_churn_analysis_evaluate]
    :end-before: [END howto_agent_churn_analysis_evaluate]

Each check is a list of the customers that failed it, so the failure message names them. The
evaluations take ``retries=0``: a check on the same output fails the same way the second time.

The last step and its judge
---------------------------

Whether a score is in range, and whether every customer was scored, is code. Whether the reason
given for a score follows from the evidence is a judgment, so a second model reviews the list,
and the last evaluation fails if it finds a score unjustified:

.. exampleinclude:: /../../ai/src/airflow/providers/common/ai/example_dags/example_agent_churn_analysis.py
    :language: python
    :start-after: [START howto_agent_churn_analysis_judge]
    :end-before: [END howto_agent_churn_analysis_judge]

The judge uses ``pydanticai_default`` like the other steps. A judge on a different model,
through its own connection, is less likely to share the mistakes of the model it checks.

The full Dag is ``example_agent_churn_analysis`` in
`example_agent_churn_analysis.py <https://github.com/apache/airflow/blob/providers-common-ai/|version|/providers/common/ai/src/airflow/providers/common/ai/example_dags/example_agent_churn_analysis.py>`__.

Run it
------

On an Airflow version that runs Dags locally (see :doc:`apache-airflow:howto/run-dags-locally`),
create a project and add the provider with the ``sql`` extra, the extra for your model vendor,
and the SQLite provider:

.. code-block:: bash

    uvx --from apache-airflow-core airflow bootstrap churn
    cd churn
    uv add "apache-airflow-providers-common-ai[sql,openai]" apache-airflow-providers-sqlite

Save the Dag as ``churn.py``, and give the run its connections in a ``connections.yaml`` next to
it. The SQLite files are relative to the directory you run from. The contracts are in a
``contracts`` folder there, which needs no connection. The model's connection holds your key,
as in :doc:`../quickstart`:

.. code-block:: yaml

    crm:
      conn_type: sqlite
      host: crm.db
    warehouse:
      conn_type: sqlite
      host: warehouse.db
    pydanticai_default:
      conn_type: pydanticai
      password: sk-...
      extra:
        model: openai:gpt-5

Run it:

.. code-block:: bash

    uv run airflow run churn.py --connections-file connections.yaml

The terminal shows each evaluation's checks as they run. This output is from a scripted model,
with the hook's statements, the agents' tool calls and the model-run summaries left out:

.. code-block:: text

    Running Dag 'example_agent_churn_analysis' from churn.py (run manual__2026-11-13T08:25:07.148751+00:00)
      ✓ seed_stand_ins
      ✓ pull_renewals
      evaluate_renewals | churn: PASS  at least one customer renews this quarter
      evaluate_renewals | churn: PASS  each renewal closes this quarter
      evaluate_renewals | churn: PASS  no customer is listed twice
      ✓ evaluate_renewals
      ✓ check_incidents
      ...
      ✓ judge_priorities
      evaluate_priorities | churn: PASS  each renewing customer is scored once
      evaluate_priorities | churn: PASS  customers with incidents score above customers without
      evaluate_priorities | churn: PASS  the judge finds each score justified
      evaluate_priorities | churn: PASS  the judge reviewed each scored customer
      ✓ evaluate_priorities
    Succeeded in 9.9s (12.1s total). History: /path/to/churn/.airflow

When the SLA agent quotes a sentence that its contract does not contain, ``evaluate_slas``
fails, and the three tasks after it don't run:

.. code-block:: text

      ✓ check_slas
      evaluate_slas | churn: PASS  each SLA belongs to a customer with incidents
      evaluate_slas | churn: error: FAIL  each quote appears word for word in its contract: 001A
      ✗ evaluate_slas failed
    Traceback (most recent call last):
      ...
    EvaluationFailed: 1 of 2 checks failed: each quote appears word for word in its contract (failed for: 001A)
    Failed in 15.2s (20.3s total): evaluate_slas. History: /path/to/churn/.airflow

``airflow standalone --project`` shows the same run: ``evaluate_slas`` failed in the grid and
the graph, the three tasks after it ``upstream_failed``, and the ``PASS`` and ``FAIL`` lines in
its **Logs** tab. A passing evaluation's results are on its **XCom** tab, and the judge's
reason for each customer on ``judge_priorities``.

Work on one step
----------------

After you change a step's prompt, rerun it and everything after it, on the outputs of the
steps before it from the last run:

.. code-block:: bash

    uv run airflow run churn.py --connections-file connections.yaml --task check_slas --downstream

To run a step on a case you write, give the outputs it reads as JSON. The evaluation between the
two steps counts as passed:

.. code-block:: bash

    uv run airflow run churn.py --connections-file connections.yaml --task check_incidents \
        --input pull_renewals='{"customers": [{"account_id": "001D", "name": "Delta Mills", "renewal_date": "2026-12-01", "amount": 150000}]}'

An evaluation runs the same way, with no model at all. This one is given an SLA for a customer
without incidents, and fails:

.. code-block:: bash

    uv run airflow run churn.py --connections-file connections.yaml --task evaluate_slas \
        --input check_incidents='{"customers": [{"account_id": "001A", "incident_ids": [101], "worst_severity": 1}]}' \
        --input check_slas='{"commitments": [{"account_id": "001B", "contract_file": "001B.txt", "commitment": "best effort", "quote": "Support is provided on a best-effort basis during business hours."}]}'

To check the Dag with no model, script the model's replies as :doc:`../local_development`
shows. The provider's test for this Dag scripts each step, and makes the SLA agent invent a
quote to see ``evaluate_slas`` stop the run.

Move to the real systems
------------------------

.. list-table::
   :header-rows: 1
   :widths: 16 30 54

   * - System
     - Local stand-in
     - What changes
   * - Salesforce
     - ``crm.db``, with tables named after Salesforce's ``Account`` and ``Opportunity`` objects
     - The toolset. Salesforce answers SOQL through ``SalesforceHook``, not SQL through a
       database hook, so ``SQLToolset`` can't reach it. Give ``pull_renewals``
       ``HookToolset(SalesforceHook(salesforce_conn_id="crm"), allowed_methods=["make_query",
       "describe_object"], pinned_arguments={"include_deleted": False})`` and say SOQL in its
       system prompt. SOQL has no statements that write. The output type and the evaluation stay.
   * - Redshift
     - ``warehouse.db``
     - The ``warehouse`` connection only: a ``redshift`` connection from the Amazon provider, or
       a ``postgres`` one. ``SQLToolset`` takes its SQL dialect from the connection's hook.
   * - Contracts on Azure
     - Text files under ``file://contracts``
     - ``CONTRACTS_PATH`` and the ``legal_docs`` connection, if the contracts are files in Azure
       Data Lake Storage: an ``abfs://`` path and an Azure connection. ``ObjectStorageToolset``
       reads text, so PDF contracts need converting first (:doc:`../operators/document_loader`).
       A contract system with an API instead of files needs a hook and its own toolset.

Then delete ``seed_stand_ins``. Give each connection a user that can only read.

The evaluations don't query the systems themselves, so they don't change. They also don't
check that a step found everything, such as a renewal it missed. That needs the step's query
run again, which is better done as a set of cases against a real model before you change a
prompt (:doc:`../local_development`).
