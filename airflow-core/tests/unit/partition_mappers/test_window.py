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

from datetime import datetime

import pytest

from airflow.partition_mappers.base import RollupMapper
from airflow.partition_mappers.temporal import (
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


class TestHourWindow:
    def test_yields_60_minute_period_starts(self):
        period_start = datetime(2024, 6, 10, 14)
        members = list(HourWindow().to_upstream(period_start))
        assert len(members) == 60
        assert members[0] == datetime(2024, 6, 10, 14, 0)
        assert members[-1] == datetime(2024, 6, 10, 14, 59)


class TestDayWindow:
    def test_yields_24_hourly_period_starts(self):
        period_start = datetime(2024, 6, 10)
        members = list(DayWindow().to_upstream(period_start))
        assert len(members) == 24
        assert members[0] == datetime(2024, 6, 10, 0)
        assert members[-1] == datetime(2024, 6, 10, 23)


class TestWeekWindow:
    def test_yields_seven_daily_period_starts(self):
        # 2024-06-10 is a Monday.
        period_start = datetime(2024, 6, 10)
        members = list(WeekWindow().to_upstream(period_start))
        assert members == [
            datetime(2024, 6, 10),
            datetime(2024, 6, 11),
            datetime(2024, 6, 12),
            datetime(2024, 6, 13),
            datetime(2024, 6, 14),
            datetime(2024, 6, 15),
            datetime(2024, 6, 16),
        ]


class TestMonthWindow:
    def test_yields_all_days_in_february_leap_year(self):
        members = list(MonthWindow().to_upstream(datetime(2024, 2, 1)))
        assert len(members) == 29
        assert members[0] == datetime(2024, 2, 1)
        assert members[-1] == datetime(2024, 2, 29)

    def test_honours_fiscal_month_offset(self):
        # 2024-06-15 → 2024-07-14 covers 30 days when month_start_day=15.
        members = list(MonthWindow().to_upstream(datetime(2024, 6, 15)))
        assert len(members) == 30
        assert members[0] == datetime(2024, 6, 15)
        assert members[-1] == datetime(2024, 7, 14)

    def test_crosses_year_boundary(self):
        members = list(MonthWindow().to_upstream(datetime(2024, 12, 1)))
        assert len(members) == 31
        assert members[-1] == datetime(2024, 12, 31)


class TestQuarterWindow:
    def test_yields_three_monthly_period_starts(self):
        # Q2 starts at 2024-04-01.
        members = list(QuarterWindow().to_upstream(datetime(2024, 4, 1)))
        assert members == [datetime(2024, 4, 1), datetime(2024, 5, 1), datetime(2024, 6, 1)]


class TestYearWindow:
    def test_yields_twelve_monthly_period_starts(self):
        members = list(YearWindow().to_upstream(datetime(2024, 1, 1)))
        assert members == [datetime(2024, m, 1) for m in range(1, 13)]


class TestRollupMapperComposition:
    def test_to_downstream_delegates_to_source_mapper(self):
        mapper = RollupMapper(
            source_mapper=StartOfWeekMapper(week_start=0),
            window=WeekWindow(),
        )
        # Wednesday 2024-06-12 belongs to the week starting Monday 2024-06-10.
        assert mapper.to_downstream("2024-06-12T14:30:00") == "2024-06-10 (W24)"

    def test_is_rollup_flag(self):
        mapper = RollupMapper(source_mapper=StartOfWeekMapper(), window=WeekWindow())
        assert mapper.is_rollup is True

    def test_hour_rollup_to_upstream_keys(self):
        mapper = RollupMapper(
            source_mapper=StartOfHourMapper(input_format="%Y-%m-%dT%H:%M", output_format="%Y-%m-%dT%H"),
            window=HourWindow(),
        )
        upstream = mapper.to_upstream("2024-06-10T14")
        assert upstream == frozenset(f"2024-06-10T14:{m:02d}" for m in range(60))

    def test_day_rollup_to_upstream_keys(self):
        mapper = RollupMapper(
            source_mapper=StartOfDayMapper(input_format="%Y-%m-%dT%H", output_format="%Y-%m-%d"),
            window=DayWindow(),
        )
        upstream = mapper.to_upstream("2024-06-10")
        assert upstream == frozenset(f"2024-06-10T{h:02d}" for h in range(24))

    def test_day_rollup_honours_timezone_in_encode(self):
        mapper = RollupMapper(
            source_mapper=StartOfDayMapper(
                input_format="%Y-%m-%dT%H%z",
                output_format="%Y-%m-%d",
                timezone="Asia/Taipei",
            ),
            window=DayWindow(),
        )
        upstream = mapper.to_upstream("2024-06-10")
        assert "2024-06-10T00+0800" in upstream
        assert "2024-06-10T23+0800" in upstream

    def test_week_rollup_with_default_format(self):
        mapper = RollupMapper(
            source_mapper=StartOfWeekMapper(input_format="%Y-%m-%d", output_format="%Y-%m-%d", week_start=0),
            window=WeekWindow(),
        )
        upstream = mapper.to_upstream("2024-06-10")
        assert upstream == frozenset(
            {
                "2024-06-10",
                "2024-06-11",
                "2024-06-12",
                "2024-06-13",
                "2024-06-14",
                "2024-06-15",
                "2024-06-16",
            }
        )

    def test_week_rollup_accepts_custom_output_format(self):
        # decode_downstream lives on the mapper, so any format embedding the date works.
        mapper = RollupMapper(
            source_mapper=StartOfWeekMapper(
                input_format="%Y-%m-%d",
                output_format="Week-of-%Y-%m-%d",
                week_start=0,
            ),
            window=WeekWindow(),
        )
        upstream = mapper.to_upstream("Week-of-2024-06-10")
        assert len(upstream) == 7
        assert "2024-06-10" in upstream

    def test_week_rollup_raises_when_downstream_key_has_no_date(self):
        mapper = RollupMapper(
            source_mapper=StartOfWeekMapper(input_format="%Y-%m-%d"),
            window=WeekWindow(),
        )
        with pytest.raises(ValueError, match="could not locate YYYY-MM-DD"):
            mapper.to_upstream("week-24")

    def test_month_rollup_fiscal_offset(self):
        mapper = RollupMapper(
            source_mapper=StartOfMonthMapper(
                input_format="%Y-%m-%d", output_format="%Y-%m", month_start_day=15
            ),
            window=MonthWindow(),
        )
        upstream = mapper.to_upstream("2024-06")
        assert "2024-06-15" in upstream
        assert "2024-07-14" in upstream

    def test_quarter_rollup_to_upstream_keys(self):
        mapper = RollupMapper(
            source_mapper=StartOfQuarterMapper(input_format="%Y-%m"),
            window=QuarterWindow(),
        )
        assert mapper.to_upstream("2024-Q2") == frozenset({"2024-04", "2024-05", "2024-06"})

    def test_quarter_rollup_raises_when_marker_missing(self):
        mapper = RollupMapper(
            source_mapper=StartOfQuarterMapper(input_format="%Y-%m"),
            window=QuarterWindow(),
        )
        with pytest.raises(ValueError, match="could not locate YYYY...Q<quarter>"):
            mapper.to_upstream("2024-06")

    def test_year_rollup_to_upstream_keys(self):
        mapper = RollupMapper(
            source_mapper=StartOfYearMapper(input_format="%Y-%m"),
            window=YearWindow(),
        )
        assert mapper.to_upstream("2024") == frozenset(f"2024-{m:02d}" for m in range(1, 13))

    def test_serialize_round_trip(self):
        from airflow.serialization.decoders import decode_partition_mapper
        from airflow.serialization.encoders import encode_partition_mapper

        mapper = RollupMapper(
            source_mapper=StartOfWeekMapper(week_start=0, input_format="%Y-%m-%d", output_format="%Y-%m-%d"),
            window=WeekWindow(),
        )
        restored = decode_partition_mapper(encode_partition_mapper(mapper))
        assert isinstance(restored, RollupMapper)
        assert isinstance(restored.source_mapper, StartOfWeekMapper)
        assert restored.source_mapper.week_start == 0
        assert isinstance(restored.window, WeekWindow)
        assert restored.to_upstream("2024-06-10") == mapper.to_upstream("2024-06-10")

    @pytest.mark.parametrize(
        ("source_factory", "window", "downstream_key"),
        [
            pytest.param(
                lambda: StartOfHourMapper(input_format="%Y-%m-%dT%H:%M", output_format="%Y-%m-%dT%H"),
                HourWindow(),
                "2024-06-10T14",
                id="hour",
            ),
            pytest.param(
                lambda: StartOfDayMapper(input_format="%Y-%m-%dT%H", output_format="%Y-%m-%d"),
                DayWindow(),
                "2024-06-10",
                id="day",
            ),
            pytest.param(
                lambda: StartOfQuarterMapper(input_format="%Y-%m"),
                QuarterWindow(),
                "2024-Q2",
                id="quarter",
            ),
            pytest.param(
                lambda: StartOfYearMapper(input_format="%Y-%m"),
                YearWindow(),
                "2024",
                id="year",
            ),
        ],
    )
    def test_window_serialize_round_trip(self, source_factory, window, downstream_key):
        from airflow.serialization.decoders import decode_partition_mapper
        from airflow.serialization.encoders import encode_partition_mapper

        mapper = RollupMapper(source_mapper=source_factory(), window=window)
        restored = decode_partition_mapper(encode_partition_mapper(mapper))
        assert isinstance(restored, RollupMapper)
        assert isinstance(restored.window, type(window))
        assert restored.to_upstream(downstream_key) == mapper.to_upstream(downstream_key)
