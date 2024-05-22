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

import collections.abc
import contextlib
import hashlib
import itertools
import logging
import math
import operator
import os
import signal
import warnings
from collections import defaultdict
from contextlib import nullcontext
from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Collection, Generator, Iterable, Mapping, Tuple
from urllib.parse import quote

import dill
import jinja2
import lazy_object_proxy
import pendulum
from deprecated import deprecated
from jinja2 import TemplateAssertionError, UndefinedError
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    and_,
    delete,
    false,
    func,
    inspect,
    or_,
    text,
    update,
)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import lazyload, reconstructor, relationship
from sqlalchemy.orm.attributes import NO_VALUE, set_committed_value
from sqlalchemy.sql.expression import case, select

from airflow import settings
from airflow.api_internal.internal_api_call import InternalApiConfig, internal_api_call
from airflow.compat.functools import cache
from airflow.configuration import conf
from airflow.datasets import Dataset
from airflow.datasets.manager import dataset_manager
from airflow.exceptions import (
    AirflowException,
    AirflowFailException,
    AirflowRescheduleException,
    AirflowSensorTimeout,
    AirflowSkipException,
    AirflowTaskTerminated,
    AirflowTaskTimeout,
    DagRunNotFound,
    RemovedInAirflow3Warning,
    TaskDeferred,
    UnmappableXComLengthPushed,
    UnmappableXComTypePushed,
    XComForMappingNotPushed,
)
from airflow.listeners.listener import get_listener_manager
from airflow.models.base import Base, StringID, TaskInstanceDependencies, _sentinel
from airflow.models.dagbag import DagBag
from airflow.models.log import Log
from airflow.models.mappedoperator import MappedOperator
from airflow.models.param import process_params
from airflow.models.renderedtifields import get_serialized_template_fields
from airflow.models.taskfail import TaskFail
from airflow.models.taskinstancekey import TaskInstanceKey
from airflow.models.taskmap import TaskMap
from airflow.models.taskreschedule import TaskReschedule
from airflow.models.xcom import LazyXComSelectSequence, XCom
from airflow.plugins_manager import integrate_macros_plugins
from airflow.sentry import Sentry
from airflow.settings import task_instance_mutation_hook
from airflow.stats import Stats
from airflow.templates import SandboxedEnvironment
from airflow.ti_deps.dep_context import DepContext
from airflow.ti_deps.dependencies_deps import REQUEUEABLE_DEPS, RUNNING_DEPS
from airflow.utils import timezone
from airflow.utils.context import (
    ConnectionAccessor,
    Context,
    InletEventsAccessors,
    OutletEventAccessors,
    VariableAccessor,
    context_get_outlet_events,
    context_merge,
)
from airflow.utils.email import send_email
from airflow.utils.helpers import prune_dict, render_template_to_string
from airflow.utils.log.logging_mixin import LoggingMixin
from airflow.utils.net import get_hostname
from airflow.utils.operator_helpers import ExecutionCallableRunner, context_to_airflow_vars
from airflow.utils.platform import getuser
from airflow.utils.retries import run_with_db_retries
from airflow.utils.session import NEW_SESSION, create_session, provide_session
from airflow.utils.sqlalchemy import (
    ExecutorConfigType,
    ExtendedJSON,
    UtcDateTime,
    tuple_in_condition,
    with_row_locks,
)
from airflow.utils.state import DagRunState, JobState, State, TaskInstanceState
from airflow.utils.task_group import MappedTaskGroup
from airflow.utils.task_instance_session import set_current_task_instance_session
from airflow.utils.timeout import timeout
from airflow.utils.xcom import XCOM_RETURN_KEY

TR = TaskReschedule

_CURRENT_CONTEXT: list[Context] = []
log = logging.getLogger(__name__)


if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import PurePath
    from types import TracebackType

    from sqlalchemy.orm.session import Session
    from sqlalchemy.sql.elements import BooleanClauseList
    from sqlalchemy.sql.expression import ColumnOperators

    from airflow.models.abstractoperator import TaskStateChangeCallback
    from airflow.models.baseoperator import BaseOperator
    from airflow.models.dag import DAG, DagModel
    from airflow.models.dagrun import DagRun
    from airflow.models.dataset import DatasetEvent
    from airflow.models.operator import Operator
    from airflow.serialization.pydantic.dag import DagModelPydantic
    from airflow.serialization.pydantic.dataset import DatasetEventPydantic
    from airflow.serialization.pydantic.taskinstance import TaskInstancePydantic
    from airflow.timetables.base import DataInterval
    from airflow.typing_compat import Literal, TypeGuard
    from airflow.utils.task_group import TaskGroup

    # This is a workaround because mypy doesn't work with hybrid_property
    # TODO: remove this hack and move hybrid_property back to main import block
    # See https://github.com/python/mypy/issues/4430
    hybrid_property = property
else:
    from sqlalchemy.ext.hybrid import hybrid_property

from airflow.models.taskinstance import TaskInstance


class TaskInstanceHistory(Base):
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
        ti: TaskInstance,
        state: str | None = None,
    ):
        super().__init__()
        for k, v in ti.__dict__.items():
            self.__dict__[k] = v

        if state:
            self.state = state

    def __hash__(self):
        return hash((self.task_id, self.dag_id, self.run_id, self.map_index))


for column in TaskInstance.__table__.columns:
    if column.name not in TaskInstanceHistory.__table__.columns:
        setattr(TaskInstanceHistory, column.name, column.copy())
