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
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKeyConstraint, Integer, PrimaryKeyConstraint, String, Text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from airflow._shared.timezones import timezone
from airflow.models.base import COLLATION_ARGS, Base, StringID
from airflow.utils.sqlalchemy import UtcDateTime


class AgentModel(Base):
    """
    An admin-managed agent: a governed route to a model.

    Holds everything a Dag author must not be able to change from inside a Dag — which
    credentials and model may be used, the standing context every run starts from, and the
    spend limit. The Dag author supplies only the prompt and names the agent.

    Everything here is typed in by an admin. Anything that accumulates from runs (what the
    agent has learned, what it has spent) lives in ``agent_state_store`` instead.
    """

    __tablename__ = "agent"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(StringID(), nullable=False, unique=True)

    conn_id: Mapped[str] = mapped_column(StringID(), nullable=False)
    model: Mapped[str] = mapped_column(String(250, **COLLATION_ARGS), nullable=False)

    # The standing context (a CLAUDE.md-style block), stored inline. The CLI reads it out of a
    # file at creation time; Airflow never looks at that file again.
    context: Mapped[str | None] = mapped_column(
        Text().with_variant(MEDIUMTEXT, "mysql"), nullable=True
    )

    memory_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    budget_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_period: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=timezone.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=timezone.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<Agent {self.name}>"


class AgentStateStoreModel(Base):
    """
    Persists key/value state scoped to an agent identity.

    Not scoped to any Dag run, task or Dag — state written by one Dag is readable by another
    Dag naming the same agent. That is the point: it is how an agent carries what it learned
    from one run into the next.

    Rows survive until explicitly deleted or the agent itself is deleted.
    """

    __tablename__ = "agent_state_store"

    agent_id: Mapped[int] = mapped_column(Integer, nullable=False, primary_key=True)
    key: Mapped[str] = mapped_column(String(512, **COLLATION_ARGS), nullable=False, primary_key=True)

    value: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT, "mysql"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=timezone.utcnow, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("agent_id", "key", name="agent_state_store_pkey"),
        ForeignKeyConstraint(
            ["agent_id"],
            ["agent.id"],
            name="agent_state_store_agent_fkey",
            ondelete="CASCADE",
        ),
    )
