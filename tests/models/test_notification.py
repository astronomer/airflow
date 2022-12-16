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

from unittest import mock

from airflow.models.notification import EmailNotification, Notification


class TestNotification:
    @mock.patch("airflow.models.notification.send_email")
    def test_notify(self, email_mock, session, dag_maker):
        email_notification = EmailNotification("success, failed", "test@example.com")
        session.add(email_notification)
        session.commit()

        Notification.notify("success", "test_dag", "test_run", "2022-12-15T00:00:00", session)
        email_mock.assert_called_once_with(
            ["test@example.com"],
            "DagRun Notification",
            "The DAG test_dag with Run ID test_run entered a success state at 2022-12-15T00:00:00",
        )
