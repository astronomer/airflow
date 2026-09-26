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

from sqlalchemy import ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from airflow._shared.timezones import timezone
from airflow.models.base import COLLATION_ARGS, Base, StringID
from airflow.utils.sqlalchemy import UtcDateTime


class DagRunStateStoreModel(Base):
    """
    Persists key/value state shared by every task in a single Dag run.

    Scoped to (dag_run_id, key), so all tasks in the run address the same rows. Different
    Dag runs get independent namespaces automatically.
    """

    __tablename__ = "dag_run_state_store"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    dag_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(512, **COLLATION_ARGS), nullable=False)

    dag_id: Mapped[str] = mapped_column(StringID(), nullable=False)
    run_id: Mapped[str] = mapped_column(StringID(), nullable=False)

    value: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT, "mysql"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=timezone.utcnow, nullable=False)
    # Absolute UTC timestamp after which cleanup may delete this row. NULL means never.
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("dag_run_id", "key", name="dag_run_state_store_uq"),
        ForeignKeyConstraint(
            ["dag_run_id"],
            ["dag_run.id"],
            name="dag_run_state_store_dag_run_fkey",
            ondelete="CASCADE",
        ),
        Index("idx_dag_run_state_store_lookup", "dag_id", "run_id"),
        Index("idx_dag_run_state_store_expires_at", "expires_at"),
    )
