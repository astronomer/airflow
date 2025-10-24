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

import datetime
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import pendulum

from airflow._shared.timezones import timezone
from airflow.timetables.base import DagRunInfo, DataInterval, Timetable

if TYPE_CHECKING:
    from pendulum import DateTime

    from airflow.sdk.definitions.asset import BaseAsset
    from airflow.timetables.base import TimeRestriction
    from airflow.utils.types import DagRunType


class _TrivialTimetable(Timetable):
    """Some code reuse for "trivial" timetables that has nothing complex."""

    periodic = False
    run_ordering: Sequence[str] = ("logical_date",)

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> Timetable:
        return cls()

    def __eq__(self, other: object) -> bool:
        """
        As long as *other* is of the same type.

        This is only for testing purposes and should not be relied on otherwise.
        """
        if not isinstance(other, type(self)):
            return NotImplemented
        return True

    def serialize(self) -> dict[str, Any]:
        return {}

    def infer_manual_data_interval(self, *, run_after: DateTime) -> DataInterval:
        return DataInterval.exact(run_after)


class NullTimetable(_TrivialTimetable):
    """
    Timetable that never schedules anything.

    This corresponds to ``schedule=None``.
    """

    can_be_scheduled = False
    description: str = "Never, external triggers only"

    @property
    def summary(self) -> str:
        return "None"

    def next_dagrun_info(
        self,
        *,
        last_automated_data_interval: DataInterval | None,
        restriction: TimeRestriction,
    ) -> DagRunInfo | None:
        return None


class OnceTimetable(_TrivialTimetable):
    """
    Timetable that schedules the execution once as soon as possible.

    This corresponds to ``schedule="@once"``.
    """

    description: str = "Once, as soon as possible"

    @property
    def summary(self) -> str:
        return "@once"

    def next_dagrun_info(
        self,
        *,
        last_automated_data_interval: DataInterval | None,
        restriction: TimeRestriction,
    ) -> DagRunInfo | None:
        if last_automated_data_interval is not None:
            return None  # Already run, no more scheduling.
        # If the user does not specify an explicit start_date, the dag is ready.
        run_after = restriction.earliest or timezone.coerce_datetime(timezone.utcnow())
        # "@once" always schedule to the start_date determined by the DAG and
        # tasks, regardless of catchup or not. This has been the case since 1.10
        # and we're inheriting it.
        if restriction.latest is not None and run_after > restriction.latest:
            return None
        return DagRunInfo.exact(run_after)


class ContinuousTimetable(_TrivialTimetable):
    """
    Timetable that schedules continually, while still respecting start_date and end_date.

    This corresponds to ``schedule="@continuous"``.
    """

    description: str = "As frequently as possible, but only one run at a time."

    active_runs_limit = 1  # Continuous DAGRuns should be constrained to one run at a time

    @property
    def summary(self) -> str:
        return "@continuous"

    def next_dagrun_info(
        self,
        *,
        last_automated_data_interval: DataInterval | None,
        restriction: TimeRestriction,
    ) -> DagRunInfo | None:
        if restriction.earliest is None:  # No start date, won't run.
            return None

        current_time = timezone.coerce_datetime(timezone.utcnow())

        if last_automated_data_interval is not None:  # has already run once
            if last_automated_data_interval.end > current_time:  # start date is future
                start = restriction.earliest
                elapsed = last_automated_data_interval.end - last_automated_data_interval.start

                end = start + elapsed.as_timedelta()
            else:
                start = last_automated_data_interval.end
                end = current_time
        else:  # first run
            start = restriction.earliest
            end = max(restriction.earliest, current_time)

        if restriction.latest is not None and end > restriction.latest:
            return None

        return DagRunInfo.interval(start, end)


class AssetTriggeredTimetable(_TrivialTimetable):
    """
    Timetable that never schedules anything.

    This should not be directly used anywhere, but only set if a DAG is triggered by assets.

    :meta private:
    """

    description: str = "Triggered by assets"

    def __init__(self, assets: BaseAsset) -> None:
        super().__init__()
        self.asset_condition = assets

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> Timetable:
        from airflow.serialization.serialized_objects import decode_asset_condition

        return cls(decode_asset_condition(data["asset_condition"]))

    @property
    def summary(self) -> str:
        return "Asset"

    def serialize(self) -> dict[str, Any]:
        from airflow.serialization.serialized_objects import encode_asset_condition

        return {"asset_condition": encode_asset_condition(self.asset_condition)}

    def generate_run_id(
        self,
        *,
        run_type: DagRunType,
        data_interval: DataInterval | None,
        run_after: DateTime,
        **extra,
    ) -> str:
        """
        Generate Run ID based on Run Type, run_after and logical Date.

        :param run_type: type of DagRun
        :param data_interval: the data interval
        :param run_after: the date before which dag run won't start.
        """
        from airflow.models.dagrun import DagRun

        logical_date = data_interval.start if data_interval is not None else run_after

        return DagRun.generate_run_id(run_type=run_type, logical_date=logical_date, run_after=run_after)

    def next_dagrun_info(
        self,
        *,
        last_automated_data_interval: DataInterval | None,
        restriction: TimeRestriction,
    ) -> DagRunInfo | None:
        return None


class PartitionMapper:
    def map(self, key): ...

    def inverse_map(self, key): ...


class IdentityMapper(PartitionMapper):
    def map(self, key):
        return key

    def inverse_map(self, key):
        yield key


class DayToWeekMapper(PartitionMapper):
    def map(self, key):
        dt = datetime.datetime.strptime(key, "%Y-%m-%d")
        dt_p = pendulum.instance(dt)
        return dt_p.start_of("week").to_date_string()

    def inverse_map(self, key):
        dt = pendulum.parse(key)
        for num in range(7):
            yield dt.add(days=num).to_date_string()


class FiveMinuteMapper(PartitionMapper):
    def _bin(self, key) -> datetime:
        dt_p = pendulum.parse(key)
        minutes = dt_p.minute
        minutes = int(minutes / 5) * 5
        dt_p = dt_p.replace(minute=minutes, second=0, microsecond=0, tzinfo=None)
        print(dt_p)
        return dt_p

    def map(self, key):
        dt_p = self._bin(key)
        out = dt_p.strftime("%Y-%m-%d %H:%M")
        return out

    def inverse_map(self, key):
        dt = self._bin(key)
        for num in range(5):
            out = dt.add(minutes=num)
            yield out.strftime("%Y-%m-%d %H:%M")

mm = FiveMinuteMapper()
mm.map('2025-03-04 15:04')
list(mm.map('2025-03-04 15:04'))


class PartitionedAssetTimetable(AssetTriggeredTimetable):
    @property
    def summary(self) -> str:
        return "Partitioned Asset"

    def __init__(self, assets: BaseAsset, partition_mapper: PartitionMapper) -> None:
        super().__init__(assets=assets)
        # todo: AIP-76 we need to constrain so people don't do boolean logic etc
        self.asset_condition = assets
        self.partition_mapper = partition_mapper
        # todo: AIP-76 in order to evaluate whether a run should be created, we need to
        #  know if all the partitions that map to it are there
        #  so essentially we need to either wrap each asset dep with a mapper class, or maybe
        #  this mapper attribute could be a dictionary of asset -> mapper, OR we apply the same
        #  mapper to all asset deps but that doesn't really sound all that great

    def serialize(self) -> dict[str, Any]:
        from airflow.serialization.serialized_objects import encode_asset_condition

        return {
            "asset_condition": encode_asset_condition(self.asset_condition),
            "partition_mapper_cls": self.partition_mapper.__class__.__name__,
        }

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> Timetable:
        from airflow.serialization.serialized_objects import decode_asset_condition

        # todo: AIP-76 need to properly serialize / deserialize
        ser_asset_condition = data["asset_condition"]
        mapper_class_name = data.get("partition_mapper_cls", None)
        if mapper_class_name:
            mapper_class = globals()[mapper_class_name]
        else:
            mapper_class = IdentityMapper
        return cls(
            assets=decode_asset_condition(ser_asset_condition),
            partition_mapper=mapper_class(),
        )
