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

"""Base class for API parameters."""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, TypeVar

from airflow.api_fastapi.core_api.base import OrmClause
from airflow.typing_compat import Self

if TYPE_CHECKING:
    from sqlalchemy.orm.attributes import InstrumentedAttribute
    from sqlalchemy.sql import ColumnElement

T = TypeVar("T")


class BaseParam(OrmClause[T], ABC):
    """Base class for path or query parameters with ORM transformation."""

    def __init__(self, value: T | None = None, skip_none: bool = True) -> None:
        super().__init__(value)
        self.attribute: ColumnElement | InstrumentedAttribute | None = None
        self.skip_none = skip_none

    def set_value(self, value: T | None) -> Self:
        self.value = value
        return self
