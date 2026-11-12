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
"""
What ``airflow run`` and ``airflow standalone --project`` exit with, by what the user has to fix.

The tasks, the command, the Dag file, or the project's setup.
"""

from __future__ import annotations

import sys
from typing import NoReturn

EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_DAG_FILE = 3
EXIT_CONFIG = 4
EXIT_INTERRUPTED = 130


def exit_with_error(message: str, code: int) -> NoReturn:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(code)
