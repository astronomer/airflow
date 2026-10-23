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
"""Save a task's progress as files, and restore them when the task is retried."""

from __future__ import annotations

import shutil
import tempfile
import threading
from collections.abc import Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from airflow.providers.common.compat.sdk import (
    AirflowOptionalProviderFeatureException,
    ObjectStoragePath,
    conf,
    get_current_context,
)
from airflow.providers.common.io.version_compat import AIRFLOW_V_3_3_PLUS

if TYPE_CHECKING:
    from collections.abc import Iterator

M = TypeVar("M", bound=Mapping[str, Any])


@dataclass(frozen=True)
class Restored(Generic[M]):
    """A checkpoint handed back by :meth:`Checkpoint.restore`."""

    uri: ObjectStoragePath
    path: Path | None
    metadata: M
    try_number: int | None


class Checkpoint(Generic[M]):
    """
    Save a task's progress as a folder of files, and restore it when the task is retried.

    Files go to ``<base>/<dag_id>/<task_id>/<ti.id>/v<n>/`` in object storage. A small pointer to the
    latest folder is kept in task state under ``key``, and is only written after the files are
    uploaded, so a retry never restores a half-written save. Clearing the task removes the pointer,
    so the task starts fresh.

    :param key: Task state key that holds the pointer.
    :param base: Object storage path for the files. Defaults to ``[common.io] checkpoints_path``.
    :param keep: If set, only the newest ``keep`` saves of the current try keep their files.
    :param warm_start: Folder to restore from when the task has no saved checkpoint yet.
    """

    def __init__(
        self,
        key: str,
        *,
        base: str | ObjectStoragePath | None = None,
        keep: int | None = None,
        warm_start: str | ObjectStoragePath | None = None,
    ) -> None:
        if not AIRFLOW_V_3_3_PLUS:
            raise AirflowOptionalProviderFeatureException("Checkpoint requires Airflow 3.3 or later.")
        base = base or conf.get("common.io", "checkpoints_path", fallback="")
        if not base:
            raise ValueError("Pass base or set [common.io] checkpoints_path.")
        if keep is not None and keep < 1:
            raise ValueError("keep must be at least 1.")
        context = get_current_context()
        self.ti = context["ti"]
        self.state = context["task_state_store"]
        self.key = key
        self.keep = keep
        self.warm_start = ObjectStoragePath(warm_start) if warm_start else None
        self.root = ObjectStoragePath(base) / self.ti.dag_id / self.ti.task_id / str(self.ti.id)
        self._version = 0
        self._in_with = False
        self._pending: threading.Thread | None = None
        self._pending_commit: tuple[ObjectStoragePath, M] | None = None
        self._error: BaseException | None = None

    def __enter__(self) -> Checkpoint[M]:
        self._in_with = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._in_with = False
        if exc_type is None:
            self._finish_background_upload()
        else:
            # Still record a finished upload, so a retry can resume from it; the block's own error wins.
            with suppress(Exception):
                self._finish_background_upload()

    @contextmanager
    def restore(self, *, download: bool = True) -> Iterator[Restored[M] | None]:
        """
        Yield the checkpoint to continue from, or ``None`` if there is none.

        That is the task's latest save, or ``warm_start`` when there is no save yet. With ``download``,
        its files are copied into a local folder that exists until the block ends.
        """
        pointer = self.state.get(self.key)
        if pointer is not None:
            uri, metadata, try_number = (
                ObjectStoragePath(pointer["path"]),
                pointer["metadata"],
                pointer["try_number"],
            )
            if not _has_files(uri):
                # A pointer is only written for a folder with files, so they were deleted since.
                raise FileNotFoundError(
                    f"The checkpoint files at {uri} were removed after they were saved, for example "
                    "by a bucket lifecycle rule. Clear the task to start fresh."
                )
        elif self.warm_start is not None:
            uri, metadata, try_number = self.warm_start, {}, None
            if not _has_files(uri):
                raise FileNotFoundError(f"warm_start folder {uri} has no files.")
        else:
            yield None
            return
        if not download:
            yield Restored(uri=uri, path=None, metadata=metadata, try_number=try_number)
            return
        with tempfile.TemporaryDirectory() as tmp:
            uri.fs.get(f"{uri.path.rstrip('/')}/", tmp, recursive=True)
            yield Restored(uri=uri, path=Path(tmp), metadata=metadata, try_number=try_number)

    @contextmanager
    def save(self, metadata: M, *, background: bool = False) -> Iterator[Path]:
        """
        Yield an empty local folder to write the checkpoint into, then upload it and write the pointer.

        With ``background``, training continues while the upload runs. This needs
        ``with Checkpoint(...) as ckpt:``, so leaving the block waits for the last upload.
        """
        if background and not self._in_with:
            raise ValueError('Use "with Checkpoint(...) as ckpt:" to save in the background.')
        self._finish_background_upload()
        tmp = Path(tempfile.mkdtemp())
        try:
            yield tmp
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        if not _has_local_files(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
            raise ValueError("Nothing to save: write at least one file into the folder.")
        dest = self.next_path()
        if background:
            self._pending = threading.Thread(target=self._upload_in_background, args=(tmp, dest, metadata))
            self._pending.start()
        else:
            try:
                _upload(tmp, dest)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            self._write_pointer(dest, metadata)

    def save_folder(self, path: str | Path, metadata: M) -> None:
        """
        Upload a folder that a library already wrote, then write the pointer.

        The folder is left in place. The upload always finishes before this returns, because the library
        may change or delete the folder right after.
        """
        path = Path(path)
        if not _has_local_files(path):
            raise ValueError(f"Nothing to save: {path} has no files.")
        self._finish_background_upload()
        dest = self.next_path()
        _upload(path, dest)
        self._write_pointer(dest, metadata)

    def next_path(self) -> ObjectStoragePath:
        """Return a new, empty folder for the next save, for engines that write to storage directly."""
        self._version += 1
        return self.root / f"v{self._version}"

    def commit(self, path: ObjectStoragePath, metadata: M) -> None:
        """Make ``path`` the checkpoint to restore from. Call it only once every file is written."""
        if not _has_files(path):
            raise ValueError(f"Nothing to commit: {path} has no files.")
        self._write_pointer(path, metadata)

    def _write_pointer(self, path: ObjectStoragePath, metadata: M) -> None:
        self.state.set(
            self.key, {"path": str(path), "metadata": dict(metadata), "try_number": self.ti.try_number}
        )
        if self.keep is not None:
            self._prune()

    def _upload_in_background(self, tmp: Path, dest: ObjectStoragePath, metadata: M) -> None:
        try:
            _upload(tmp, dest)
            # The pointer is written later on the task's own thread, which owns task state access.
            self._pending_commit = (dest, metadata)
        except BaseException as e:
            self._error = e
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _finish_background_upload(self) -> None:
        if self._pending is not None:
            self._pending.join()
            self._pending = None
        if self._error is not None:
            error, self._error = self._error, None
            raise error
        if self._pending_commit is not None:
            path, metadata = self._pending_commit
            self._pending_commit = None
            self._write_pointer(path, metadata)

    def _prune(self) -> None:
        if not self.root.exists():
            return
        versions = sorted(
            (p for p in self.root.iterdir() if p.name.startswith("v") and p.name[1:].isdigit()),
            key=lambda p: int(p.name[1:]),
        )
        for old in versions[: -self.keep]:
            old.rmdir(recursive=True)


def _has_local_files(path: Path) -> bool:
    return any(p.is_file() for p in path.rglob("*"))


def _upload(local: Path, dest: ObjectStoragePath) -> None:
    dest.fs.put(f"{local}/", dest.path, recursive=True)


def _has_files(path: ObjectStoragePath) -> bool:
    try:
        return bool(path.fs.find(path.path))
    except FileNotFoundError:
        return False
