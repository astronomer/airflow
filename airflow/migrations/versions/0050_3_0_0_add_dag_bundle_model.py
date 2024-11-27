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
Add DAG Bundle model.

Revision ID: ab4f6e0be65e
Revises: eed27faa34e3
Create Date: 2024-11-27 04:56:10.658565

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy_utils import UUIDType

# revision identifiers, used by Alembic.
revision = "ab4f6e0be65e"
down_revision = "eed27faa34e3"
branch_labels = None
depends_on = None
airflow_version = "3.0.0"


def upgrade():
    """Apply Add DAG Bundle model."""
    with op.batch_alter_table("dag", schema=None) as batch_op:
        batch_op.add_column(sa.Column("bundle_id", UUIDType(binary=False), nullable=False))
        batch_op.add_column(sa.Column("latest_bundle_version", sa.String(length=200), nullable=True))
        batch_op.create_foreign_key(batch_op.f("dag_bundle_id_fkey"), "dag_bundle", ["bundle_id"], ["id"])
        batch_op.drop_column("processor_subdir")

    with op.batch_alter_table("import_error", schema=None) as batch_op:
        batch_op.add_column(sa.Column("bundle_id", UUIDType(binary=False), nullable=False))
        batch_op.create_foreign_key(
            batch_op.f("import_error_bundle_id_fkey"), "dag_bundle", ["bundle_id"], ["id"]
        )


def downgrade():
    """Unapply Add DAG Bundle model."""
    with op.batch_alter_table("import_error", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("import_error_bundle_id_fkey"), type_="foreignkey")
        batch_op.drop_column("bundle_id")

    with op.batch_alter_table("dag", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("processor_subdir", sa.VARCHAR(length=2000), autoincrement=False, nullable=True)
        )
        batch_op.drop_constraint(batch_op.f("dag_bundle_id_fkey"), type_="foreignkey")
        batch_op.drop_column("latest_bundle_version")
        batch_op.drop_column("bundle_id")
