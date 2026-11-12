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


Run Dags locally
================

Run a Dag the way you run any Python script: there is nothing to initialize and no server to start first.
Every run is kept in the project, and Airflow's UI shows it. When you want a Dag on a schedule, the same
project runs it there, from the same file.

Local runs are for developing Dags, not for production. They need macOS or Linux; on Windows, use WSL2 as
described in :doc:`/start`.

Create a project
----------------

Create a project with `uv <https://docs.astral.sh/uv/>`__:

.. code-block:: bash

    uvx --from apache-airflow-core airflow bootstrap demo
    cd demo

``airflow bootstrap`` writes a ``pyproject.toml`` that depends on Airflow, on a Python version Airflow
supports, and an example Dag in ``pipeline.py``. The first ``uv run`` installs Airflow into the project from
what ``uvx`` already downloaded. In a project that already has a ``pyproject.toml``, run
``uv add apache-airflow`` instead.

The example Dag:

.. exampleinclude:: /../src/airflow/local_run/example_dags/pipeline.py
    :language: python
    :start-after: [START run_dags_locally_pipeline]
    :end-before: [END run_dags_locally_pipeline]

Keep the call to ``workflow.run()`` under ``if __name__ == "__main__":``. A run imports the file again, the
way Airflow finds Dags, and without the guard that import would start the run a second time; an unguarded
call is refused before any run starts.

Run a Dag
---------

.. code-block:: bash

    uv run pipeline.py

The run prints one line per task on stderr, then your script goes on:

.. code-block:: text

    Running Dag 'example' from pipeline.py (run manual__2026-11-06T10:00:00.000000+00:00)
      ✓ numbers
      ✓ double[0]
      ✓ double[1]
      ✓ double[2]
      ✓ total
    Succeeded in 1.3s (4.4s total). History: /path/to/demo/.airflow
    total: 12

The first time is how long the tasks took; the total also counts starting the run, from the
``workflow.run()`` call.

Log lines and warnings go to stderr too, one line each, and a task's lines start with its name:
``total | pipeline: summing 3 values``. What a task prints goes to stdout, as it would in a plain script.
Each task's log in the history keeps every line in full.

``workflow.run()`` returns the run's result. ``result.output("total")`` is what the ``total`` task
returned, as the object it returned; ``result.output("double", 1)`` is the second mapped ``double``.
``result.state`` and ``result.task_states`` hold the run's and each task's state. A run that fails raises
``DagExecutionError``, which carries the same result, and the terminal shows each failed task's error from
your own code.

``workflow.run()`` takes:

* ``run_conf``: the run's ``conf``.
* ``conn_file_path`` and ``variable_file_path``: connections and variables files (JSON, YAML or env). The
  run also reads ``AIRFLOW_CONN_*`` and ``AIRFLOW_VAR_*`` environment variables.
* ``debug``: run every task in the run's own process, so that ``breakpoint()`` and your IDE's debugger stop
  in it. Otherwise each task try runs in a process of its own, as it does on a worker.

To look up connections and variables in a secrets backend, such as one that holds your development
credentials, name it in ``pyproject.toml``:

.. code-block:: toml

    [tool.airflow.secrets]
    backend = "airflow.providers.amazon.aws.secrets.secrets_manager.SecretsManagerBackend"
    backend_kwargs = { connections_prefix = "dev/airflow/connections", variables_prefix = "dev/airflow/variables" }

A run then looks in its connections and variables files first, then in that backend, then in ``AIRFLOW_CONN_*``
and ``AIRFLOW_VAR_*``; ``airflow standalone --project`` uses the backend too. Install the backend's provider in
the project, and give the backend its credentials the way it reads them, such as ``AWS_PROFILE``, or as
``AIRFLOW__SECRETS__BACKEND_KWARG__<NAME>`` variables. No other ``AIRFLOW__*`` setting reaches a local run, so a
backend configured for a deployment is not used.

To run a Dag from the command line instead, without a ``__main__`` block:

.. code-block:: bash

    uv run airflow run pipeline.py

``airflow run`` prints the same summary, then each task's output. It takes ``--dag-id`` for a file that
defines several Dags, ``--conf``, ``--connections-file``, ``--variables-file`` and ``--debug``.

.. _run-dags-locally:run-one-task:

Run one task
------------

After a run, you can change one task and run only that task again. The tasks before it don't run again: it
gets the outputs they returned in the earlier run.

.. code-block:: bash

    uv run airflow run pipeline.py --task total

.. code-block:: text

    Rerunning total in run manual__2026-11-06T10:00:00.000000+00:00, with the outputs of double, numbers
      ✓ total (try 2)
    Succeeded in 0.4s (2.1s total). History: /path/to/demo/.airflow
    Outputs:
      total = 12

The task runs as a new try in the latest run that has the outputs it needs, the way **Clear** reruns a task
in the UI. The new try runs the file as it is now, and the earlier try and its log stay in the history.
``airflow run`` prints the outputs of the tasks it ran.

``--task`` takes a task ID, or one mapped try as the run prints it: ``--task 'double[1]'``. Repeat it to
select more tasks, and use ``--group`` to select every task in a task group. With a selection:

* ``--downstream`` also runs the tasks after the selected ones, and ``--upstream`` the tasks before them.
* ``--run-id`` reruns the tasks in that run instead of the latest one.
* ``--conf`` starts a new run with that conf, in which the selected tasks and the tasks before them run.

When no earlier run has the outputs the selected tasks need, for example after you add a task before them,
they run in a new run too. The tasks they need run first, and the run records the tasks it leaves out as
skipped.

In Python, ``workflow.run()`` takes the same selection as keyword arguments:

.. code-block:: python

    if __name__ == "__main__":
        result = workflow.run(task_ids=["total"])
        print("total:", result.output("total"))

``task_ids`` takes task IDs and ``(task_id, map_index)`` tuples. The other arguments are
``task_group_ids``, ``include_upstream``, ``include_downstream`` and ``run_id``.

To stop in one task with your IDE's debugger, add ``debug=True`` to that call and use the IDE's Debug
button. Or leave the file as it is, and add a run configuration for the module ``airflow`` with the
arguments ``run pipeline.py --task total --debug``: ``"module": "airflow"`` in VS Code's ``launch.json``,
or **Module name** in PyCharm.

To test a task's code without Airflow, call its function with the arguments you choose:
``total.function([2, 4, 6])`` returns ``12``.

Look at the runs
----------------

The first run creates ``.airflow/`` next to your ``pyproject.toml``. It holds the project's history: a SQLite
database with every run, each task's logs, and a ``.gitignore`` that keeps it out of version control. Delete
it to start a new history.

To look at the history in Airflow's UI:

.. code-block:: bash

    uv run airflow standalone --project

It prints the address it serves on, ``http://127.0.0.1:`` and a free port, or the port ``--port`` names. The
UI shows each run's graph, task states, logs, Dag versions and code. While it runs, each run you start ends
with a link to its page instead of the history's path. Ctrl-C stops it.

The server answers on this machine only and needs no login. It accepts changes only from its own pages, and
from programs on this machine, which could open the project's database anyway.

Put a Dag on a schedule
-----------------------

``airflow standalone --project`` also runs a scheduler, a Dag processor and a triggerer for the project, on
the same history. They find every Dag in the project. Dags start paused: unpause one in the UI and it runs
on its schedule. **Trigger** and **Clear** work as in any Airflow deployment.

A run you start or rerun with ``workflow.run()`` or ``airflow run`` while the server runs stays with the
process that started it: the scheduler leaves it alone, so no task runs twice. The components log to
``.airflow/logs/scheduler.log``, ``dag-processor.log`` and ``triggerer.log``.

Limits
------

* A local run needs its Dag created at module level in a ``.py`` file, so that importing the file finds it:
  not in a notebook, and not inside the ``__main__`` block.
* Local runs and ``airflow standalone --project`` use SQLite and the ``LocalExecutor``. To run Airflow for
  more than one person, see :doc:`/installation/index`.
