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

if TYPE_CHECKING:
    from airflow.sdk.definitions.partition_mappers.window import Window


class PartitionMapper:
    """
    Base partition mapper class.

    Maps keys from asset events to target dag run partitions.
    """

    is_rollup: bool = False


class RollupMapper(PartitionMapper):
    """
    Partition mapper that rolls up many upstream keys into one downstream key.

    Compose a ``source_mapper`` (which normalizes each upstream key to the
    downstream granularity) with a ``window`` that declares the full set of
    upstream keys required for a given downstream key. The scheduler holds
    the Dag run until every upstream key in the window has arrived.
    """

    is_rollup: bool = True

    def __init__(self, *, source_mapper: PartitionMapper, window: Window) -> None:
        self.source_mapper = source_mapper
        self.window = window
