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

import uuid6
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy_utils import UUIDType

from airflow.models.base import Base
from airflow.utils.sqlalchemy import UtcDateTime


class DagBundle(Base):
    """A table for DAG Bundles."""

    __tablename__ = "dag_bundle"
    id = Column(UUIDType(binary=False), primary_key=True, default=uuid6.uuid7)
    name = Column(String(200), nullable=False, unique=True)
    classpath = Column(String(1000), nullable=False)
    kwargs = Column("kwargs", Text, nullable=False)
    refresh_interval = Column(Integer, nullable=True)
    latest_version = Column(String(200), nullable=True)
    last_refreshed = Column(UtcDateTime, nullable=True)

    def __init__(self, *, name, classpath, kwargs, refresh_interval):
        self.name = name
        self.classpath = classpath
        self.kwargs = kwargs
        self.refresh_interval = refresh_interval
