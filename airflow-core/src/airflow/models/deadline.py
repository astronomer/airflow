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
from datetime import datetime
from typing import TYPE_CHECKING, Any

import uuid6
from sqlalchemy import Boolean, ForeignKey, Index, Integer, and_, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, relationship
from sqlalchemy_utils import UUIDType

from airflow._shared.observability.metrics.stats import Stats
from airflow._shared.timezones import timezone
from airflow.models.base import Base
from airflow.models.callback import Callback, CallbackDefinitionProtocol
from airflow.utils.session import provide_session
from airflow.utils.sqlalchemy import UtcDateTime, mapped_column

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from airflow.models.callback import CallbackDefinitionProtocol
    from airflow.models.deadline_alert import DeadlineAlert


logger = logging.getLogger(__name__)

CALLBACK_METRICS_PREFIX = "deadline_alerts"


class classproperty:
    """
    Decorator that converts a method with a single cls argument into a property.

    Mypy won't let us use both @property and @classmethod together, this is a workaround
    to combine the two.

    Usage:

    class Circle:
        def __init__(self, radius):
            self.radius = radius

        @classproperty
        def pi(cls):
            return 3.14159

    print(Circle.pi)  # Outputs: 3.14159
    """

    def __init__(self, method):
        self.method = method

    def __get__(self, instance, cls=None):
        return self.method(cls)


class Deadline(Base):
    """A Deadline is a 'need-by' date which triggers a callback if the provided time has passed."""

    __tablename__ = "deadline"

    id: Mapped[str] = mapped_column(UUIDType(binary=False), primary_key=True, default=uuid6.uuid7)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=timezone.utcnow)
    last_updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=timezone.utcnow, onupdate=timezone.utcnow
    )

    # If the Deadline Alert is for a DAG, store the DAG run ID from the dag_run.
    dagrun_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("dag_run.id", ondelete="CASCADE"), nullable=True
    )
    dagrun = relationship("DagRun", back_populates="deadlines")

    # The time after which the Deadline has passed and the callback should be triggered.
    deadline_time: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    # Whether the deadline has been marked as missed by the scheduler
    missed: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Callback that will run when this deadline is missed
    callback_id: Mapped[str] = mapped_column(
        UUIDType(binary=False), ForeignKey("callback.id", ondelete="CASCADE"), nullable=False
    )
    callback = relationship("Callback", uselist=False, cascade="all, delete-orphan", single_parent=True)

    # The DeadlineAlert that generated this deadline
    deadline_alert_id: Mapped[str | None] = mapped_column(
        UUIDType(binary=False), ForeignKey("deadline_alert.id", ondelete="SET NULL"), nullable=True
    )
    deadline_alert: Mapped[DeadlineAlert | None] = relationship("DeadlineAlert")

    __table_args__ = (Index("deadline_missed_deadline_time_idx", missed, deadline_time, unique=False),)

    def __init__(
        self,
        deadline_time: datetime,
        callback: CallbackDefinitionProtocol,
        dagrun_id: int,
        deadline_alert_id: str | None,
        dag_id: str | None = None,
    ):
        super().__init__()
        self.deadline_time = deadline_time
        self.dagrun_id = dagrun_id
        self.missed = False
        self.callback = Callback.create_from_sdk_def(
            callback_def=callback, prefix=CALLBACK_METRICS_PREFIX, dag_id=dag_id
        )
        self.deadline_alert_id = deadline_alert_id

    def __repr__(self):
        def _determine_resource() -> tuple[str, str]:
            """Determine the type of resource based on which values are present."""
            if self.dagrun_id:
                # The deadline is for a Dag run:
                return "DagRun", f"Dag: {self.dagrun.dag_id} Run: {self.dagrun_id}"

            return "Unknown", ""

        resource_type, resource_details = _determine_resource()

        return (
            f"[{resource_type} Deadline] "
            f"created at {self.created_at}, "
            f"{resource_details}, "
            f"needed by {self.deadline_time} "
            f"or run: {self.callback}"
        )

    @classmethod
    def prune_deadlines(cls, *, session: Session, conditions: dict[Mapped, Any]) -> int:
        """
        Remove deadlines from the table which match the provided conditions and return the number removed.

        NOTE: This should only be used to remove deadlines which are associated with
            successful events (DagRuns, etc). If the deadline was missed, it will be
            handled by the scheduler.

        :param conditions: Dictionary of conditions to evaluate against.
        :param session: Session to use.
        """
        from airflow.models import DagRun  # Avoids circular import

        # Assemble the filter conditions.
        filter_conditions = [column == value for column, value in conditions.items()]
        if not filter_conditions:
            return 0

        try:
            # Get deadlines which match the provided conditions and their associated DagRuns.
            deadline_dagrun_pairs = session.execute(
                select(Deadline, DagRun).join(DagRun).where(and_(*filter_conditions))
            ).all()

        except AttributeError as e:
            logger.exception("Error resolving deadlines: %s", e)
            raise

        if not deadline_dagrun_pairs:
            return 0

        deleted_count = 0
        dagruns_to_refresh = set()

        for deadline, dagrun in deadline_dagrun_pairs:
            if dagrun.end_date <= deadline.deadline_time:
                # If the DagRun finished before the Deadline:
                session.delete(deadline)
                Stats.incr(
                    "deadline_alerts.deadline_not_missed",
                    tags={"dag_id": dagrun.dag_id, "dagrun_id": dagrun.run_id},
                )
                deleted_count += 1
                dagruns_to_refresh.add(dagrun)
        session.flush()

        logger.debug("%d deadline records were deleted matching the conditions %s", deleted_count, conditions)

        # Refresh any affected DAG runs.
        for dagrun in dagruns_to_refresh:
            session.refresh(dagrun)

        return deleted_count

    def handle_miss(self, session: Session):
        """Handle a missed deadline by queueing the callback."""

        def get_simple_context():
            from airflow.api_fastapi.core_api.datamodels.dag_run import DAGRunResponse
            from airflow.models import DagRun

            # TODO: Use the TaskAPI from within Triggerer to fetch full context instead of sending this context
            #  from the scheduler

            # Fetch the DagRun from the database again to avoid errors when self.dagrun's relationship fields
            # are not in the current session.
            dagrun = session.get(DagRun, self.dagrun_id)

            return {
                "dag_run": DAGRunResponse.model_validate(dagrun).model_dump(mode="json"),
                "deadline": {"id": self.id, "deadline_time": self.deadline_time},
            }

        self.callback.data["kwargs"] = self.callback.data["kwargs"] | {"context": get_simple_context()}
        self.missed = True
        self.callback.queue()
        session.add(self)
        Stats.incr(
            "deadline_alerts.deadline_missed",
            tags={"dag_id": self.dagrun.dag_id, "dagrun_id": self.dagrun.run_id},
        )


def __getattr__(name: str):
    import warnings

    if name == "ReferenceModels":
        from airflow.sdk.definitions.deadline import ReferenceModels

        warnings.warn(
            "Importing ReferenceModels from airflow.models.deadline is deprecated. "
            "Use airflow.sdk.definitions.deadline.ReferenceModels instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return ReferenceModels
    if name == "DeadlineReferenceType":
        from airflow.sdk.definitions.deadline import ReferenceModels

        warnings.warn(
            "Importing DeadlineReferenceType from airflow.models.deadline is deprecated. "
            "Use airflow.sdk.definitions.deadline.ReferenceModels.BaseDeadlineReference instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return ReferenceModels.BaseDeadlineReference
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@provide_session
def _fetch_from_db(model_reference: Mapped, session=None, **conditions) -> datetime | None:
    """
    Fetch a datetime value from the database using the provided model reference and filtering conditions.

    For example, to fetch a TaskInstance's start_date:
        _fetch_from_db(
            TaskInstance.start_date, dag_id='example_dag', task_id='example_task', run_id='example_run'
        )

    This generates SQL equivalent to:
        SELECT start_date
        FROM task_instance
        WHERE dag_id = 'example_dag'
            AND task_id = 'example_task'
            AND run_id = 'example_run'

    :param model_reference: SQLAlchemy Column to select (e.g., DagRun.logical_date, TaskInstance.start_date)
    :param conditions: Filtering conditions applied as equality comparisons in the WHERE clause.
                       Multiple conditions are combined with AND.
    :param session: SQLAlchemy session (auto-provided by decorator)
    """
    query = select(model_reference)

    for key, value in conditions.items():
        inspected = inspect(model_reference)
        if inspected is not None:
            query = query.where(getattr(inspected.class_, key) == value)

    compiled_query = query.compile(compile_kwargs={"literal_binds": True})
    pretty_query = "\n    ".join(str(compiled_query).splitlines())
    logger.debug(
        "Executing query:\n    %r\nAs SQL:\n    %s",
        query,
        pretty_query,
    )

    try:
        result = session.scalar(query)
    except SQLAlchemyError:
        logger.exception("Database query failed.")
        raise

    if result is None:
        message = f"No matching record found in the database for query:\n    {pretty_query}"
        logger.error(message)
        raise ValueError(message)

    return result
