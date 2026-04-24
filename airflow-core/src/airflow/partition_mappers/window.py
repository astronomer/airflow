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

if TYPE_CHECKING:
    from collections.abc import Iterable


class Window(ABC):
    """
    Describes a rollup window: which decoded upstream items make up one decoded downstream period.

    Paired with a source mapper inside a :class:`RollupMapper`. The window
    operates purely in the source mapper's *decoded* form (``datetime`` for
    temporal mappers, domain-specific types for future segment / runtime
    mappers). It does not touch key strings, timezones, or formats — those
    belong to the source mapper. ``RollupMapper`` orchestrates the three:
    decode the downstream key, expand via the window, encode each upstream.
    """

    @abstractmethod
    def to_upstream(self, decoded_downstream: Any) -> Iterable[Any]:
        """Yield each decoded upstream item composing *decoded_downstream*."""

    def serialize(self) -> dict[str, Any]:
        return {}

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> Window:
        return cls()


class HourWindow(Window):
    """Sixty consecutive minute period-starts making up one hour."""

    def to_upstream(self, period_start: datetime) -> Iterable[datetime]:
        return (period_start + timedelta(minutes=i) for i in range(60))


class DayWindow(Window):
    """
    Twenty-four consecutive hourly period-starts making up one day.

    Arithmetic is done on naive datetime steps so the 24-hour stride is
    unambiguous across DST transitions; the source mapper handles timezone
    awareness when it encodes each upstream member back to a key string.
    """

    def to_upstream(self, period_start: datetime) -> Iterable[datetime]:
        return (period_start + timedelta(hours=i) for i in range(24))


class WeekWindow(Window):
    """Seven consecutive daily period-starts making up one week."""

    def to_upstream(self, period_start: datetime) -> Iterable[datetime]:
        return (period_start + timedelta(days=i) for i in range(7))


class MonthWindow(Window):
    """
    All daily period-starts making up one calendar month.

    The source mapper's ``decode_downstream`` already accounts for fiscal
    ``month_start_day``, so this just iterates from the period start to the
    matching day of the next month.
    """

    def to_upstream(self, period_start: datetime) -> Iterable[datetime]:
        next_month = period_start.month % 12 + 1
        next_year = period_start.year + (1 if period_start.month == 12 else 0)
        next_start = period_start.replace(year=next_year, month=next_month)
        days = (next_start - period_start).days
        return (period_start + timedelta(days=i) for i in range(days))


class QuarterWindow(Window):
    """Three monthly period-starts making up one calendar quarter (e.g. Jan/Feb/Mar for Q1)."""

    def to_upstream(self, period_start: datetime) -> Iterable[datetime]:
        return (period_start.replace(month=period_start.month + i) for i in range(3))


class YearWindow(Window):
    """Twelve consecutive monthly period-starts making up one calendar year."""

    def to_upstream(self, period_start: datetime) -> Iterable[datetime]:
        return (period_start.replace(month=i + 1) for i in range(12))
