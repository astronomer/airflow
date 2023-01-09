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
from airflow.utils.sqlalchemy import UtcDateTime


class TaskRunCache(Base):
    """Class to store task cache data in the database"""

    __tablename__ = "task_run_cache"
    key = Column(String(), primary_key=True)
    expiration_date = Column(UtcDateTime)
    dag_id = Column(String())
    task_id = Column(String())
    run_id = Column(String())

    def __init__(self, key, dag_id, task_id, run_id, expiration_date=None):
        self.key = key
        self.expiration_date = expiration_date
        self.dag_id = dag_id
        self.task_id = task_id
        self.run_id = run_id

    @classmethod
    @provide_session
    def get(cls, key, session=None):
        return session.query(cls).filter(cls.key == key).one_or_none()

    @classmethod
    @provide_session
    def set(cls, key, task_id, dag_id, run_id, expiration_date=None, session=None):
        task_run_cache = cls(
            key=key, dag_id=dag_id, task_id=task_id, run_id=run_id, expiration_date=expiration_date
        )
        session.add(task_run_cache)
        session.flush()
