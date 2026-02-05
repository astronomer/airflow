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

"""Validation and transformation utilities for API parameters."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import overload

from fastapi import HTTPException
from pendulum.parsing.exceptions import ParserError

from airflow._shared.timezones import timezone
from airflow.api_fastapi.compat import HTTP_422_UNPROCESSABLE_CONTENT
from airflow.utils.state import DagRunState, TaskInstanceState
from airflow.utils.types import DagRunType


def _safe_parse_datetime(date_to_check: str) -> datetime:
    """
    Parse datetime and raise error for invalid dates.

    :param date_to_check: the string value to be parsed
    """
    if not date_to_check:
        raise ValueError(f"{date_to_check} cannot be None.")
    return _safe_parse_datetime_optional(date_to_check)


@overload
def _safe_parse_datetime_optional(date_to_check: str) -> datetime: ...


@overload
def _safe_parse_datetime_optional(date_to_check: None) -> None: ...


def _safe_parse_datetime_optional(date_to_check: str | None) -> datetime | None:
    """
    Parse datetime and raise error for invalid dates.

    Allow None values.

    :param date_to_check: the string value to be parsed
    """
    if date_to_check is None:
        return None
    try:
        return timezone.parse(date_to_check, strict=True)
    except (TypeError, ParserError):
        raise HTTPException(
            400, f"Invalid datetime: {date_to_check!r}. Please check the date parameter have this value."
        )


def _transform_dag_run_states(states: Iterable[str] | None) -> list[DagRunState | None] | None:
    try:
        if not states:
            return None
        return [None if s in ("none", None) else DagRunState(s) for s in states]
    except ValueError:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid value for state. Valid values are {', '.join(DagRunState)}",
        )


def _transform_dag_run_types(types: list[str] | None) -> list[DagRunType | None] | None:
    try:
        if not types:
            return None
        return [None if run_type in ("none", None) else DagRunType(run_type) for run_type in types]
    except ValueError:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid value for run type. Valid values are {', '.join(DagRunType)}",
        )


def _transform_ti_states(states: list[str] | None) -> list[TaskInstanceState | None] | None:
    """Transform a list of state strings into a list of TaskInstanceState enums handling special 'None' cases."""
    if not states:
        return None

    try:
        return [None if s in ("no_status", "none", None) else TaskInstanceState(s) for s in states]
    except ValueError:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid value for state. Valid values are {', '.join(TaskInstanceState)}",
        )


def _optional_boolean(value: bool | None) -> bool | None:
    return value if value is not None else False
