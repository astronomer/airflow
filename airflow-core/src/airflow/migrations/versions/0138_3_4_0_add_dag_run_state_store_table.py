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
Add the ``dag_run_state_store`` table.

Revision ID: 8a1d6c4f0b53
Revises: c9f4b3e7a218
Create Date: 2026-09-26 10:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

from airflow.migrations.db_types import StringID
from airflow.utils.sqlalchemy import UtcDateTime

# revision identifiers, used by Alembic.
revision = "8a1d6c4f0b53"
down_revision = "c9f4b3e7a218"
branch_labels = None
depends_on = None
airflow_version = "3.4.0"


def upgrade():
    """Apply add the ``dag_run_state_store`` table."""
    op.create_table(
        "dag_run_state_store",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("dag_run_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("dag_id", StringID(), nullable=False),
        sa.Column("run_id", StringID(), nullable=False),
        sa.Column("value", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.Column("expires_at", UtcDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dag_run_id"], ["dag_run.id"], name="dag_run_state_store_dag_run_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="dag_run_state_store_pkey"),
        sa.UniqueConstraint("dag_run_id", "key", name="dag_run_state_store_uq"),
    )
    with op.batch_alter_table("dag_run_state_store", schema=None) as batch_op:
        batch_op.create_index("idx_dag_run_state_store_lookup", ["dag_id", "run_id"], unique=False)
        batch_op.create_index("idx_dag_run_state_store_expires_at", ["expires_at"], unique=False)


def downgrade():
    """Unapply add the ``dag_run_state_store`` table."""
    with op.batch_alter_table("dag_run_state_store", schema=None) as batch_op:
        batch_op.drop_index("idx_dag_run_state_store_expires_at")
        batch_op.drop_index("idx_dag_run_state_store_lookup")

    op.drop_table("dag_run_state_store")
