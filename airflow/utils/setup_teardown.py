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

from contextlib import contextmanager

from airflow.exceptions import AirflowException


class SetupTeardownContext:
    """Track whether the next added task is a setup or teardown task"""

    is_setup: bool = False
    is_teardown: bool = False
    on_failure_fail_dagrun: bool = False

    @classmethod
    @contextmanager
    def setup(cls):
        if cls.is_setup or cls.is_teardown:
            raise AirflowException("You cannot mark a setup or teardown task as setup or teardown again.")

        cls.is_setup = True
        try:
            yield
        finally:
            cls.is_setup = False

    @classmethod
    @contextmanager
    def teardown(cls, *, on_failure_fail_dagrun=False):
        if cls.is_setup or cls.is_teardown:
            raise AirflowException("You cannot mark a setup or teardown task as setup or teardown again.")

        cls.is_teardown = True
        cls.on_failure_fail_dagrun = on_failure_fail_dagrun
        try:
            yield
        finally:
            cls.is_teardown = False
            cls.on_failure_fail_dagrun = False


@contextmanager
def setup_teardown(setups=None, teardowns=None, *, dag=None, task_group=None):
    """
    Context manager that sets up setup tasks as upstream of teardown tasks
    and sets up tasks in the context as upstream of teardown tasks.
    e.g usage:
    with setup_teardown(setup1, teardown1):
        task1 >> task2

    """
    from airflow.models.dag import DagContext
    from airflow.utils.task_group import TaskGroupContext

    if not setups and not teardowns:
        raise AirflowException("You must specify at least one setup or teardown task.")

    if not isinstance(setups, list):
        setups = [setups]
    if not isinstance(teardowns, list):
        teardowns = [teardowns]
    setup_tasks = [x.operator for x in setups]
    teardown_tasks = [x.operator for x in teardowns]
    dag = dag or DagContext.get_current_dag()
    task_group = task_group or TaskGroupContext.get_current_task_group(dag)

    root_task = None
    for task in setup_tasks:
        if not task._is_setup:
            raise AirflowException(f"Expected setup task, got {task}")
        if root_task:
            task.set_upstream(root_task)
        root_task = task
        task.dag = dag
    leave_task = None
    for task in teardown_tasks:
        if not task._is_teardown:
            raise AirflowException(f"Expected teardown task, got {task}")
        if leave_task:
            leave_task.set_upstream(task)
        task.dag = dag
        leave_task = task

    yield
    roots = set(task_group.roots) - set(setup_tasks) - set(teardown_tasks)
    leaves = set(task_group.leaves) - set(setup_tasks) - set(teardown_tasks)
    if setup_tasks:
        setup_tasks[-1].set_downstream(list(roots))
    if teardown_tasks:
        teardown_tasks[-1].set_upstream(list(leaves))
    for x, y in zip(setup_tasks, teardown_tasks):
        x.set_downstream(y)
