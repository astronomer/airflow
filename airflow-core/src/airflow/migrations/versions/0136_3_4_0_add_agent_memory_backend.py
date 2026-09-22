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
Let an agent name its own memory backend.

Revision ID: c5d2f0a41b76
Revises: a1c4e8b73f92
Create Date: 2026-09-22 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from airflow.models.base import COLLATION_ARGS, StringID

revision = "c5d2f0a41b76"
down_revision = "a1c4e8b73f92"
branch_labels = None
depends_on = None
airflow_version = "3.4.0"


def upgrade():
    """Add the per-agent memory backend columns."""
    with op.batch_alter_table("agent", schema=None) as batch_op:
        batch_op.add_column(sa.Column("memory_backend", sa.String(500, **COLLATION_ARGS), nullable=True))
        batch_op.add_column(sa.Column("memory_conn_id", StringID(), nullable=True))


def downgrade():
    """Drop the per-agent memory backend columns."""
    with op.batch_alter_table("agent", schema=None) as batch_op:
        batch_op.drop_column("memory_conn_id")
        batch_op.drop_column("memory_backend")
