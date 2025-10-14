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
"""Secrets backend implementations for execution time contexts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from airflow.secrets.base_secrets import BaseSecretsBackend

if TYPE_CHECKING:
    from airflow.sdk import Connection


class ExecutionAPISecretsBackend(BaseSecretsBackend):
    """Secrets backend routing requests through SUPERVISOR_COMMS."""

    def get_conn_value(self, conn_id: str) -> str | None:  # pragma: no cover - unused
        raise NotImplementedError("Use get_connection instead")

    def get_connection(self, conn_id: str):  # noqa: ANN401
        from airflow.sdk.execution_time.comms import ErrorResponse, GetConnection
        from airflow.sdk.execution_time.context import _process_connection_result_conn
        from airflow.sdk.execution_time.task_runner import SUPERVISOR_COMMS

        try:
            msg = SUPERVISOR_COMMS.send(GetConnection(conn_id=conn_id))
        except Exception:  # pragma: no cover - defensive
            return None

        if isinstance(msg, ErrorResponse):
            return None

        return _process_connection_result_conn(msg)

    def get_variable(self, key: str) -> str | None:
        from airflow.sdk.execution_time.comms import ErrorResponse, GetVariable
        from airflow.sdk.execution_time.task_runner import SUPERVISOR_COMMS

        try:
            msg = SUPERVISOR_COMMS.send(GetVariable(key=key))
        except Exception:  # pragma: no cover - defensive
            return None

        if isinstance(msg, ErrorResponse):
            return None

        return getattr(msg, "value", None)

