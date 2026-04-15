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
"""
Example Dags demonstrating runtime partition key assignment.

These Dags showcase :class:`~airflow.sdk.PartitionAtRuntime` and the new
``partition_keys`` API on outlet events, where partition keys are discovered
and emitted at task execution time rather than being derived from a schedule.

Three patterns are shown:

1. **Single runtime key** — a task resolves which partition to process and sets
   exactly one key, which is also recorded on the Dag run.

2. **Fan-out** — a task discovers a dynamic set of partitions at runtime and
   emits one asset event per partition, triggering a separate downstream Dag run
   for each.

3. **Fan-out with per-partition metadata** — same as fan-out but each
   :class:`~airflow.sdk.PartitionKey` also carries extra metadata that is
   merged into the corresponding asset event.
"""

from __future__ import annotations

from airflow.sdk import (
    DAG,
    AllowedKeyMapper,
    Asset,
    PartitionAtRuntime,
    PartitionedAssetTimetable,
    PartitionKey,
    asset,
    task,
)

# ---------------------------------------------------------------------------
# Pattern 1: single runtime partition key
# ---------------------------------------------------------------------------

single_key_asset = Asset(
    uri="file://incoming/daily-report.csv",
    name="daily_report",
)


with DAG(
    dag_id="produce_daily_report",
    schedule=PartitionAtRuntime(),
    tags=["runtime-partition", "single-key"],
):
    """
    Produce a daily report whose partition date is resolved at runtime.

    ``schedule=PartitionAtRuntime()`` signals that this Dag is externally
    triggered and that a task will set the partition key during execution.
    Setting exactly one key also records it on the Dag run, so downstream
    :class:`~airflow.sdk.PartitionedAssetTimetable` Dags receive the correct
    partition context.
    """

    @task(outlets=[single_key_asset])
    def generate_report(*, outlet_events):
        """Resolve today's report partition and emit a single asset event."""
        # In practice, compute the partition from business logic or
        # an upstream API response.
        report_date = "2024-06-15"
        outlet_events[single_key_asset].partition_keys = [report_date]

    generate_report()


@asset(
    uri="file://analytics/daily-report-summary.csv",
    name="daily_report_summary",
    schedule=PartitionedAssetTimetable(assets=single_key_asset),
    tags=["runtime-partition", "single-key"],
)
def summarise_daily_report(self):
    """
    Summarise a daily report partition.

    Triggered by ``daily_report`` with the partition key set at runtime by
    ``produce_daily_report``.
    """
    pass


# ---------------------------------------------------------------------------
# Pattern 2: fan-out — one event per discovered partition
# ---------------------------------------------------------------------------

region_snapshots = Asset(
    uri="file://incoming/snapshots/regions.csv",
    name="region_snapshots",
)


with DAG(
    dag_id="discover_and_snapshot_regions",
    schedule=PartitionAtRuntime(),
    tags=["runtime-partition", "fan-out"],
):
    """
    Discover active regions at runtime and snapshot each one.

    The task queries an external source to find which regions are active,
    then sets ``partition_keys`` to the full list.  The scheduler creates one
    downstream Dag run per key via the fan-out mechanism.
    """

    @task(outlets=[region_snapshots])
    def snapshot_regions(*, outlet_events):
        """Emit one asset event per discovered region."""
        # Regions could come from an API call, a database query, etc.
        active_regions = ["us-east", "eu-west", "ap-south"]
        outlet_events[region_snapshots].partition_keys = active_regions

    snapshot_regions()


@asset(
    uri="file://analytics/region-aggregation.csv",
    name="region_aggregation",
    schedule=PartitionedAssetTimetable(
        assets=region_snapshots,
        default_partition_mapper=AllowedKeyMapper(["us-east", "eu-west", "ap-south"]),
    ),
    tags=["runtime-partition", "fan-out"],
)
def aggregate_region(self):
    """
    Aggregate data for a single region partition.

    One run of this asset is triggered for each region key emitted by
    ``discover_and_snapshot_regions``.
    """
    pass


# ---------------------------------------------------------------------------
# Pattern 3: fan-out with per-partition metadata via PartitionKey
# ---------------------------------------------------------------------------

raw_feed = Asset(
    uri="file://incoming/feeds/raw.csv",
    name="raw_feed",
)


with DAG(
    dag_id="ingest_feeds_with_metadata",
    schedule=PartitionAtRuntime(),
    tags=["runtime-partition", "fan-out", "partition-key-extra"],
):
    """
    Ingest data feeds discovered at runtime, attaching source metadata to each.

    :class:`~airflow.sdk.PartitionKey` objects let you carry per-partition
    ``extra`` data alongside the key.  That metadata is merged into the asset
    event and made available to downstream tasks via ``inlet_events``.
    """

    @task(outlets=[raw_feed])
    def ingest_feeds(*, outlet_events):
        """Discover feeds and emit one partitioned event per feed with source metadata."""
        feeds = [
            ("feed_a", "s3://bucket/feed_a/latest.csv"),
            ("feed_b", "s3://bucket/feed_b/latest.csv"),
            ("feed_c", "s3://bucket/feed_c/latest.csv"),
        ]
        outlet_events[raw_feed].partition_keys = [
            PartitionKey(key=feed_id, extra={"source_uri": uri}) for feed_id, uri in feeds
        ]

    ingest_feeds()


@asset(
    uri="file://analytics/feeds/processed.csv",
    name="processed_feed",
    schedule=PartitionedAssetTimetable(assets=raw_feed),
    tags=["runtime-partition", "fan-out", "partition-key-extra"],
)
def process_feed(self):
    """
    Process a single feed partition.

    One run of this asset is triggered per feed key.  The ``source_uri``
    attached via :class:`~airflow.sdk.PartitionKey` is available on the
    triggering asset event in ``inlet_events``.
    """
    pass
