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

LLM Retry Policies
===================

.. note::
    Requires Airflow >= 3.3.0.

The ``LLMRetryPolicy`` uses an LLM to classify task errors and make intelligent
retry decisions. It works with any LLM provider supported by pydantic-ai
(OpenAI, Anthropic, Bedrock, Vertex, Ollama, etc.).

For the core retry policy concepts, see :doc:`apache-airflow:core-concepts/tasks`.

Setup
-----

1. Install the provider with the LLM backend you need:

   .. code-block:: bash

       pip install 'apache-airflow-providers-common-ai[anthropic]'

2. Create a connection (``Admin > Connections``):

   - **Connection Id**: ``pydanticai_default``
   - **Connection Type**: ``Pydantic AI``
   - **Password**: Your API key
   - **Extra**: ``{"model": "anthropic:claude-haiku-4-5"}``

Usage
-----

.. code-block:: python

    from airflow.providers.common.ai.policies.retry import LLMRetryPolicy
    from airflow.sdk.definitions.retry_policy import RetryAction, RetryRule
    from datetime import timedelta

    llm_policy = LLMRetryPolicy(
        llm_conn_id="pydanticai_default",
        timeout=30.0,  # max seconds to wait for LLM response
        fallback_rules=[  # used when LLM call fails
            RetryRule(exception=ConnectionError, action=RetryAction.RETRY, retry_delay=timedelta(seconds=10)),
            RetryRule(exception=PermissionError, action=RetryAction.FAIL),
        ],
    )


    @task(retries=5, retry_policy=llm_policy)
    def call_external_api(): ...

How it works
------------

When a task fails, ``LLMRetryPolicy``:

1. Sends the exception message to the configured LLM. By default, the message
   is first masked through Airflow's secrets masker (see ``redactor`` below)
   and truncated to ``max_exception_length`` characters before it is added
   to the prompt.
2. The LLM classifies the error into a category (``rate_limit``, ``auth``,
   ``network``, ``data``, ``resource``, ``transient``, ``permanent``)
3. The policy looks that category up in ``retry_delays`` and returns RETRY
   (with that category's delay) or FAIL. The lookup happens in the worker, not
   in the model
4. The classification reason is logged in the task logs

This classification call is a separate LLM request, made by ``LLMRetryPolicy``
itself rather than by an operator -- it is not subject to an operator's
``usage_limits``, and it runs on every task failure regardless
of any cost cap configured on the failing task. It is bounded by ``timeout``
and ``max_exception_length``, but not by a cost limit.

If the LLM call fails (provider down, timeout, bad credentials), or the model
cannot produce one of the seven categories even after pydantic-ai re-prompts
it, the policy falls back to ``fallback_rules`` if configured, or to the task's
standard retry behaviour. The retry table is not consulted in that case --
there is no category to look up.

What the model can and cannot do
--------------------------------

The model answers one question: which kind of failure is this. It is
given no tools and there is no way to attach any, so it cannot run code, call
an API, read a connection, or reach your data. Beyond your ``instructions``,
it sees only the exception's class name, the exception message (after
redaction and truncation), and how many attempts are left. The prompt says
``attempt {try_number} of {max_tries}``, so the model knows the limit and not
just where it is right now. That only moves the category -- an instruction like
"after two attempts treat an expired token as ``auth`` rather than
``transient``" (see the Snowflake example below) works because the model can see
which attempt this is.

It returns two fields: ``category``, constrained to the seven values above, and
``reasoning``. It does not decide whether to retry and it does not choose the
delay -- both come from ``retry_delays`` in the worker process, keyed on the
category. A model cannot return a category the policy does not recognize, and
it cannot return a category paired with an action that contradicts it.

``category`` and ``reasoning`` are only recorded on a RETRY. They are written
to the task instance's ``retry_reason`` (truncated to 500 characters, see
below), then cleared once the next attempt starts running. On a FAIL they are
not written anywhere -- they only show up in the task log.

Two limits are worth knowing about:

* RETRY cannot give a task more attempts than ``retries`` allows. FAIL, though, ends the task
  straight away even when attempts were left, so a wrong classification costs
  the task the retries it would otherwise have had.
* A delay from ``retry_delays`` is used as-is. There is no upper limit -- a
  task's own ``max_retry_delay`` does not clamp it. A ``None`` delay means no
  override at all, so the task's own ``retry_delay`` /
  ``retry_exponential_backoff`` / ``max_retry_delay`` apply instead (see
  :doc:`apache-airflow:core-concepts/tasks`).

Retry table
-----------

``retry_delays`` maps a category to the delay before its retry. A category
absent from the mapping fails the task. The default is:

.. code-block:: python

    from datetime import timedelta

    DEFAULT_RETRY_DELAYS = {
        "rate_limit": timedelta(seconds=60),
        "network": timedelta(seconds=10),
        "transient": timedelta(seconds=30),
    }
    # auth, data, resource and permanent are absent, so they FAIL.

Pass your own to change either half of that. It **replaces** the default
rather than merging into it, so include every category you want retried --
or spread the default and edit what you need:

.. code-block:: python

    from airflow.providers.common.ai.policies.retry import DEFAULT_RETRY_DELAYS

    LLMRetryPolicy(
        llm_conn_id="pydanticai_default",
        retry_delays={**DEFAULT_RETRY_DELAYS, "resource": None},
    )

Written out in full instead:

.. code-block:: python

    LLMRetryPolicy(
        llm_conn_id="pydanticai_default",
        retry_delays={
            "rate_limit": timedelta(minutes=5),  # our provider's window is longer
            "network": timedelta(seconds=10),
            "transient": timedelta(seconds=30),
            "resource": None,  # retry, but on the task's own backoff
        },
    )

Delays are ``timedelta``, not seconds. Naming a category outside the seven,
passing a bare int, or passing a negative delay raises ``ValueError`` when the
policy is constructed rather than on the first task failure.

Custom instructions
-------------------

The default classifier is written for generic infrastructure errors. Override
``instructions`` to teach it your stack's error strings. Instructions decide how
errors are sorted into the seven categories; they cannot add categories or set
delays. Those are ``retry_delays``, above.

.. code-block:: python

    SNOWFLAKE_INSTRUCTIONS = (
        "You are an error classifier for Snowflake-backed data pipelines. "
        "Classify the error into one of: rate_limit, auth, network, data, "
        "resource, transient, permanent.\n\n"
        "Snowflake-specific guidance:\n"
        "- 'Statement queued' or 'concurrency limit' -> rate_limit\n"
        "- 'JWT token expired' -> transient (the token rotates)\n"
        "- 'Authentication token has expired' AFTER multiple retries -> auth\n"
        "- 'Column does not exist' -> data (schema drift needs a human fix)\n"
        "- 'Warehouse suspended' -> transient (auto-resume)\n"
    )

    snowflake_policy = LLMRetryPolicy(
        llm_conn_id="pydanticai_default",
        instructions=SNOWFLAKE_INSTRUCTIONS,
        retry_delays={
            "rate_limit": timedelta(seconds=120),  # queued statements clear slowly
            "network": timedelta(seconds=10),
            "transient": timedelta(seconds=30),
        },
        fallback_rules=[
            RetryRule(
                exception=ConnectionError,
                action=RetryAction.RETRY,
                retry_delay=timedelta(seconds=30),
            ),
        ],
    )


    @task(retries=5, retry_policy=snowflake_policy)
    def query_snowflake(): ...

When writing custom instructions:

- Use the seven category names as-is. The model is constrained to them, so a
  name you invent cannot come back. A model that insists on one anyway is
  re-prompted once by pydantic-ai and then gives up, which lands the task on
  ``fallback_rules`` or on its own retry behaviour, having billed two calls.
  Offering a name the schema rejects is therefore worse than offering none.
- Be concrete with examples (``"'Warehouse suspended' -> transient"``) rather
  than vague rules ("treat warehouse issues as recoverable").
- Do not spell out delays or "do NOT retry" instructions. The model no longer
  decides either one, and telling it to only spends tokens.
- ``retry_reason`` is truncated to 500 chars in the audit log -- keep
  ``reasoning`` outputs concise.

Parameters
----------

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Parameter
     - Default
     - Description
   * - ``llm_conn_id``
     - (required)
     - Airflow connection ID for the LLM provider.
   * - ``model_id``
     - None
     - Override the model from the connection (e.g., ``"openai:gpt-4o-mini"``).
   * - ``instructions``
     - (built-in)
     - Custom system prompt for error classification.
   * - ``fallback_rules``
     - None
     - List of ``RetryRule`` objects used when the LLM call fails.
   * - ``timeout``
     - 30.0
     - Max seconds to wait for the LLM response before falling back.
   * - ``retry_delays``
     - ``rate_limit`` 60s, ``network`` 10s, ``transient`` 30s
     - Which categories are retried, and how long to wait before each. A
       category absent from the mapping fails the task; a ``None`` delay
       retries on the task's own ``retry_delay`` and backoff. **Replaces**
       the default mapping rather than merging into it. Raises
       ``ValueError`` at construction time for an unknown category name or a
       negative delay.
   * - ``redactor``
     - None (uses ``redact_registered_secrets``)
     - Callable ``(str) -> str`` applied to the exception's string
       representation before it is added to the classification prompt. The
       default only masks values already registered via ``mask_secret()``
       (e.g. connection passwords Airflow captured while resolving the
       failing task's connections) -- it is not general-purpose PII
       detection and will not catch arbitrary sensitive strings that were
       never registered as secrets. Passing a custom callable **replaces**
       the default masker entirely rather than stacking on top of it.
   * - ``redact_exception``
     - True
     - Whether to redact the exception's string representation before it is
       added to the classification prompt. Set to ``False`` to disable
       redaction entirely. Raises ``ValueError`` at construction time if
       combined with an explicit ``redactor``.
   * - ``max_exception_length``
     - 4096
     - Maximum number of characters of the (already redacted) exception
       message included in the prompt. Longer messages are truncated with a
       trailing ``"... (truncated)"`` marker. Must be a positive integer.

Custom redactors
----------------

The default ``redactor`` only masks values already registered with Airflow's
secrets masker via ``mask_secret()``. It does not detect free-text PII --
email addresses, customer names, account numbers -- that were never
registered as secrets. If your task's exception messages can contain that
kind of data, supply your own ``redactor`` callable. It **replaces** the
default masker rather than running in addition to it, so combine your own
logic with :func:`~airflow.providers.common.ai.policies.retry.redact_registered_secrets`
yourself if you still want known-secret masking too:

.. code-block:: python

    import re

    from airflow.providers.common.ai.policies.retry import redact_registered_secrets

    EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


    def redact_emails_and_secrets(message: str) -> str:
        return redact_registered_secrets(EMAIL_RE.sub("<email>", message))


    llm_policy = LLMRetryPolicy(
        llm_conn_id="pydanticai_default",
        redactor=redact_emails_and_secrets,
        max_exception_length=2048,  # keep long tracebacks from inflating token cost
    )

To disable redaction entirely (for example, if you are certain your
exception messages contain no sensitive data and need the raw text for
accurate classification), pass ``redact_exception=False``:

.. code-block:: python

    LLMRetryPolicy(llm_conn_id="pydanticai_default", redact_exception=False)

Local LLM support
-----------------

By default, the built-in ``redactor`` already masks known secrets before the
exception data reaches the LLM provider. For environments where exception
data must not leave your own infrastructure at all -- even in masked form --
point to a local model via Ollama or vLLM instead, so the classification
never crosses the network boundary. See :ref:`howto/self_hosted_models` for
general self-hosted connection setup:

.. code-block:: python

    LLMRetryPolicy(
        llm_conn_id="ollama_local",  # host=http://localhost:11434
        model_id="ollama:llama3.2",
    )
