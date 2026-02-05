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

"""Pagination parameters for API endpoints."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import HTTPException, Query
from pydantic import NonNegativeInt
from sqlalchemy import Column
from sqlalchemy.inspection import inspect

from airflow.api_fastapi.common.parameters.base import BaseParam
from airflow.configuration import conf
from airflow.models import Base

if TYPE_CHECKING:
    from sqlalchemy.sql import ColumnElement, Select


class LimitFilter(BaseParam[NonNegativeInt]):
    """Filter on the limit."""

    def to_orm(self, select: Select) -> Select:
        if self.value is None and self.skip_none:
            return select

        return select.limit(self.value)

    @classmethod
    def depends(cls, limit: NonNegativeInt = conf.getint("api", "fallback_page_limit")) -> LimitFilter:
        return cls().set_value(min(limit, conf.getint("api", "maximum_page_limit")))


class OffsetFilter(BaseParam[NonNegativeInt]):
    """Filter on offset."""

    def to_orm(self, select: Select) -> Select:
        if self.value is None and self.skip_none:
            return select
        return select.offset(self.value)

    @classmethod
    def depends(cls, offset: NonNegativeInt = 0) -> OffsetFilter:
        return cls().set_value(offset)


class SortParam(BaseParam[list[str]]):
    """Order result by the attribute."""

    MAX_SORT_PARAMS = 10

    def __init__(
        self, allowed_attrs: list[str], model: Base, to_replace: dict[str, str | Column] | None = None
    ) -> None:
        super().__init__()
        self.allowed_attrs = allowed_attrs
        self.model = model
        self.to_replace = to_replace

    def to_orm(self, select: Select) -> Select:
        if self.skip_none is False:
            raise ValueError(f"Cannot set 'skip_none' to False on a {type(self)}")

        order_by_values = self.value if self.value is not None else [self.get_primary_key_string()]
        if len(order_by_values) > self.MAX_SORT_PARAMS:
            raise HTTPException(
                400,
                f"Ordering with more than {self.MAX_SORT_PARAMS} parameters is not allowed. Provided: {order_by_values}",
            )

        columns: list[ColumnElement] = []
        for order_by_value in order_by_values:
            lstriped_orderby = order_by_value.lstrip("-")
            column: Column | None = None
            if self.to_replace:
                replacement = self.to_replace.get(lstriped_orderby, lstriped_orderby)
                if isinstance(replacement, str):
                    lstriped_orderby = replacement
                else:
                    column = replacement

            if (self.allowed_attrs and lstriped_orderby not in self.allowed_attrs) and column is None:
                raise HTTPException(
                    400,
                    f"Ordering with '{lstriped_orderby}' is disallowed or "
                    f"the attribute does not exist on the model",
                )
            if column is None:
                column = getattr(self.model, lstriped_orderby)

            if order_by_value.startswith("-"):
                columns.append(column.desc())
            else:
                columns.append(column.asc())

        # Reset default sorting
        select = select.order_by(None)

        primary_key_column = self.get_primary_key_column()
        # Always add a final discriminator to enforce deterministic ordering.
        if order_by_values and order_by_values[0].startswith("-"):
            columns.append(primary_key_column.desc())
        else:
            columns.append(primary_key_column.asc())

        return select.order_by(*columns)

    def get_primary_key_column(self) -> Column:
        """Get the primary key column of the model of SortParam object."""
        return inspect(self.model).primary_key[0]

    def get_primary_key_string(self) -> str:
        """Get the primary key string of the model of SortParam object."""
        return self.get_primary_key_column().name

    @classmethod
    def for_model(
        cls,
        allowed_attrs: list[str],
        model: Base,
        to_replace: dict[str, str | Column] | None = None,
        default: str | None = None,
    ) -> Callable[[list[str]], SortParam]:
        """
        Create a dependency function for sorting on a model.

        Usage:
            order_by: Annotated[SortParam, Depends(SortParam.for_model(["dag_id", "state"], DagModel))]
        """
        # Create a temporary instance to get the primary key string for defaults
        temp_instance = cls(allowed_attrs, model, to_replace)
        primary_key_str = temp_instance.get_primary_key_string()
        to_replace_attrs = list(to_replace.keys()) if to_replace else []
        all_attrs = allowed_attrs + to_replace_attrs

        def depends_sort(
            order_by: list[str] = Query(
                default=[default] if default is not None else [primary_key_str],
                description=f"Attributes to order by, multi criteria sort is supported. Prefix with `-` for descending order. "
                f"Supported attributes: `{', '.join(all_attrs) if all_attrs else primary_key_str}`",
            ),
        ) -> SortParam:
            # Create a new instance for each request to avoid shared state between concurrent requests
            return cls(allowed_attrs, model, to_replace).set_value(order_by)

        return depends_sort
