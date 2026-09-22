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
"""A ``remember`` tool backed by the agent's memory backend."""

from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING, Any

from pydantic_ai.toolsets.function import FunctionToolset

if TYPE_CHECKING:
    from airflow.sdk.types import Logger


def normalize_lesson(text: str) -> str:
    """Reduce a lesson to a comparable form, so a reworded duplicate still matches."""
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def split_lessons(blob: str | None) -> list[str]:
    """Return the individual lessons held in a markdown bullet list."""
    if not blob:
        return []
    return [line[2:].strip() for line in blob.splitlines() if line.startswith("- ")]


def find_duplicate(lesson: str, existing: list[str]) -> str | None:
    """
    Return an existing lesson that already says this, or None.

    Matches when one wraps the other, not just on equality: a model restates a rule it was
    given with a clause bolted on, and keeping both doubles that rule's weight in every
    later prompt.
    """
    candidate = normalize_lesson(lesson)
    if not candidate:
        return None
    for known in existing:
        other = normalize_lesson(known)
        if other and (candidate == other or candidate in other or other in candidate):
            return known
    return None


def build_memory_toolset(agent: Any, log: Logger, context: str | None = None) -> FunctionToolset:
    """
    Return a toolset with a single ``remember`` tool.

    Lessons already covered by ``context``, the agent's standing instructions, are refused:
    memory that restates its own instructions adds nothing and dilutes the rest. Duplicates
    already in memory are left to the backend, which knows what it holds.
    """
    context_lessons = split_lessons(context)
    # One model turn can emit several tool calls, run concurrently. Without this each reads
    # the same memory and overwrites the others.
    write_lock = threading.Lock()

    def remember(lesson: str) -> str:
        """Store a lesson worth carrying into future runs of this agent."""
        lesson = lesson.strip()
        if not lesson:
            return "Nothing to store."

        if duplicate := find_duplicate(lesson, context_lessons):
            log.info("Agent %r was already told this, not storing: %s", agent.name, lesson)
            return (
                f"Not stored: the house rules already say this ({duplicate!r}). "
                "Only store something the rules do not already cover."
            )

        with write_lock:
            stored = agent.remember(lesson)

        if stored.metadata.get("stored") is False:
            log.info("Agent %r already remembers this, not storing: %s", agent.name, lesson)
            return f"Not stored: you already remember this ({stored.content!r}). Only store something new."

        log.info("Agent %r remembered a lesson: %s", agent.name, lesson)
        # Without the nudge back to prose, a model can spend its whole turn storing lessons
        # and return neither text nor a tool call, which pydantic-ai fails the run over.
        return "Stored. Store any other lessons now, then write your final answer."

    toolset = FunctionToolset()
    # Explicit because pydantic-ai cannot infer it for a closure under postponed annotations,
    # and wrongly assumes the first parameter is a RunContext.
    toolset.add_function(remember, takes_ctx=False)
    return toolset
