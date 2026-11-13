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

"""Task-state values owned by one execution, with explicit file persistence."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import AbstractContextManager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from airflow.sdk.exceptions import LocalRunConfigError


class LocalStateStore(AbstractContextManager):
    def __init__(
        self, *, identity: dict[str, str], run_id: str, path: Path | None = None, resume: bool = False
    ) -> None:
        self.identity = identity
        self.run_id = run_id
        self.path = path
        self.resume = resume
        self.values: dict[str, dict[str, Any]] = {}
        self._lock: int | None = None

    def __enter__(self):
        if self.path is None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = os.open(f"{self.path}.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise LocalRunConfigError(f"Task state file {self.path} is already in use") from None
            if self.path.exists():
                self._load(self.path)
            elif self.resume:
                raise LocalRunConfigError(f"No task state to resume: {self.path}")
            self._save(self.values)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args) -> None:
        if self._lock is not None:
            os.close(self._lock)
            self._lock = None

    def _load(self, path: Path) -> None:
        try:
            saved = json.loads(path.read_text())
            if saved["version"] != 1 or saved["identity"] != self.identity:
                raise ValueError("the format or project, Dag and task identity does not match")
            values = saved["values"]
            if not isinstance(values, dict):
                raise ValueError("values must be an object")
            for value in values.values():
                if not isinstance(value, dict) or set(value) != {"value", "expires_at"}:
                    raise ValueError("invalid task-state value")
                if value["expires_at"] is not None:
                    expiry = datetime.fromisoformat(value["expires_at"])
                    if expiry.tzinfo is None:
                        raise ValueError("expiry must include a timezone")
            if self.resume:
                self.values = values
        except (ValueError, KeyError, TypeError) as error:
            raise LocalRunConfigError(f"Cannot read task state from {self.path}: {error}") from error

    def _save(self, values: dict[str, dict[str, Any]]) -> None:
        if self.path is None:
            return
        payload = {
            "version": 1,
            "identity": self.identity,
            "run_id": self.run_id,
            "values": values,
        }
        fd, name = tempfile.mkstemp(prefix=f".{self.path.name}-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(payload, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(name)

    def get(self, key: str) -> dict[str, Any] | None:
        entry = self.values.get(key)
        if entry and entry["expires_at"] is not None:
            if datetime.fromisoformat(entry["expires_at"]) <= datetime.now(tz=UTC):
                self.delete(key)
                return None
        return entry

    def set(self, key: str, value: Any, expires_at: datetime | None) -> None:
        values = {
            **self.values,
            key: {"value": value, "expires_at": expires_at.isoformat() if expires_at else None},
        }
        self._save(values)
        self.values = values

    def delete(self, key: str) -> None:
        values = {name: entry for name, entry in self.values.items() if name != key}
        self._save(values)
        self.values = values

    def clear(self) -> None:
        self._save({})
        self.values = {}
