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

import pytest
from sqlalchemy import select

from airflow.models.hitl import HITLDetail
from airflow.models.hitl_history import HITLDetailHistory

pytestmark = pytest.mark.db_test


class TestAssignedUsersHybrid:
    @pytest.mark.parametrize("model", [HITLDetail, HITLDetailHistory])
    def test_class_level_access_terminates_and_is_selectable(self, model):
        """
        Regression test: without a class-level expression, accessing ``assigned_users`` on
        the class fell back to the instance getter, whose iteration over the ``assignees``
        JSON column expression never terminates (``col[0]``, ``col[1]``, ... forever). That
        hung anything walking class attributes, e.g. ``dir(model)`` or ``Mock(spec=model)``.
        """
        statement = select(model.assigned_users)

        assert "assignees" in str(statement)
        # dir() walks every class attribute, including the hybrid descriptors.
        assert "assigned_users" in dir(model)

    def test_instance_access_maps_assignees(self):
        detail = HITLDetail(assignees=[{"id": "1", "name": "alice"}, {"id": "2", "name": "bob"}])

        assert detail.assigned_users == [
            {"id": "1", "name": "alice"},
            {"id": "2", "name": "bob"},
        ]

    def test_instance_access_without_assignees(self):
        assert HITLDetail(assignees=None).assigned_users == []
