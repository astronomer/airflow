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

from unittest.mock import patch

import pytest
from sqlalchemy import or_

from airflow import models
from airflow.providers.mysql.transfers.s3_to_mysql import S3ToMySqlOperator
from airflow.utils.session import create_session

pytestmark = pytest.mark.db_test


class TestS3ToMySqlTransfer:
    @pytest.fixture(autouse=True)
    def setup_connections(self, create_connection_without_db):
        create_connection_without_db(
            models.Connection(
                conn_id="s3_test",
                conn_type="s3",
                schema="test",
                extra='{"aws_access_key_id": "aws_access_key_id", "aws_secret_access_key":'
                ' "aws_secret_access_key"}',
            )
        )
        create_connection_without_db(
            models.Connection(
                conn_id="mysql_test",
                conn_type="mysql",
                host="some.host.com",
                schema="test_db",
                login="user",
                password="password",
            )
        )

        self.s3_to_mysql_transfer_kwargs = {
            "aws_conn_id": "s3_test",
            "mysql_conn_id": "mysql_test",
            "s3_source_key": "test/s3_to_mysql_test.csv",
            "mysql_table": "mysql_table",
            "mysql_duplicate_key_handling": "IGNORE",
            "mysql_extra_options": """
                FIELDS TERMINATED BY ','
                IGNORE 1 LINES
            """,
            "mysql_local_infile": False,
            "task_id": "task_id",
            "dag": None,
        }

    @patch("airflow.providers.mysql.transfers.s3_to_mysql.S3Hook.download_file")
    @patch("airflow.providers.mysql.transfers.s3_to_mysql.MySqlHook.bulk_load_custom")
    @patch("airflow.providers.mysql.transfers.s3_to_mysql.os.remove")
    def test_execute(self, mock_remove, mock_bulk_load_custom, mock_download_file):
        S3ToMySqlOperator(**self.s3_to_mysql_transfer_kwargs).execute({})

        mock_download_file.assert_called_once_with(key=self.s3_to_mysql_transfer_kwargs["s3_source_key"])
        mock_bulk_load_custom.assert_called_once_with(
            table=self.s3_to_mysql_transfer_kwargs["mysql_table"],
            tmp_file=mock_download_file.return_value,
            duplicate_key_handling=self.s3_to_mysql_transfer_kwargs["mysql_duplicate_key_handling"],
            extra_options=self.s3_to_mysql_transfer_kwargs["mysql_extra_options"],
        )
        mock_remove.assert_called_once_with(mock_download_file.return_value)

    @patch("airflow.providers.mysql.transfers.s3_to_mysql.S3Hook.download_file")
    @patch("airflow.providers.mysql.transfers.s3_to_mysql.MySqlHook.bulk_load_custom")
    @patch("airflow.providers.mysql.transfers.s3_to_mysql.os.remove")
    def test_execute_exception(self, mock_remove, mock_bulk_load_custom, mock_download_file):
        mock_bulk_load_custom.side_effect = RuntimeError("Some exception occurred")

        with pytest.raises(RuntimeError, match="Some exception occurred"):
            S3ToMySqlOperator(**self.s3_to_mysql_transfer_kwargs).execute({})

        mock_download_file.assert_called_once_with(key=self.s3_to_mysql_transfer_kwargs["s3_source_key"])
        mock_bulk_load_custom.assert_called_once_with(
            table=self.s3_to_mysql_transfer_kwargs["mysql_table"],
            tmp_file=mock_download_file.return_value,
            duplicate_key_handling=self.s3_to_mysql_transfer_kwargs["mysql_duplicate_key_handling"],
            extra_options=self.s3_to_mysql_transfer_kwargs["mysql_extra_options"],
        )
        mock_remove.assert_called_once_with(mock_download_file.return_value)

    def teardown_method(self):
        with create_session() as session:
            (
                session.query(models.Connection)
                .filter(
                    or_(models.Connection.conn_id == "s3_test", models.Connection.conn_id == "mysql_test")
                )
                .delete()
            )
