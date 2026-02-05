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

"""DAG-specific filter parameters for API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypeVar

from fastapi import Query
from sqlalchemy import and_, func, not_, or_, select as sql_select

from airflow.api_fastapi.common.parameters.base import BaseParam
from airflow.api_fastapi.common.parameters.filters import _TagFilterModel
from airflow.api_fastapi.core_api.security import GetUserDep
from airflow.models.asset import (
    AssetModel,
    DagScheduleAssetReference,
    TaskInletAssetReference,
    TaskOutletAssetReference,
)
from airflow.models.dag import DagModel, DagTag
from airflow.models.dag_favorite import DagFavorite
from airflow.utils.state import TaskInstanceState

if TYPE_CHECKING:
    from sqlalchemy.sql import Select

T = TypeVar("T")


class _FavoriteFilter(BaseParam[bool]):
    """Filter Dags by favorite status."""

    def __init__(self, user_id: str, value: T | None = None, skip_none: bool = True) -> None:
        super().__init__(skip_none=skip_none)
        self.user_id = user_id

    def to_orm(self, select_stmt: Select) -> Select:
        if self.value is None and self.skip_none:
            return select_stmt

        if self.value:
            select_stmt = select_stmt.join(DagFavorite, DagFavorite.dag_id == DagModel.dag_id).where(
                DagFavorite.user_id == self.user_id
            )
        else:
            select_stmt = select_stmt.where(
                not_(
                    sql_select(DagFavorite)
                    .where(and_(DagFavorite.dag_id == DagModel.dag_id, DagFavorite.user_id == self.user_id))
                    .exists()
                )
            )

        return select_stmt

    @classmethod
    def depends(cls, user: GetUserDep, is_favorite: bool | None = Query(None)) -> _FavoriteFilter:
        instance = cls(user_id=str(user.get_id())).set_value(is_favorite)
        return instance


class _ExcludeStaleFilter(BaseParam[bool]):
    """Filter on is_stale."""

    def to_orm(self, select: Select) -> Select:
        if self.value and self.skip_none:
            return select.where(DagModel.is_stale != self.value)
        return select

    @classmethod
    def depends(cls, exclude_stale: bool = True) -> _ExcludeStaleFilter:
        return cls().set_value(exclude_stale)


class _TagsFilter(BaseParam[_TagFilterModel]):
    """Filter on tags."""

    def to_orm(self, select: Select) -> Select:
        if self.skip_none is False:
            raise ValueError(f"Cannot set 'skip_none' to False on a {type(self)}")

        if not self.value or not self.value.tags:
            return select

        conditions = [DagModel.tags.any(DagTag.name == tag) for tag in self.value.tags]
        operator = or_ if not self.value.tags_match_mode or self.value.tags_match_mode == "any" else and_
        return select.where(operator(*conditions))

    @classmethod
    def depends(
        cls,
        tags: list[str] = Query(default_factory=list),
        tags_match_mode: Literal["any", "all"] | None = None,
    ) -> _TagsFilter:
        return cls().set_value(_TagFilterModel(tags=tags, tags_match_mode=tags_match_mode))


class _OwnersFilter(BaseParam[list[str]]):
    """Filter on owners."""

    def to_orm(self, select: Select) -> Select:
        if self.skip_none is False:
            raise ValueError(f"Cannot set 'skip_none' to False on a {type(self)}")

        if not self.value:
            return select

        conditions = [DagModel.owners.ilike(f"%{owner}%") for owner in self.value]
        return select.where(or_(*conditions))

    @classmethod
    def depends(cls, owners: list[str] = Query(default_factory=list)) -> _OwnersFilter:
        return cls().set_value(owners)


class _DagIdAssetReferenceFilter(BaseParam[list[str]]):
    """Search on dag_id."""

    def __init__(self, skip_none: bool = True) -> None:
        super().__init__(skip_none=skip_none)

    @classmethod
    def depends(cls, dag_ids: list[str] = Query(None)) -> _DagIdAssetReferenceFilter:
        # needed to handle cases where dag_ids=a1,b1
        if dag_ids and len(dag_ids) == 1 and "," in dag_ids[0]:
            dag_ids = dag_ids[0].split(",")
        return cls().set_value(dag_ids)

    def to_orm(self, select: Select) -> Select:
        if self.value is None and self.skip_none:
            return select

        # At this point, self.value is either a list[str] or None -> coerce falsy None to an empty list
        dag_ids = self.value or []
        return select.where(
            (AssetModel.scheduled_dags.any(DagScheduleAssetReference.dag_id.in_(dag_ids)))
            | (AssetModel.producing_tasks.any(TaskOutletAssetReference.dag_id.in_(dag_ids)))
            | (AssetModel.consuming_tasks.any(TaskInletAssetReference.dag_id.in_(dag_ids)))
        )


class _HasAssetScheduleFilter(BaseParam[bool]):
    """Filter Dags that have asset-based scheduling."""

    def to_orm(self, select: Select) -> Select:
        if self.value is None and self.skip_none:
            return select

        asset_ref_subquery = sql_select(DagScheduleAssetReference.dag_id).distinct()

        if self.value:
            # Filter Dags that have asset-based scheduling
            return select.where(DagModel.dag_id.in_(asset_ref_subquery))

        # Filter Dags that do NOT have asset-based scheduling
        return select.where(DagModel.dag_id.notin_(asset_ref_subquery))

    @classmethod
    def depends(
        cls,
        has_asset_schedule: bool | None = Query(None, description="Filter Dags with asset-based scheduling"),
    ) -> _HasAssetScheduleFilter:
        return cls().set_value(has_asset_schedule)


class _AssetDependencyFilter(BaseParam[str]):
    """Filter Dags by specific asset dependencies."""

    def to_orm(self, select: Select) -> Select:
        if self.value is None and self.skip_none:
            return select

        asset_dag_subquery = (
            sql_select(DagScheduleAssetReference.dag_id)
            .join(AssetModel, DagScheduleAssetReference.asset_id == AssetModel.id)
            .where(or_(AssetModel.name.ilike(f"%{self.value}%"), AssetModel.uri.ilike(f"%{self.value}%")))
            .distinct()
        )

        return select.where(DagModel.dag_id.in_(asset_dag_subquery))

    @classmethod
    def depends(
        cls,
        asset_dependency: str | None = Query(
            None, description="Filter Dags by asset dependency (name or URI)"
        ),
    ) -> _AssetDependencyFilter:
        return cls().set_value(asset_dependency)


class _PendingActionsFilter(BaseParam[bool]):
    """Filter Dags by having pending HITL actions (more than 1)."""

    def to_orm(self, select: Select) -> Select:
        if self.value is None and self.skip_none:
            return select

        from airflow.models.hitl import HITLDetail
        from airflow.models.taskinstance import TaskInstance

        # Join with HITLDetail and TaskInstance to find Dags
        pending_actions_count_subquery = (
            sql_select(func.count(HITLDetail.ti_id))
            .join(TaskInstance, HITLDetail.ti_id == TaskInstance.id)
            .where(
                HITLDetail.responded_at.is_(None),
                TaskInstance.state == TaskInstanceState.DEFERRED,
            )
            .where(TaskInstance.dag_id == DagModel.dag_id)
            .scalar_subquery()
        )

        if self.value is True:
            # Filter to show only Dags with pending actions
            where_clause = pending_actions_count_subquery >= 1
        else:
            # Filter to show only Dags without pending actions
            where_clause = pending_actions_count_subquery == 0

        return select.where(where_clause)

    @classmethod
    def depends(cls, has_pending_actions: bool | None = Query(None)) -> _PendingActionsFilter:
        return cls().set_value(has_pending_actions)
