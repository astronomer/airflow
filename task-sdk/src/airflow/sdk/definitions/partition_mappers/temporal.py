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

from airflow.sdk.definitions.partition_mappers.base import PartitionMapper, RollupMapper


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
        super().__init__(**kwargs)
        self.week_start = week_start


class WeeklyRollupMapper(StartOfWeekMapper, RollupMapper):
    """
    Map a time-based partition key to the start of its week, requiring all 7 daily keys.

    Use this when a partitioned Dag should only run once every daily asset partition
    for a full week has been produced.
    """


class StartOfMonthMapper(_BaseTemporalMapper):
    """Map a time-based partition key to the start of its month."""

    default_output_format = "%Y-%m"

    def __init__(self, *, month_start_day: int = 1, **kwargs) -> None:
        super().__init__(**kwargs)
        self.month_start_day = month_start_day


class MonthlyRollupMapper(StartOfMonthMapper, RollupMapper):
    """
    Map a time-based partition key to the start of its month, requiring all daily keys in that month.

    Use this when a partitioned Dag should only run once every daily asset partition
    for a full calendar month has been produced.
    """


class StartOfQuarterMapper(_BaseTemporalMapper):
    """Map a time-based partition key to quarter."""

    default_output_format = "%Y-Q{quarter}"


class StartOfYearMapper(_BaseTemporalMapper):
    """Map a time-based partition key to year."""

    default_output_format = "%Y"
