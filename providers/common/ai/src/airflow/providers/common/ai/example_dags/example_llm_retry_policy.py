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
"""
Example DAG demonstrating LLM-powered retry policies.

Uses an LLM (via PydanticAIHook) to name the kind of failure. The policy
then looks that category up in its retry table to decide whether to retry,
fail immediately, or retry after a specific delay.

Prerequisites:
  - Connection ``pydanticai_default`` with ``conn_type='pydanticai'``,
    ``password=<API key>``, ``extra='{"model": "anthropic:claude-haiku-4-5-20251001"}'``
  - ``pip install apache-airflow-providers-common-ai[anthropic]``
"""

from __future__ import annotations

from datetime import timedelta

from airflow.providers.common.compat.sdk import dag, task

try:
    from airflow.providers.common.ai.policies.retry import DEFAULT_RETRY_DELAYS, LLMRetryPolicy
    from airflow.sdk.definitions.retry_policy import RetryAction, RetryRule

    llm_policy = LLMRetryPolicy(
        llm_conn_id="pydanticai_default",
        timeout=30.0,
        fallback_rules=[
            RetryRule(exception=ConnectionError, action=RetryAction.RETRY, retry_delay=timedelta(seconds=10)),
            RetryRule(exception=PermissionError, action=RetryAction.FAIL),
        ],
    )

    # The default table fails ``resource``, on the grounds that a missing table needs a
    # human. Here the table is created upstream, so it is worth one more look.
    patient_policy = LLMRetryPolicy(
        llm_conn_id="pydanticai_default",
        retry_delays={**DEFAULT_RETRY_DELAYS, "resource": timedelta(minutes=5)},
    )

    @dag(catchup=False, tags=["example", "retry_policy", "llm"])
    def example_llm_retry_policy():
        @task(retries=3, retry_delay=timedelta(minutes=1), retry_policy=llm_policy)
        def task_auth_error():
            """Should classify as ``auth``, absent from the retry table -> FAIL immediately."""
            raise PermissionError("403 Forbidden: API key expired for service account analytics@proj.iam")

        @task(retries=3, retry_delay=timedelta(minutes=1), retry_policy=llm_policy)
        def task_rate_limit():
            """Should classify as ``rate_limit``, which the retry table maps to a 60s delay."""
            raise RuntimeError("429 Too Many Requests: Rate limit exceeded. Retry after 60 seconds.")

        @task(retries=3, retry_delay=timedelta(minutes=1), retry_policy=llm_policy)
        def task_data_error():
            """Should classify as ``data``, absent from the retry table -> FAIL immediately."""
            raise ValueError("Column 'user_id' expected type INT but got STRING in row 42.")

        @task(retries=3, retry_delay=timedelta(minutes=1), retry_policy=patient_policy)
        def task_missing_table():
            """Should classify as ``resource``, which this policy's table retries after 5m."""
            raise FileNotFoundError("Table 'analytics.daily_orders' does not exist")

        task_auth_error()
        task_rate_limit()
        task_data_error()
        task_missing_table()

    example_llm_retry_policy()
except ImportError:
    # RetryPolicy requires Airflow 3.3+; example DAG is skipped on older versions.
    pass
