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

"""Add TaskRunCache table

Revision ID: df22e6a7f1cb
Revises: 290244fb8b83
Create Date: 2023-01-09 10:33:59.533624

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from airflow.migrations.db_types import TIMESTAMP

# revision identifiers, used by Alembic.
revision = "df22e6a7f1cb"
down_revision = "290244fb8b83"
branch_labels = None
depends_on = None
airflow_version = "2.6.0"


def upgrade():
    """Apply Add TaskRunCache table"""
    op.create_table(
        "task_run_cache",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("expiration_date", TIMESTAMP()),
        sa.Column("dag_id", sa.String()),
        sa.Column("task_id", sa.String()),
        sa.Column("run_id", sa.String()),
        sa.PrimaryKeyConstraint("key", name=op.f("task_run_cache_pkey")),
    )


def downgrade():
    """Unapply Add TaskRunCache table"""
    op.drop_table("task_run_cache")
