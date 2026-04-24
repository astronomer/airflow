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


class Window:
    """
    Describes a rollup window: which upstream keys make up one downstream key.

    Paired with a ``source_mapper`` :class:`PartitionMapper` inside a
    :class:`RollupMapper`. The source_mapper normalizes upstream keys to the
    downstream granularity; the window enumerates the complete set of
    upstream keys that roll up into one downstream key. Runtime logic
    lives in ``airflow.partition_mappers.window`` on the scheduler side.
    """


class HourWindow(Window):
    """Sixty consecutive minute keys making up one hour."""


class DayWindow(Window):
    """Twenty-four consecutive hourly keys making up one day."""


class WeekWindow(Window):
    """Seven consecutive daily keys making up one week."""


class MonthWindow(Window):
    """All daily keys making up one calendar month."""


class QuarterWindow(Window):
    """Three consecutive monthly keys making up one calendar quarter."""


class YearWindow(Window):
    """Twelve consecutive monthly keys making up one calendar year."""
