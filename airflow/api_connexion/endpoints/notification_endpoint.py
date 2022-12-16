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

from flask import request
from marshmallow import ValidationError
from sqlalchemy.orm import Session

from airflow.api_connexion.exceptions import BadRequest, NotFound
from airflow.api_connexion.parameters import apply_sorting
from airflow.api_connexion.schemas.notification_schema import (
    NotificationCollection,
    notification_collection_schema,
    notification_schema,
)
from airflow.api_connexion.types import APIResponse
from airflow.models.notification import Notification
from airflow.utils.session import NEW_SESSION, provide_session


@provide_session
def get_notification(*, notification_id: str, session: Session = NEW_SESSION) -> APIResponse:
    notification = session.query(Notification).filter(Notification.id == notification_id).one_or_none()
    if notification is None:
        raise NotFound(
            "Notification not found",
            detail=f"The Notification with notification_id: `{notification_id}` was not found",
        )
    return notification_schema.dump(notification)


@provide_session
def get_notifications(
    *,
    limit: int,
    offset: int = 0,
    order_by: str = "id",
    session: Session = NEW_SESSION,
) -> APIResponse:
    """Get all notifications"""
    allowed_filter_attrs = ("id", "states", "tags", "type", "created_at", "updated_at")
    query = session.query(Notification)
    total_entries = query.count()
    query = apply_sorting(query=query, order_by=order_by, allowed_attrs=allowed_filter_attrs)
    notifications = query.offset(offset).limit(limit).all()
    return notification_collection_schema.dump(
        NotificationCollection(notifications=notifications, total_entries=total_entries)
    )


@provide_session
def patch_notification(*, notification_id: int, session: Session = NEW_SESSION) -> APIResponse:
    """Update notification"""
    try:
        data = notification_schema.load(request.json)
    except ValidationError as err:
        raise BadRequest(detail=str(err.messages))
    notification = Notification.get(notification_id)
    if not notification:
        raise NotFound(
            "Notification not found",
            detail=f"The Notification with notification_id: `{notification_id}` was not found",
        )
    for key in data:
        setattr(notification, key, data[key])
    session.merge(notification)
    session.commit()
    return notification_schema.dump(notification)


@provide_session
def post_notification(*, session: Session = NEW_SESSION) -> APIResponse:
    """Create new notification"""
    try:
        data = notification_schema.load(request.json)
    except ValidationError as err:
        raise BadRequest(detail=str(err.messages))
    notification = Notification(**data)
    session.add(notification)
    session.commit()
    return notification_schema.dump(notification)
