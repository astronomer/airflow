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
Worker-side datamodels for the agents Execution API routes.

Hand written rather than generated: the POC adds the routes without regenerating
``_generated.py``. These mirror
``airflow.api_fastapi.execution_api.datamodels.agent``.
"""

from __future__ import annotations

from pydantic import BaseModel, JsonValue


class AgentResponse(BaseModel):
    """An agent definition, as a worker sees it."""

    name: str
    conn_id: str
    model: str
    context: str | None = None
    memory_enabled: bool = False
    memory_backend: str | None = None
    memory_conn_id: str | None = None
    budget_limit: float | None = None
    budget_period: str | None = None


class AgentStateStoreResponse(BaseModel):
    """Agent state store value returned to a worker."""

    value: JsonValue


class AgentStateStorePutBody(BaseModel):
    """Request body for setting an agent state store value."""

    value: JsonValue
