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
"""Secrets role definitions for backend chain selection."""

from __future__ import annotations

from enum import Enum

__all__ = ["SecretsRole", "ROLE_TO_SECRETS_CHAIN"]


class SecretsRole(Enum):
    """Execution contexts for secrets backend selection."""

    # Worker-side contexts
    WORKER_TASK_RUNNER = "task_runner"  # Child process with SUPERVISOR_COMMS
    WORKER_SUPERVISOR = "supervisor"  # Parent process before SUPERVISOR_COMMS exists

    # Server-side contexts with direct database access
    API_SERVER = "api_server"
    SCHEDULER = "scheduler"

    # Hybrid contexts that behave like servers via InProcessExecutionAPI
    DAG_PROCESSOR = "dag_processor"
    TRIGGERER = "triggerer"


# Populated by airflow.secrets.__init__ to avoid circular imports
ROLE_TO_SECRETS_CHAIN: dict[SecretsRole, list[str]] = {}


