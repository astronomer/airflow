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
A PR reviewer that learns from being corrected.

The task names an agent and passes a prompt. Everything else -- which credentials, which
model, the house rules it starts from, whether it may remember anything -- lives on the
agent, where a Dag author cannot change it.

Create the agent once::

    airflow agents add pr_reviewer \\
      --conn-id pydanticai_default \\
      --model anthropic:claude-haiku-4-5 \\
      --context-file pr_reviewer_context.md \\
      --memory

**Run 1.** Trigger the Dag. The review appears in the Agent Review tab on the task
instance and the task waits. Click *Request changes* and tell it what it missed::

    You missed the biggest problem: renaming a public field with no deprecated
    alias breaks every Dag that used it.

The agent turns that into a rule, saves it, and rewrites the review. Approve the rewrite.

    airflow agents show pr_reviewer      # the rule is now in memory

**Run 2.** Trigger again. Same Dag, same PR, and this time the review leads with the
breaking rename, because the rule is already in its prompt. Nobody had to say it twice.

To prove the improvement came from memory rather than luck::

    airflow agents clear-state pr_reviewer

and run again: it is back to missing it.

Why a human, and not the agent noticing by itself? Because nothing else tells the agent
whether its review was any good. Asked to introspect, it reliably "learns" a rule it was
already given, which crowds out the thing it actually missed. A reviewer typing one
sentence is the only real signal in this loop.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum

from airflow.providers.common.ai.operators.agent import AgentOperator
from airflow.sdk import DAG

PR_DIFF = '''
--- a/airflow-core/src/airflow/models/taskinstance.py
+++ b/airflow-core/src/airflow/models/taskinstance.py
@@ class TaskInstance(Base):
-    try_number: Mapped[int] = mapped_column(Integer, default=0)
+    attempt: Mapped[int] = mapped_column(Integer, default=0)

@@ def _handle_reschedule(self, ...):
-        if self.try_number > self.max_tries:
-            raise AirflowException("Task exhausted its retries")
+        if self.attempt > self.max_tries:
+            raise AirflowException("Task exhausted its retries")

--- a/airflow-core/src/airflow/utils/state.py
+++ b/airflow-core/src/airflow/utils/state.py
@@
-def get_state(ti):
+def get_state(ti):
+    # increment the counter
+    counter += 1
     return ti.state
'''

with DAG(
    dag_id="example_agent_pr_reviewer",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["agent", "memory"],
):
    AgentOperator(
        task_id="review",
        agent="pr_reviewer",
        # Nothing here asks the agent what it learned. It has no way to judge its own
        # review, so asking produces a restatement of the house rules rather than a lesson.
        # The learning happens when a reviewer corrects it below.
        prompt=(
            "Review this pull request against the house rules.\n\n"
            f"{PR_DIFF}\n\n"
            "List what you would block this PR on, most serious first."
        ),
        enable_hitl_review=True,
        # Bounded so a demo nobody comes back to does not hold a worker overnight.
        hitl_timeout=timedelta(minutes=30),
    )
