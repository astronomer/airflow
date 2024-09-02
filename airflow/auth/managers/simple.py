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

from airflow.auth.managers.base_auth_manager import BaseAuthManager
from airflow.auth.managers.models.base_user import BaseUser


class AdminUser(BaseUser):
    """Admin user."""

    def get_id(self) -> str:
        return "1"

    def get_name(self) -> str:
        return "admin"


class SimpleAuthManager(BaseAuthManager):
    """Simple auth manager that allows all actions."""

    def get_user(self):
        return AdminUser()

    def is_logged_in(self) -> bool:
        return True

    def is_authorized_configuration(self, **kwargs) -> bool:
        return True

    def is_authorized_connection(self, **kwargs) -> bool:
        return True

    def is_authorized_dag(self, **kwargs) -> bool:
        return True

    def is_authorized_dataset(self, **kwargs) -> bool:
        return True

    def is_authorized_pool(self, **kwargs) -> bool:
        return True

    def is_authorized_variable(self, **kwargs) -> bool:
        return True

    def is_authorized_view(self, **kwargs) -> bool:
        return True

    def is_authorized_custom_view(self, **kwargs) -> bool:
        return True

    def get_url_login(self, **kwargs) -> str:
        return "/"

    def get_url_logout(self) -> str:
        return "/"
