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
"""Variable subcommands"""
import json
import os
from json import JSONDecodeError

import rich_click as click

from airflow.cli.simple_table import AirflowConsole
from airflow.models import Variable
from airflow.utils import cli as cli_utils
from airflow.utils.cli import suppress_logs_and_warning_click_compatible
from airflow.utils.session import create_session
from airflow.cli import airflow_cmd, click_dry_run, click_verbose, click_yes, click_output

click_json = click.option(
    '-j',
    '--json',
    help="Deserialize JSON variable"
)

click_default = click.option(
    '-d',
    '--default',
    help='Default value returned if variable does not exist'
)

click_key = click.argument(
    'key',
)

click_value = click.argument(
    'value',
)

click_variable_output = click.argument(
    'output',
    type=click.File(mode='w', encoding='UTF-8'),
)

click_variable_file = click.argument(
    'files',
    type=click.Path(exists=True),
)

@airflow_cmd.group()
@click.pass_context
def variables(ctx):
    pass

@suppress_logs_and_warning_click_compatible
@variables.command('list')
@click.pass_context
@click_output
def variables_list(ctx, output):
    """Displays all of the variables"""
    with create_session() as session:
        variables = session.query(Variable)
    AirflowConsole().print_as(data=variables, output=output, mapper=lambda x: {"key": x.key})


@suppress_logs_and_warning_click_compatible
@variables.command('get')
@click.pass_context
@click_key
@click_json
@click_default
def variables_get(ctx, key, json, default):
    """Displays variable by a given name"""
    try:
        if default is None:
            var = Variable.get(key, deserialize_json=json)
            print(var)
        else:
            var = Variable.get(key, deserialize_json=json, default_var=default)
            print(var)
    except (ValueError, KeyError) as e:
        raise SystemExit(str(e).strip("'\""))


@cli_utils.action_cli_click_compatible
@variables.command('set')
@click.pass_context
@click_key
@click_value
@click_json
def variables_set(ctx, key, value, json):
    """Creates new variable with a given name and value"""
    Variable.set(key, value, serialize_json=json)
    print(f"Variable {key} created")


@cli_utils.action_cli_click_compatible
@variables.command('delete')
@click.pass_context
@click_key
def variables_delete(ctx, key):
    """Deletes variable by a given name"""
    Variable.delete(key)
    print(f"Variable {key} deleted")


@cli_utils.action_cli_click_compatible
@variables.command('import')
@click.pass_context
@click_variable_file
def variables_import(ctx, files):
    """Imports variables from a given file"""
    if os.path.exists(files):
        _import_helper(files)
    else:
        raise SystemExit("Missing variables file.")


@variables.command('export')
@click.pass_context
@click_variable_output
def variables_export(ctx, output):
    """Exports all of the variables to the file"""
    _variable_export_helper(output)


def _import_helper(filepath):
    """Helps import variables from the file"""
    with open(filepath) as varfile:
        data = varfile.read()

    try:
        var_json = json.loads(data)
    except JSONDecodeError:
        raise SystemExit("Invalid variables file.")
    else:
        suc_count = fail_count = 0
        for k, v in var_json.items():
            try:
                Variable.set(k, v, serialize_json=not isinstance(v, str))
            except Exception as e:
                print(f'Variable import failed: {repr(e)}')
                fail_count += 1
            else:
                suc_count += 1
        print(f"{suc_count} of {len(var_json)} variables successfully updated.")
        if fail_count:
            print(f"{fail_count} variable(s) failed to be updated.")


def _variable_export_helper(filepath):
    """Helps export all of the variables to the file"""
    var_dict = {}
    with create_session() as session:
        qry = session.query(Variable).all()

        data = json.JSONDecoder()
        for var in qry:
            try:
                val = data.decode(var.val)
            except Exception:
                val = var.val
            var_dict[var.key] = val
    filepath.write(json.dumps(var_dict, sort_keys=True, indent=4))
    # with open(filepath, 'w') as varfile:
    #     varfile.write(json.dumps(var_dict, sort_keys=True, indent=4))
    print(f"{len(var_dict)} variables successfully exported to {filepath.name}")
