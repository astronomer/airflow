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

import pytest

from airflow.sdk.definitions._internal.local_run_args import RUN_OPTION_DEFAULTS, merge_run_options


@pytest.mark.parametrize(
    ("given", "command_line"),
    [
        pytest.param(
            {"connections_file": "conns.yaml"},
            {"connections_file": "./conns.yaml"},
            id="same-path-written-apart",
        ),
        pytest.param({"task_ids": [["double", 1]]}, {"task_ids": [("double", 1)]}, id="map-index-as-a-list"),
    ],
)
def test_an_option_given_the_same_way_twice_is_taken(given, command_line):
    assert merge_run_options(given, command_line) == RUN_OPTION_DEFAULTS | command_line


def test_keyword_options_alone_are_not_held_to_the_command_lines_rules():
    given = {"include_downstream": True}

    assert merge_run_options(given, {}) == RUN_OPTION_DEFAULTS | given
