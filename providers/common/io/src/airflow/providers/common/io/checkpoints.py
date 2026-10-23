#
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
"""Save, find and reuse model checkpoints from Airflow tasks."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from airflow.providers.common.compat.sdk import ObjectStoragePath, conf, get_current_context

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from airflow.sdk import Asset

Record = dict[str, Any]

BEST_KEY = "best_checkpoint"


class Checkpoints:
    """
    Save, find and reuse checkpoints for the current task.

    Files are uploaded to ``<base>/<name>/ckpts/<id>/``. A small JSON record is written to
    ``<base>/<name>/records/<id>.json`` only after the upload finishes, so a checkpoint without a
    record does not exist. Records live in storage, not in task state, so other tasks, later runs
    and other Dags can find them, and clearing a task does not lose them.

    :param name: Folder for this model. Defaults to the Dag id; set it to keep finding checkpoints
        after a Dag rename, or to share them between Dags.
    :param label: Tells parallel copies of a task apart and stays the same across runs,
        e.g. ``"lr=0.1"``. Required for mapped tasks that use ``start="latest"``.
    :param start: Where an attempt with no checkpoint of its own starts: ``"fresh"``, ``"latest"``
        (the newest checkpoint from earlier runs), ``"best"`` or a checkpoint id.
    :param base: Object storage path to keep checkpoints under, e.g. ``s3://my_conn@bucket/``.
        Defaults to ``[common.io] checkpoints_path``.
    :param keep_last: If set, after each save only this task's newest ``keep_last`` checkpoints in
        the current run keep their files. The best checkpoint is kept when ``best_model_ref`` is set.
    :param best_model_ref: Asset whose state points to the best checkpoint. Needed for
        ``start="best"``, ``best()`` and ``set_best()``. The task must have it as an inlet or outlet.
    """

    def __init__(
        self,
        name: str | None = None,
        *,
        label: str | None = None,
        start: str = "fresh",
        base: str | ObjectStoragePath | None = None,
        keep_last: int | None = None,
        best_model_ref: Asset | None = None,
    ) -> None:
        self.context = get_current_context()
        self.ti = self.context["ti"]
        base = base or conf.get("common.io", "checkpoints_path", fallback="")
        if not base:
            raise ValueError("Pass base or set [common.io] checkpoints_path.")
        if start == "latest" and self.ti.map_index >= 0 and label is None:
            raise ValueError('Mapped tasks need a label to use start="latest".')
        if keep_last is not None and keep_last < 1:
            raise ValueError("keep_last must be at least 1.")
        self.root = ObjectStoragePath(base) / (name or self.ti.dag_id)
        self.label = label
        self.start = start
        self.keep_last = keep_last
        self.best_model_ref = best_model_ref
        self._parent: str | None = None
        self._pending: threading.Thread | None = None
        self._error: BaseException | None = None
        self._in_with = False

    def __enter__(self) -> Checkpoints:
        self._in_with = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._in_with = False
        if exc_type is None:
            self._wait()
        elif self._pending is not None:
            # Let the last upload finish so a retry can resume from it; the block's own error wins.
            self._pending.join()
            self._pending = None

    @contextmanager
    def save(
        self, step: int, metrics: dict[str, float] | None = None, *, background: bool = False
    ) -> Iterator[Path]:
        """
        Yield a local folder to write checkpoint files into, then upload it and write its record.

        With ``background=True`` the upload runs in a thread so training can continue. This needs
        ``with Checkpoints(...) as ckpt:``, so leaving the block waits for the last upload.
        """
        if background and not self._in_with:
            raise ValueError('Use "with Checkpoints(...) as ckpt:" to save in the background.')
        self._wait()
        ckpt_id = uuid.uuid4().hex
        tmp = Path(tempfile.mkdtemp())
        try:
            yield tmp
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        record = {
            "id": ckpt_id,
            "path": str(self.root / "ckpts" / ckpt_id),
            "step": step,
            "metrics": metrics or {},
            "dag_id": self.ti.dag_id,
            "run_id": self.ti.run_id,
            "task_id": self.ti.task_id,
            "map_index": self.ti.map_index,
            "label": self.label,
            "try_number": self.ti.try_number,
            "parent": self._parent,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if background:
            self._pending = threading.Thread(target=self._upload_in_background, args=(tmp, record))
            self._pending.start()
        else:
            self._upload(tmp, record)
            self._prune()

    def _wait(self) -> None:
        if self._pending is not None:
            self._pending.join()
            self._pending = None
            if self._error is None:
                self._prune()
        if self._error is not None:
            error, self._error = self._error, None
            raise error

    def _prune(self) -> None:
        # Runs on the task's own thread, never the upload thread, because it reads the best checkpoint.
        if self.keep_last is None:
            return
        map_index = self.ti.map_index
        mine = self.find(
            dag_id=self.ti.dag_id,
            run_id=self.ti.run_id,
            task_id=self.ti.task_id,
            where=lambda r: r["map_index"] == map_index,
        )
        best_id = self._best_id()
        for r in mine[self.keep_last :]:
            if r["id"] != best_id:
                self._retire(r)

    def _upload(self, tmp: Path, record: Record) -> None:
        try:
            dest = ObjectStoragePath(record["path"])
            for file in tmp.rglob("*"):
                if file.is_file():
                    _copy(file, dest / file.relative_to(tmp).as_posix())
            _write_json(self._record_path(record["id"]), record)
            self._parent = record["id"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _upload_in_background(self, tmp: Path, record: Record) -> None:
        try:
            self._upload(tmp, record)
        except BaseException as e:
            self._error = e

    @contextmanager
    def load(self, record: Record) -> Iterator[Path]:
        """Download a checkpoint's files into a local folder for the duration of the block."""
        src = ObjectStoragePath(record["path"])
        with tempfile.TemporaryDirectory() as tmp:
            for file in src.rglob("*"):
                if file.is_file():
                    _copy(file, Path(tmp) / file.relative_to(src).as_posix())
            yield Path(tmp)

    def resume(self) -> Record | None:
        """Return this task's own latest checkpoint, else follow ``start``."""
        record = self.latest()
        if record is None and self.start == "latest":
            record = self._latest_from_earlier_runs()
        elif record is None and self.start == "best":
            record = self.best()
        elif record is None and self.start != "fresh":
            record = self.get(self.start)
        self._parent = record["id"] if record else None
        return record

    def _latest_from_earlier_runs(self) -> Record | None:
        # Matched by task and label, not Dag id, so a renamed Dag keeps its history.
        if self.label is not None:
            found = self.find(task_id=self.ti.task_id, label=self.label, limit=1)
        else:
            map_index = self.ti.map_index
            found = self.find(
                task_id=self.ti.task_id,
                where=lambda r: r.get("label") is None and r["map_index"] == map_index,
                limit=1,
            )
        return found[0] if found else None

    def latest(self) -> Record | None:
        """Return the latest checkpoint saved by this task instance in this run."""
        map_index = self.ti.map_index
        found = self.find(
            dag_id=self.ti.dag_id,
            run_id=self.ti.run_id,
            task_id=self.ti.task_id,
            where=lambda r: r["map_index"] == map_index,
            limit=1,
        )
        return found[0] if found else None

    def find(
        self,
        *,
        run_id: str | None = None,
        task_id: str | None = None,
        label: str | None = None,
        dag_id: str | None = None,
        where: Callable[[Record], bool] | None = None,
        latest_per_task: bool = False,
        limit: int | None = None,
    ) -> list[Record]:
        """
        Return checkpoint records matching every filter, newest first.

        ``where`` takes a record and returns ``True`` to keep it, e.g.
        ``where=lambda r: r["metrics"]["loss"] < 0.3``. With ``latest_per_task``, only the newest
        record of each task instance is kept.
        """
        records_dir = self.root / "records"
        if not records_dir.exists():
            return []
        filters = {"run_id": run_id, "task_id": task_id, "label": label, "dag_id": dag_id}
        filters = {k: v for k, v in filters.items() if v is not None}
        records = [json.loads(p.read_text()) for p in records_dir.glob("*.json")]
        records = [r for r in records if all(r.get(k) == v for k, v in filters.items())]
        if where is not None:
            records = [r for r in records if where(r)]
        records.sort(key=lambda r: r["created_at"], reverse=True)
        if latest_per_task:
            seen = set()
            newest = []
            for r in records:
                key = (r["dag_id"], r["run_id"], r["task_id"], r["map_index"])
                if key not in seen:
                    seen.add(key)
                    newest.append(r)
            records = newest
        return records[:limit]

    def get(self, ckpt_id: str) -> Record:
        """Return one checkpoint's record, including checkpoints removed by ``cleanup``."""
        try:
            return json.loads(self._record_path(ckpt_id).read_text())
        except FileNotFoundError:
            return json.loads(self._history_path(ckpt_id).read_text())

    def history(self, record: Record) -> list[Record]:
        """Return ``record`` and the checkpoints it came from, newest first."""
        chain = [record]
        while chain[-1]["parent"]:
            chain.append(self.get(chain[-1]["parent"]))
        return chain

    def best(self) -> Record | None:
        best_id = self._best_store().get(BEST_KEY)
        return self.get(best_id) if best_id else None

    def set_best(self, record: Record) -> None:
        """
        Mark ``record`` as the best checkpoint. Deciding whether it is better is up to the caller.

        Only use this if your model registry (e.g. MLflow) does not already track the best model.
        """
        self._best_store().set(BEST_KEY, record["id"])

    def cleanup(self, keep_last: int = 2) -> list[str]:
        """
        Delete the files of all but the newest ``keep_last`` checkpoints of each task.

        The best checkpoint is kept only when ``best_model_ref`` is set. Records move to ``history/``,
        so ``find()`` skips them but ``history()`` still works.
        """
        best_id = self._best_id()
        kept: dict[tuple, int] = {}
        deleted = []
        for r in self.find():
            key = (r["dag_id"], r["task_id"], r["map_index"], r.get("label"))
            kept[key] = kept.get(key, 0) + 1
            if kept[key] <= keep_last or r["id"] == best_id:
                continue
            self._retire(r)
            deleted.append(r["id"])
        return deleted

    def _retire(self, record: Record) -> None:
        # Move the record before deleting files, so find() never returns a checkpoint without files.
        _write_json(self._history_path(record["id"]), {**record, "files_deleted": True})
        self._record_path(record["id"]).unlink()
        ObjectStoragePath(record["path"]).rmdir(recursive=True)

    def _best_id(self) -> str | None:
        return self._best_store().get(BEST_KEY) if self.best_model_ref else None

    def _record_path(self, ckpt_id: str) -> ObjectStoragePath:
        return self.root / "records" / f"{ckpt_id}.json"

    def _history_path(self, ckpt_id: str) -> ObjectStoragePath:
        return self.root / "history" / f"{ckpt_id}.json"

    def _best_store(self):
        if self.best_model_ref is None:
            raise ValueError("Pass best_model_ref to use the best checkpoint.")
        try:
            return self.context["asset_state_store"][self.best_model_ref]
        except KeyError:
            raise ValueError("Add best_model_ref to this task's inlets or outlets.") from None


def _copy(src: Path | ObjectStoragePath, dst: Path | ObjectStoragePath) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as fin, dst.open("wb") as fout:
        shutil.copyfileobj(fin, fout)


def _write_json(path: ObjectStoragePath, data: Record) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
