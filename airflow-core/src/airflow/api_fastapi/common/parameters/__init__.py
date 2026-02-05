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
API parameters for FastAPI endpoints.

This module provides filter, pagination, and search parameter building blocks
for querying Airflow resources via the REST API.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from pydantic import AfterValidator

from airflow.api_fastapi.common.parameters.base import BaseParam
from airflow.api_fastapi.common.parameters.dag import (
    _AssetDependencyFilter,
    _DagIdAssetReferenceFilter,
    _ExcludeStaleFilter,
    _FavoriteFilter,
    _HasAssetScheduleFilter,
    _OwnersFilter,
    _PendingActionsFilter,
    _TagsFilter,
)
from airflow.api_fastapi.common.parameters.filters import (
    FilterOptionEnum,
    FilterParam,
    Range,
    RangeFilter,
    _SearchParam,
    _TagFilterModel,
)
from airflow.api_fastapi.common.parameters.pagination import (
    LimitFilter,
    OffsetFilter,
    SortParam,
)
from airflow.api_fastapi.common.parameters.task_instance import (
    QueryTaskInstanceTaskGroupFilter,
)
from airflow.api_fastapi.common.parameters.validation import (
    _optional_boolean,
    _safe_parse_datetime,
    _safe_parse_datetime_optional,
    _transform_dag_run_states,
    _transform_dag_run_types,
    _transform_ti_states,
)

# Connection model import (needed for QueryConnectionIdPatternSearch)
from airflow.models import Connection
from airflow.models.asset import AssetAliasModel, AssetModel
from airflow.models.dag import DagModel, DagTag
from airflow.models.dag_version import DagVersion
from airflow.models.dagrun import DagRun
from airflow.models.errors import ParseImportError
from airflow.models.hitl import HITLDetail as HITLDetailModel
from airflow.models.pool import Pool
from airflow.models.taskinstance import TaskInstance
from airflow.models.variable import Variable
from airflow.models.xcom import XComModel
from airflow.utils.state import DagRunState, TaskInstanceState

# Common Safe DateTime type aliases
DateTimeQuery = Annotated[str, AfterValidator(_safe_parse_datetime)]
OptionalDateTimeQuery = Annotated[str | None, AfterValidator(_safe_parse_datetime_optional)]

# Pagination type aliases
QueryLimit = Annotated[LimitFilter, Depends(LimitFilter.depends)]
QueryOffset = Annotated[OffsetFilter, Depends(OffsetFilter.depends)]

# DAG filter type aliases
QueryPausedFilter = Annotated[
    FilterParam[bool | None],
    Depends(FilterParam.for_attr(DagModel.is_paused, bool | None, filter_name="paused")),
]
QueryHasImportErrorsFilter = Annotated[
    FilterParam[bool | None],
    Depends(
        FilterParam.for_attr(
            DagModel.has_import_errors,
            bool | None,
            filter_name="has_import_errors",
            description="Filter Dags by having import errors. Only Dags that have been successfully loaded before will be returned.",
        )
    ),
]
QueryFavoriteFilter = Annotated[_FavoriteFilter, Depends(_FavoriteFilter.depends)]
QueryExcludeStaleFilter = Annotated[_ExcludeStaleFilter, Depends(_ExcludeStaleFilter.depends)]
QueryDagIdPatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(DagModel.dag_id, "dag_id_pattern"))
]
QueryDagDisplayNamePatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(DagModel.dag_display_name, "dag_display_name_pattern"))
]
QueryBundleNameFilter = Annotated[
    FilterParam[str | None],
    Depends(FilterParam.for_attr(DagModel.bundle_name, str | None, filter_name="bundle_name")),
]
QueryBundleVersionFilter = Annotated[
    FilterParam[str | None],
    Depends(FilterParam.for_attr(DagModel.bundle_version, str | None, filter_name="bundle_version")),
]
QueryDagIdPatternSearchWithNone = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(DagModel.dag_id, "dag_id_pattern", False))
]
QueryTagsFilter = Annotated[_TagsFilter, Depends(_TagsFilter.depends)]
QueryOwnersFilter = Annotated[_OwnersFilter, Depends(_OwnersFilter.depends)]
QueryHasAssetScheduleFilter = Annotated[_HasAssetScheduleFilter, Depends(_HasAssetScheduleFilter.depends)]
QueryAssetDependencyFilter = Annotated[_AssetDependencyFilter, Depends(_AssetDependencyFilter.depends)]
QueryPendingActionsFilter = Annotated[_PendingActionsFilter, Depends(_PendingActionsFilter.depends)]

# DagRun filter type aliases
QueryLastDagRunStateFilter = Annotated[
    FilterParam[DagRunState | None],
    Depends(FilterParam.for_attr(DagRun.state, DagRunState | None, filter_name="last_dag_run_state")),
]
QueryDagRunStateFilter = Annotated[
    FilterParam[list[str]],
    Depends(
        FilterParam.for_attr(
            DagRun.state,
            list[str],
            FilterOptionEnum.ANY_EQUAL,
            default_factory=list,
            transform_callable=_transform_dag_run_states,
        )
    ),
]
QueryDagRunRunTypesFilter = Annotated[
    FilterParam[list[str]],
    Depends(
        FilterParam.for_attr(
            attribute=DagRun.run_type,
            _type=list[str],
            filter_option=FilterOptionEnum.ANY_EQUAL,
            default_factory=list,
            transform_callable=_transform_dag_run_types,
        )
    ),
]
QueryDagRunTriggeringUserSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(DagRun.triggering_user_name, "triggering_user"))
]
QueryDagRunVersionFilter = Annotated[
    FilterParam[list[int]],
    Depends(
        FilterParam.for_attr(
            DagVersion.version_number,
            list[int],
            FilterOptionEnum.ANY_EQUAL,
            default_factory=list,
            filter_name="dag_version",
        )
    ),
]

# DagTags filter type aliases
QueryDagTagPatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(DagTag.name, "tag_name_pattern"))
]

# TaskInstance filter type aliases
QueryTIStateFilter = Annotated[
    FilterParam[list[str]],
    Depends(
        FilterParam.for_attr(
            TaskInstance.state,
            list[str],
            FilterOptionEnum.ANY_EQUAL,
            default_factory=list,
            transform_callable=_transform_ti_states,
        )
    ),
]
QueryTIPoolFilter = Annotated[
    FilterParam[list[str]],
    Depends(
        FilterParam.for_attr(TaskInstance.pool, list[str], FilterOptionEnum.ANY_EQUAL, default_factory=list)
    ),
]
QueryTIQueueFilter = Annotated[
    FilterParam[list[str]],
    Depends(
        FilterParam.for_attr(TaskInstance.queue, list[str], FilterOptionEnum.ANY_EQUAL, default_factory=list)
    ),
]
QueryTIPoolNamePatternSearch = Annotated[
    _SearchParam,
    Depends(_SearchParam.for_attr(TaskInstance.pool, "pool_name_pattern")),
]
QueryTIQueueNamePatternSearch = Annotated[
    _SearchParam,
    Depends(_SearchParam.for_attr(TaskInstance.queue, "queue_name_pattern")),
]
QueryTIExecutorFilter = Annotated[
    FilterParam[list[str]],
    Depends(
        FilterParam.for_attr(
            TaskInstance.executor, list[str], FilterOptionEnum.ANY_EQUAL, default_factory=list
        )
    ),
]
QueryTITaskDisplayNamePatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(TaskInstance.task_display_name, "task_display_name_pattern"))
]
QueryTITaskGroupFilter = Annotated[
    QueryTaskInstanceTaskGroupFilter, Depends(QueryTaskInstanceTaskGroupFilter.depends)
]
QueryTIDagVersionFilter = Annotated[
    FilterParam[list[int]],
    Depends(
        FilterParam.for_attr(
            DagVersion.version_number,
            list[int],
            FilterOptionEnum.ANY_EQUAL,
            default_factory=list,
        )
    ),
]
QueryTITryNumberFilter = Annotated[
    FilterParam[list[int]],
    Depends(
        FilterParam.for_attr(
            TaskInstance.try_number, list[int], FilterOptionEnum.ANY_EQUAL, default_factory=list
        )
    ),
]
QueryTIOperatorFilter = Annotated[
    FilterParam[list[str]],
    Depends(
        FilterParam.for_attr(
            TaskInstance.operator, list[str], FilterOptionEnum.ANY_EQUAL, default_factory=list
        )
    ),
]
QueryTIOperatorNamePatternSearch = Annotated[
    _SearchParam,
    Depends(_SearchParam.for_attr(TaskInstance.custom_operator_name, "operator_name_pattern")),
]
QueryTIMapIndexFilter = Annotated[
    FilterParam[list[int]],
    Depends(
        FilterParam.for_attr(
            TaskInstance.map_index, list[int], FilterOptionEnum.ANY_EQUAL, default_factory=list
        )
    ),
]

# Asset filter type aliases
QueryAssetNamePatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(AssetModel.name, "name_pattern"))
]
QueryUriPatternSearch = Annotated[_SearchParam, Depends(_SearchParam.for_attr(AssetModel.uri, "uri_pattern"))]
QueryAssetAliasNamePatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(AssetAliasModel.name, "name_pattern"))
]
QueryAssetDagIdPatternSearch = Annotated[
    _DagIdAssetReferenceFilter, Depends(_DagIdAssetReferenceFilter.depends)
]

# Connection filter type aliases
QueryConnectionIdPatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(Connection.conn_id, "connection_id_pattern"))
]

# Import error filter type aliases
QueryParseImportErrorFilenamePatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(ParseImportError.filename, "filename_pattern"))
]

# Pool filter type aliases
QueryPoolNamePatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(Pool.pool, "pool_name_pattern"))
]

# Variable filter type aliases
QueryVariableKeyPatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(Variable.key, "variable_key_pattern"))
]

# XCom filter type aliases
QueryXComKeyPatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(XComModel.key, "xcom_key_pattern"))
]
QueryXComDagDisplayNamePatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(DagModel.dag_display_name, "dag_display_name_pattern"))
]
QueryXComRunIdPatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(XComModel.run_id, "run_id_pattern"))
]
QueryXComTaskIdPatternSearch = Annotated[
    _SearchParam, Depends(_SearchParam.for_attr(XComModel.task_id, "task_id_pattern"))
]

# HITL filter type aliases
QueryHITLDetailDagIdPatternSearch = Annotated[
    _SearchParam,
    Depends(_SearchParam.for_attr(TaskInstance.dag_id, "dag_id_pattern")),
]
QueryHITLDetailTaskIdPatternSearch = Annotated[
    _SearchParam,
    Depends(_SearchParam.for_attr(TaskInstance.task_id, "task_id_pattern")),
]
QueryHITLDetailTaskIdFilter = Annotated[
    FilterParam[str | None],
    Depends(FilterParam.for_attr(TaskInstance.task_id, str | None, filter_name="task_id")),
]
QueryHITLDetailMapIndexFilter = Annotated[
    FilterParam[int | None],
    Depends(FilterParam.for_attr(TaskInstance.map_index, int | None, filter_name="map_index")),
]
QueryHITLDetailSubjectSearch = Annotated[
    _SearchParam,
    Depends(_SearchParam.for_attr(HITLDetailModel.subject, "subject_search")),
]
QueryHITLDetailBodySearch = Annotated[
    _SearchParam,
    Depends(_SearchParam.for_attr(HITLDetailModel.body, "body_search")),
]
QueryHITLDetailResponseReceivedFilter = Annotated[
    FilterParam[bool | None],
    Depends(
        FilterParam.for_attr(HITLDetailModel.response_received, bool | None, filter_name="response_received")
    ),
]
QueryHITLDetailRespondedUserIdFilter = Annotated[
    FilterParam[list[str]],
    Depends(
        FilterParam.for_attr(
            HITLDetailModel.responded_by_user_id,
            list[str],
            FilterOptionEnum.ANY_EQUAL,
            default_factory=list,
            filter_name="responded_by_user_id",
        )
    ),
]
QueryHITLDetailRespondedUserNameFilter = Annotated[
    FilterParam[list[str]],
    Depends(
        FilterParam.for_attr(
            HITLDetailModel.responded_by_user_name,
            list[str],
            FilterOptionEnum.ANY_EQUAL,
            default_factory=list,
            filter_name="responded_by_user_name",
        )
    ),
]

# UI Shared type aliases
QueryIncludeUpstream = Annotated[bool, AfterValidator(_optional_boolean)]
QueryIncludeDownstream = Annotated[bool, AfterValidator(_optional_boolean)]

state_priority: list[None | TaskInstanceState] = [
    TaskInstanceState.FAILED,
    TaskInstanceState.UPSTREAM_FAILED,
    TaskInstanceState.UP_FOR_RETRY,
    TaskInstanceState.UP_FOR_RESCHEDULE,
    TaskInstanceState.QUEUED,
    TaskInstanceState.SCHEDULED,
    TaskInstanceState.DEFERRED,
    TaskInstanceState.RUNNING,
    TaskInstanceState.RESTARTING,
    None,
    TaskInstanceState.SUCCESS,
    TaskInstanceState.SKIPPED,
    TaskInstanceState.REMOVED,
]

__all__ = [
    # Base
    "BaseParam",
    # Pagination
    "LimitFilter",
    "OffsetFilter",
    "SortParam",
    "QueryLimit",
    "QueryOffset",
    # Filters
    "FilterOptionEnum",
    "FilterParam",
    "Range",
    "RangeFilter",
    "_SearchParam",
    "_TagFilterModel",
    # DAG filters (classes)
    "_AssetDependencyFilter",
    "_DagIdAssetReferenceFilter",
    "_ExcludeStaleFilter",
    "_FavoriteFilter",
    "_HasAssetScheduleFilter",
    "_OwnersFilter",
    "_PendingActionsFilter",
    "_TagsFilter",
    # DAG filter type aliases
    "QueryPausedFilter",
    "QueryHasImportErrorsFilter",
    "QueryFavoriteFilter",
    "QueryExcludeStaleFilter",
    "QueryDagIdPatternSearch",
    "QueryDagDisplayNamePatternSearch",
    "QueryBundleNameFilter",
    "QueryBundleVersionFilter",
    "QueryDagIdPatternSearchWithNone",
    "QueryTagsFilter",
    "QueryOwnersFilter",
    "QueryHasAssetScheduleFilter",
    "QueryAssetDependencyFilter",
    "QueryPendingActionsFilter",
    # DagRun filter type aliases
    "QueryLastDagRunStateFilter",
    "QueryDagRunStateFilter",
    "QueryDagRunRunTypesFilter",
    "QueryDagRunTriggeringUserSearch",
    "QueryDagRunVersionFilter",
    # DagTags filter type aliases
    "QueryDagTagPatternSearch",
    # Asset filter type aliases
    "QueryAssetNamePatternSearch",
    "QueryUriPatternSearch",
    "QueryAssetAliasNamePatternSearch",
    "QueryAssetDagIdPatternSearch",
    # Connection filter type aliases
    "QueryConnectionIdPatternSearch",
    # Import error filter type aliases
    "QueryParseImportErrorFilenamePatternSearch",
    # Pool filter type aliases
    "QueryPoolNamePatternSearch",
    # Variable filter type aliases
    "QueryVariableKeyPatternSearch",
    # XCom filter type aliases
    "QueryXComKeyPatternSearch",
    "QueryXComDagDisplayNamePatternSearch",
    "QueryXComRunIdPatternSearch",
    "QueryXComTaskIdPatternSearch",
    # HITL filter type aliases
    "QueryHITLDetailDagIdPatternSearch",
    "QueryHITLDetailTaskIdPatternSearch",
    "QueryHITLDetailTaskIdFilter",
    "QueryHITLDetailMapIndexFilter",
    "QueryHITLDetailSubjectSearch",
    "QueryHITLDetailBodySearch",
    "QueryHITLDetailResponseReceivedFilter",
    "QueryHITLDetailRespondedUserIdFilter",
    "QueryHITLDetailRespondedUserNameFilter",
    # Task instance filter (class)
    "QueryTaskInstanceTaskGroupFilter",
    # Task instance filter type aliases
    "QueryTIStateFilter",
    "QueryTIPoolFilter",
    "QueryTIQueueFilter",
    "QueryTIPoolNamePatternSearch",
    "QueryTIQueueNamePatternSearch",
    "QueryTIExecutorFilter",
    "QueryTITaskDisplayNamePatternSearch",
    "QueryTITaskGroupFilter",
    "QueryTIDagVersionFilter",
    "QueryTITryNumberFilter",
    "QueryTIOperatorFilter",
    "QueryTIOperatorNamePatternSearch",
    "QueryTIMapIndexFilter",
    # Validation
    "_optional_boolean",
    "_safe_parse_datetime",
    "_safe_parse_datetime_optional",
    "_transform_dag_run_states",
    "_transform_dag_run_types",
    "_transform_ti_states",
    # DateTime type aliases
    "DateTimeQuery",
    "OptionalDateTimeQuery",
    # UI Shared
    "QueryIncludeUpstream",
    "QueryIncludeDownstream",
    "state_priority",
]
