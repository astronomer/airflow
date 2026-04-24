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

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from airflow.partition_mappers.window import Window


class PartitionMapper(ABC):
    """
    Base partition mapper class.

    Maps keys from asset events to target dag run partitions.
    """

    is_rollup: bool = False

    @abstractmethod
    def to_downstream(self, key: str) -> str | Iterable[str]:
        """Return the target key that the given source partition key maps to."""

    def decode_downstream(self, downstream_key: str) -> Any:
        """
        Recover the canonical decoded form of *downstream_key*.

        Used by :class:`RollupMapper` to hand the window an opaque "anchor"
        for the downstream period; the window iterates in this decoded space
        and the mapper re-encodes each expected upstream via
        :meth:`encode_upstream`. Default is identity (string in, string out)
        — temporal mappers override to return ``datetime``, future segment
        mappers will return whatever shape suits them.
        """
        return downstream_key

    def encode_upstream(self, decoded: Any) -> str:
        """
        Encode an expected upstream object back into a key string.

        Pair of :meth:`decode_downstream`. Default is identity. Temporal
        mappers override to apply timezone + ``input_format``.
        """
        return decoded

    def serialize(self) -> dict[str, Any]:
        return {}

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> PartitionMapper:
        return cls()


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

    def to_downstream(self, key: str) -> str | Iterable[str]:
        return self.source_mapper.to_downstream(key)

    def to_upstream(self, downstream_key: str) -> frozenset[str]:
        """Return the complete set of upstream partition keys required for *downstream_key*."""
        decoded = self.source_mapper.decode_downstream(downstream_key)
        return frozenset(
            self.source_mapper.encode_upstream(expected_upstream)
            for expected_upstream in self.window.to_upstream(decoded)
        )

    def serialize(self) -> dict[str, Any]:
        from airflow.serialization.encoders import encode_partition_mapper, encode_window

        return {
            "source_mapper": encode_partition_mapper(self.source_mapper),
            "window": encode_window(self.window),
        }

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> PartitionMapper:
        from airflow.serialization.decoders import decode_partition_mapper, decode_window

        return cls(
            source_mapper=decode_partition_mapper(data["source_mapper"]),
            window=decode_window(data["window"]),
        )
