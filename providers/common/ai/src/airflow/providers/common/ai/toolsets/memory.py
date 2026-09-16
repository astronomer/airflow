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
"""A ``remember`` tool backed by the agent state store."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pydantic_ai.toolsets.function import FunctionToolset

if TYPE_CHECKING:
    from airflow.sdk.types import Logger

LESSON_PREFIX = "- "


def normalize_lesson(text: str) -> str:
    """Reduce a lesson to a comparable form: lowercase, punctuation and spacing dropped."""
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def split_lessons(blob: str | None) -> list[str]:
    """Return the individual lessons held in a memory blob."""
    if not blob:
        return []
    return [line[len(LESSON_PREFIX) :].strip() for line in blob.splitlines() if line.startswith(LESSON_PREFIX)]


def find_duplicate(lesson: str, existing: list[str]) -> str | None:
    """
    Return the existing lesson that already says this, or None.

    Matches on the normalized form, and also when one wraps the other. A model asked to
    record what it learned will happily restate a rule it was already given, with an extra
    clause bolted on -- "...--even when refactoring, the rule applies". Those are the same
    lesson, and storing both silently doubles that rule's weight in every later prompt at
    the expense of everything else.
    """
    candidate = normalize_lesson(lesson)
    if not candidate:
        return None
    for known in existing:
        other = normalize_lesson(known)
        if not other:
            continue
        if candidate == other or candidate in other or other in candidate:
            return known
    return None


def build_memory_toolset(agent: Any, key: str, log: Logger, context: str | None = None) -> FunctionToolset:
    """
    Return a toolset with a single ``remember`` tool that appends to the agent's memory.

    Memory is one blob rather than ranked entries: the POC wants to watch it grow and find
    out how fast, not to decide yet which entries earn a place in the prompt.

    ``context`` is the agent's standing context. Lessons already covered by it are refused,
    because memory that restates its own instructions adds nothing and dilutes the rest.
    """
    context_lessons = split_lessons(context)

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

        known = split_lessons(agent.get_state(key))
        if duplicate := find_duplicate(lesson, known):
            log.info("Agent %r already remembers this, not storing: %s", agent.name, lesson)
            return (
                f"Not stored: you already remember this ({duplicate!r}). "
                "Only store something new."
            )

        blob = "\n".join(f"{LESSON_PREFIX}{line}" for line in [*known, lesson])
        agent.set_state(key, blob)
        log.info(
            "Agent %r remembered a lesson (%d lessons, %d bytes)", agent.name, len(known) + 1, len(blob)
        )
        # The nudge matters: without it a model can spend its whole turn storing lessons and
        # then return neither text nor a tool call, which pydantic-ai fails the run over.
        return "Stored. Store any other lessons now, then write your final answer."

    toolset = FunctionToolset()
    # takes_ctx is explicit: pydantic-ai cannot infer it for a closure whose annotations are
    # strings under `from __future__ import annotations`, and guesses that it wants RunContext.
    toolset.add_function(remember, takes_ctx=False)
    return toolset
