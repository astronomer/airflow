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

from typing import TYPE_CHECKING

from airflow.providers.openlineage.extractors.base import OperatorLineage
from airflow.providers.openlineage.version_compat import BaseOperator

if TYPE_CHECKING:
    from airflow.sdk.definitions.context import Context


class EmptyOperator(BaseOperator):
    """
    Operator that does literally nothing.

    It can be used to group tasks in a DAG.
    The task is evaluated by the scheduler but never processed by the executor.
    """

    ui_color = "#e8f7e4"

    def execute(self, context: Context):
        pass

    def get_openlineage_facets_on_start(self) -> OperatorLineage:
        return OperatorLineage()

    def get_openlineage_facets_on_complete(self, task_instance) -> OperatorLineage:
        return OperatorLineage()

    def get_openlineage_facets_on_failure(self, task_instance) -> OperatorLineage:
        return OperatorLineage()
