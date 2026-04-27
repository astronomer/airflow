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

import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from airflow._shared.timezones.timezone import make_aware, parse_timezone
from airflow.partition_mappers.base import PartitionMapper

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

    def decode_downstream(self, downstream_key: str) -> datetime:
        """
        Recover the period-start datetime from a previously formatted downstream key.

        Inverse of ``format``. The default implementation uses ``strptime`` with
        ``output_format``, which works for any format made of standard strptime
        directives. Subclasses with custom format markers (e.g. ``{quarter}``) or
        ambiguous directives (e.g. bare ``%V``) override this.
        """
        return datetime.strptime(downstream_key, self.output_format)

    def encode_upstream(self, dt: datetime) -> str:
        """
        Format *dt* as an upstream partition key string.

        Pair of :meth:`decode_downstream`: takes a (decoded) period-start
        datetime and produces a key string in the upstream's ``input_format``
        with ``timezone`` applied. Used by :class:`RollupMapper` to render each
        upstream member yielded by the window back into the form upstream
        producers actually emit.
        """
        return make_aware(dt, self._timezone).strftime(self.input_format)

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
    _YMD_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

    def __init__(
        self,
        *,
        week_start: int = 0,
        timezone: str | Timezone | FixedTimezone = "UTC",
        input_format: str = "%Y-%m-%dT%H:%M:%S",
        output_format: str | None = None,
    ) -> None:
        if not 0 <= week_start <= 6:
            raise ValueError(f"week_start must be between 0 (Monday) and 6 (Sunday), got {week_start!r}")
        super().__init__(timezone=timezone, input_format=input_format, output_format=output_format)
        self.week_start = week_start  # 0 = Monday (ISO default), 6 = Sunday

    def normalize(self, dt: datetime) -> datetime:
        days_since_start = (dt.weekday() - self.week_start) % 7
        start = dt - timedelta(days=days_since_start)
        return start.replace(hour=0, minute=0, second=0, microsecond=0)

    def decode_downstream(self, downstream_key: str) -> datetime:
        # %V (ISO week) cannot be parsed by strptime without %G+%u, so locate
        # the YYYY-MM-DD slice with a regex. Robust across formats that mix
        # the date with extras like "(W%V)".
        match = self._YMD_RE.search(downstream_key)
        if match is None:
            raise ValueError(
                f"StartOfWeekMapper.decode_downstream could not locate YYYY-MM-DD in {downstream_key!r}; "
                "output_format must include '%Y-%m-%d'."
            )
        return datetime.strptime(match.group(), "%Y-%m-%d")

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
        if not 1 <= month_start_day <= 28:
            raise ValueError(f"month_start_day must be between 1 and 28, got {month_start_day!r}")
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

    def decode_downstream(self, downstream_key: str) -> datetime:
        # The default strptime returns day=1; pin to month_start_day so fiscal
        # months recover the correct period start.
        return super().decode_downstream(downstream_key).replace(day=self.month_start_day)

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


class StartOfQuarterMapper(_BaseTemporalMapper):
    """Map a time-based partition key to quarter."""

    default_output_format = "%Y-Q{quarter}"
    _YEAR_QUARTER_RE = re.compile(r"(\d{4}).*?Q([1-4])")

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

    def decode_downstream(self, downstream_key: str) -> datetime:
        # output_format carries a ``{quarter}`` placeholder, so strptime doesn't
        # apply directly. Locate ``YYYY...Q<digit>`` and rebuild the period start.
        match = self._YEAR_QUARTER_RE.search(downstream_key)
        if match is None:
            raise ValueError(
                f"StartOfQuarterMapper.decode_downstream could not locate YYYY...Q<quarter> in "
                f"{downstream_key!r}; output_format must include the year and 'Q{{quarter}}'."
            )
        year = int(match.group(1))
        quarter = int(match.group(2))
        return datetime(year, (quarter - 1) * 3 + 1, 1)


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
