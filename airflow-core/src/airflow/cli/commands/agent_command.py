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
"""Agents sub-commands."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from airflow._shared.state import AgentScope
from airflow._shared.timezones import timezone
from airflow.cli.simple_table import AirflowConsole
from airflow.models.agent import AgentModel, AgentStateStoreModel
from airflow.state import get_state_backend
from airflow.utils import cli as cli_utils
from airflow.utils.providers_configuration_loader import providers_configuration_loaded
from airflow.utils.session import NEW_SESSION, provide_session

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# Kept in step with airflow.providers.common.ai.toolsets.memory by convention: core must not
# import a provider, so the blob format lives in both places.
MEMORY_KEY = "learned"
LESSON_PREFIX = "- "


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _show_agents(agents, output):
    AirflowConsole().print_as(
        data=agents,
        output=output,
        mapper=lambda x: {
            "name": x.name,
            "conn_id": x.conn_id,
            "model": x.model,
            "memory": x.memory_enabled,
            "budget": f"{x.budget_limit}/{x.budget_period}" if x.budget_limit is not None else "",
            "context_bytes": len(x.context or ""),
        },
    )


def _fetch_agent(name: str, session: Session) -> AgentModel:
    agent = session.scalar(select(AgentModel).where(AgentModel.name == name))
    if agent is None:
        raise SystemExit(f"Agent {name} does not exist")
    return agent


@cli_utils.action_cli
@providers_configuration_loaded
@provide_session
def agent_add(args, session: Session = NEW_SESSION):
    """Create an agent."""
    if session.scalar(select(AgentModel).where(AgentModel.name == args.name)) is not None:
        raise SystemExit(f"Agent {args.name} already exists")

    context = Path(args.context_file).read_text() if args.context_file else None
    now = timezone.utcnow()
    session.add(
        AgentModel(
            name=args.name,
            conn_id=args.conn_id,
            model=args.model,
            context=context,
            memory_enabled=args.memory,
            budget_limit=args.budget,
            budget_period=args.period,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()
    print(f"Agent {args.name} created")


@cli_utils.action_cli
@providers_configuration_loaded
@provide_session
def agent_list(args, session: Session = NEW_SESSION):
    """List all agents."""
    _show_agents(session.scalars(select(AgentModel).order_by(AgentModel.name)).all(), args.output)


@cli_utils.action_cli
@providers_configuration_loaded
@provide_session
def agent_show(args, session: Session = NEW_SESSION):
    """Show an agent's definition, what it has learned, and what it has spent."""
    agent = _fetch_agent(args.name, session)
    print(f"name:           {agent.name}")
    print(f"conn_id:        {agent.conn_id}")
    print(f"model:          {agent.model}")
    print(f"memory_enabled: {agent.memory_enabled}")
    print(f"budget:         {agent.budget_limit} per {agent.budget_period}")
    print("\n--- context ---")
    print(agent.context or "(none)")

    rows = session.scalars(
        select(AgentStateStoreModel)
        .where(AgentStateStoreModel.agent_id == agent.id)
        .order_by(AgentStateStoreModel.key)
    ).all()
    print("\n--- state ---")
    if not rows:
        print("(empty)")
    for row in rows:
        print(f"\n[{row.key}] (updated {row.updated_at})")
        print(json.loads(row.value))


@cli_utils.action_cli
@providers_configuration_loaded
@provide_session
def agent_remember(args, session: Session = NEW_SESSION):
    """
    Write a lesson into an agent's memory by hand.

    The lessons that change an answer are facts the agent could not derive -- a project
    convention, a naming rule, where a file has to go. Those come from a person.
    """
    agent = _fetch_agent(args.name, session)
    backend = get_state_backend()
    scope = AgentScope(agent_id=agent.id)

    stored = backend.get(scope, MEMORY_KEY, session=session)
    known = [
        line[len(LESSON_PREFIX) :].strip()
        for line in (json.loads(stored) if stored else "").splitlines()
        if line.startswith(LESSON_PREFIX)
    ]

    lesson = args.lesson.strip()
    if any(_normalize(lesson) == _normalize(k) for k in known):
        raise SystemExit(f"Agent {args.name} already remembers that")

    blob = "\n".join(f"{LESSON_PREFIX}{line}" for line in [*known, lesson])
    backend.set(scope, MEMORY_KEY, json.dumps(blob), session=session)
    session.commit()
    print(f"Agent {args.name} now remembers {len(known) + 1} lesson(s)")


@cli_utils.action_cli
@providers_configuration_loaded
@provide_session
def agent_delete(args, session: Session = NEW_SESSION):
    """Delete an agent and everything it has learned."""
    agent = _fetch_agent(args.name, session)
    session.delete(agent)
    session.commit()
    print(f"Agent {args.name} deleted")


@cli_utils.action_cli
@providers_configuration_loaded
@provide_session
def agent_clear_state(args, session: Session = NEW_SESSION):
    """Wipe what an agent has learned, leaving its definition alone."""
    agent = _fetch_agent(args.name, session)
    get_state_backend().clear(AgentScope(agent_id=agent.id), session=session)
    session.commit()
    print(f"Cleared state for agent {args.name}")
