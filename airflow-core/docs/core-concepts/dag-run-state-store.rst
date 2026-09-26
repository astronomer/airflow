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

.. _concepts:dag-run-state-store:

Dag Run State Store
===================

.. versionadded:: 3.4

The Dag run state store is a key/value store scoped to a single Dag run (``dag_id`` + ``run_id``). Every task in the run reads and writes the same keys, and the state is removed with the run.

Use it when a value belongs to the run rather than to any one task. :ref:`Task state <concepts:task-state-store>` is removed when its task instance is cleared, and asset state outlives the run entirely, so neither gives a value that lives exactly as long as the run.

It is reached through the task context as ``context["dag_run_state_store"]`` and exposes ``get``, ``set``, ``delete`` and ``clear``, plus the async counterparts ``aget``, ``aset``, ``adelete`` and ``aclear``.

.. code-block:: python

    @task
    def resolve_model(**context):
        model = pick_model()
        context["dag_run_state_store"].set("model", model)


    @task
    def score(**context):
        # every task in this run sees the value resolve_model wrote
        model = context["dag_run_state_store"].get("model")
        return run_inference(model)

A task can only reach the state of the run it belongs to. The scope is resolved on the API server from the caller's own task instance, so nothing in the request can redirect a read or a write to another run.

Concurrent writes
-----------------

.. warning::

    The Dag run state store is not safe for read-modify-write from tasks running in parallel.

Concurrent ``set`` calls on one key are last-writer-wins, and a reader never sees a partial value. Which writer wins is not defined.

That means a task cannot read a key, change the value and write it back while other tasks might do the same. Both read the old value, both write, and one update is lost. There is no atomic increment.

Give each writer its own key instead:

.. code-block:: python

    # loses updates when tasks run in parallel
    total = store.get("spend", 0)
    store.set("spend", total + cost)

    # safe: no two tasks write the same key
    store.set(f"spend/{context['ti'].task_id}", cost)

To count task instances in the run, read their states rather than maintaining a counter. Airflow already tracks them, and a hand-written counter misses tasks that are killed before they can update it.

Retention
---------

Rows are removed when the Dag run row is deleted. They also carry an expiry, set at write time from ``[state_store] dag_run_default_retention_days``, and expired rows are removed by ``airflow state-store clean``. Pass ``retention`` to ``set`` to override it for one key, or ``NEVER_EXPIRE`` to keep it until the run is deleted.
