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

Checkpoints for long-running tasks
==================================

.. warning::

    ``Checkpoint`` is experimental. Its API may change, and it may move into Task Steps
    (`AIP-112 <https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=440304696>`__).

A task that runs for hours, such as model training or a large index build, starts again from zero
when it fails and Airflow retries it. :class:`~airflow.providers.common.io.checkpoint.Checkpoint`
saves the task's progress as a folder of files while it runs, and hands that folder back to the
retry, so it continues from the last save.

If your progress is a small value, such as a row offset, a page number or an external job id, store
it directly in the :doc:`task state store <apache-airflow:core-concepts/task-state-store>` instead.
``Checkpoint`` is for progress that is files: model weights, a DuckDB database, a FAISS index, or
dbt's ``run_results.json``.

How it works
------------

Each save is uploaded to object storage, into its own folder:

.. code-block:: text

    <base>/<dag_id>/<task_id>/<ti.id>/v<n>/

Once the upload finishes, a small pointer to that folder is written to task state. A retry reads the
pointer and gets the folder back. Because the pointer is written last, a task that dies in the
middle of a save leaves the pointer on the previous complete save, and the retry never sees a
half-written one. ``ti.id`` differs for every try, so an old attempt that is still running never
writes into the folder of the attempt that replaced it.

Requires Airflow 3.3 or later.

Saving and restoring
--------------------

Set the storage location once, in the Airflow config:

.. code-block:: ini

    [common.io]
    checkpoints_path = s3://my_conn@my-bucket/checkpoints/

Then, in the task:

.. code-block:: python

    from typing import TypedDict

    from airflow.providers.common.io.checkpoint import Checkpoint


    class Step(TypedDict):
        step: int
        loss: float


    @task(retries=3)
    def train():
        with Checkpoint[Step]("ckpt", keep=2) as ckpt:
            with ckpt.restore() as found:
                model = load_model(found.path) if found else new_model()
                start = found.metadata["step"] + 1 if found else 0

            for step in range(start, total_steps):
                loss = train_step(model)
                if step % 500 == 0:
                    with ckpt.save(Step(step=step, loss=loss)) as folder:
                        save_model(model, folder)

* ``"ckpt"`` is the task state key that holds the pointer.
* ``restore()`` yields ``None`` when there is nothing to restore. Otherwise it yields the files in a
  local folder (``found.path``), the metadata you saved (``found.metadata``), the folder in storage
  (``found.uri``) and the try that saved it (``found.try_number``). The local folder is removed when
  the block ends.
* ``save()`` yields an empty local folder. Write your files into it in any format. When the block
  ends, the folder is uploaded, then the pointer is written. If the block raises, nothing is saved.
* The metadata is a small JSON value saved next to the pointer, such as the step to continue from.
  Typing it with a ``TypedDict`` lets your editor check ``found.metadata["step"]``.

When the task runs again
------------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Situation
     - ``restore()`` yields
   * - Airflow retries the task after a failure
     - The last complete save
   * - The task died during a save
     - The save before it, since the pointer was not written yet
   * - The task was cleared
     - ``None``: clearing removes the pointer, so the task starts fresh
   * - A new Dag run
     - ``None``, unless ``warm_start`` is set (see below)
   * - The saved files were deleted, for example by a bucket lifecycle rule
     - Raises ``FileNotFoundError``. Clear the task to start fresh.

A save always contains at least one file: ``save()`` and ``commit()`` refuse an empty folder. So a
saved checkpoint whose files are gone was deleted after it was saved, and ``restore()`` says so
instead of handing back an empty folder.

Starting from an earlier result
-------------------------------

A new run starts fresh. To start it from an earlier result, for example to fine-tune a model you
trained before, pass its folder as ``warm_start``:

.. code-block:: python

    Checkpoint[Step]("ckpt", warm_start="s3://my_conn@my-bucket/models/churn/v12/")

``restore()`` returns that folder when the task has no save of its own yet. A retry still resumes its
own save first. A ``warm_start`` result has empty metadata and a ``try_number`` of ``None``. The
folder usually comes from a model registry, or from an asset event's ``extra`` published by the run
that produced it.

Engines that write to object storage
------------------------------------

Some engines, such as PyTorch distributed checkpointing or Spark, write to object storage
themselves. Give them a fresh folder with ``next_path()``, and call ``commit()`` once they have
finished writing:

.. code-block:: python

    path = ckpt.next_path()
    engine.save_checkpoint(path.as_uri())
    ckpt.commit(path, Step(step=step, loss=loss))

``as_uri()`` returns the location without the Airflow connection id, e.g. ``s3://my-bucket/...``,
which tools that do not know Airflow connections can use.

Libraries that save their own checkpoints
-----------------------------------------

Training libraries such as Hugging Face, Keras, Lightning and XGBoost save checkpoints themselves,
on their own schedule. Hook into the library's callback, and hand the folder it wrote to
``save_folder()``. It uploads the folder as it is, then writes the pointer, and leaves the folder in
place. For example, with the Hugging Face ``Trainer``:

.. code-block:: python

    from transformers import TrainerCallback


    class SaveToCheckpoint(TrainerCallback):
        def __init__(self, ckpt):
            self.ckpt = ckpt

        def on_save(self, args, state, control, **kwargs):
            if state.is_world_process_zero:
                folder = f"{args.output_dir}/checkpoint-{state.global_step}"
                self.ckpt.save_folder(folder, {"step": state.global_step})


    with Checkpoint("ckpt") as ckpt:
        trainer = Trainer(model=model, args=args, train_dataset=data, callbacks=[SaveToCheckpoint(ckpt)])
        with ckpt.restore() as found:
            trainer.train(resume_from_checkpoint=str(found.path) if found else None)

``save_folder()`` always waits for its upload, since the library may change or delete the folder
right after. When training runs on several processes, save from the main process only.

Large checkpoints
-----------------

Files are streamed to and from storage, so memory use does not grow with the checkpoint size.
Saving does need free local disk for one checkpoint.

By default, training waits while a save uploads. Pass ``background=True`` to keep training while the
upload runs. Background saves need ``Checkpoint`` used as a ``with`` block: leaving the block waits
for the last upload and fails the task if it broke.

.. code-block:: python

    with Checkpoint[Step]("ckpt") as ckpt:
        for step in range(total_steps):
            loss = train_step(model)
            if step % 500 == 0:
                with ckpt.save(Step(step=step, loss=loss), background=True) as folder:
                    save_model(model, folder)

Only one upload runs at a time: a save waits for the previous upload first. With ``background=True``,
saving needs free local disk for two checkpoints, one uploading and one being written. When training
runs on several processes, save from the main process only.

Cleaning up
-----------

``keep=N`` deletes all but the newest ``N`` saves of the current try. Everything else, such as the
saves of earlier tries, cleared tasks and older runs, is left to your bucket's lifecycle rules, for
example deleting objects under the checkpoints prefix after 30 days. On S3, also add a rule that
aborts incomplete multipart uploads, which a task killed during an upload can leave behind.

What it is not for
------------------

* **Files a later Dag run needs**, such as Spark streaming state or dbt ``state:modified``: use a
  fixed path, and publish it in an asset event's ``extra`` when the run succeeds.
* **Training on a remote service**, such as SageMaker or Databricks: there, a retry should reconnect
  to the running job rather than restore files.
* **Passing large data to a downstream task**: use the :doc:`object storage XCom backend <xcom_backend>`.

Reference
---------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Parameter or method
     - What it does
   * - ``key``
     - Task state key that holds the pointer.
   * - ``base``
     - Object storage path for the files. Defaults to ``[common.io] checkpoints_path``.
   * - ``keep``
     - Keep only the newest ``keep`` saves of the current try.
   * - ``warm_start``
     - Folder to restore from when the task has no save of its own.
   * - ``restore(download=True)``
     - Yields the checkpoint to continue from, or ``None``. With ``download=False``, only ``uri`` is
       set, not ``path``.
   * - ``save(metadata, background=False)``
     - Yields an empty local folder, then uploads it and writes the pointer.
   * - ``save_folder(path, metadata)``
     - Uploads a local folder that a library already wrote, then writes the pointer.
   * - ``next_path()``
     - Returns a new, empty folder in object storage for the next save.
   * - ``commit(path, metadata)``
     - Makes ``path`` the checkpoint to restore from.
