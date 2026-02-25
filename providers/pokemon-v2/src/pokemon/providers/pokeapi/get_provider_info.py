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

"""Provider info entrypoint for Pokémon provider."""

from __future__ import annotations

from pathlib import Path

import yaml


def get_provider_info() -> dict:
    """
    Return provider information by reading provider.yaml.

    This function is called by Airflow's provider discovery mechanism.
    """
    # provider.yaml should be in the package root (pokemon/)
    provider_yaml_path = Path(__file__).parent.parent.parent / "provider.yaml"

    with provider_yaml_path.open() as f:
        provider_info = yaml.safe_load(f)

    return provider_info
