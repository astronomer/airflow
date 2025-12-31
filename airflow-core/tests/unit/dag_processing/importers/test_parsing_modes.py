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
"""Tests for ParsingMode enum."""

from __future__ import annotations

from airflow.dag_processing.bundles.base import ParsingMode


class TestParsingMode:
    """Test the ParsingMode enum."""

    def test_parsing_mode_values(self):
        assert ParsingMode.CONTINUOUS.value == "continuous"
        assert ParsingMode.ON_CHANGE.value == "on_change"
        assert ParsingMode.API_ONLY.value == "api_only"

    def test_parsing_mode_is_string(self):
        assert isinstance(ParsingMode.CONTINUOUS, str)
        assert ParsingMode.CONTINUOUS == "continuous"

    def test_parsing_mode_from_string(self):
        assert ParsingMode("continuous") == ParsingMode.CONTINUOUS
        assert ParsingMode("on_change") == ParsingMode.ON_CHANGE
        assert ParsingMode("api_only") == ParsingMode.API_ONLY
