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

from airflow.providers.common.compat.sdk import ObjectStoragePath, get_current_context

if TYPE_CHECKING:
    from collections.abc import Iterator

    from airflow.sdk import Asset, Context

Record = dict[str, Any]

BEST_KEY = "best_checkpoint"


class Checkpoints:
    """
    Save, find and reuse checkpoints for the current task.

    Files are uploaded to ``<base>/<name>/ckpts/<id>/``. A small JSON record is written to
    ``<base>/<name>/records/<id>.json`` only after the upload finishes, so a checkpoint without a
    record does not exist. Records live in storage, not in task state, so other tasks, later runs
    and other Dags can find them, and clearing a task does not lose them.

    :param base: Object storage path to keep checkpoints under, e.g. ``s3://my_conn@bucket/``.
    :param name: Folder for this model. Defaults to the Dag id; set it to keep finding checkpoints
        after a Dag rename, or to share them between Dags.
    :param trial: Optional label for this trial, e.g. ``"lr=0.1"``.
    :param start: Where an attempt with no checkpoint of its own starts: ``"fresh"``, ``"best"``
        or a checkpoint id.
    :param best_model: Asset whose state holds the best checkpoint id. Needed for ``start="best"``
        and ``promote_if_better``. The task must have it as an inlet or outlet.
    """

    def __init__(
        self,
        base: str | ObjectStoragePath,
        *,
        name: str | None = None,
        trial: str | None = None,
        start: str = "fresh",
        best_model: Asset | None = None,
        context: Context | None = None,
    ) -> None:
        self.context = context or get_current_context()
        self.ti = self.context["ti"]
        self.root = ObjectStoragePath(base) / (name or self.ti.dag_id)
        self.trial = trial
        self.start = start
        self.best_model = best_model
        self._parent: str | None = None
        self._pending: threading.Thread | None = None
        self._error: BaseException | None = None

    @contextmanager
    def save(
        self, step: int, metrics: dict[str, float] | None = None, *, background: bool = False
    ) -> Iterator[Path]:
        """
        Yield a local folder to write checkpoint files into, then upload it and write its record.

        With ``background=True`` the upload runs in a thread so training can continue. Call
        ``wait()`` before the task finishes, or the last checkpoint may not be recorded.
        """
        self.wait()
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
            "trial": self.trial,
            "try_number": self.ti.try_number,
            "parent": self._parent,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if background:
            self._pending = threading.Thread(target=self._upload_in_background, args=(tmp, record))
            self._pending.start()
        else:
            self._upload(tmp, record)

    def wait(self) -> None:
        """Wait for a background upload to finish, and raise its error if it failed."""
        if self._pending is not None:
            self._pending.join()
            self._pending = None
        if self._error is not None:
            error, self._error = self._error, None
            raise error

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
        if record is None and self.start == "best":
            record = self.best()
        elif record is None and self.start != "fresh":
            record = self.get(self.start)
        self._parent = record["id"] if record else None
        return record

    def latest(self) -> Record | None:
        """Return the latest checkpoint saved by this task instance in this run."""
        found = self.find(
            dag_id=self.ti.dag_id,
            run_id=self.ti.run_id,
            task_id=self.ti.task_id,
            map_index=self.ti.map_index,
        )
        return found[0] if found else None

    def find(self, *, latest_only: bool = False, **filters: Any) -> list[Record]:
        """
        Return records matching every filter, newest first.

        Filters are record fields, e.g. ``run_id=...`` or ``trial="lr=0.1"``. With ``latest_only``,
        keep only the newest record of each task instance.
        """
        records_dir = self.root / "records"
        if not records_dir.exists():
            return []
        records = [json.loads(p.read_text()) for p in records_dir.glob("*.json")]
        records = [r for r in records if all(r.get(k) == v for k, v in filters.items())]
        records.sort(key=lambda r: r["created_at"], reverse=True)
        if latest_only:
            seen = set()
            newest = []
            for r in records:
                key = (r["dag_id"], r["run_id"], r["task_id"], r["map_index"])
                if key not in seen:
                    seen.add(key)
                    newest.append(r)
            records = newest
        return records

    def get(self, ckpt_id: str) -> Record:
        return json.loads(self._record_path(ckpt_id).read_text())

    def best(self) -> Record | None:
        best_id = self._best_store().get(BEST_KEY)
        return self.get(best_id) if best_id else None

    def promote_if_better(self, record: Record, *, metric: str, lower_is_better: bool = False) -> bool:
        """Make ``record`` the best checkpoint if it beats the current one on ``metric``."""
        current = self.best()
        if current is not None:
            new, old = record["metrics"][metric], current["metrics"][metric]
            if (new >= old) if lower_is_better else (new <= old):
                return False
        self._best_store().set(BEST_KEY, record["id"])
        return True

    def cleanup(self, keep_last: int = 2) -> list[str]:
        """Delete all but the newest ``keep_last`` checkpoints of each task instance, never the best one."""
        best_id = self._best_store().get(BEST_KEY) if self.best_model else None
        kept: dict[tuple, int] = {}
        deleted = []
        for r in self.find():
            key = (r["dag_id"], r["task_id"], r["map_index"], r["trial"])
            kept[key] = kept.get(key, 0) + 1
            if kept[key] <= keep_last or r["id"] == best_id:
                continue
            # Record first, so a half-deleted checkpoint is never found.
            self._record_path(r["id"]).unlink()
            ObjectStoragePath(r["path"]).rmdir(recursive=True)
            deleted.append(r["id"])
        return deleted

    def _record_path(self, ckpt_id: str) -> ObjectStoragePath:
        return self.root / "records" / f"{ckpt_id}.json"

    def _best_store(self):
        if self.best_model is None:
            raise ValueError("Pass best_model to use the best checkpoint.")
        return self.context["asset_state_store"][self.best_model]


def _copy(src: Path | ObjectStoragePath, dst: Path | ObjectStoragePath) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as fin, dst.open("wb") as fout:
        shutil.copyfileobj(fin, fout)


def _write_json(path: ObjectStoragePath, data: Record) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
