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
Cursor-based (keyset) pagination helpers.

:meta private:
"""

from __future__ import annotations

import base64
import json
import uuid as uuid_mod
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy import and_, or_

if TYPE_CHECKING:
    from sqlalchemy.sql import ColumnElement, Select

    from airflow.api_fastapi.common.parameters import SortParam


def encode_cursor(row: Any, sort_param: SortParam) -> str:
    """
    Encode cursor token from the last row of a result set.

    The token is a base64url-encoded JSON list containing the sort column
    values in the same order as the resolved sort columns.
    """
    resolved = sort_param.get_resolved_columns()
    if not resolved:
        raise ValueError("SortParam has no resolved columns.")

    values: list[Any] = []
    for attr_name, _col, _desc in resolved:
        val = getattr(row, attr_name, None)
        if val is None:
            values.append(None)
        elif isinstance(val, datetime):
            values.append(val.isoformat())
        else:
            values.append(str(val))

    return base64.urlsafe_b64encode(json.dumps(values).encode()).decode()


def decode_cursor(token: str) -> list[Any]:
    """Decode a cursor token and return the list of values."""
    try:
        data = json.loads(base64.urlsafe_b64decode(token))
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor token")

    if not isinstance(data, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor token structure")

    return data


def _coerce_cursor_value(raw: Any, col: ColumnElement) -> Any:
    """Convert a JSON-serialized cursor value to the Python type expected by the column."""
    if raw is None:
        return None

    from sqlalchemy import Integer, String
    from sqlalchemy.sql.sqltypes import Uuid

    col_type = getattr(col, "type", None)
    if col_type is None:
        return raw

    if isinstance(col_type, Uuid):
        return uuid_mod.UUID(str(raw))
    if isinstance(col_type, Integer):
        return int(raw)
    if isinstance(col_type, String):
        return str(raw)

    type_name = type(col_type).__name__.lower()
    if "datetime" in type_name or "timestamp" in type_name or "date" in type_name:
        return datetime.fromisoformat(str(raw))

    return raw


def apply_cursor_filter(statement: Select, cursor: str, sort_param: SortParam) -> Select:
    """
    Apply a keyset pagination WHERE clause from a cursor token.

    Builds a composite comparison that respects mixed ASC/DESC ordering
    on the resolved sort columns.
    """
    cursor_values = decode_cursor(cursor)

    resolved = sort_param.get_resolved_columns()
    if len(cursor_values) != len(resolved):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cursor token does not match current query shape")

    parsed_values: list[Any] = []
    for i, (_name, col, _desc) in enumerate(resolved):
        parsed_values.append(_coerce_cursor_value(cursor_values[i], col))

    # Build the keyset WHERE clause for mixed ASC/DESC ordering.
    # For columns (c1 ASC, c2 DESC, c3 ASC) with cursor values (v1, v2, v3):
    #   (c1 > v1) OR
    #   (c1 = v1 AND c2 < v2) OR
    #   (c1 = v1 AND c2 = v2 AND c3 > v3)
    or_clauses = []
    for i, (_, col, is_desc) in enumerate(resolved):
        eq_conditions = [resolved[j][1] == parsed_values[j] for j in range(i)]
        if is_desc:
            bound = col < parsed_values[i]
        else:
            bound = col > parsed_values[i]
        or_clauses.append(and_(*eq_conditions, bound))

    return statement.where(or_(*or_clauses))
