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

import pytest

from airflow.partition_mappers.temporal import (
    StartOfDayMapper,
    StartOfHourMapper,
    StartOfMonthMapper,
    StartOfQuarterMapper,
    StartOfWeekMapper,
    StartOfYearMapper,
    _BaseTemporalMapper,
)


class TestTemporalMappers:
    @pytest.mark.parametrize(
        ("mapper_cls", "expected_downstream_key"),
        [
            (StartOfHourMapper, "2026-02-10T14"),
            (StartOfDayMapper, "2026-02-10"),
            (StartOfWeekMapper, "2026-02-09 (W07)"),
            (StartOfMonthMapper, "2026-02"),
            (StartOfQuarterMapper, "2026-Q1"),
            (StartOfYearMapper, "2026"),
        ],
    )
    def test_to_downstream(
        self,
        mapper_cls: type[_BaseTemporalMapper],
        expected_downstream_key: str,
    ):
        pm = mapper_cls()
        assert pm.to_downstream("2026-02-10T14:30:45") == expected_downstream_key

    @pytest.mark.parametrize(
        ("timezone", "expected_timezone"),
        [
            (None, "UTC"),
            ("America/New_York", "America/New_York"),
        ],
    )
    @pytest.mark.parametrize(
        ("mapper_cls", "expected_outut_format", "extra_kwargs"),
        [
            (StartOfHourMapper, "%Y-%m-%dT%H", {}),
            (StartOfDayMapper, "%Y-%m-%d", {}),
            (StartOfWeekMapper, "%Y-%m-%d (W%V)", {"week_start": 0}),
            (StartOfMonthMapper, "%Y-%m", {"month_start_day": 1}),
            (StartOfQuarterMapper, "%Y-Q{quarter}", {}),
            (StartOfYearMapper, "%Y", {}),
        ],
    )
    def test_serialize(
        self,
        mapper_cls: type[_BaseTemporalMapper],
        expected_outut_format: str,
        extra_kwargs: dict[str, int],
        timezone: str | None,
        expected_timezone: str,
    ):
        pm = mapper_cls() if timezone is None else mapper_cls(timezone=timezone)
        assert (
            pm.serialize()
            == {
                "timezone": expected_timezone,
                "input_format": "%Y-%m-%dT%H:%M:%S",
                "output_format": expected_outut_format,
            }
            | extra_kwargs
        )

    @pytest.mark.parametrize(
        "mapper_cls",
        [
            StartOfHourMapper,
            StartOfDayMapper,
            StartOfWeekMapper,
            StartOfMonthMapper,
            StartOfQuarterMapper,
            StartOfYearMapper,
        ],
    )
    def test_deserialize(self, mapper_cls):
        pm = mapper_cls.deserialize(
            {
                "timezone": "UTC",
                "input_format": "%Y-%m-%dT%H:%M:%S",
                "output_format": "customized-format",
            }
        )
        assert isinstance(pm, mapper_cls)
        assert pm.input_format == "%Y-%m-%dT%H:%M:%S"
        assert pm.output_format == "customized-format"

    def test_to_downstream_timezone_aware(self):
        """Input is interpreted as local time in the given timezone."""
        pm = StartOfDayMapper(timezone="America/New_York")
        # 2026-02-10T23:00:00 in New York local time → start-of-day is 2026-02-10
        assert pm.to_downstream("2026-02-10T23:00:00") == "2026-02-10"
        # 2026-02-11T01:00:00 in New York local time → start-of-day is 2026-02-11
        assert pm.to_downstream("2026-02-11T01:00:00") == "2026-02-11"

    def test_to_downstream_input_timezone_differs_from_mapper_timezone(self):
        """When input_format includes %z and the parsed tz differs from the mapper tz,
        the key is converted to the mapper timezone before normalization."""
        pm = StartOfDayMapper(
            timezone="America/New_York",
            input_format="%Y-%m-%dT%H:%M:%S%z",
        )
        # 2026-02-11T04:00:00+00:00 UTC == 2026-02-10T23:00:00-05:00 New York
        # → start-of-day in New York is 2026-02-10, not 2026-02-11
        assert pm.to_downstream("2026-02-11T04:00:00+0000") == "2026-02-10"
        # 2026-02-11T06:00:00+00:00 UTC == 2026-02-11T01:00:00-05:00 New York
        # → start-of-day in New York is 2026-02-11
        assert pm.to_downstream("2026-02-11T06:00:00+0000") == "2026-02-11"


class TestStartOfWeekMapperValidation:
    @pytest.mark.parametrize("week_start", [-1, 7, 100])
    def test_rejects_out_of_range(self, week_start):
        with pytest.raises(ValueError, match="week_start must be between 0"):
            StartOfWeekMapper(week_start=week_start)

    @pytest.mark.parametrize("week_start", [0, 3, 6])
    def test_accepts_valid_range(self, week_start):
        assert StartOfWeekMapper(week_start=week_start).week_start == week_start


class TestStartOfMonthMapperValidation:
    @pytest.mark.parametrize("month_start_day", [0, 29, 31, -1])
    def test_rejects_out_of_range(self, month_start_day):
        with pytest.raises(ValueError, match="month_start_day must be between 1 and 28"):
            StartOfMonthMapper(month_start_day=month_start_day)

    @pytest.mark.parametrize("month_start_day", [1, 15, 28])
    def test_accepts_valid_range(self, month_start_day):
        assert StartOfMonthMapper(month_start_day=month_start_day).month_start_day == month_start_day
