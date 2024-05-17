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

"""task_instance uuid PK.

Revision ID: c95a329fa366
Revises: 677fdbb7fc54
Create Date: 2024-05-17 12:43:00.936515

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy_utils import UUIDType

from airflow.utils.sqlalchemy import UtcDateTime

# revision identifiers, used by Alembic.
revision = "c95a329fa366"
down_revision = "677fdbb7fc54"
branch_labels = None
depends_on = None
airflow_version = "2.10.0"

ti_dependent_tables = {
    "rendered_task_instance_fields": "rtif_ti_fkey",
    "task_fail": "task_fail_ti_fkey",
    "task_map": "task_map_task_instance_fkey",
    "task_reschedule": "task_reschedule_ti_fkey",
    "xcom": "xcom_task_instance_fkey",
    "task_instance_note": "task_instance_note_ti_fkey",
}


def upgrade():
    """Apply task_instance uuid PK."""
    for table, constraint in ti_dependent_tables.items():
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(constraint, type_="foreignkey")

    with op.batch_alter_table("task_instance", schema=None) as batch_op:
        batch_op.add_column(sa.Column("id", UUIDType()))
        batch_op.add_column(sa.Column("dag_run_id", sa.Integer()))
        batch_op.add_column(sa.Column("is_latest_try", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("retry_after", UtcDateTime(timezone=True), nullable=True))
        batch_op.alter_column("try_number", existing_type=sa.INTEGER(), nullable=False)
        batch_op.drop_constraint("task_instance_dag_run_fkey", type_="foreignkey")
        batch_op.drop_constraint("task_instance_pkey", type_="primary")

    op.execute("""
        UPDATE task_instance SET id = gen_random_uuid();
    """)
    op.execute("""
        UPDATE task_instance SET dag_run_id = dag_run.id
        FROM dag_run
        WHERE task_instance.dag_id = dag_run.dag_id AND task_instance.run_id = dag_run.run_id;
    """)

    with op.batch_alter_table("task_instance", schema=None) as batch_op:
        batch_op.alter_column("dag_run_id", existing_type=sa.INTEGER(), nullable=False)
        batch_op.create_unique_constraint(
            "task_instance_logical_key", ["dag_run_id", "task_id", "map_index", "try_number"]
        )
        batch_op.create_primary_key("task_instance_pkey", ["id"])
        batch_op.create_foreign_key(
            "task_instance_dag_run_fkey", "dag_run", ["dag_run_id"], ["id"], ondelete="CASCADE"
        )

    with op.batch_alter_table("rendered_task_instance_fields", schema=None) as batch_op:
        batch_op.add_column(sa.Column("task_instance_id", UUIDType()))

    op.execute("""
        UPDATE rendered_task_instance_fields SET task_instance_id = task_instance.id
        FROM task_instance
        WHERE
            rendered_task_instance_fields.dag_id = task_instance.dag_id
            AND rendered_task_instance_fields.run_id = task_instance.run_id
            AND rendered_task_instance_fields.task_id = task_instance.task_id
            AND rendered_task_instance_fields.map_index = task_instance.map_index
    """)

    with op.batch_alter_table("rendered_task_instance_fields", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "rtif_ti_fkey", "task_instance", ["task_instance_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.drop_column("dag_id")
        batch_op.drop_column("run_id")
        batch_op.drop_column("task_id")
        batch_op.drop_column("map_index")
        batch_op.alter_column("task_instance_id", existing_type=UUIDType(), nullable=False)

    with op.batch_alter_table("task_map", schema=None) as batch_op:
        batch_op.add_column(sa.Column("task_instance_id", UUIDType(), nullable=False))
        batch_op.create_foreign_key(
            "task_map_task_instance_fkey", "task_instance", ["task_instance_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.drop_column("map_index")
        batch_op.drop_column("task_id")
        batch_op.drop_column("dag_id")
        batch_op.drop_column("run_id")

    with op.batch_alter_table("task_reschedule", schema=None) as batch_op:
        batch_op.add_column(sa.Column("task_instance_id", UUIDType(), nullable=True))
        batch_op.drop_index("idx_task_reschedule_dag_run")
        batch_op.drop_index("idx_task_reschedule_dag_task_run")
        batch_op.drop_constraint("task_reschedule_dr_fkey", type_="foreignkey")
        batch_op.create_foreign_key(
            "task_reschedule_ti_fkey", "task_instance", ["task_instance_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.drop_column("task_id")
        batch_op.drop_column("try_number")
        batch_op.drop_column("run_id")
        batch_op.drop_column("map_index")
        batch_op.drop_column("dag_id")

    with op.batch_alter_table("xcom", schema=None) as batch_op:
        batch_op.add_column(sa.Column("task_instance_id", UUIDType()))

    op.execute("""
        UPDATE xcom SET task_instance_id = task_instance.id
        FROM task_instance
        WHERE
            xcom.dag_id = task_instance.dag_id
            AND xcom.run_id = task_instance.run_id
            AND xcom.task_id = task_instance.task_id
            AND xcom.map_index = task_instance.map_index
    """)

    with op.batch_alter_table("xcom", schema=None) as batch_op:
        batch_op.alter_column("task_instance_id", existing_type=UUIDType(), nullable=False)
        batch_op.drop_index("idx_xcom_task_instance")
        batch_op.create_foreign_key(
            "xcom_task_instance_fkey", "task_instance", ["task_instance_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.drop_column("task_id")
        batch_op.drop_column("run_id")
        batch_op.drop_column("map_index")
        batch_op.drop_column("dag_run_id")
        batch_op.drop_column("dag_id")

    # ### end Alembic commands ###


def downgrade():
    """Unapply task_instance uuid PK."""
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("xcom", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dag_id", sa.VARCHAR(length=250), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column("dag_run_id", sa.INTEGER(), autoincrement=False, nullable=False))
        batch_op.add_column(
            sa.Column(
                "map_index",
                sa.INTEGER(),
                server_default=sa.text("'-1'::integer"),
                autoincrement=False,
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("run_id", sa.VARCHAR(length=250), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column("task_id", sa.VARCHAR(length=250), autoincrement=False, nullable=False))
        batch_op.drop_constraint("xcom_task_instance_fkey", type_="foreignkey")
        batch_op.create_foreign_key(
            "xcom_task_instance_fkey",
            "task_instance",
            ["dag_id", "task_id", "run_id", "map_index"],
            ["dag_id", "task_id", "run_id", "map_index"],
            ondelete="CASCADE",
        )
        batch_op.create_index(
            "idx_xcom_task_instance", ["dag_id", "task_id", "run_id", "map_index"], unique=False
        )
        batch_op.drop_column("task_instance_id")

    with op.batch_alter_table("task_reschedule", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dag_id", sa.VARCHAR(length=250), autoincrement=False, nullable=False))
        batch_op.add_column(
            sa.Column(
                "map_index",
                sa.INTEGER(),
                server_default=sa.text("'-1'::integer"),
                autoincrement=False,
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("run_id", sa.VARCHAR(length=250), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column("try_number", sa.INTEGER(), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column("task_id", sa.VARCHAR(length=250), autoincrement=False, nullable=False))
        batch_op.drop_constraint("task_reschedule_ti_fkey", type_="foreignkey")
        batch_op.create_foreign_key(
            "task_reschedule_ti_fkey",
            "task_instance",
            ["dag_id", "task_id", "run_id", "map_index"],
            ["dag_id", "task_id", "run_id", "map_index"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "task_reschedule_dr_fkey",
            "dag_run",
            ["dag_id", "run_id"],
            ["dag_id", "run_id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(
            "idx_task_reschedule_dag_task_run", ["dag_id", "task_id", "run_id", "map_index"], unique=False
        )
        batch_op.create_index("idx_task_reschedule_dag_run", ["dag_id", "run_id"], unique=False)
        batch_op.drop_column("task_instance_id")

    with op.batch_alter_table("task_map", schema=None) as batch_op:
        batch_op.add_column(sa.Column("run_id", sa.VARCHAR(length=250), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column("dag_id", sa.VARCHAR(length=250), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column("task_id", sa.VARCHAR(length=250), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column("map_index", sa.INTEGER(), autoincrement=False, nullable=False))
        batch_op.drop_constraint("task_map_task_instance_fkey", type_="foreignkey")
        batch_op.create_foreign_key(
            "task_map_task_instance_fkey",
            "task_instance",
            ["dag_id", "task_id", "run_id", "map_index"],
            ["dag_id", "task_id", "run_id", "map_index"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        )
        batch_op.drop_column("task_instance_id")

    with op.batch_alter_table("task_instance_note", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "task_instance_note_ti_fkey",
            "task_instance",
            ["dag_id", "task_id", "run_id", "map_index"],
            ["dag_id", "task_id", "run_id", "map_index"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("task_instance", schema=None) as batch_op:
        batch_op.drop_constraint("task_instance_dag_run_fkey", type_="foreignkey")
        batch_op.create_foreign_key(
            "task_instance_dag_run_fkey",
            "dag_run",
            ["dag_id", "run_id"],
            ["dag_id", "run_id"],
            ondelete="CASCADE",
        )
        batch_op.drop_constraint("task_instance_logical_key", type_="unique")
        batch_op.alter_column("try_number", existing_type=sa.INTEGER(), nullable=True)
        batch_op.drop_column("retry_after")
        batch_op.drop_column("is_latest_try")
        batch_op.drop_column("dag_run_id")
        batch_op.drop_column("id")

    with op.batch_alter_table("task_fail", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "task_fail_ti_fkey",
            "task_instance",
            ["dag_id", "task_id", "run_id", "map_index"],
            ["dag_id", "task_id", "run_id", "map_index"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("rendered_task_instance_fields", schema=None) as batch_op:
        batch_op.add_column(sa.Column("run_id", sa.VARCHAR(length=250), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column("dag_id", sa.VARCHAR(length=250), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column("task_id", sa.VARCHAR(length=250), autoincrement=False, nullable=False))
        batch_op.add_column(
            sa.Column(
                "map_index",
                sa.INTEGER(),
                server_default=sa.text("'-1'::integer"),
                autoincrement=False,
                nullable=False,
            )
        )
        batch_op.drop_constraint("rtif_ti_fkey", type_="foreignkey")
        batch_op.create_foreign_key(
            "rtif_ti_fkey",
            "task_instance",
            ["dag_id", "task_id", "run_id", "map_index"],
            ["dag_id", "task_id", "run_id", "map_index"],
            ondelete="CASCADE",
        )
        batch_op.drop_column("task_instance_id")

    # ### end Alembic commands ###
