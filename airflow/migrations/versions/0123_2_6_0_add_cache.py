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

"""Add cache

Revision ID: 1d4555d1e483
Revises: 290244fb8b83
Create Date: 2023-01-07 05:28:04.483443

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "1d4555d1e483"
down_revision = "290244fb8b83"
branch_labels = None
depends_on = None
airflow_version = "2.6.0"


def upgrade():
    """Apply Add cache"""
    op.create_table(
        "cache",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("dag_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("key", name=op.f("cache_pkey")),
    )


def downgrade():
    """Unapply Add cache"""
    op.drop_table("cache")
