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

from airflow.__main__ import main


@mock.patch("airflow.configuration.write_default_airflow_configuration_if_needed", autospec=True)
@mock.patch("airflow.cli.commands.run_command.run", autospec=True)
def test_run_command_does_not_write_default_config(mock_run, mock_write_default_config):
    with mock.patch.object(sys, "argv", ["airflow", "run", "pipeline.py"]):
        main()

    mock_run.assert_called_once()
    mock_write_default_config.assert_not_called()
