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

from typing import TYPE_CHECKING

from airflow.sdk.definitions.partition_mappers.base import PartitionMapper

if TYPE_CHECKING:
    from airflow.sdk.definitions.partition_mappers.window import Window


class _BaseTemporalMapper(PartitionMapper):
    default_output_format: str

    def __init__(
        self,
        input_format: str = "%Y-%m-%dT%H:%M:%S",
        output_format: str | None = None,
    ) -> None:
        self.input_format = input_format
        self.output_format = output_format or self.default_output_format


class StartOfHourMapper(_BaseTemporalMapper):
    """Map a time-based partition key to hour."""

    default_output_format = "%Y-%m-%dT%H"


class StartOfDayMapper(_BaseTemporalMapper):
    """Map a time-based partition key to day."""

    default_output_format = "%Y-%m-%d"


class StartOfWeekMapper(_BaseTemporalMapper):
    """Map a time-based partition key to the start of its week."""

    default_output_format = "%Y-%m-%d (W%V)"

    def __init__(self, *, week_start: int = 0, **kwargs) -> None:
        if not 0 <= week_start <= 6:
            raise ValueError(f"week_start must be between 0 (Monday) and 6 (Sunday), got {week_start!r}")
        super().__init__(**kwargs)
        self.week_start = week_start


class StartOfMonthMapper(_BaseTemporalMapper):
    """Map a time-based partition key to the start of its month."""

    default_output_format = "%Y-%m"

    def __init__(self, *, month_start_day: int = 1, **kwargs) -> None:
        if not 1 <= month_start_day <= 28:
            raise ValueError(f"month_start_day must be between 1 and 28, got {month_start_day!r}")
        super().__init__(**kwargs)
        self.month_start_day = month_start_day


class StartOfQuarterMapper(_BaseTemporalMapper):
    """Map a time-based partition key to quarter."""

    default_output_format = "%Y-Q{quarter}"


class StartOfYearMapper(_BaseTemporalMapper):
    """Map a time-based partition key to year."""

    default_output_format = "%Y"


class FanOutMapper(PartitionMapper):
    """
    Partition mapper that fans one upstream key out into multiple downstream keys.

    Compose an ``upstream_mapper`` (which parses the coarse-granularity upstream
    key and normalizes it to a period start) with a ``window`` that enumerates
    the fine-granularity members of that period. ``fine_mapper`` formats each
    member into a downstream key string; if omitted, a default fine mapper is
    chosen from the window class (e.g. ``WeekWindow`` → ``StartOfDayMapper``).

    Symmetric to :class:`~airflow.sdk.RollupMapper`: rollup is N→1 (downstream
    waits for all members), fanout is 1→N (one upstream event creates many
    downstream Dag runs).

    .. code-block:: python

        # Weekly upstream → 7 daily downstream Dag runs
        FanOutMapper(upstream_mapper=StartOfWeekMapper(), window=WeekWindow())
    """

    def __init__(
        self,
        *,
        upstream_mapper: PartitionMapper,
        window: Window,
        fine_mapper: PartitionMapper | None = None,
    ) -> None:
        self.upstream_mapper = upstream_mapper
        self.window = window
        self.fine_mapper = fine_mapper or _resolve_default_fine_mapper(window)


_DEFAULT_FINE_MAPPER_BY_WINDOW_NAME: dict[str, type[_BaseTemporalMapper]] = {
    "DayWindow": StartOfHourMapper,
    "WeekWindow": StartOfDayMapper,
    "MonthWindow": StartOfDayMapper,
    "QuarterWindow": StartOfMonthMapper,
    "YearWindow": StartOfMonthMapper,
}


def _resolve_default_fine_mapper(window: Window) -> PartitionMapper:
    """
    Return the conventional fine-grained mapper for *window*.

    Looked up by the window's class **name** rather than identity so that the
    SDK ``Window`` classes (used in Dag-author code) and the core ``Window``
    classes (used after deserialization) both resolve to the same default.
    """
    cls = _DEFAULT_FINE_MAPPER_BY_WINDOW_NAME.get(type(window).__name__)
    if cls is None:
        raise ValueError(
            f"FanOutMapper has no default fine_mapper for window type "
            f"{type(window).__name__}; pass fine_mapper explicitly."
        )
    return cls()
