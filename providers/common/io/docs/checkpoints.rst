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

Model Training Checkpoints
==========================

:class:`~airflow.providers.common.io.checkpoints.Checkpoints` saves model checkpoints while a task
trains, so a crash does not send it back to the start, and hands the best model to later runs.
You keep using your own training library and its own file format.

The problem: checkpointing by hand
----------------------------------

The Dag below trains three models in parallel, one per learning rate, picks the best one, and lets
the next run start from it. It works, but every piece of checkpoint handling is written by hand:

.. code-block:: python

    import io
    import json
    import time
    import uuid

    from airflow.sdk import Asset, ObjectStoragePath, dag, task

    CKPTS = ObjectStoragePath("s3://my_conn@ml-checkpoints/ckpts/")
    BEST_MODEL = Asset("best_model")

    LRS = [0.05, 0.5, 0.1]


    @dag(schedule=None)
    def train_by_hand():
        @task(inlets=[BEST_MODEL])
        def train(lr: float, *, ti=None, task_state_store=None, asset_state_store=None) -> dict:
            import numpy as np

            rng = np.random.default_rng(0)
            X = rng.normal(size=(1000, 5))
            y = (X @ rng.normal(size=5) > 0).astype(float)

            warm_start = asset_state_store[BEST_MODEL].get("best_ckpt")
            if warm_start:
                with (ObjectStoragePath(warm_start) / "weights.npy").open("rb") as f:
                    w = np.load(io.BytesIO(f.read()))
            else:
                w = np.zeros(5)

            loss = None
            for epoch in range(20):
                p = 1 / (1 + np.exp(-(X @ w)))
                w -= lr * X.T @ (p - y) / len(y)
                loss = float(-np.mean(y * np.log(p + 1e-9) + (1 - y) * np.log(1 - p + 1e-9)))
                time.sleep(0.2)

            name = uuid.uuid4().hex[:12]
            buf = io.BytesIO()
            np.save(buf, w)
            with (CKPTS / name / "weights.npy").open("wb") as f:
                f.write(buf.getvalue())
            with (CKPTS / name / "meta.json").open("w") as f:
                json.dump({"loss": loss, "lr": lr, "run_id": ti.run_id, "warm_start": warm_start}, f)
            task_state_store.set("latest_ckpt", name)

            return {"lr": lr, "loss": loss, "ckpt": str(CKPTS / name)}

        @task(outlets=[BEST_MODEL])
        def select_best(results, *, asset_state_store=None) -> None:
            best = min(results, key=lambda r: r["loss"])
            asset_state_store[BEST_MODEL].set("best_ckpt", best["ckpt"])

        select_best(train.expand(lr=LRS))


    train_by_hand()

What this Dag already gets right:

* **Works across workers.** Checkpoints go to object storage, not local disk, so any worker can load
  them.
* **Trials are isolated.** Each trial is its own mapped task, so one trial failing does not stop or
  affect the others.
* **Runs do not overwrite each other.** Every checkpoint gets a new random name.
* **The best trial wins.** ``select_best`` compares the trials and keeps the one with the lowest loss.
* **The next run builds on the last.** The best model is kept on an Asset, so the next run starts
  from it instead of from scratch.

What it still lacks:

* **A crash loses the whole trial.** The model is only saved at the end, so a retry starts from zero.
* **Every run continues from the best model.** There is no way to start fresh without wiping the
  asset state by hand.
* **A half-written checkpoint breaks later runs.** If the task dies after writing ``weights.npy``
  but before ``meta.json``, the next run can load an incomplete checkpoint.
* **Other tasks and runs cannot find checkpoints.** Results only travel through XCom, and the
  ``latest_ckpt`` pointer lives in one task's state, which clearing the task deletes.
* **History is hand-made.** Only ``meta.json`` records which model a model started from.
* **Nothing is cleaned up.** Old checkpoints pile up in the bucket forever.

Each of these problems is silent: the Dag still finishes with success.

Checkpointing with ``Checkpoints``
----------------------------------

``Checkpoints`` takes care of all of the above:

* **Crash safety.** A retry continues from its own last checkpoint.
* **Safe saves.** A checkpoint only counts once all its files are uploaded, so an interrupted save is
  never loaded.
* **Parallel trials stay separate.** Each mapped task only resumes its own checkpoints.
* **An explicit start.** New runs start fresh by default, or from the best model, or from an exact
  checkpoint, as you choose.
* **Best model only when better.** The best model is replaced only if the new one beats it.
* **Findable everywhere.** Other tasks, later runs and other Dags can list checkpoints.
* **Survives clearing.** Checkpoints live in object storage, so clearing a task does not lose them.
* **History.** Each checkpoint records the checkpoint it came from.
* **Cleanup.** Old checkpoints can be deleted, keeping the newest ones and the best model.

The same Dag, rewritten:

.. code-block:: python

    import time
    from datetime import timedelta

    from airflow.providers.common.io.checkpoints import Checkpoints
    from airflow.sdk import Asset, Param, dag, task

    BASE = "s3://my_conn@ml-checkpoints/"
    BEST_MODEL = Asset("best_model")

    LRS = [0.05, 0.5, 0.1]


    @dag(schedule=None, params={"start": Param("fresh", type="string")})
    def train_with_checkpoints():
        @task(retries=2, retry_delay=timedelta(seconds=10), inlets=[BEST_MODEL])
        def train(lr: float, *, params=None, ti=None):
            import numpy as np

            rng = np.random.default_rng(0)
            X = rng.normal(size=(1000, 5))
            y = (X @ rng.normal(size=5) > 0).astype(float)

            ckpt = Checkpoints(BASE, trial=f"lr={lr}", start=params["start"], best_model=BEST_MODEL)
            start = ckpt.resume()
            if start:
                with ckpt.load(start) as folder:
                    w = np.load(folder / "weights.npy")
            else:
                w = np.zeros(5)

            # A retry continues its own epochs; a start from another run trains all 20.
            first_epoch = start["step"] if start and start["run_id"] == ti.run_id else 0

            for epoch in range(first_epoch, 20):
                p = 1 / (1 + np.exp(-(X @ w)))
                w -= lr * X.T @ (p - y) / len(y)
                loss = float(-np.mean(y * np.log(p + 1e-9) + (1 - y) * np.log(1 - p + 1e-9)))
                time.sleep(0.2)
                if (epoch + 1) % 5 == 0:
                    with ckpt.save(step=epoch + 1, metrics={"loss": loss}) as folder:
                        np.save(folder / "weights.npy", w)

        @task(outlets=[BEST_MODEL])
        def select_best(*, ti=None):
            ckpt = Checkpoints(BASE, best_model=BEST_MODEL)
            latest = ckpt.find(run_id=ti.run_id, task_id="train", latest_only=True)
            best = min(latest, key=lambda r: r["metrics"]["loss"])
            ckpt.promote_if_better(best, metric="loss", lower_is_better=True)
            ckpt.cleanup(keep_last=2)

        train.expand(lr=LRS) >> select_best()


    train_with_checkpoints()

To continue from the best model, trigger the Dag with ``{"start": "best"}``:

.. code-block:: bash

    airflow dags trigger train_with_checkpoints -c '{"start": "best"}'

Coming from Metaflow
^^^^^^^^^^^^^^^^^^^^

``Checkpoints`` follows the same model as Metaflow's ``@checkpoint`` extension: your training code
writes files into a local folder, and each parallel task keeps its own checkpoints.

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * -
     - Metaflow ``@checkpoint``
     - Airflow ``Checkpoints``
   * - Turn it on
     - ``@checkpoint`` decorator on a step
     - ``Checkpoints(...)`` inside the task
   * - Save
     - Write into ``current.checkpoint.directory``, then call ``current.checkpoint.save()``
     - Write into the folder from ``with ckpt.save(...) as folder:``. It uploads when the block ends.
   * - Resume on retry
     - Loaded automatically into the checkpoint directory
     - Call ``resume()``, then ``load()`` the result
   * - Start of a new run
     - ``load_policy``: ``"fresh"`` (default), ``"eager"`` (latest checkpoint of earlier runs) or
       ``None`` (you choose)
     - ``start``: ``"fresh"`` (default), ``"best"`` (the best model so far) or a checkpoint id
   * - Checkpoints are kept per
     - Flow, step and ``foreach`` index
     - ``name`` (the Dag id by default), task and map index
   * - Listing checkpoints
     - ``current.checkpoint.list(task=...)`` with the Client API to find runs
     - ``find(run_id=..., trial=...)`` from any task

What you can call
-----------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Call
     - What it does
   * - ``save(step, metrics)``
     - Gives you a local folder to write checkpoint files into. When the ``with`` block ends, the
       files are uploaded and the checkpoint's record is written. If the block fails, nothing is
       recorded.
   * - ``resume()``
     - Returns the checkpoint to start from, or ``None``. A retry gets its own latest checkpoint.
       Otherwise it follows ``start``.
   * - ``load(record)``
     - Downloads a checkpoint's files into a local folder for the duration of the ``with`` block.
   * - ``latest()``
     - Returns this task's latest checkpoint in the current run.
   * - ``find(**filters, latest_only=False)``
     - Lists checkpoints, newest first, filtered by any record field such as ``run_id``, ``task_id``
       or ``trial``. ``latest_only`` keeps the newest checkpoint of each task.
   * - ``get(ckpt_id)``
     - Returns one checkpoint's record.
   * - ``best()``
     - Returns the current best model's record, or ``None``.
   * - ``promote_if_better(record, metric, lower_is_better)``
     - Makes ``record`` the best model if it beats the current one on ``metric``.
   * - ``cleanup(keep_last=2)``
     - Deletes all but the newest ``keep_last`` checkpoints of each task, never the best model.

Options
-------

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Option
     - Meaning
   * - ``base``
     - Object storage path to keep checkpoints under. The connection id goes in the user part of
       the URL, e.g. ``s3://my_conn@my-bucket/``.
   * - ``name``
     - Folder for this model. Defaults to the Dag id. Set it to keep finding checkpoints after
       renaming the Dag, or to share checkpoints between Dags.
   * - ``trial``
     - Optional readable label for the trial, e.g. ``"lr=0.1"``.
   * - ``start``
     - Where an attempt with no checkpoint of its own starts: ``"fresh"`` (default), ``"best"``,
       or a checkpoint id.
   * - ``best_model``
     - Asset whose state holds the best model. Needed for ``start="best"``, ``best()`` and
       ``promote_if_better``. The task must have this asset in its ``inlets`` or ``outlets``.

Where checkpoints are stored
----------------------------

.. code-block:: text

    <base>/<name>/ckpts/<id>/...        your checkpoint files
    <base>/<name>/records/<id>.json     one record per checkpoint, written last

A record holds the checkpoint's ``id``, ``path``, ``step``, ``metrics``, ``dag_id``, ``run_id``,
``task_id``, ``map_index``, ``trial``, ``try_number``, ``parent`` (the checkpoint it came from) and
``created_at``. Records are plain dicts, so they can be passed through XCom.

To trace where a model came from, follow ``parent``:

.. code-block:: python

    record = ckpt.best()
    while record:
        print(record["run_id"], record["trial"], record["step"], record["metrics"])
        record = ckpt.get(record["parent"]) if record["parent"] else None

Limitations
-----------

* Requires Airflow 3. The best model features need the asset state store, available from Airflow 3.3.
* Checkpoints are not shown in the Airflow UI. Use ``find()`` to list them.
* If two Dag runs call ``promote_if_better`` at the same time, the last one wins, even if its model
  is worse (wip).
* ``cleanup`` deletes records too, so following ``parent`` stops at a deleted checkpoint.
* Uploads happen while training waits, which can be slow for very large checkpoints.
