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
"""Base deserializer for primitive types and basic objects."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from dateutil import relativedelta
from pendulum.tz.timezone import FixedTimezone, Timezone

from airflow._shared.timezones.timezone import from_timestamp, parse_timezone
from airflow.serialization.enums import DagAttributeTypes as DAT, Encoding

if TYPE_CHECKING:
    from airflow.sdk.definitions.edges import EdgeInfoType


def decode_timezone(var: str | int) -> Timezone | FixedTimezone:
    """Decode a previously serialized Pendulum Timezone."""
    return parse_timezone(var)


def decode_relativedelta(var: dict[str, Any]) -> relativedelta.relativedelta:
    """Decode a relativedelta object."""
    if "weekday" in var:
        var["weekday"] = relativedelta.weekday(*var["weekday"])
    return relativedelta.relativedelta(**var)


class BaseDeserializer:
    """Handles deserialization of primitive types and basic objects."""

    # JSON primitive types.
    _primitive_types = (int, bool, float, str)

    def deserialize(self, encoded_var: Any) -> Any:
        """
        Route to appropriate deserialization method based on type.
        
        :param encoded_var: The encoded data to deserialize
        :return: Deserialized object
        """
        if self._is_primitive(encoded_var):
            return self.deserialize_primitive(encoded_var)
        elif isinstance(encoded_var, list):
            return self.deserialize_list(encoded_var)
        
        if not isinstance(encoded_var, dict):
            raise ValueError(f"The encoded_var should be dict and is {type(encoded_var)}")
        
        # Check if it's an encoded type
        if Encoding.TYPE not in encoded_var:
            # Plain dict
            return self.deserialize_plain_dict(encoded_var)
            
        var = encoded_var[Encoding.VAR]
        type_ = encoded_var[Encoding.TYPE]
        
        # Route based on type
        if type_ == DAT.DICT:
            return self.deserialize_dict(var)
        elif type_ == DAT.SET:
            return self.deserialize_set(var)
        elif type_ == DAT.TUPLE:
            return self.deserialize_tuple(var)
        elif type_ == DAT.DATETIME:
            return self.deserialize_datetime(var)
        elif type_ == DAT.TIMEDELTA:
            return self.deserialize_timedelta(var)
        elif type_ == DAT.TIMEZONE:
            return self.deserialize_timezone(var)
        elif type_ == DAT.RELATIVEDELTA:
            return self.deserialize_relativedelta(var)
        else:
            # Unknown type - let calling code handle it
            raise ValueError(f"BaseDeserializer cannot handle type {type_}")

    def _is_primitive(self, var: Any) -> bool:
        """Check if variable is a primitive type."""
        return var is None or isinstance(var, self._primitive_types)

    def deserialize_primitive(self, var: Any) -> Any:
        """Deserialize primitive types."""
        return var

    def deserialize_list(self, var: list[Any]) -> list[Any]:
        """Deserialize a list."""
        # Avoid circular imports
        from airflow.serialization.serialized_objects import BaseSerialization
        return [BaseSerialization.deserialize(v) for v in var]

    def deserialize_plain_dict(self, var: dict[str, Any]) -> dict[str, Any]:
        """Deserialize a plain dict (not encoded)."""
        # Avoid circular imports
        from airflow.serialization.serialized_objects import BaseSerialization
        return {k: BaseSerialization.deserialize(v) for k, v in var.items()}

    def deserialize_dict(self, var: dict[str, Any]) -> dict[str, Any]:
        """Deserialize an encoded dict."""
        # Avoid circular imports
        from airflow.serialization.serialized_objects import BaseSerialization
        return {k: BaseSerialization.deserialize(v) for k, v in var.items()}

    def deserialize_set(self, var: list[Any]) -> set[Any]:
        """Deserialize a set."""
        # Avoid circular imports
        from airflow.serialization.serialized_objects import BaseSerialization
        return {BaseSerialization.deserialize(v) for v in var}

    def deserialize_tuple(self, var: list[Any]) -> tuple[Any, ...]:
        """Deserialize a tuple."""
        # Avoid circular imports
        from airflow.serialization.serialized_objects import BaseSerialization
        return tuple(BaseSerialization.deserialize(v) for v in var)

    def deserialize_datetime(self, var: float) -> datetime.datetime:
        """Deserialize a datetime."""
        return from_timestamp(var)

    def deserialize_timedelta(self, var: float) -> datetime.timedelta:
        """Deserialize a timedelta."""
        return datetime.timedelta(seconds=var)

    def deserialize_timezone(self, var: str | int) -> Timezone | FixedTimezone:
        """Deserialize a timezone."""
        return decode_timezone(var)

    def deserialize_relativedelta(self, var: dict[str, Any]) -> relativedelta.relativedelta:
        """Deserialize a relativedelta."""
        return decode_relativedelta(var)
