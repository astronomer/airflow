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

from typing import NamedTuple

from marshmallow import Schema, fields, validate
from marshmallow_sqlalchemy import SQLAlchemySchema, auto_field

from airflow.models.notification import Notification
from airflow.utils.session import provide_session


@provide_session
def notification_types(session=None):
    return [n.type for n in session.query(Notification.type).distinct().all()]


class NotificationSchema(SQLAlchemySchema):
    """Schema for Notification item"""

    class Meta:
        """Meta."""

        model = Notification

    id = auto_field(dump_only=True)
    states = auto_field()
    tags = auto_field()
    status = auto_field()
    type = auto_field(validate=validate.OneOf(notification_types()))
    created_at = auto_field(dump_only=True)
    updated_at = auto_field(dump_only=True)


class NotificationCollection(NamedTuple):
    """List of notifications"""

    notifications: list[Notification]
    total_entries: int


class NotificationCollectionSchema(Schema):
    """Notification collection schema"""

    notifications = fields.List(fields.Nested(NotificationSchema))
    total_entries = fields.Int()


notification_schema = NotificationSchema()
notification_collection_schema = NotificationCollectionSchema()
