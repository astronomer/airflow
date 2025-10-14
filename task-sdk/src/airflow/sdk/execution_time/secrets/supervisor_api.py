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
"""Secrets backend for supervisor contexts using Execution API client."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from airflow.sdk.api.client import Client

from airflow.secrets.base_secrets import BaseSecretsBackend


class SupervisorAPIClientSecretsBackend(BaseSecretsBackend):
    """
    Secrets backend for supervisor contexts that uses the Execution API client directly.

    This is used in the worker supervisor process (parent of task runner) before
    SUPERVISOR_COMMS is available. It makes direct API calls via client.connections.get()
    instead of routing through inter-process communication.

    The supervisor needs this for remote logging connection retrieval in
    _get_remote_logging_conn().
    """

    def __init__(self, client: Client):
        super().__init__()
        self.client = client

    def get_connection(self, conn_id: str, *, deserialize_json: bool = False):
        """Fetch connection from Execution API via client."""
        from airflow.sdk.api.datamodels._generated import ConnectionResponse
        from airflow.sdk.definitions.connection import Connection
        from airflow.sdk.execution_time.comms import ConnectionResult

        try:
            conn = self.client.connections.get(conn_id)
            if isinstance(conn, ConnectionResponse):
                conn_result = ConnectionResult.from_conn_response(conn)
                # Convert ConnectionResult to SDK Connection
                return Connection(**conn_result.model_dump(exclude={"type"}, by_alias=True))
        except Exception:
            # Let other backends try
            return None

        return None

    def get_variable(self, key: str, *, deserialize_json: bool = False):
        """Variables not needed in supervisor context for remote logging."""
        return None

