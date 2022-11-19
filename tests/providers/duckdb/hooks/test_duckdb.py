#
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
from unittest import mock

import pytest

from airflow.models import Connection
from airflow.providers.duckdb.hooks.duck_db import DuckdbHook


class TestDuckdbHook:
    @pytest.mark.parametrize(
        "return_value, expected",
        [
            (
                Connection(conn_id="duckdb_default", conn_type="duckdb"),
                "duckdb:///:memory:"
            ),
            (
                Connection(conn_id="duckdb_default", conn_type="duckdb", host="path/db.duckdb"),
                "duckdb:///path/db.duckdb"
            )
        ]
    )
    def test_get_conn(self, db, get_connection, return_value, expected):
        get_connection.return_value = return_value
        hook = DuckdbHook()
        conn = hook.get_conn()
        assert conn == expected

    @pytest.mark.parametrize(
        "return_value, expected",
        [
            (
                Connection(conn_id="duckdb_default", conn_type="duckdb"),
                ":memory:"
            ),
            (
                Connection(conn_id="duckdb_default", conn_type="duckdb", host="path/db.duckdb"),
                "path/db.duckdb"
            )
        ]
    )
    @mock.patch("airflow.hooks.base.BaseHook.get_connection")
    @mock.patch("duckdb.connect")
    def test_get_uri(self, db, get_connection, return_value, expected):
        get_connection.return_value = return_value
        hook = DuckdbHook()
        hook.get_uri()
        db.assert_called_once_with(expected)
