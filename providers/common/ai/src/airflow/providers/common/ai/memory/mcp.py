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
Keep an agent's memory in an MCP server, so other tools can read it too.

Airflow depends on the protocol, never on a particular server: whatever an operator
chooses to run is their business, the same as their database. Do not add a specific
memory server to this provider's dependencies.

Tool names and the argument each takes are configurable, because MCP standardises the
transport and not what a memory looks like. The defaults suit servers that model memory
as markdown notes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

from airflow.providers.common.ai.hooks.mcp import MCPHook
from airflow.sdk.memory import BaseMemoryBackend, Memory

if TYPE_CHECKING:
    from collections.abc import Coroutine

DEFAULT_TOOLS = {
    "remember": "write_note",
    "recall": "search_notes",
    "forget": "delete_note",
}


class _LoopThread:
    """
    Runs coroutines on a background event loop.

    The memory interface is synchronous but MCP clients are not, and ``remember`` is called
    from inside a tool call that is itself running in a loop, so ``asyncio.run`` would
    raise. One long-lived loop on its own thread sidesteps both.
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True, name="mcp-memory").start()

    def run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        future: Future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()


class MCPMemoryBackend(BaseMemoryBackend):
    """
    An agent's memory, held by an MCP server.

    Each lesson is its own note, rather than one note appended to. That makes ``recall``
    something the server can rank and ``forget`` something it can address, and it avoids
    two workers reading and rewriting the same note at once.

    Connection extra (all optional)::

        {"memory_directory": "agents",     # notes go under <directory>/<agent>
         "memory_project": "team",         # server-side project, if it has them
         "tools": {"recall": "search"}}    # override any of the tool names
    """

    def __init__(self, conn_id: str | None = None) -> None:
        super().__init__(conn_id)
        if not conn_id:
            raise ValueError("MCPMemoryBackend needs a connection naming the MCP server.")
        self._hook = MCPHook(mcp_conn_id=conn_id)
        self._extra = self._hook.get_connection(conn_id).extra_dejson
        self._tools = {**DEFAULT_TOOLS, **self._extra.get("tools", {})}
        self._loop = _LoopThread()

    def _directory(self, scope: str) -> str:
        return f"{self._extra.get('memory_directory', 'agents')}/{scope}"

    def _call(self, tool: str, args: dict[str, Any]) -> Any:
        from fastmcp import Client

        if project := self._extra.get("memory_project"):
            args.setdefault("project", project)

        async def run() -> Any:
            async with Client(self._hook.get_transport()) as client:
                return await client.call_tool(tool, args)

        return self._loop.run(run())

    def remember(self, scope: str, content: str, metadata: dict[str, Any] | None = None) -> Memory:
        # Digest, not hash(): str hashing is salted per process, so the same lesson would
        # get a new title every run and pile up copies instead of overwriting.
        title = hashlib.sha256(content.strip().encode()).hexdigest()[:16]
        self._call(
            self._tools["remember"],
            {
                "title": title,
                "content": content,
                "directory": self._directory(scope),
                "tags": ["airflow-agent", scope],
                "metadata": metadata or {},
            },
        )
        return Memory(content=content, id=title, metadata={"stored": True, **(metadata or {})})

    def recall(self, scope: str, query: str | None = None, limit: int = 20) -> list[Memory]:
        result = self._call(self._tools["recall"], {"query": query or scope})
        return [
            Memory(content=c, id=i)
            for i, c in _extract_results(result, self._directory(scope))[:limit]
        ]

    def forget(self, scope: str, memory_id: str) -> None:
        self._call(self._tools["forget"], {"identifier": memory_id})

    def describe(self, scope: str) -> dict[str, Any]:
        return {"backend": type(self).__name__, "conn_id": self.conn_id, "path": self._directory(scope)}


def _slug(value: str) -> str:
    """Flatten separators so a path compares equal however the server spelled it."""
    return re.sub(r"[^a-z0-9/]+", "-", value.casefold())


def _extract_results(result: Any, directory: str) -> list[tuple[str | None, str]]:
    """
    Pull (id, content) pairs out of whatever the server sent back.

    Deliberately forgiving: MCP fixes the transport, not the response shape, so servers
    differ over whether results arrive as structured content, as JSON in a text block, or
    as prose. Anything unrecognised comes back as a single entry rather than being dropped.
    """
    payload = getattr(result, "structured_content", None) or getattr(result, "data", None)

    if payload is None:
        blocks = getattr(result, "content", None) or []
        texts = [t for t in (getattr(b, "text", None) for b in blocks) if t]
        if not texts:
            return []
        try:
            payload = json.loads(texts[0])
        except (ValueError, TypeError):
            return [(None, "\n".join(texts))]

    rows = payload.get("results", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return [(None, str(rows))]

    found = []
    for row in rows:
        if not isinstance(row, dict):
            found.append((None, str(row)))
            continue
        content = row.get("content") or row.get("text") or row.get("title")
        if not content:
            continue
        path = str(row.get("permalink") or row.get("file_path") or "")
        # Other agents share the server; only this one's notes belong in this prompt.
        # Compared loosely because servers slugify: an agent named oncall_triage is filed
        # under oncall-triage.
        if directory and path and _slug(directory) not in _slug(path):
            continue
        found.append((row.get("permalink") or row.get("identifier"), content))
    return found
