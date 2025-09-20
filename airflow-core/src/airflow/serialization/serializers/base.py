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
"""Base serializer for primitive types and basic objects."""

from __future__ import annotations

import datetime
import enum
import math
from typing import TYPE_CHECKING, Any

from dateutil import relativedelta
from pendulum.tz.timezone import FixedTimezone, Timezone

from airflow.exceptions import SerializationError
from airflow.serialization.enums import DagAttributeTypes as DAT, Encoding

if TYPE_CHECKING:
    from airflow.sdk.definitions.edges import EdgeInfoType


def encode_timezone(var: Timezone | FixedTimezone) -> str | int:
    """
    Encode a Pendulum Timezone for serialization.

    Airflow only supports timezone objects that implements Pendulum's Timezone
    interface. We try to keep as much information as possible to make conversion
    round-tripping possible (see ``decode_timezone``). We need to special-case
    UTC; Pendulum implements it as a FixedTimezone (i.e. it gets encoded as
    0 without the special case), but passing 0 into ``pendulum.timezone`` does
    not give us UTC (but ``+00:00``).
    """
    if isinstance(var, FixedTimezone):
        if var.offset == 0:
            return "UTC"
        return var.offset
    if isinstance(var, Timezone):
        return var.name
    from airflow.utils.docs import get_docs_url
    raise ValueError(
        f"DAG timezone should be a pendulum.tz.Timezone, not {var!r}. "
        f"See {get_docs_url('timezone.html#time-zone-aware-dags')}"
    )


def encode_relativedelta(var: relativedelta.relativedelta) -> dict[str, Any]:
    """Encode a relativedelta object."""
    encoded = {k: v for k, v in var.__dict__.items() if not k.startswith("_") and v}
    if var.weekday and var.weekday.n:
        # Every n'th Friday for example
        encoded["weekday"] = [var.weekday.weekday, var.weekday.n]
    elif var.weekday:
        encoded["weekday"] = [var.weekday.weekday]
    return encoded


class BaseSerializer:
    """Handles serialization of primitive types and basic objects."""

    # JSON primitive types.
    _primitive_types = (int, bool, float, str)

    # Time types.
    # datetime.date and datetime.time are converted to strings.
    _datetime_types = (datetime.datetime,)

    def serialize(self, var: Any, *, strict: bool = False) -> Any:
        """
        Route to appropriate serialization method based on type.
        
        :param var: The object to serialize
        :param strict: If True, raise exception for unknown types
        :return: Serialized representation
        """
        # Primitives
        if self._is_primitive(var):
            return self.serialize_primitive(var)
        
        # Collections
        elif isinstance(var, dict):
            return self.serialize_dict(var, strict=strict)
        elif isinstance(var, list):
            return self.serialize_list(var, strict=strict)
        elif isinstance(var, set):
            return self.serialize_set(var, strict=strict)
        elif isinstance(var, tuple):
            return self.serialize_tuple(var, strict=strict)
        
        # Date/Time types
        elif isinstance(var, self._datetime_types):
            return self.serialize_datetime(var)
        elif isinstance(var, datetime.timedelta):
            return self.serialize_timedelta(var)
        elif isinstance(var, (Timezone, FixedTimezone)):
            return self.serialize_timezone(var)
        elif isinstance(var, relativedelta.relativedelta):
            return self.serialize_relativedelta(var)
        
        # Unknown type - let calling code handle it
        else:
            return None

    def _is_primitive(self, var: Any) -> bool:
        """Check if variable is a primitive type."""
        return var is None or isinstance(var, self._primitive_types)

    @staticmethod
    def _encode(x: Any, type_: Any) -> dict[Encoding, Any]:
        """Encode data by a JSON dict."""
        return {Encoding.VAR: x, Encoding.TYPE: type_}

    def serialize_primitive(self, var: Any) -> Any:
        """Serialize primitive types."""
        if var is None:
            return var
        # enum.IntEnum is an int instance, it causes json dumps error so we use its value.
        if isinstance(var, enum.Enum):
            return var.value
        # These are not allowed in JSON. https://datatracker.ietf.org/doc/html/rfc8259#section-6
        if isinstance(var, float) and (math.isnan(var) or math.isinf(var)):
            return str(var)
        return var

    def serialize_dict(self, var: dict[Any, Any], *, strict: bool = False) -> dict[str, Any]:
        """Serialize a dictionary."""
        # Avoid circular imports
        from airflow.serialization.serialized_objects import BaseSerialization
        return self._encode(
            {str(k): BaseSerialization.serialize(v, strict=strict) for k, v in var.items()},
            type_=DAT.DICT,
        )

    def serialize_list(self, var: list[Any], *, strict: bool = False) -> list[Any]:
        """Serialize a list."""
        # Avoid circular imports
        from airflow.serialization.serialized_objects import BaseSerialization
        return [BaseSerialization.serialize(v, strict=strict) for v in var]

    def serialize_set(self, var: set[Any], *, strict: bool = False) -> dict[str, Any]:
        """Serialize a set."""
        # Avoid circular imports
        from airflow.serialization.serialized_objects import BaseSerialization
        # FIXME: casts set to list in customized serialization in future.
        try:
            return self._encode(
                sorted(BaseSerialization.serialize(v, strict=strict) for v in var),
                type_=DAT.SET,
            )
        except TypeError:
            return self._encode(
                [BaseSerialization.serialize(v, strict=strict) for v in var],
                type_=DAT.SET,
            )

    def serialize_tuple(self, var: tuple[Any, ...], *, strict: bool = False) -> dict[str, Any]:
        """Serialize a tuple."""
        # Avoid circular imports
        from airflow.serialization.serialized_objects import BaseSerialization
        # FIXME: casts tuple to list in customized serialization in future.
        return self._encode(
            [BaseSerialization.serialize(v, strict=strict) for v in var],
            type_=DAT.TUPLE,
        )

    def serialize_datetime(self, var: datetime.datetime) -> dict[str, Any]:
        """Serialize a datetime."""
        return self._encode(var.timestamp(), type_=DAT.DATETIME)

    def serialize_timedelta(self, var: datetime.timedelta) -> dict[str, Any]:
        """Serialize a timedelta."""
        return self._encode(var.total_seconds(), type_=DAT.TIMEDELTA)

    def serialize_timezone(self, var: Timezone | FixedTimezone) -> dict[str, Any]:
        """Serialize a timezone."""
        return self._encode(encode_timezone(var), type_=DAT.TIMEZONE)

    def serialize_relativedelta(self, var: relativedelta.relativedelta) -> dict[str, Any]:
        """Serialize a relativedelta."""
        return self._encode(encode_relativedelta(var), type_=DAT.RELATIVEDELTA)

    def default_serialization(self, var: Any, *, strict: bool) -> str:
        """Default serialization for unknown types."""
        import logging
        log = logging.getLogger(__name__)
        log.debug("Cast type %s to str in serialization.", type(var))
        if strict:
            raise SerializationError("Encountered unexpected type")
        return str(var)
