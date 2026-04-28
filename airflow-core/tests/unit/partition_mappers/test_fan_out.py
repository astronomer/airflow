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
    FanOutMapper,
    StartOfDayMapper,
    StartOfHourMapper,
    StartOfMonthMapper,
    StartOfQuarterMapper,
    StartOfWeekMapper,
    StartOfYearMapper,
)
from airflow.partition_mappers.window import (
    DayWindow,
    HourWindow,
    MonthWindow,
    QuarterWindow,
    WeekWindow,
    YearWindow,
)


class TestFanOutMapper:
    def test_week_to_seven_daily_keys(self):
        """A weekly upstream key produces seven consecutive daily keys."""
        mapper = FanOutMapper(upstream_mapper=StartOfWeekMapper(), window=WeekWindow())
        # 2024-01-15 is a Monday, so it's already the week start under the default ISO week.
        result = list(mapper.to_downstream("2024-01-15T00:00:00"))
        assert result == [
            "2024-01-15",
            "2024-01-16",
            "2024-01-17",
            "2024-01-18",
            "2024-01-19",
            "2024-01-20",
            "2024-01-21",
        ]

    def test_normalises_mid_week_upstream_to_week_start(self):
        """An upstream timestamp on Wednesday still yields the seven days from Monday."""
        mapper = FanOutMapper(upstream_mapper=StartOfWeekMapper(), window=WeekWindow())
        result = list(mapper.to_downstream("2024-01-17T13:42:00"))
        assert result[0] == "2024-01-15"
        assert len(result) == 7

    def test_day_to_24_hourly_keys(self):
        """A daily upstream key produces 24 consecutive hourly keys."""
        mapper = FanOutMapper(upstream_mapper=StartOfDayMapper(), window=DayWindow())
        result = list(mapper.to_downstream("2024-01-15T03:30:00"))
        assert len(result) == 24
        assert result[0] == "2024-01-15T00"
        assert result[23] == "2024-01-15T23"

    def test_month_to_daily_keys(self):
        """A monthly upstream key produces one downstream key per day of the month."""
        mapper = FanOutMapper(upstream_mapper=StartOfMonthMapper(), window=MonthWindow())
        result = list(mapper.to_downstream("2024-02-10T00:00:00"))
        # February 2024 has 29 days (leap year).
        assert len(result) == 29
        assert result[0] == "2024-02-01"
        assert result[28] == "2024-02-29"

    def test_quarter_to_three_monthly_keys(self):
        """A quarterly upstream key produces three monthly keys."""
        mapper = FanOutMapper(upstream_mapper=StartOfQuarterMapper(), window=QuarterWindow())
        result = list(mapper.to_downstream("2024-02-10T00:00:00"))
        assert result == ["2024-01", "2024-02", "2024-03"]

    def test_year_to_twelve_monthly_keys(self):
        """A yearly upstream key produces twelve monthly keys."""
        mapper = FanOutMapper(upstream_mapper=StartOfYearMapper(), window=YearWindow())
        result = list(mapper.to_downstream("2024-07-04T00:00:00"))
        assert len(result) == 12
        assert result[0] == "2024-01"
        assert result[11] == "2024-12"

    def test_default_fine_mapper_resolution(self):
        """Each window class resolves to a sensible default fine mapper."""
        cases = [
            (WeekWindow(), StartOfDayMapper),
            (MonthWindow(), StartOfDayMapper),
            (DayWindow(), StartOfHourMapper),
            (QuarterWindow(), StartOfMonthMapper),
            (YearWindow(), StartOfMonthMapper),
        ]
        for window, expected_cls in cases:
            mapper = FanOutMapper(upstream_mapper=StartOfWeekMapper(), window=window)
            assert isinstance(mapper.fine_mapper, expected_cls)

    def test_no_default_for_hour_window_requires_explicit_fine_mapper(self):
        """HourWindow has no default fine_mapper (no minute-level mapper exists)."""
        with pytest.raises(ValueError, match="HourWindow"):
            FanOutMapper(upstream_mapper=StartOfDayMapper(), window=HourWindow())

    def test_explicit_fine_mapper_overrides_default(self):
        """Passing fine_mapper explicitly overrides the lookup."""
        custom_fine = StartOfDayMapper(output_format="%Y/%m/%d")
        mapper = FanOutMapper(
            upstream_mapper=StartOfWeekMapper(),
            window=WeekWindow(),
            fine_mapper=custom_fine,
        )
        result = list(mapper.to_downstream("2024-01-15T00:00:00"))
        assert result[0] == "2024/01/15"

    def test_chained_fanout_upstream_rejected(self):
        """An upstream_mapper that itself returns multiple keys is not supported."""
        # FanOutMapper's upstream_mapper must produce a single coarse key, so
        # nesting one FanOutMapper inside another is rejected with a clear
        # error rather than silently producing wrong output.
        outer = FanOutMapper(
            upstream_mapper=FanOutMapper(
                upstream_mapper=StartOfMonthMapper(),
                window=MonthWindow(),
            ),
            window=DayWindow(),
            fine_mapper=StartOfHourMapper(),
        )
        with pytest.raises(TypeError, match="single key"):
            list(outer.to_downstream("2024-02-10T00:00:00"))

    def test_serialize_roundtrip(self):
        """Serialize + deserialize reconstructs an equivalent mapper."""
        mapper = FanOutMapper(
            upstream_mapper=StartOfWeekMapper(timezone="UTC"),
            window=WeekWindow(),
            fine_mapper=StartOfDayMapper(output_format="%Y/%m/%d"),
        )
        data = mapper.serialize()
        restored = FanOutMapper.deserialize(data)
        assert isinstance(restored, FanOutMapper)
        assert isinstance(restored.upstream_mapper, StartOfWeekMapper)
        assert isinstance(restored.window, WeekWindow)
        assert isinstance(restored.fine_mapper, StartOfDayMapper)
        assert restored.fine_mapper.output_format == "%Y/%m/%d"
        # Behavior round-trips too.
        assert list(restored.to_downstream("2024-01-15T00:00:00")) == list(
            mapper.to_downstream("2024-01-15T00:00:00")
        )
