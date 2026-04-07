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

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from airflow._shared.timezones.timezone import make_aware, parse_timezone
from airflow.partition_mappers.base import PartitionMapper, RollupMapper

if TYPE_CHECKING:
    from pendulum import FixedTimezone, Timezone


class _BaseTemporalMapper(PartitionMapper, ABC):
    """Base class for Temporal Partition Mappers."""

    default_output_format: str

    def __init__(
        self,
        *,
        timezone: str | Timezone | FixedTimezone = "UTC",
        input_format: str = "%Y-%m-%dT%H:%M:%S",
        output_format: str | None = None,
    ):
        self.input_format = input_format
        self.output_format = output_format or self.default_output_format
        if isinstance(timezone, str):
            timezone = parse_timezone(timezone)
        self._timezone = timezone

    def to_downstream(self, key: str) -> str:
        dt = datetime.strptime(key, self.input_format)
        if dt.tzinfo is None:
            dt = make_aware(dt, self._timezone)
        else:
            dt = dt.astimezone(self._timezone)
        normalized = self.normalize(dt)
        return self.format(normalized)

    @abstractmethod
    def normalize(self, dt: datetime) -> datetime:
        """Return canonical start datetime for the partition."""

    def format(self, dt: datetime) -> str:
        """Format the normalized datetime."""
        return dt.strftime(self.output_format)

    def serialize(self) -> dict[str, Any]:
        from airflow.serialization.encoders import encode_timezone

        return {
            "timezone": encode_timezone(self._timezone),
            "input_format": self.input_format,
            "output_format": self.output_format,
        }

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> PartitionMapper:
        return cls(
            timezone=parse_timezone(data.get("timezone", "UTC")),
            input_format=data["input_format"],
            output_format=data["output_format"],
        )


class StartOfHourMapper(_BaseTemporalMapper):
    """Map a time-based partition key to hour."""

    default_output_format = "%Y-%m-%dT%H"

    def normalize(self, dt: datetime) -> datetime:
        return dt.replace(minute=0, second=0, microsecond=0)


class StartOfDayMapper(_BaseTemporalMapper):
    """Map a time-based partition key to day."""

    default_output_format = "%Y-%m-%d"

    def normalize(self, dt: datetime) -> datetime:
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)


class StartOfWeekMapper(_BaseTemporalMapper):
    """Map a time-based partition key to the start of its week."""

    default_output_format = "%Y-%m-%d (W%V)"

    def __init__(
        self,
        *,
        week_start: int = 0,
        timezone: str | Timezone | FixedTimezone = "UTC",
        input_format: str = "%Y-%m-%dT%H:%M:%S",
        output_format: str | None = None,
    ) -> None:
        super().__init__(timezone=timezone, input_format=input_format, output_format=output_format)
        self.week_start = week_start  # 0 = Monday (ISO default), 6 = Sunday

    def normalize(self, dt: datetime) -> datetime:
        days_since_start = (dt.weekday() - self.week_start) % 7
        start = dt - timedelta(days=days_since_start)
        return start.replace(hour=0, minute=0, second=0, microsecond=0)

    def serialize(self) -> dict[str, Any]:
        return {**super().serialize(), "week_start": self.week_start}

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> PartitionMapper:
        return cls(
            week_start=data.get("week_start", 0),
            timezone=parse_timezone(data.get("timezone", "UTC")),
            input_format=data["input_format"],
            output_format=data["output_format"],
        )


class WeeklyRollupMapper(StartOfWeekMapper, RollupMapper):
    """
    Map a time-based partition key to the start of its week, requiring all 7 daily keys.

    Use this when a partitioned Dag should only run once every daily asset partition
    for a full week has been produced. Configure ``week_start`` to set which day begins
    the week (0 = Monday, 6 = Sunday).
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "%Y-%m-%d" not in self.output_format:
            raise ValueError(
                f"WeeklyRollupMapper requires output_format to contain '%Y-%m-%d' so that "
                f"to_upstream() can recover the week-start date, got: {self.output_format!r}"
            )

    def to_upstream(self, downstream_key: str) -> frozenset[str]:
        # Parse via output_format (not a hardcoded slice) so custom formats work correctly.
        # Arithmetic stays on naive datetimes to keep day-counting unambiguous across
        # DST transitions; each result is made timezone-aware before formatting so that
        # %z in input_format produces the correct offset.
        week_start_naive = datetime.strptime(downstream_key, self.output_format)
        return frozenset(
            make_aware(week_start_naive + timedelta(days=i), self._timezone).strftime(self.input_format)
            for i in range(7)
        )


class StartOfMonthMapper(_BaseTemporalMapper):
    """Map a time-based partition key to the start of its month."""

    default_output_format = "%Y-%m"

    def __init__(
        self,
        *,
        month_start_day: int = 1,
        timezone: str | Timezone | FixedTimezone = "UTC",
        input_format: str = "%Y-%m-%dT%H:%M:%S",
        output_format: str | None = None,
    ) -> None:
        super().__init__(timezone=timezone, input_format=input_format, output_format=output_format)
        self.month_start_day = month_start_day  # 1–28; use >1 for fiscal-month offsets

    def normalize(self, dt: datetime) -> datetime:
        if dt.day < self.month_start_day:
            month = dt.month - 1 or 12
            year = dt.year - (1 if dt.month == 1 else 0)
            start = dt.replace(year=year, month=month, day=self.month_start_day)
        else:
            start = dt.replace(day=self.month_start_day)
        return start.replace(hour=0, minute=0, second=0, microsecond=0)

    def serialize(self) -> dict[str, Any]:
        return {**super().serialize(), "month_start_day": self.month_start_day}

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> PartitionMapper:
        return cls(
            month_start_day=data.get("month_start_day", 1),
            timezone=parse_timezone(data.get("timezone", "UTC")),
            input_format=data["input_format"],
            output_format=data["output_format"],
        )


class MonthlyRollupMapper(StartOfMonthMapper, RollupMapper):
    """
    Map a time-based partition key to the start of its month, requiring all daily keys in that month.

    Use this when a partitioned Dag should only run once every daily asset partition
    for a full calendar month has been produced. Configure ``month_start_day`` for
    fiscal-month offsets (e.g. ``month_start_day=15`` for a mid-month period).
    """

    def to_upstream(self, downstream_key: str) -> frozenset[str]:
        # Use naive datetimes for day-counting to avoid DST ambiguity, then make
        # each result timezone-aware before formatting so %z produces the correct offset.
        period_start_naive = datetime.strptime(downstream_key, self.output_format).replace(
            day=self.month_start_day
        )
        next_month = period_start_naive.month % 12 + 1
        next_year = period_start_naive.year + (1 if period_start_naive.month == 12 else 0)
        next_start_naive = period_start_naive.replace(year=next_year, month=next_month)
        days = (next_start_naive - period_start_naive).days
        return frozenset(
            make_aware(period_start_naive + timedelta(days=i), self._timezone).strftime(self.input_format)
            for i in range(days)
        )


class StartOfQuarterMapper(_BaseTemporalMapper):
    """Map a time-based partition key to quarter."""

    default_output_format = "%Y-Q{quarter}"

    def normalize(self, dt: datetime) -> datetime:
        quarter = (dt.month - 1) // 3
        month = quarter * 3 + 1
        return dt.replace(
            month=month,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    def format(self, dt: datetime) -> str:
        quarter = (dt.month - 1) // 3 + 1
        return dt.strftime(self.output_format).format(quarter=quarter)


class StartOfYearMapper(_BaseTemporalMapper):
    """Map a time-based partition key to year."""

    default_output_format = "%Y"

    def normalize(self, dt: datetime) -> datetime:
        return dt.replace(
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
