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

Training a model can take hours or days, and a crash, an out of memory error or a lost worker means
starting over unless progress was saved. :class:`~airflow.providers.common.io.checkpoints.Checkpoints`
saves training progress from an Airflow task to object storage, and lets a retry continue from the
last complete checkpoint. You keep using your own training library and its own file format.

What is a checkpoint?
---------------------

A checkpoint is a snapshot of training at one point in time, saved so training can continue from
there later instead of starting over. It usually holds:

* **The model's weights:** everything it has learned so far.
* **The optimizer's state:** how it was learning, so training continues smoothly.
* **Where it was:** which step or epoch.

With ``Checkpoints``, each checkpoint has two parts:

* **The files:** whatever your training saves, in its own format, such as ``weights.npy`` or
  ``model.safetensors``.
* **The record:** a small note about those files, with the step, the scores, the Dag, run and task
  that made it, and the checkpoint it came from. A checkpoint only counts once its record exists,
  so a save that was cut off halfway is never used.

Why not save checkpoints yourself?
----------------------------------

You can, and many people do. Here is a typical Dag that trains three models in parallel, picks the
best one, and lets the next run start from it:

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

It gets a lot right:

* **It works across workers.** Checkpoints go to object storage, not local disk.
* **Trials are isolated.** Each one is its own mapped task, so one failing does not stop the others.
* **Runs do not overwrite each other.** Every checkpoint gets a new random name.
* **The best trial wins,** and **the next run builds on it** through an Asset.

But the model code is a handful of lines, and the checkpoint plumbing is everything else. And it
still lacks things:

* **A crash loses the whole trial.** The model is only saved at the end, so a retry starts from zero.
* **Every run continues from the best model.** There is no easy way to start fresh.
* **A half-written checkpoint can break later runs.** Nothing marks a checkpoint as complete.
* **Other tasks and runs cannot find checkpoints** without being handed their paths.
* **There is no history,** and **nothing is ever cleaned up.**

Worst of all, when one of these goes wrong, the Dag still finishes with success.

Coming from Metaflow
--------------------

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
     - ``start``: ``"fresh"`` (default), ``"latest"``, ``"best"`` or a checkpoint id
   * - Checkpoints are kept per
     - Flow, step and ``foreach`` index
     - ``name`` (the Dag id by default), task, map index and ``label``
   * - Listing checkpoints
     - ``current.checkpoint.list(task=...)`` with the Client API to find runs
     - ``find(...)`` from any task, across runs

Your first checkpoint
---------------------

First, tell Airflow where checkpoints live. You only do this once, in the ``[common.io]`` section of
the Airflow config:

.. code-block:: ini

    [common.io]
    checkpoints_path = s3://my_conn@ml-checkpoints/

Then, inside your task:

.. code-block:: python

    from airflow.providers.common.io.checkpoints import Checkpoints


    @task(retries=2)
    def train():
        ckpt = Checkpoints()

        start = ckpt.resume()
        if start:
            with ckpt.load(start) as folder:
                model = load_model(folder)
        else:
            model = new_model()

        for epoch in range(100):
            loss = train_one_epoch(model)
            with ckpt.save(step=epoch, metrics={"loss": loss}) as folder:
                save_model(model, folder)

Here is what each line does:

* ``Checkpoints()`` opens the checkpoints for this model. The model's name defaults to the Dag id.
* ``resume()`` asks "is there a checkpoint I should continue from?" On the first try there is none.
  On a retry, it returns this task's own latest checkpoint.
* ``load()`` downloads that checkpoint into a normal local folder, and you load your model from it
  the way you always do.
* ``save()`` gives you a normal local folder to save into. When the ``with`` block ends, the files
  are uploaded and the record is written.

You never touch the cloud yourself. You only deal with local folders, and ``Checkpoints`` moves
them up and down.

Why a local folder? Every training library (PyTorch, Hugging Face, NumPy, XGBoost) can write to one,
while many cannot write to ``s3://`` directly. Writing everything locally first also means a save
only counts once it is complete.

Where does a run start?
-----------------------

A retry always continues its own work first. ``start`` decides what happens when a task has no
checkpoint of its own yet:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - ``start=``
     - Meaning
   * - ``"fresh"`` (default)
     - Start from zero. A new run never picks up an old run's work by accident.
   * - ``"latest"``
     - Continue from the newest checkpoint of earlier runs. Useful when a run failed for good and
       you start a new one the next day.
   * - ``"best"``
     - Start from the best model so far (see below).
   * - a checkpoint id
     - Start from that exact checkpoint. Find ids with ``find()``.

A common pattern is to wire ``start`` to a Dag param, so you choose when you trigger the run:

.. code-block:: python

    @dag(params={"start": Param("fresh", type="string")})
    def train_model():
        @task
        def train(*, params=None):
            ckpt = Checkpoints(start=params["start"])
            ...

.. code-block:: bash

    airflow dags trigger train_model -c '{"start": "latest"}'

Many trials, one winner
-----------------------

Grid searches train several versions at once and keep the best. Give each trial a ``label``, so it
keeps its own checkpoints and can be found again in later runs:

.. code-block:: python

    BEST_MODEL = Asset("best_model")


    @task(retries=2, inlets=[BEST_MODEL])
    def train(lr: float, *, params=None):
        ckpt = Checkpoints(label=f"lr={lr}", start=params["start"], best_model_ref=BEST_MODEL)
        ...  # resume, train and save, as above


    @task(outlets=[BEST_MODEL])
    def pick_winner(*, ti=None):
        ckpt = Checkpoints(best_model_ref=BEST_MODEL)
        latest = ckpt.find(run_id=ti.run_id, task_id="train", latest_per_task=True)
        winner = min(latest, key=lambda r: r["metrics"]["loss"])

        current = ckpt.best()
        if current is None or winner["metrics"]["loss"] < current["metrics"]["loss"]:
            ckpt.set_best(winner)


    train.expand(lr=[0.01, 0.1, 0.5]) >> pick_winner()

``set_best`` only moves the "best model" pointer. Deciding what "better" means is up to you, so any
rule works, from the lowest loss to a holdout comparison or a human approval. The pointer lives in
the state of the Asset you pass as ``best_model_ref``, so the task must have that Asset in its
``inlets`` or ``outlets``.

.. note::

    Use ``set_best``, ``best()`` and ``start="best"`` only if your model registry does not already
    track a best model. If you use a registry such as MLflow, keep the champion there, and use
    ``Checkpoints`` for saving and resuming training progress. Tracking the best model in both places
    gives two answers that can drift apart.

Finding checkpoints
-------------------

``find()`` searches every checkpoint of this model, across all runs, newest first. Every argument is
optional:

.. code-block:: python

    ckpt.find()                                                       # everything
    ckpt.find(label="lr=0.1", limit=5)                                # one label's last 5
    ckpt.find(run_id=run_id, task_id="train", latest_per_task=True)   # each trial's last save
    ckpt.find(where=lambda r: r["metrics"]["loss"] < 0.3)             # by score, or anything else

``where`` takes a record and returns ``True`` to keep it. Dags that use the same ``name`` share their
checkpoints, so ``find()`` also sees what other Dags saved.

Every checkpoint also remembers the checkpoint it came from, so you can trace a model back through
its earlier runs:

.. code-block:: python

    for record in ckpt.history(ckpt.best()):
        print(record["dag_id"], record["run_id"], record["step"], record["metrics"])

That answers questions like "which run did this model grow from?" or "did this run really start
from the best model?"

Keeping storage tidy
--------------------

Long training can save every few minutes, and checkpoints pile up. Two tools help:

* ``Checkpoints(keep_last=3)`` removes old checkpoints as training goes. After each save, only this
  task's newest three checkpoints in the current run keep their files.
* ``ckpt.cleanup(keep_last=2)`` tidies up everything for this model, across all runs. Run it in a
  separate task, for example at the end of the Dag.

Both delete only the files. The small records are kept, so ``history()`` never breaks. Both also
keep the best model, as long as that ``Checkpoints`` was given ``best_model_ref``.

Nothing is ever deleted unless you ask for it. For age-based rules, such as "delete anything older
than 90 days", use your bucket's lifecycle rules.

Large models
------------

Files are streamed to storage, so saving does not load a checkpoint into memory a second time. But
by default, training waits while a checkpoint uploads, and for a model of many gigabytes that can
take minutes.

Pass ``background=True`` and training only waits for your code to write the files locally. The
upload runs while the next steps train. Background saves need ``Checkpoints`` used as a ``with``
block, so leaving the block waits for the last upload, and fails the task if it broke:

.. code-block:: python

    with Checkpoints(keep_last=3) as ckpt:
        for step in range(total_steps):
            train_step(model)
            if step % 1000 == 0:
                with ckpt.save(step=step, metrics={"loss": loss}, background=True) as folder:
                    torch.save(model.state_dict(), folder / "model.pt")

Things to know:

* Only one upload runs at a time. If the next save comes before the previous upload finishes, it
  waits for it first. Background uploads help most when training between saves takes longer than
  one upload.
* Saving needs free local disk for one checkpoint, or two with ``background=True`` (one uploading,
  one being written).
* If the task is killed during an upload, the checkpoint has no record, so a retry resumes from the
  previous complete checkpoint.
* On S3, a killed upload can leave hidden parts behind that are still stored. Add a bucket lifecycle
  rule that aborts incomplete multipart uploads after a few days.

Using with Hugging Face
-----------------------

The Hugging Face ``Trainer`` already saves its own checkpoint folders, with the model, optimizer,
learning rate schedule and random state. A small callback uploads each folder after the ``Trainer``
writes it:

.. code-block:: python

    import shutil
    from pathlib import Path

    from transformers import TrainerCallback


    class SaveToCheckpoints(TrainerCallback):
        def __init__(self, ckpt):
            self.ckpt = ckpt

        def on_save(self, args, state, control, **kwargs):
            src = Path(args.output_dir) / f"checkpoint-{state.global_step}"
            loss = next(h["loss"] for h in reversed(state.log_history) if "loss" in h)
            with self.ckpt.save(step=state.global_step, metrics={"loss": loss}) as folder:
                shutil.copytree(src, folder, dirs_exist_ok=True)

Add the callback to the ``Trainer``, and pass the checkpoint back when resuming. The ``Trainer``
then continues from the exact step it stopped at:

.. code-block:: python

    ckpt = Checkpoints()
    trainer = Trainer(model=model, args=args, train_dataset=dataset, callbacks=[SaveToCheckpoints(ckpt)])

    start = ckpt.resume()
    if start:
        with ckpt.load(start) as folder:
            trainer.train(resume_from_checkpoint=str(folder))
    else:
        trainer.train()

Hugging Face decides what goes into a checkpoint. ``Checkpoints`` decides where it is stored and
which one to continue from. The callback copies the folder, so a checkpoint briefly takes up twice
its size on local disk. Set ``save_total_limit=1`` in ``TrainingArguments`` so the ``Trainer`` does
not keep old copies locally.

Reference
---------

Options
^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Option
     - Meaning
   * - ``name``
     - Folder for this model. Defaults to the Dag id. Set it to keep your checkpoints after renaming
       the Dag, or to share checkpoints between Dags.
   * - ``label``
     - Tells parallel copies of a task apart, and stays the same across runs, e.g. ``"lr=0.1"``.
       Required for mapped tasks that use ``start="latest"``, so a reordered list never resumes
       another copy's checkpoint.
   * - ``start``
     - ``"fresh"`` (default), ``"latest"``, ``"best"`` or a checkpoint id. See
       `Where does a run start?`_.
   * - ``base``
     - Object storage path to keep checkpoints under, e.g. ``s3://my_conn@my-bucket/``. The
       connection id goes in the user part of the URL. Defaults to ``[common.io] checkpoints_path``.
   * - ``keep_last``
     - If set, after each save only this task's newest ``keep_last`` checkpoints in the current run
       keep their files.
   * - ``best_model_ref``
     - Asset whose state points to the best model. Needed for ``start="best"``, ``best()`` and
       ``set_best()``. The task must have this Asset in its ``inlets`` or ``outlets``.

Methods
^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Method
     - What it does
   * - ``save(step, metrics, background=False)``
     - Gives you a local folder to save into, then uploads it and writes the record.
   * - ``resume()``
     - Returns the checkpoint to start from, or ``None``.
   * - ``load(record)``
     - Downloads a checkpoint into a local folder for the duration of the ``with`` block.
   * - ``latest()``
     - Returns this task's latest checkpoint in the current run.
   * - ``find(run_id, task_id, label, dag_id, where, latest_per_task, limit)``
     - Lists checkpoints across all runs, newest first.
   * - ``get(ckpt_id)``
     - Returns one checkpoint's record, including checkpoints removed by ``cleanup``.
   * - ``history(record)``
     - Returns ``record`` and the checkpoints it came from, newest first.
   * - ``best()``
     - Returns the best model's record, or ``None``.
   * - ``set_best(record)``
     - Marks ``record`` as the best model.
   * - ``cleanup(keep_last=2)``
     - Deletes the files of all but the newest ``keep_last`` checkpoints of each task, across runs.

Where checkpoints are stored
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text

    <base>/<name>/ckpts/<id>/...        your checkpoint files
    <base>/<name>/records/<id>.json     one record per checkpoint, written last
    <base>/<name>/history/<id>.json     records of checkpoints removed by cleanup

A record holds the checkpoint's ``id``, ``path``, ``step``, ``metrics``, ``dag_id``, ``run_id``,
``task_id``, ``map_index``, ``label``, ``try_number``, ``parent`` (the checkpoint it came from) and
``created_at``. Records are plain dicts, so they can be passed through XCom.

Limitations
-----------

* Requires Airflow 3. The best model features need the asset state store, available from Airflow 3.3.
* ``Checkpoints`` only works inside a running Airflow task.
* Checkpoints are not shown in the Airflow UI. Use ``find()`` to list them.
* ``cleanup`` and ``keep_last`` only protect the best model when that ``Checkpoints`` is given
  ``best_model_ref``.
* If two Dag runs call ``set_best`` at the same time, the last one wins, even if its model is worse.
