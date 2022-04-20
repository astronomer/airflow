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
"""Connection sub-commands"""
import io
import json
import os
import warnings
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse, urlunparse

import rich_click as click
from rich.console import Console
from sqlalchemy.orm import exc

from airflow.cli import airflow_cmd, click_output, click_verbose
from airflow.cli.simple_table import AirflowConsole

# from airflow.cli.utils.console import console
from airflow.exceptions import AirflowNotFoundException
from airflow.hooks.base import BaseHook
from airflow.models import Connection
from airflow.secrets.local_filesystem import load_connections_dict
from airflow.utils import cli as cli_utils, yaml
from airflow.utils.cli import suppress_logs_and_warning_click_compatible
from airflow.utils.session import create_session

console = Console()

click_conn_id = click.argument(
    'conn-id',
    type=click.STRING,
)

click_conn_id_filter = click.option(
    '--conn-id',
    help='If passed, only items with the specified connection ID will be displayed',
)

click_conn_uri = click.option(
    '--conn-uri',
    help='Connection URI, required to add a connection without conn_type',
)

click_conn_json = click.option(
    '--conn-json',
    help='Connection JSON, required to add a connection using JSON representation',
)

click_conn_type = click.option(
    '--conn-type',
    help='Connection type, required to add a connection without conn_uri',
)

click_conn_description = click.option(
    '--conn-description',
    help='Connection description, optional when adding a connection',
)

click_format = click.option(
    '--format',
    help='Deprecated -- use `--file-format` instead. File format to use for the export.',
    type=click.Choice(['json', 'yaml', 'env']),
)

click_file_format = click.option(
    '--file-format', help='File format for the export', type=click.Choice(['json', 'yaml', 'env'])
)

click_conn_host = click.option(
    '--conn-host',
    help='Connection host, optional when adding a connection',
)

click_conn_login = click.option(
    '--conn-login',
    help='Connection login, optional when adding a connection',
)

click_conn_password = click.option(
    '--conn-password', help='Connection password, optional when adding a connection'
)

click_conn_schema = click.option(
    '--conn-schema',
    help='Connection schema, optional when adding a connection',
)

click_conn_port = click.option(
    '--conn-port',
    help='Connection port, optional when adding a connection',
)

click_conn_extra = click.option(
    '--conn-extra',
    help='Connection `Extra` field, optional when adding a connection',
)

click_serialization_format = click.option(
    '--serialization-format',
    help='When exporting as `.env` format, defines how connections should be serialized. Default is `uri`.',
    type=click.Choice(['json', 'uri']),
)

click_file_input = click.argument(
    'input',
    type=click.Path(exists=True),
)

click_file_output = click.argument(
    'output',
    type=click.File(mode='w', encoding='UTF-8'),
)


@airflow_cmd.group()
@click.pass_context
def connections(ctx):
    """Commands for managing connections"""


def _connection_mapper(conn: Connection) -> Dict[str, Any]:
    return {
        'id': conn.id,
        'conn_id': conn.conn_id,
        'conn_type': conn.conn_type,
        'description': conn.description,
        'host': conn.host,
        'schema': conn.schema,
        'login': conn.login,
        'password': conn.password,
        'port': conn.port,
        'is_encrypted': conn.is_encrypted,
        'is_extra_encrypted': conn.is_encrypted,
        'extra_dejson': conn.extra_dejson,
        'get_uri': conn.get_uri(),
    }


@connections.command('get')
@click.pass_context
@click_conn_id
@click_verbose
@click_output
@suppress_logs_and_warning_click_compatible
def connections_get(ctx, conn_id, verbose, output):
    """Get a connection."""
    try:
        conn = BaseHook.get_connection(conn_id)
    except AirflowNotFoundException:
        raise SystemExit("Connection not found.")
    AirflowConsole().print_as(
        data=[conn],
        output=output,
        mapper=_connection_mapper,
    )


@connections.command('list')
@click.pass_context
@click_verbose
@click_output
@click.argument('conn-id', required=False)
@suppress_logs_and_warning_click_compatible
def connections_list(ctx, verbose, output, conn_id=None):
    """Lists all connections at the command line"""
    with create_session() as session:
        query = session.query(Connection)
        if conn_id:
            query = query.filter(Connection.conn_id == conn_id)
        conns = query.all()

        AirflowConsole().print_as(
            data=conns,
            output=output,
            mapper=_connection_mapper,
        )


def _connection_to_dict(conn: Connection) -> dict:
    return dict(
        conn_type=conn.conn_type,
        description=conn.description,
        login=conn.login,
        password=conn.password,
        host=conn.host,
        port=conn.port,
        schema=conn.schema,
        extra=conn.extra,
    )


def _format_connections(conns: List[Connection], file_format: str, serialization_format: str) -> str:
    if serialization_format == 'json':
        serializer_func = lambda x: json.dumps(_connection_to_dict(x))
    elif serialization_format == 'uri':
        serializer_func = Connection.get_uri
    else:
        raise SystemExit(f"Received unexpected value for `--serialization-format`: {serialization_format!r}")
    if file_format == '.env':
        connections_env = ""
        for conn in conns:
            connections_env += f"{conn.conn_id}={serializer_func(conn)}\n"
        return connections_env

    connections_dict = {}
    for conn in conns:
        connections_dict[conn.conn_id] = _connection_to_dict(conn)

    if file_format == '.yaml':
        return yaml.dump(connections_dict)

    if file_format == '.json':
        return json.dumps(connections_dict, indent=2)

    return json.dumps(connections_dict)


def _is_stdout(fileio: io.TextIOWrapper) -> bool:
    return fileio.name == '<stdout>'


def _valid_uri(uri: str) -> bool:
    """Check if a URI is valid, by checking if both scheme and netloc are available"""
    uri_parts = urlparse(uri)
    return uri_parts.scheme != '' and uri_parts.netloc != ''


@connections.command('export')
@click.pass_context
@click_verbose
@click_file_format
@click_format
@click_serialization_format
@click_file_output
def connections_export(ctx, verbose, file_format, format, serialization_format, output):
    """Exports all connections to a file"""
    file_formats = ['.yaml', '.json', '.env']
    if format:
        warnings.warn("Option `--format` is deprecated.  Use `--file-format` instead.", DeprecationWarning)
    if format and file_format:
        raise SystemExit('Option `--format` is deprecated.  Use `--file-format` instead.')
    default_format = '.json'
    provided_file_format = None
    if format or file_format:
        provided_file_format = f".{(format or file_format).lower()}"

    file_is_stdout = _is_stdout(output)
    if file_is_stdout:
        filetype = provided_file_format or default_format
    elif provided_file_format:
        filetype = provided_file_format
    else:
        filetype = Path(output.name).suffix
        filetype = filetype.lower()
        if filetype not in file_formats:
            raise SystemExit(
                f"Unsupported file format. The file must have the extension {', '.join(file_formats)}."
            )

    if serialization_format and not filetype == '.env':
        raise SystemExit("Option `--serialization-format` may only be used with file type `env`.")

    with create_session() as session:
        connections = session.query(Connection).order_by(Connection.conn_id).all()

    msg = _format_connections(
        conns=connections,
        file_format=filetype,
        serialization_format=serialization_format or 'uri',
    )
    output.write(msg)
    if file_is_stdout:
        console.print("\nConnections successfully exported.")
    else:
        console.print(f"Connections successfully exported to {output.name}.")


alternative_conn_specs = ['conn_type', 'conn_host', 'conn_login', 'conn_password', 'conn_schema', 'conn_port']


@connections.command('add')
@click.pass_context
@click_conn_id
@click_conn_uri
@click_conn_json
@click_conn_type
@click_conn_extra
@click_conn_description
@click_conn_host
@click_conn_login
@click_conn_password
@click_conn_port
@click_conn_schema
@cli_utils.action_cli_click_compatible
def connections_add(
    ctx,
    conn_id,
    conn_uri,
    conn_json,
    conn_type,
    conn_extra,
    conn_description,
    conn_host,
    conn_login,
    conn_password,
    conn_port,
    conn_schema,
):
    """Adds new connection"""
    has_uri = bool(conn_uri)
    has_json = bool(conn_json)
    has_type = bool(conn_type)

    if not has_type and not (has_json or has_uri):
        raise SystemExit('Must supply either conn-uri or conn-json if not supplying conn-type')

    if has_json and has_uri:
        raise SystemExit('Cannot supply both conn-uri and conn-json')

    if has_uri or has_json:
        invalid_args = []
        if has_uri and not _valid_uri(conn_uri):
            raise SystemExit(f'The URI provided to --conn-uri is invalid: {conn_uri}')

        for arg in alternative_conn_specs:
            if eval(arg) is not None:
                invalid_args.append(arg)

        if has_json and conn_extra:
            invalid_args.append("--conn-extra")

        if invalid_args:
            raise SystemExit(
                "The following args are not compatible with "
                f"the --conn-{'uri' if has_uri else 'json'} flag: {invalid_args!r}"
            )

    if conn_uri:
        new_conn = Connection(conn_id=conn_id, description=conn_description, uri=conn_uri)
        if conn_extra is not None:
            new_conn.set_extra(conn_extra)
    elif conn_json:
        new_conn = Connection.from_json(conn_id=conn_id, value=conn_json)
        if not new_conn.conn_type:
            raise SystemExit('conn-json is invalid; must supply conn-type')
    else:
        new_conn = Connection(
            conn_id=conn_id,
            conn_type=conn_type,
            description=conn_description,
            host=conn_host,
            login=conn_login,
            password=conn_password,
            schema=conn_schema,
            port=conn_port,
        )
        if conn_extra is not None:
            new_conn.set_extra(conn_extra)

    with create_session() as session:
        if not session.query(Connection).filter(Connection.conn_id == new_conn.conn_id).first():
            session.add(new_conn)
            msg = 'Successfully added `conn_id`={conn_id} : {uri}'
            msg = msg.format(
                conn_id=new_conn.conn_id,
                uri=conn_uri
                or urlunparse(
                    (
                        new_conn.conn_type,
                        f"{new_conn.login or ''}:{'******' if new_conn.password else ''}@{new_conn.host or ''}:{new_conn.port or ''}",
                        new_conn.schema or '',
                        '',
                        '',
                        '',
                    )
                ),
            )
            console.print(msg)
        else:
            msg = f'A connection with `conn_id`={new_conn.conn_id} already exists.'
            raise SystemExit(msg)


@connections.command('delete')
@click.pass_context
@click_conn_id
@cli_utils.action_cli_click_compatible
def connections_delete(ctx, conn_id):
    """Deletes connection from DB"""
    with create_session() as session:
        try:
            to_delete = session.query(Connection).filter(Connection.conn_id == conn_id).one()
        except exc.NoResultFound:
            raise SystemExit(f'Did not find a connection with `conn_id`={conn_id}')
        except exc.MultipleResultsFound:
            raise SystemExit(f'Found more than one connection with `conn_id`={conn_id}')
        else:
            session.delete(to_delete)
            console.print(f"Successfully deleted connection with `conn_id`={to_delete.conn_id}")


@connections.command('import')
@click.pass_context
@click_file_input
@cli_utils.action_cli_click_compatible(check_db=False)
def connections_import(ctx, input):
    """Imports connections from a file"""
    if os.path.exists(input):
        _import_helper(input)
    else:
        raise SystemExit("Missing connections file.")


def _import_helper(file_path):
    """Load connections from a file and save them to the DB. On collision, skip."""
    connections_dict = load_connections_dict(file_path)
    with create_session() as session:
        for conn_id, conn in connections_dict.items():
            if session.query(Connection).filter(Connection.conn_id == conn_id).first():
                console.print(f'Could not import connection {conn_id}: connection already exists.')
                continue

            session.add(conn)
            session.commit()
            console.print(f'Imported connection {conn_id}')
