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

"""Filter parameters for API endpoints."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, cast

from fastapi import HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_

from airflow.api_fastapi.common.parameters.base import BaseParam
from airflow.models import Base

if TYPE_CHECKING:
    from sqlalchemy.orm.attributes import InstrumentedAttribute
    from sqlalchemy.sql import ColumnElement, Select

T = TypeVar("T")


class _SearchParam(BaseParam[str]):
    """Search on attribute."""

    DESCRIPTION = (
        "SQL LIKE expression — use `%` / `_` wildcards (e.g. `%customer_%`). "
        "or the pipe `|` operator for OR logic (e.g. `dag1 | dag2`). "
        "Regular expressions are **not** supported."
    )

    def __init__(self, attribute: ColumnElement, skip_none: bool = True) -> None:
        super().__init__(skip_none=skip_none)
        self.attribute: ColumnElement = attribute

    def to_orm(self, select: Select) -> Select:
        if self.value is None and self.skip_none:
            return select

        val_str = str(self.value)
        if "|" in val_str:
            search_terms = [term.strip() for term in val_str.split("|") if term.strip()]
            if len(search_terms) > 1:
                return select.where(or_(*(self.attribute.ilike(f"%{term}%") for term in search_terms)))

        return select.where(self.attribute.ilike(f"%{self.value}%"))

    def transform_aliases(self, value: str | None) -> str | None:
        if value == "~":
            value = "%"
        return value

    @classmethod
    def for_attr(
        cls,
        attribute: ColumnElement,
        pattern_name: str,
        skip_none: bool = True,
    ) -> Callable[[str | None], _SearchParam]:
        """
        Create a dependency function for searching on an attribute.

        Usage:
            dag_id_pattern: Annotated[_SearchParam, Depends(_SearchParam.for_attr(DagModel.dag_id, "dag_id_pattern"))]
        """

        def depends_search(
            value: str | None = Query(alias=pattern_name, default=None, description=cls.DESCRIPTION),
        ) -> _SearchParam:
            search_param = cls(attribute, skip_none)
            value = search_param.transform_aliases(value)
            return search_param.set_value(value)

        return depends_search


class FilterOptionEnum(Enum):
    """Filter options for FilterParam."""

    EQUAL = "eq"
    NOT_EQUAL = "ne"
    LESS_THAN = "lt"
    LESS_THAN_EQUAL = "le"
    GREATER_THAN = "gt"
    GREATER_THAN_EQUAL = "ge"
    IN = "in"
    NOT_IN = "not_in"
    ANY_EQUAL = "any_eq"
    ALL_EQUAL = "all_eq"
    IS_NONE = "is_none"
    CONTAINS = "contains"


class FilterParam(BaseParam[T]):
    """Filter on attribute."""

    def __init__(
        self,
        attribute: InstrumentedAttribute,
        value: T | None = None,
        filter_option: FilterOptionEnum = FilterOptionEnum.EQUAL,
        skip_none: bool = True,
    ) -> None:
        super().__init__(value, skip_none)
        self.attribute: InstrumentedAttribute = attribute
        self.value: T | None = value
        self.filter_option: FilterOptionEnum = filter_option

    @classmethod
    def for_attr(
        cls,
        attribute: ColumnElement | InstrumentedAttribute,
        _type: type,
        filter_option: FilterOptionEnum = FilterOptionEnum.EQUAL,
        filter_name: str | None = None,
        default_value: T | None = None,
        default_factory: Callable[[], T | None] | None = None,
        skip_none: bool = True,
        transform_callable: Callable[[T | None], Any] | None = None,
        *,
        description: str | None = None,
    ) -> Callable[[T | None], FilterParam[T | None]]:
        """
        Create a dependency function for filtering on an attribute.

        Usage:
            paused: Annotated[FilterParam[bool | None], Depends(FilterParam.for_attr(DagModel.is_paused, bool | None))]
        """
        # if filter_name is not provided, use the attribute name as the default
        filter_name = filter_name or getattr(attribute, "name", str(attribute))
        # can only set either default_value or default_factory
        query = (
            Query(alias=filter_name, default_factory=default_factory, description=description)
            if default_factory is not None
            else Query(alias=filter_name, default=default_value, description=description)
        )

        def depends_filter(value: T | None = query) -> FilterParam[T | None]:
            if transform_callable:
                value = transform_callable(value)
            attr = cast("InstrumentedAttribute", attribute)
            return cls(attr, value, filter_option, skip_none)

        # Add type hint to value at runtime for FastAPI OpenAPI schema generation
        depends_filter.__annotations__["value"] = _type

        return depends_filter

    def to_orm(self, select: Select) -> Select:
        if isinstance(self.value, (list, str)) and not self.value and self.skip_none:
            return select
        if self.value is None and self.skip_none:
            return select

        if isinstance(self.value, list):
            if self.filter_option == FilterOptionEnum.IN:
                return select.where(self.attribute.in_(self.value))
            if self.filter_option == FilterOptionEnum.NOT_IN:
                return select.where(self.attribute.notin_(self.value))
            if self.filter_option == FilterOptionEnum.ANY_EQUAL:
                conditions = [self.attribute == val for val in self.value]
                return select.where(or_(*conditions))
            if self.filter_option == FilterOptionEnum.ALL_EQUAL:
                conditions = [self.attribute == val for val in self.value]
                return select.where(and_(*conditions))
            raise HTTPException(
                400, f"Invalid filter option {self.filter_option} for list value {self.value}"
            )

        if self.filter_option == FilterOptionEnum.EQUAL:
            return select.where(self.attribute == self.value)
        if self.filter_option == FilterOptionEnum.NOT_EQUAL:
            return select.where(self.attribute != self.value)
        if self.filter_option == FilterOptionEnum.LESS_THAN:
            return select.where(self.attribute < self.value)
        if self.filter_option == FilterOptionEnum.LESS_THAN_EQUAL:
            return select.where(self.attribute <= self.value)
        if self.filter_option == FilterOptionEnum.GREATER_THAN:
            return select.where(self.attribute > self.value)
        if self.filter_option == FilterOptionEnum.GREATER_THAN_EQUAL:
            return select.where(self.attribute >= self.value)
        if self.filter_option == FilterOptionEnum.IS_NONE:
            if self.value is None:
                return select
            if self.value is False:
                return select.where(self.attribute.is_not(None))
            if self.value is True:
                return select.where(self.attribute.is_(None))
        if self.filter_option == FilterOptionEnum.CONTAINS:
            # For JSON/JSONB columns, convert to text before applying LIKE
            from sqlalchemy import Text, cast

            if str(self.attribute.type).upper() in ("JSON", "JSONB"):
                return select.where(cast(self.attribute, Text).contains(self.value))
            return select.where(self.attribute.contains(self.value))
        raise ValueError(f"Invalid filter option {self.filter_option} for value {self.value}")


class _TagFilterModel(BaseModel):
    """Tag Filter Model with a match mode parameter."""

    tags: list[str]
    tags_match_mode: Literal["any", "all"] | None


class Range(BaseModel, Generic[T]):
    """Range with a lower and upper bound."""

    lower_bound_gte: T | None
    lower_bound_gt: T | None
    upper_bound_lte: T | None
    upper_bound_lt: T | None


class RangeFilter(BaseParam[Range]):
    """Filter on range in between the lower and upper bound."""

    def __init__(self, value: Range | None, attribute: InstrumentedAttribute) -> None:
        super().__init__(value)
        self.attribute: InstrumentedAttribute = attribute

    def to_orm(self, select: Select) -> Select:
        if self.skip_none is False:
            raise ValueError(f"Cannot set 'skip_none' to False on a {type(self)}")

        if self.value is None:
            return select

        if self.value.lower_bound_gte:
            select = select.where(self.attribute >= self.value.lower_bound_gte)
        if self.value.lower_bound_gt:
            select = select.where(self.attribute > self.value.lower_bound_gt)
        if self.value.upper_bound_lte:
            select = select.where(self.attribute <= self.value.upper_bound_lte)
        if self.value.upper_bound_lt:
            select = select.where(self.attribute < self.value.upper_bound_lt)

        return select

    def is_active(self) -> bool:
        """Check if the range filter has any active bounds."""
        return self.value is not None and (
            self.value.lower_bound_gte is not None
            or self.value.lower_bound_gt is not None
            or self.value.upper_bound_lte is not None
            or self.value.upper_bound_lt is not None
        )

    @classmethod
    def for_datetime(
        cls, filter_name: str, model: Base, attribute_name: str | None = None
    ) -> Callable[[datetime | None, datetime | None, datetime | None, datetime | None], RangeFilter]:
        """
        Create a dependency function for datetime range filtering.

        Usage:
            start_date_range: Annotated[RangeFilter, Depends(RangeFilter.for_datetime("start_date", DagRun))]
        """

        def depends_datetime(
            lower_bound_gte: datetime | None = Query(alias=f"{filter_name}_gte", default=None),
            lower_bound_gt: datetime | None = Query(alias=f"{filter_name}_gt", default=None),
            upper_bound_lte: datetime | None = Query(alias=f"{filter_name}_lte", default=None),
            upper_bound_lt: datetime | None = Query(alias=f"{filter_name}_lt", default=None),
        ) -> RangeFilter:
            attr = getattr(model, attribute_name or filter_name)
            if filter_name in ("start_date", "end_date"):
                attr = func.coalesce(attr, func.now())
            return cls(
                Range(
                    lower_bound_gte=lower_bound_gte,
                    lower_bound_gt=lower_bound_gt,
                    upper_bound_lte=upper_bound_lte,
                    upper_bound_lt=upper_bound_lt,
                ),
                attr,
            )

        return depends_datetime

    @classmethod
    def for_float(
        cls, filter_name: str, model: Base
    ) -> Callable[[float | None, float | None, float | None, float | None], RangeFilter]:
        """
        Create a dependency function for float range filtering.

        Usage:
            duration_range: Annotated[RangeFilter, Depends(RangeFilter.for_float("duration", TaskInstance))]
        """

        def depends_float(
            lower_bound_gte: float | None = Query(alias=f"{filter_name}_gte", default=None),
            lower_bound_gt: float | None = Query(alias=f"{filter_name}_gt", default=None),
            upper_bound_lte: float | None = Query(alias=f"{filter_name}_lte", default=None),
            upper_bound_lt: float | None = Query(alias=f"{filter_name}_lt", default=None),
        ) -> RangeFilter:
            return cls(
                Range(
                    lower_bound_gte=lower_bound_gte,
                    lower_bound_gt=lower_bound_gt,
                    upper_bound_lte=upper_bound_lte,
                    upper_bound_lt=upper_bound_lt,
                ),
                getattr(model, filter_name),
            )

        return depends_float
