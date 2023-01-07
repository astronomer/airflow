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

from sqlalchemy import Column, String

from airflow.models.base import Base
from airflow.utils.session import provide_session


class Cache(Base):
    """Class to store cache data in database"""

    __tablename__ = "cache"
    key = Column(String(), primary_key=True)
    dag_id = Column(String())
    task_id = Column(String())
    run_id = Column(String())

    def __init__(self, key, dag_id, task_id, run_id):
        self.key = key
        self.dag_id = dag_id
        self.task_id = task_id
        self.run_id = run_id

    @classmethod
    @provide_session
    def get(cls, key, session=None):
        return session.query(cls).filter(cls.key == key).first()

    @classmethod
    @provide_session
    def set(cls, key, task_id, dag_id, run_id, session=None):
        cache = cls(key, dag_id, task_id, run_id)
        session.merge(cache)
        session.commit()
