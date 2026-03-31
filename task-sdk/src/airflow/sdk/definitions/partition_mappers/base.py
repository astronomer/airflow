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


class PartitionMapper:
    """
    Base partition mapper class.

    Maps keys from asset events to target dag run partitions.
    """

    is_rollup: bool = False


class RollupMapper(PartitionMapper):
    """
    Partition mapper that supports rollup (many upstream keys → one downstream key).

    Subclass this when the downstream Dag should wait for a complete set of upstream
    partition keys before triggering. The scheduler calls ``to_upstream`` to discover
    which source keys are required and only creates a Dag run once all of them have
    arrived in ``PartitionedAssetKeyLog``.
    """

    is_rollup: bool = True
