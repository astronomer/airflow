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
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    Integer,
    PrimaryKeyConstraint,
    text,
)

from airflow.models.base import Base, StringID
from airflow.models.taskinstance import TaskInstance

_CURRENT_CONTEXT: list[Context] = []
log = logging.getLogger(__name__)


if TYPE_CHECKING:
    from airflow.serialization.pydantic.taskinstance import TaskInstancePydantic
    from airflow.utils.context import Context


class TaskInstanceHistory(Base):
    """
    TBD.

    :meta private:
    """

    __tablename__ = "task_instance_history"
    task_id = Column(StringID(), primary_key=True, nullable=False)
    dag_id = Column(StringID(), primary_key=True, nullable=False)
    run_id = Column(StringID(), primary_key=True, nullable=False)
    map_index = Column(Integer, primary_key=True, nullable=False, server_default=text("-1"))
    try_number = Column(Integer, primary_key=True, default=0)

    __table_args__ = (
        PrimaryKeyConstraint(
            "dag_id", "task_id", "run_id", "map_index", "try_number", name="task_instance_history_pkey"
        ),
        # ForeignKeyConstraint(
        #    ["dag_id", "run_id"],
        #    ["dag_run.dag_id", "dag_run.run_id"],
        #    name="task_instance_dag_run_fkey",
        #    ondelete="CASCADE",
        # ),
    )

    # dag_model: DagModel = relationship(
    #    "DagModel",
    #    primaryjoin="TaskInstance.dag_id == DagModel.dag_id",
    #    foreign_keys="dag_id",
    #    uselist=False,
    #    innerjoin=True,
    #    viewonly=True,
    # )

    # dag_run = relationship("DagRun", back_populates="task_instances", lazy="joined", innerjoin=True)
    # rendered_task_instance_fields = relationship("RenderedTaskInstanceFields", lazy="noload", uselist=False)
    # execution_date = association_proxy("dag_run", "execution_date")

    def __init__(
        self,
        ti: TaskInstance | TaskInstancePydantic,
        state: str | None = None,
    ):
        super().__init__()
        for k, v in ti.__dict__.items():
            if not k.startswith("_"):
                setattr(self, k, v)

        if state:
            self.state = state

    # def __hash__(self):
    #    return hash((self.task_id, self.dag_id, self.run_id, self.map_index))


for column in TaskInstance.__table__.columns:
    if column.name not in TaskInstanceHistory.__table__.columns:
        setattr(TaskInstanceHistory, column.name, column.copy())
