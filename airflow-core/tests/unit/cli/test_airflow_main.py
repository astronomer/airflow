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

import sys
from unittest import mock

import pytest

from airflow.__main__ import main

STANDALONE = "airflow.cli.commands.standalone_command.standalone"


@pytest.mark.parametrize(
    ("argv", "command", "writes_default_config"),
    [
        pytest.param(
            ["bootstrap", "demo"], "airflow.cli.commands.bootstrap_command.bootstrap", False, id="bootstrap"
        ),
        pytest.param(["run", "pipeline.py"], "airflow.cli.commands.run_command.run", False, id="run"),
        pytest.param(["standalone", "--project"], STANDALONE, False, id="standalone-project"),
        pytest.param(["standalone"], STANDALONE, True, id="standalone"),
    ],
)
@mock.patch("airflow.configuration.write_default_airflow_configuration_if_needed", autospec=True)
def test_default_config_is_written_only_for_commands_using_airflow_home(
    mock_write_default_config, argv, command, writes_default_config
):
    with (
        mock.patch(command, autospec=True) as mock_command,
        mock.patch.object(sys, "argv", ["airflow", *argv]),
    ):
        main()

    mock_command.assert_called_once()
    assert mock_write_default_config.called is writes_default_config
