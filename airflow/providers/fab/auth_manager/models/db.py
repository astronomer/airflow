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

import os

import airflow
from airflow.models.base import BaseDBManager
from airflow.providers.fab.auth_manager.models import metadata


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in [metadata.schema]
    else:
        return True


class FABDBManager(BaseDBManager):
    """
    Manages FAB database.
    """

    version_table_name = "fab_alembic_version"

    def __init__(self, session):
        self.session = session
        migration_dir: str = "providers/fab/alembic"
        alembic_file: str = "providers/fab/alembic.ini"
        package_dir = os.path.dirname(airflow.__file__)
        self.migration_dir = os.path.join(package_dir, migration_dir)
        self.alembic_file = os.path.join(package_dir, alembic_file)
