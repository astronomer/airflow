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
Execution API routes for agents.

A worker resolves an agent by the name written in the Dag, then reads and writes that
agent's state store. Agents are addressed by name throughout: workers never see the
integer id.
"""

from __future__ import annotations

import json
from typing import Annotated

from cadwyn import VersionedAPIRouter
from fastapi import HTTPException, Query, status
from sqlalchemy import select

from airflow._shared.state import AgentScope
from airflow.api_fastapi.common.db.common import SessionDep
from airflow.api_fastapi.execution_api.datamodels.agent import (
    AgentResponse,
    AgentStateStorePutBody,
    AgentStateStoreResponse,
)
from airflow.api_fastapi.execution_api.security import ExecutionAPIRoute
from airflow.models.agent import AgentModel
from airflow.state import get_state_backend

router = VersionedAPIRouter(
    route_class=ExecutionAPIRoute,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Unauthorized"},
        status.HTTP_404_NOT_FOUND: {"description": "Not found"},
    },
)


def _fetch_agent(name: str, session: SessionDep) -> AgentModel:
    agent = session.scalar(select(AgentModel).where(AgentModel.name == name))
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"reason": "not_found", "message": f"Agent with name={name!r} not found"},
        )
    return agent


@router.get("/{name}")
def get_agent(name: str, session: SessionDep) -> AgentResponse:
    """Resolve an agent by name."""
    agent = _fetch_agent(name, session)
    return AgentResponse(
        name=agent.name,
        conn_id=agent.conn_id,
        model=agent.model,
        context=agent.context,
        memory_enabled=agent.memory_enabled,
        budget_limit=agent.budget_limit,
        budget_period=agent.budget_period,
    )


@router.get("/{name}/value")
def get_agent_state_store(
    name: str,
    key: Annotated[str, Query(min_length=1)],
    session: SessionDep,
) -> AgentStateStoreResponse:
    """Get an agent state store value."""
    agent = _fetch_agent(name, session)
    value = get_state_backend().get(AgentScope(agent_id=agent.id), key, session=session)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"reason": "not_found", "message": f"Agent state store key {key!r} not found"},
        )
    return AgentStateStoreResponse(value=json.loads(value))


@router.put("/{name}/value", status_code=status.HTTP_204_NO_CONTENT)
def set_agent_state_store(
    name: str,
    key: Annotated[str, Query(min_length=1)],
    body: AgentStateStorePutBody,
    session: SessionDep,
) -> None:
    """Set an agent state store value."""
    agent = _fetch_agent(name, session)
    get_state_backend().set(AgentScope(agent_id=agent.id), key, json.dumps(body.value), session=session)


@router.delete("/{name}/value", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_state_store(
    name: str,
    key: Annotated[str, Query(min_length=1)],
    session: SessionDep,
) -> None:
    """Delete a single agent state store key."""
    agent = _fetch_agent(name, session)
    get_state_backend().delete(AgentScope(agent_id=agent.id), key, session=session)
