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

import io
import json
import re
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from airflow.cli import cli_parser
from airflow.cli.commands import connection
from airflow.cli.commands.connection import connections
from airflow.models import Connection
from airflow.utils.db import merge_conn
from airflow.utils.session import create_session, provide_session
from tests.test_utils.db import clear_db_connections


@pytest.fixture(scope='module', autouse=True)
def clear_connections():
    yield
    clear_db_connections(add_default_connections_back=False)


class TestCliGetConnection:
    parser = cli_parser.get_parser()

    def setup_method(self):
        clear_db_connections(add_default_connections_back=True)

    def test_cli_connection_get(self):
        runner = CliRunner()
        with redirect_stdout(io.StringIO()) as stdout:
            result = runner.invoke(connections, ["get", "google_cloud_default", "--output", "json"])
            assert result.exit_code == 0
            stdout = result.output
        assert "google-cloud-platform:///default" in stdout

    def test_cli_connection_get_invalid(self):
        runner = CliRunner()
        # with pytest.raises(SystemExit, match=re.escape("Connection not found.")):
        result = runner.invoke(connections, ["get", "INVALID"])
        assert result.exit_code == 1
        assert result.output.strip() == "Connection not found."


class TestCliListConnections:
    parser = cli_parser.get_parser()
    EXPECTED_CONS = [
        ('airflow_db', 'mysql'),
        ('google_cloud_default', 'google_cloud_platform'),
        ('http_default', 'http'),
        ('local_mysql', 'mysql'),
        ('mongo_default', 'mongo'),
        ('mssql_default', 'mssql'),
        ('mysql_default', 'mysql'),
        ('pinot_broker_default', 'pinot'),
        ('postgres_default', 'postgres'),
        ('presto_default', 'presto'),
        ('sqlite_default', 'sqlite'),
        ('trino_default', 'trino'),
        ('vertica_default', 'vertica'),
    ]

    def setup_method(self):
        clear_db_connections(add_default_connections_back=True)

    def test_cli_connections_list_as_json(self):
        runner = CliRunner()
        args = ["list", "--output", "json"]
        with redirect_stdout(io.StringIO()) as stdout:
            result = runner.invoke(connections, args)
            assert result.exit_code == 0
            stdout = result.output

        for conn_id, conn_type in self.EXPECTED_CONS:
            assert conn_type in stdout
            assert conn_id in stdout

    def test_cli_connections_filter_conn_id(self):
        runner = CliRunner()
        args = ["list", "--output", "json", 'http_default']

        with redirect_stdout(io.StringIO()) as stdout:
            result = runner.invoke(connections, args)

            assert result.exit_code == 0
            stdout = result.output
        assert "http_default" in stdout


class TestCliExportConnections:
    parser = cli_parser.get_parser()

    def setup_method(self):
        clear_db_connections(add_default_connections_back=False)
        merge_conn(
            Connection(
                conn_id="airflow_db",
                conn_type="mysql",
                description="mysql conn description",
                host="mysql",
                login="root",
                password="plainpassword",
                schema="airflow",
            ),
        )
        merge_conn(
            Connection(
                conn_id="druid_broker_default",
                conn_type="druid",
                description="druid-broker conn description",
                host="druid-broker",
                port=8082,
                extra='{"endpoint": "druid/v2/sql"}',
            ),
        )

    def test_cli_connections_export_should_return_error_for_invalid_command(self):
        # with pytest.raises(SystemExit):
        args = ["export"]
        runner = CliRunner()
        result = runner.invoke(connections, args)
        assert result.exit_code == 2
        # self.parser.parse_args(["connections", "export"])

    def test_cli_connections_export_should_return_error_for_invalid_format(self):
        # with pytest.raises(SystemExit):
        args = ["export", "--format", "invalid", "/path/to/file"]
        runner = CliRunner()
        result = runner.invoke(connections, args)
        assert result.exit_code == 2
        # self.parser.parse_args(["connections", "export", "--format", "invalid", "/path/to/file"])

    def test_cli_connections_export_should_return_error_for_invalid_export_format(self, tmp_path):
        runner = CliRunner()
        output_filepath = str(tmp_path / 'connections.invalid')
        args = ["export", output_filepath]
        result = runner.invoke(connections, args)
        assert result.exit_code == 1
        assert 'Unsupported file format' in result.stdout

    @mock.patch.object(connection, 'create_session')
    def test_cli_connections_export_should_raise_error_if_create_session_fails(
        self, mock_create_session, tmp_path
    ):
        runner = CliRunner()
        output_filepath = str(tmp_path / 'connections.json')

        def my_side_effect():
            raise Exception("dummy exception")

        mock_create_session.side_effect = my_side_effect
        args = ["export", output_filepath]
        result = runner.invoke(connections, args)
        assert result.exit_code == 1
        assert 'dummy exception' in str(result.exception)

    @mock.patch.object(connection, 'create_session')
    def test_cli_connections_export_should_raise_error_if_fetching_connections_fails(
        self, mock_session, tmp_path
    ):
        output_filepath = str(tmp_path / 'connections.json')
        runner = CliRunner()

        def my_side_effect(_):
            raise Exception("dummy exception")

        mock_session.return_value.__enter__.return_value.query.return_value.order_by.side_effect = (
            my_side_effect
        )
        args = ["export", output_filepath]
        result = runner.invoke(connections, args)
        assert result.exit_code == 1
        assert 'dummy exception' in str(result.exception)

    @mock.patch.object(connection, 'create_session')
    def test_cli_connections_export_should_not_raise_error_if_connections_is_empty(
        self, mock_session, tmp_path
    ):
        runner = CliRunner()
        output_filepath = str(tmp_path / 'connections.json')
        mock_session.return_value.__enter__.return_value.query.return_value.all.return_value = []
        args = ["export", output_filepath]
        runner.invoke(connections, args)
        assert Path(output_filepath).read_text() == '{}'

    def test_cli_connections_export_should_export_as_json(self, tmp_path):
        runner = CliRunner()
        output_filepath = str(tmp_path / 'connections.json')
        args = ["export", output_filepath]
        runner.invoke(connections, args)
        expected_connections = {
            "airflow_db": {
                "conn_type": "mysql",
                "description": "mysql conn description",
                "host": "mysql",
                "login": "root",
                "password": "plainpassword",
                "schema": "airflow",
                "port": None,
                "extra": None,
            },
            "druid_broker_default": {
                "conn_type": "druid",
                "description": "druid-broker conn description",
                "host": "druid-broker",
                "login": None,
                "password": None,
                "schema": None,
                "port": 8082,
                "extra": "{\"endpoint\": \"druid/v2/sql\"}",
            },
        }
        assert json.loads(Path(output_filepath).read_text()) == expected_connections

    def test_cli_connections_export_should_export_as_yaml(self, tmp_path):
        runner = CliRunner()
        output_filepath = str(tmp_path / 'connections.yaml')
        args = ["export", output_filepath]
        runner.invoke(connections, args)
        expected_connections = (
            "airflow_db:\n"
            "  conn_type: mysql\n"
            "  description: mysql conn description\n"
            "  extra: null\n"
            "  host: mysql\n"
            "  login: root\n"
            "  password: plainpassword\n"
            "  port: null\n"
            "  schema: airflow\n"
            "druid_broker_default:\n"
            "  conn_type: druid\n"
            "  description: druid-broker conn description\n"
            "  extra: \'{\"endpoint\": \"druid/v2/sql\"}\'\n"
            "  host: druid-broker\n"
            "  login: null\n"
            "  password: null\n"
            "  port: 8082\n"
            "  schema: null\n"
        )
        # pytest.set_trace()
        assert Path(output_filepath).read_text() == expected_connections

    @pytest.mark.parametrize(
        'serialization_format, expected',
        [
            (
                'uri',
                [
                    "airflow_db=mysql://root:plainpassword@mysql/airflow",
                    "druid_broker_default=druid://druid-broker:8082?endpoint=druid%2Fv2%2Fsql",
                ],
            ),
            (
                None,  # tests that default is URI
                [
                    "airflow_db=mysql://root:plainpassword@mysql/airflow",
                    "druid_broker_default=druid://druid-broker:8082?endpoint=druid%2Fv2%2Fsql",
                ],
            ),
            (
                'json',
                [
                    'airflow_db={"conn_type": "mysql", "description": "mysql conn description", '
                    '"login": "root", "password": "plainpassword", "host": "mysql", "port": null, '
                    '"schema": "airflow", "extra": null}',
                    'druid_broker_default={"conn_type": "druid", "description": "druid-broker conn '
                    'description", "login": null, "password": null, "host": "druid-broker", "port": 8082, '
                    '"schema": null, "extra": "{\\"endpoint\\": \\"druid/v2/sql\\"}"}',
                ],
            ),
        ],
    )
    def test_cli_connections_export_should_export_as_env(self, serialization_format, expected, tmp_path):
        """
        When exporting with env file format, we should
        """
        output_filepath = str(tmp_path / 'connections.env')
        args_input = ["export", output_filepath]
        if serialization_format:
            args_input = [*args_input, '--serialization-format', serialization_format]
        runner = CliRunner()
        runner.invoke(connections, args_input)
        assert Path(output_filepath).read_text().splitlines() == expected

    def test_cli_connections_export_should_export_as_env_for_uppercase_file_extension(self, tmp_path):
        output_filepath = str(tmp_path / 'connections.ENV')
        args = ["export", output_filepath]
        runner = CliRunner()
        runner.invoke(connections, args)
        expected_connections = [
            "airflow_db=mysql://root:plainpassword@mysql/airflow",
            "druid_broker_default=druid://druid-broker:8082?endpoint=druid%2Fv2%2Fsql",
        ]

        assert Path(output_filepath).read_text().splitlines() == expected_connections

    def test_cli_connections_export_should_force_export_as_specified_format(self, tmp_path):
        output_filepath = str(tmp_path / 'connections.yaml')
        args = [
            "export",
            output_filepath,
            "--format",
            "json",
        ]
        runner = CliRunner()
        runner.invoke(connections, args)
        expected_connections = {
            "airflow_db": {
                "conn_type": "mysql",
                "description": "mysql conn description",
                "host": "mysql",
                "login": "root",
                "password": "plainpassword",
                "schema": "airflow",
                "port": None,
                "extra": None,
            },
            "druid_broker_default": {
                "conn_type": "druid",
                "description": "druid-broker conn description",
                "host": "druid-broker",
                "login": None,
                "password": None,
                "schema": None,
                "port": 8082,
                "extra": "{\"endpoint\": \"druid/v2/sql\"}",
            },
        }
        assert json.loads(Path(output_filepath).read_text()) == expected_connections


TEST_URL = "postgresql://airflow:airflow@host:5432/airflow"
TEST_JSON = json.dumps(
    {
        "conn_type": "postgres",
        "login": "airflow",
        "password": "airflow",
        "host": "host",
        "port": 5432,
        "schema": "airflow",
        "description": "new0-json description",
    }
)


class TestCliAddConnections:
    parser = cli_parser.get_parser()

    def setup_method(self):
        clear_db_connections(add_default_connections_back=False)

    @pytest.mark.parametrize(
        'cmd, expected_output, expected_conn',
        [
            (
                [
                    "add",
                    "new0-json",
                    f"--conn-json={TEST_JSON}",
                ],
                "Successfully added `conn_id`=new0-json : postgres://airflow:******@host:5432/airflow",
                {
                    "conn_type": "postgres",
                    "description": "new0-json description",
                    "host": "host",
                    "is_encrypted": True,
                    "is_extra_encrypted": False,
                    "login": "airflow",
                    "port": 5432,
                    "schema": "airflow",
                },
            ),
            (
                [
                    "add",
                    "new0",
                    f"--conn-uri={TEST_URL}",
                    "--conn-description=new0 description",
                ],
                "Successfully added `conn_id`=new0 : postgresql://airflow:airflow@host:5432/airflow",
                {
                    "conn_type": "postgres",
                    "description": "new0 description",
                    "host": "host",
                    "is_encrypted": True,
                    "is_extra_encrypted": False,
                    "login": "airflow",
                    "port": 5432,
                    "schema": "airflow",
                },
            ),
            (
                [
                    "add",
                    "new1",
                    f"--conn-uri={TEST_URL}",
                    "--conn-description=new1 description",
                ],
                "Successfully added `conn_id`=new1 : postgresql://airflow:airflow@host:5432/airflow",
                {
                    "conn_type": "postgres",
                    "description": "new1 description",
                    "host": "host",
                    "is_encrypted": True,
                    "is_extra_encrypted": False,
                    "login": "airflow",
                    "port": 5432,
                    "schema": "airflow",
                },
            ),
            (
                [
                    "add",
                    "new2",
                    f"--conn-uri={TEST_URL}",
                    "--conn-extra",
                    "{'extra': 'yes'}",
                ],
                "Successfully added `conn_id`=new2 : postgresql://airflow:airflow@host:5432/airflow",
                {
                    "conn_type": "postgres",
                    "description": None,
                    "host": "host",
                    "is_encrypted": True,
                    "is_extra_encrypted": True,
                    "login": "airflow",
                    "port": 5432,
                    "schema": "airflow",
                },
            ),
            (
                [
                    "add",
                    "new3",
                    f"--conn-uri={TEST_URL}",
                    "--conn-extra",
                    "{'extra': 'yes'}",
                    "--conn-description",
                    "new3 description",
                ],
                "Successfully added `conn_id`=new3 : postgresql://airflow:airflow@host:5432/airflow",
                {
                    "conn_type": "postgres",
                    "description": "new3 description",
                    "host": "host",
                    "is_encrypted": True,
                    "is_extra_encrypted": True,
                    "login": "airflow",
                    "port": 5432,
                    "schema": "airflow",
                },
            ),
            (
                [
                    "add",
                    "new4",
                    "--conn-type=hive_metastore",
                    "--conn-login=airflow",
                    "--conn-password=airflow",
                    "--conn-host=host",
                    "--conn-port=9083",
                    "--conn-schema=airflow",
                    "--conn-description=  new4 description  ",
                ],
                "Successfully added `conn_id`=new4 : hive_metastore://airflow:******@host:9083/airflow",
                {
                    "conn_type": "hive_metastore",
                    "description": "  new4 description  ",
                    "host": "host",
                    "is_encrypted": True,
                    "is_extra_encrypted": False,
                    "login": "airflow",
                    "port": 9083,
                    "schema": "airflow",
                },
            ),
            (
                [
                    "add",
                    "new5",
                    "--conn-uri",
                    "",
                    "--conn-type=google_cloud_platform",
                    "--conn-extra",
                    "{'extra': 'yes'}",
                    "--conn-description=new5 description",
                ],
                "Successfully added `conn_id`=new5 : google_cloud_platform://:@:",
                {
                    "conn_type": "google_cloud_platform",
                    "description": "new5 description",
                    "host": None,
                    "is_encrypted": False,
                    "is_extra_encrypted": True,
                    "login": None,
                    "port": None,
                    "schema": None,
                },
            ),
        ],
    )
    def test_cli_connection_add(self, cmd, expected_output, expected_conn):
        runner = CliRunner()
        result = runner.invoke(connections, cmd)
        expected_key_message, expected_value_message = expected_output.split(' : ')
        key_message, value_message = result.output.strip().split(' : ')
        assert expected_key_message.strip() == key_message.strip()
        assert expected_value_message.strip() == value_message.strip()

        conn_id = cmd[1]
        with create_session() as session:
            comparable_attrs = [
                "conn_type",
                "description",
                "host",
                "is_encrypted",
                "is_extra_encrypted",
                "login",
                "port",
                "schema",
            ]
            current_conn = session.query(Connection).filter(Connection.conn_id == conn_id).first()
            assert expected_conn == {attr: getattr(current_conn, attr) for attr in comparable_attrs}

    def test_cli_connections_add_duplicate(self):
        conn_id = "to_be_duplicated"
        cmd = ["add", conn_id, f"--conn-uri={TEST_URL}"]
        runner = CliRunner()
        runner.invoke(connections, cmd)

        result = runner.invoke(connections, cmd)
        assert f"A connection with `conn_id`={conn_id} already exists" in result.output.strip()

    def test_cli_connections_add_delete_with_missing_parameters(self):
        # Attempt to add without providing conn_uri
        cmd = ["add", "new1"]
        runner = CliRunner()
        result = runner.invoke(connections, cmd)
        assert "Must supply either conn-uri or conn-json if not supplying conn-type" in result.output.strip()

    def test_cli_connections_add_json_invalid_args(self):
        """can't supply extra and json"""
        cmd = ["add", "new1", f"--conn-json={TEST_JSON}", "--conn-extra='hi'"]
        runner = CliRunner()
        result = runner.invoke(connections, cmd)
        assert re.match(
            r"The following args are not compatible with the --conn-json flag: \['--conn-extra'\]",
            result.output,
        )

    def test_cli_connections_add_json_and_uri(self):
        """can't supply both uri and json"""
        cmd = ["add", "new1", f"--conn-uri={TEST_URL}", f"--conn-json={TEST_JSON}"]
        runner = CliRunner()
        result = runner.invoke(connections, cmd)
        assert re.match("Cannot supply both conn-uri and conn-json", result.output)

    def test_cli_connections_add_invalid_uri(self):
        # Attempt to add with invalid uri
        cmd = ["add", "new1", f"--conn-uri={'nonsense_uri'}"]
        runner = CliRunner()
        result = runner.invoke(connections, cmd)
        assert re.match(r"The URI provided to --conn-uri is invalid: nonsense_uri", result.output)


class TestCliDeleteConnections:
    parser = cli_parser.get_parser()

    def setup_method(self):
        clear_db_connections(add_default_connections_back=False)

    @provide_session
    def test_cli_delete_connections(self, session=None):
        merge_conn(
            Connection(
                conn_id="new1",
                conn_type="mysql",
                description="mysql description",
                host="mysql",
                login="root",
                password="",
                schema="airflow",
            ),
            session=session,
        )
        # Delete connections
        with redirect_stdout(io.StringIO()) as stdout:
            cmd = ["delete", "new1"]
            runner = CliRunner()
            result = runner.invoke(connections, cmd)
            stdout = result.output
        # Check deletion stdout
        assert "Successfully deleted connection with `conn_id`=new1" in stdout

        # Check deletions
        result = session.query(Connection).filter(Connection.conn_id == "new1").first()

        assert result is None

    def test_cli_delete_invalid_connection(self):
        cmd = ["delete", "fake"]
        runner = CliRunner()
        result = runner.invoke(connections, cmd)
        assert result.exit_code == 1
        assert "Did not find a connection with `conn_id`=fake" in str(result.exception)


class TestCliImportConnections:
    parser = cli_parser.get_parser()

    def setup_method(self):
        clear_db_connections(add_default_connections_back=False)

    @mock.patch('os.path.exists')
    def test_cli_connections_import_should_return_error_if_file_does_not_exist(self, mock_exists):
        mock_exists.return_value = False
        filepath = '/does/not/exist.json'
        cmd = ["import", filepath]
        runner = CliRunner()
        result = runner.invoke(connections, cmd)
        assert result.exit_code == 2

    @pytest.mark.parametrize('filepath', ["sample.jso", "sample.environ"])
    @mock.patch('os.path.exists')
    def test_cli_connections_import_should_return_error_if_file_format_is_invalid(
        self, mock_exists, filepath, tmp_path
    ):
        mock_exists.return_value = True
        test_path = tmp_path / filepath
        open(test_path, 'a').close()
        runner = CliRunner()
        args = ["import", str(test_path)]
        result = runner.invoke(connections, args)
        assert result.exit_code == 1
        assert 'Unsupported file format' in str(result.exception)

    @mock.patch('airflow.secrets.local_filesystem._parse_secret_file')
    @mock.patch('os.path.exists')
    def test_cli_connections_import_should_load_connections(
        self, mock_exists, mock_parse_secret_file, tmp_path
    ):
        mock_exists.return_value = True

        # Sample connections to import
        expected_connections = {
            "new0": {
                "conn_type": "postgres",
                "description": "new0 description",
                "host": "host",
                "login": "airflow",
                "password": "password",
                "port": 5432,
                "schema": "airflow",
                "extra": "test",
            },
            "new1": {
                "conn_type": "mysql",
                "description": "new1 description",
                "host": "host",
                "login": "airflow",
                "password": "password",
                "port": 3306,
                "schema": "airflow",
                "extra": "test",
            },
        }

        # We're not testing the behavior of _parse_secret_file, assume it successfully reads JSON, YAML or env
        mock_parse_secret_file.return_value = expected_connections
        test_path = tmp_path / "sample.json"
        open(test_path, 'a').close()
        cmd = ["import", str(test_path)]
        runner = CliRunner()
        runner.invoke(connections, cmd)

        # Verify that the imported connections match the expected, sample connections
        with create_session() as session:
            current_conns = session.query(Connection).all()

            comparable_attrs = [
                "conn_id",
                "conn_type",
                "description",
                "host",
                "login",
                "password",
                "port",
                "schema",
                "extra",
            ]

            current_conns_as_dicts = {
                current_conn.conn_id: {attr: getattr(current_conn, attr) for attr in comparable_attrs}
                for current_conn in current_conns
            }
            assert expected_connections == current_conns_as_dicts

    @provide_session
    @mock.patch('airflow.secrets.local_filesystem._parse_secret_file')
    @mock.patch('os.path.exists')
    def test_cli_connections_import_should_not_overwrite_existing_connections(
        self,
        mock_exists,
        mock_parse_secret_file,
        tmp_path,
        session=None,
    ):
        mock_exists.return_value = True

        # Add a pre-existing connection "new3"
        merge_conn(
            Connection(
                conn_id="new3",
                conn_type="mysql",
                description="original description",
                host="mysql",
                login="root",
                password="password",
                schema="airflow",
            ),
            session=session,
        )

        # Sample connections to import, including a collision with "new3"
        expected_connections = {
            "new2": {
                "conn_type": "postgres",
                "description": "new2 description",
                "host": "host",
                "login": "airflow",
                "password": "password",
                "port": 5432,
                "schema": "airflow",
                "extra": "test",
            },
            "new3": {
                "conn_type": "mysql",
                "description": "updated description",
                "host": "host",
                "login": "airflow",
                "password": "new password",
                "port": 3306,
                "schema": "airflow",
                "extra": "test",
            },
        }

        # We're not testing the behavior of _parse_secret_file, assume it successfully reads JSON, YAML or env
        mock_parse_secret_file.return_value = expected_connections

        with redirect_stdout(io.StringIO()) as stdout:
            test_path = tmp_path / "sample.json"
            open(test_path, 'a').close()
            cmd = ["import", str(test_path)]
            runner = CliRunner()
            result = runner.invoke(connections, cmd)
            stdout = result.output
            assert 'Could not import connection new3: connection already exists.' in stdout

        # Verify that the imported connections match the expected, sample connections
        current_conns = session.query(Connection).all()

        comparable_attrs = [
            "conn_id",
            "conn_type",
            "description",
            "host",
            "login",
            "password",
            "port",
            "schema",
            "extra",
        ]

        current_conns_as_dicts = {
            current_conn.conn_id: {attr: getattr(current_conn, attr) for attr in comparable_attrs}
            for current_conn in current_conns
        }
        assert current_conns_as_dicts['new2'] == expected_connections['new2']

        # The existing connection's description should not have changed
        assert current_conns_as_dicts['new3']['description'] == 'original description'
