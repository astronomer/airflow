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
"""The memory backend used when a deployment has not configured one."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from airflow.sdk.memory import BaseMemoryBackend, Memory

if TYPE_CHECKING:
    from airflow.sdk.execution_time.context import ResolvedAgent

LESSON_PREFIX = "- "
MEMORY_KEY = "learned"


def normalize(text: str) -> str:
    """Reduce a lesson to a comparable form, so a reworded duplicate still matches."""
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def split_lessons(blob: str | None) -> list[str]:
    """Return the individual lessons held in a memory blob."""
    if not blob:
        return []
    return [line[len(LESSON_PREFIX) :].strip() for line in blob.splitlines() if line.startswith(LESSON_PREFIX)]


def find_duplicate(lesson: str, existing: list[str]) -> str | None:
    """
    Return an existing lesson that already says this, or None.

    Matches when one wraps the other, not just on equality: a model restates a rule it was
    given with a clause bolted on, and keeping both doubles that rule's weight in every
    later prompt.
    """
    candidate = normalize(lesson)
    if not candidate:
        return None
    for known in existing:
        other = normalize(known)
        if other and (candidate == other or candidate in other or other in candidate):
            return known
    return None


class MetastoreMemoryBackend(BaseMemoryBackend):
    """
    Keeps memory in Airflow's own database, as one markdown list per agent.

    The fallback, not the goal. It cannot rank, so ``recall`` ignores the query and returns
    everything, and it is invisible to anything outside Airflow. Point an agent at a shared
    backend when its lessons are worth having on a laptop too.
    """

    def __init__(self, conn_id: str | None = None, agent: ResolvedAgent | None = None) -> None:
        super().__init__(conn_id)
        if agent is None:
            raise ValueError("MetastoreMemoryBackend needs the agent it is storing memory for.")
        self._agent = agent

    def _read(self) -> list[str]:
        return split_lessons(self._agent.get_state(MEMORY_KEY))

    def remember(self, scope: str, content: str, metadata: dict[str, Any] | None = None) -> Memory:
        content = content.strip()
        known = self._read()
        if duplicate := find_duplicate(content, known):
            return Memory(content=duplicate, metadata={"stored": False, "duplicate_of": duplicate})
        self._agent.set_state(MEMORY_KEY, "\n".join(f"{LESSON_PREFIX}{c}" for c in [*known, content]))
        return Memory(content=content, metadata={"stored": True})

    def recall(self, scope: str, query: str | None = None, limit: int = 20) -> list[Memory]:
        return [Memory(content=c) for c in self._read()[:limit]]

    def forget(self, scope: str, memory_id: str) -> None:
        kept = [c for c in self._read() if normalize(c) != normalize(memory_id)]
        self._agent.set_state(MEMORY_KEY, "\n".join(f"{LESSON_PREFIX}{c}" for c in kept))

    def describe(self, scope: str) -> dict[str, Any]:
        return {"backend": type(self).__name__, "entries": len(self._read())}
