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

import duckdb

from airflow.providers.common.sql.hooks.sql import DbApiHook


class DuckdbHook(DbApiHook):
    """Interact with DuckDB."""

    onn_name_attr = "duckdb_conn_id"
    default_conn_name = "duckdb_default"
    conn_type = "duckdb"
    hook_name = "Duckdb"
    placeholder = "?"

    def get_conn(self):
        conn_id = getattr(self, self.conn_name_attr)
        conn = self.get_connection(conn_id)
        if not conn.host:
            return duckdb.connect(":memory:")
        return duckdb.connect(conn.host)

    def get_uri(self) -> str:
        """Override DbApiHook get_uri method for get_sqlalchemy_engine()"""
        conn_id = getattr(self, self.conn_name_attr)
        conn = self.get_connection(conn_id)
        if not conn.host:
            return "duckdb:///:memory:"
        return f"duckdb:///{conn.host}"
