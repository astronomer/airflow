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
"""
Where an agent keeps what it has learned.

Separate from the state store on purpose. A state store hands back the value at a key;
``recall`` hands back the entries most relevant to a question, ranked. A key/value store
cannot do the second, and squeezing memory through ``get``/``set`` means fetching
everything and ranking it in Airflow, which is the one job a memory store is good at.

Implementations live outside the SDK: the metastore one in ``execution_time.memory``,
others in providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

__all__ = ["BaseMemoryBackend", "Memory"]


@dataclass(frozen=True)
class Memory:
    """One thing an agent learned."""

    content: str
    id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.content


class BaseMemoryBackend(ABC):
    """
    Read and write an agent's memory.

    Instantiated on the worker with the connection id from the agent, if it has one. The API
    server never builds one: it only ever sees a reference saying where memory lives.
    """

    def __init__(self, conn_id: str | None = None) -> None:
        self.conn_id = conn_id

    @abstractmethod
    def remember(self, scope: str, content: str, metadata: dict[str, Any] | None = None) -> Memory:
        """Store a lesson and return it, with whatever id the backend assigned."""

    @abstractmethod
    def recall(self, scope: str, query: str | None = None, limit: int = 20) -> list[Memory]:
        """
        Return up to ``limit`` entries, most relevant first.

        ``query`` is what the agent is about to work on. Backends that cannot rank ignore it
        and return everything up to ``limit``.
        """

    @abstractmethod
    def forget(self, scope: str, memory_id: str) -> None:
        """Delete one entry. No-op if it is already gone."""

    def describe(self, scope: str) -> dict[str, Any]:
        """
        Summarise where this scope's memory lives, for the reference row in the metastore.

        Deliberately excludes content: the API server reads this, and must not hold what the
        agent learned.
        """
        return {"backend": type(self).__name__, "conn_id": self.conn_id}
