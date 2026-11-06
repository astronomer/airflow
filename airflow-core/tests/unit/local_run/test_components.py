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

import os
import signal
import threading
from unittest import mock

import pytest

from airflow.local_run import components


@mock.patch.object(components, "exit_with_parent", autospec=True)
@mock.patch.object(components, "run_scheduler", autospec=True)
def test_scheduler_is_the_projects_own(mock_run_scheduler, mock_exit_with_parent):
    components.main(["scheduler"])

    mock_run_scheduler.assert_called_once_with()
    mock_exit_with_parent.assert_called_once_with(os.getppid())


@pytest.mark.parametrize(
    ("name", "argv"),
    [
        pytest.param("dag-processor", ["dag-processor"], id="dag-processor"),
        pytest.param("triggerer", ["triggerer", "--skip-serve-logs"], id="triggerer"),
    ],
)
@mock.patch.object(components, "exit_with_parent", autospec=True)
@mock.patch.object(components, "get_parser", autospec=True)
def test_other_components_run_their_own_command(mock_get_parser, mock_exit_with_parent, name, argv):
    components.main([name])

    parse_args = mock_get_parser.return_value.parse_args
    parse_args.assert_called_once_with(argv)
    parse_args.return_value.func.assert_called_once_with(parse_args.return_value)


@mock.patch.object(os, "kill", autospec=True)
def test_component_stops_once_the_server_has_gone(mock_kill):
    stopped = threading.Event()
    mock_kill.side_effect = lambda pid, signum: stopped.set()

    # No process has this parent, as none has once its parent has gone.
    components.exit_with_parent(-1, interval=0.01)

    assert stopped.wait(timeout=5)
    mock_kill.assert_called_once_with(os.getpid(), signal.SIGTERM)
