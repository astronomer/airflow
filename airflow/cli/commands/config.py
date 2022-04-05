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
"""Config sub-commands"""
import io

import pygments
import rich_click as click
from pygments.lexers.configs import IniLexer
from rich.console import Console

from airflow.cli import airflow_cmd, click_color
from airflow.configuration import conf
from airflow.utils.cli import should_use_colors
from airflow.utils.code_utils import get_terminal_formatter


@airflow_cmd.group()
@click.pass_context
def config(ctx):
    """Commands for the metadata database"""


@config.command('list')
@click.pass_context
@click_color
def show_config(ctx, color):
    """Show current application configuration"""
    with io.StringIO() as output:
        conf.write(output)
        code = output.getvalue()
        if should_use_colors(color):
            code = pygments.highlight(code=code, formatter=get_terminal_formatter(), lexer=IniLexer())
        console = Console()
        code = code.replace('[', r'\[')
        console.print(code, highlight=False)


@config.command('get-value')
@click.pass_context
@click.argument('section')
@click.argument('option')
def get_value(ctx, section, option):
    """Get one value from configuration

    section - The section of the configuration to get the value
    option - The opinion name of the configuration
    """
    if not conf.has_section(section):
        raise SystemExit(f'The section [{section}] is not found in config.')

    if not conf.has_option(section, option):
        raise SystemExit(f'The option [{section}/{option}] is not found in config.')
    console = Console()
    value = conf.get(section, option)
    console.print(value)
