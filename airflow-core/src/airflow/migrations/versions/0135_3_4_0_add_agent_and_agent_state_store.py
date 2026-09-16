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
Add agent and agent_state_store tables.

Revision ID: a1c4e8b73f92
Revises: b6a9c2e7d410
Create Date: 2026-09-16 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from airflow.models.base import COLLATION_ARGS, StringID
from airflow.utils.sqlalchemy import UtcDateTime

revision = "a1c4e8b73f92"
down_revision = "b6a9c2e7d410"
branch_labels = None
depends_on = None
airflow_version = "3.4.0"


def upgrade():
    """Add the agent and agent_state_store tables."""
    op.create_table(
        "agent",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", StringID(), nullable=False),
        sa.Column("conn_id", StringID(), nullable=False),
        sa.Column("model", sa.String(250, **COLLATION_ARGS), nullable=False),
        sa.Column("context", sa.Text().with_variant(MEDIUMTEXT, "mysql"), nullable=True),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("budget_limit", sa.Float(), nullable=True),
        sa.Column("budget_period", sa.String(16), nullable=True),
        sa.Column("created_at", UtcDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", UtcDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="agent_pkey"),
        sa.UniqueConstraint("name", name="agent_name_uq"),
    )
    op.create_table(
        "agent_state_store",
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(512, **COLLATION_ARGS), nullable=False),
        sa.Column("value", sa.Text().with_variant(MEDIUMTEXT, "mysql"), nullable=False),
        sa.Column("updated_at", UtcDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("agent_id", "key", name="agent_state_store_pkey"),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent.id"],
            name="agent_state_store_agent_fkey",
            ondelete="CASCADE",
        ),
    )


def downgrade():
    """Drop the agent and agent_state_store tables."""
    op.drop_table("agent_state_store")
    op.drop_table("agent")
