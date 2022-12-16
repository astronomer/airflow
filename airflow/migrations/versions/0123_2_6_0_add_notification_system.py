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

"""Add notification system

Revision ID: 153c17b023ba
Revises: 290244fb8b83
Create Date: 2022-12-15 10:12:59.387307

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "153c17b023ba"
down_revision = "290244fb8b83"
branch_labels = None
depends_on = None
airflow_version = "2.6.0"


def upgrade():
    """Apply Add notification system"""
    op.create_table(
        "notification",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("states", sa.Text(), nullable=False),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("notification_pkey")),
    )
    op.create_table(
        "email_notification",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email_list", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["id"], ["notification.id"], name=op.f("email_notification_id_fkey")),
        sa.PrimaryKeyConstraint("id", name=op.f("email_notification_pkey")),
    )


def downgrade():
    """Unapply Add notification system"""
    op.drop_table("email_notification")
    op.drop_table("notification")
