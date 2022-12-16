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

from sqlalchemy import Column, Enum, ForeignKey, Integer, String, Text

from airflow.models.base import Base
from airflow.utils.dates import timezone
from airflow.utils.email import send_email
from airflow.utils.session import provide_session
from airflow.utils.sqlalchemy import UtcDateTime


class Notification(Base):
    """Notification table"""

    __tablename__ = "notification"

    id = Column(Integer, primary_key=True)
    states = Column(Text())
    tags = Column(Text())
    status = Column(Enum("active", "inactive", name="status"), default="active")
    type = Column(String(50))
    created_at = Column(UtcDateTime(), default=timezone.utcnow())
    updated_at = Column(UtcDateTime, default=timezone.utcnow, onupdate=timezone.utcnow)

    __mapper_args__ = {
        "polymorphic_identity": "notification",
        "polymorphic_on": type,
    }

    def __init__(self, states, tags=None):
        self.states = states
        self.tags = tags

    def send_message(self, subject, message):
        raise NotImplementedError()

    @classmethod
    def notify(cls, state, dag_id, run_id, session, tags=None):
        # Find notification objects with given state and tag
        notifications = session.query(cls).filter(cls.status == "active").filter(cls.states.contains(state))
        notifications = notifications.all()
        # Send message to each notification object
        for notification in notifications:
            if notification.tags:
                if not tags:
                    continue
                if not set(tags).intersection(set(notification.tags.split(","))):
                    continue
            try:
                notification.send_message(state, dag_id, run_id)
            except Exception:
                # TODO: notify user of failure
                pass

    @classmethod
    @provide_session
    def get_notifications(cls, session=None):
        return session.query(cls).all()

    @classmethod
    @provide_session
    def get(cls, notification_id: int, session=None):
        return session.query(cls).get(notification_id)


class EmailNotification(Notification):
    """Email Notification table"""

    __tablename__ = "email_notification"
    __mapper_args__ = {"polymorphic_identity": "email_notification"}
    id = Column(Integer, ForeignKey("notification.id"), primary_key=True)
    email_list = Column(Text())

    def __init__(self, states, email_list, tags=None):
        super().__init__(states, tags)
        self.email_list = email_list

    def send_message(self, state, dag_id, run_id):
        subject = "DagRun Notification"
        time = timezone.utcnow()
        html_content = f"The DAG {dag_id} with Run ID {run_id} entered a {state} state at {time}"
        email_list = self.email_list.split(",")
        if not isinstance(email_list, list):
            email_list = [email_list]
        return send_email(email_list, subject, html_content)
