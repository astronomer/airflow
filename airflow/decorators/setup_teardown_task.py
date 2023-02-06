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

from airflow.decorators import python_task
from airflow.decorators.base import _TaskDecorator
from airflow.models import BaseOperator

TEARDOWN_TASK_ATTR_NAME = "_airflow_teardown_task"
SETUP_TASK_ATTR_NAME = "_airflow_setup_task"


def task_decorator(attribute_name):
    def task_decorator_inner(func, **kwargs):
        def decorator(f):
            def create_python_task(f, **kwargs):
                task = python_task(f, **kwargs)
                setattr(task.operator_class, attribute_name, True)  # type: ignore
                return task

            return create_python_task(f, **kwargs)

        if isinstance(func, _TaskDecorator):
            setattr(func.operator_class, attribute_name, True)
            return func
        elif isinstance(func, BaseOperator):
            setattr(func, attribute_name, True)
            return func
        return decorator(func)

    return task_decorator_inner


teardown_task = task_decorator(TEARDOWN_TASK_ATTR_NAME)
setup_task = task_decorator(SETUP_TASK_ATTR_NAME)
