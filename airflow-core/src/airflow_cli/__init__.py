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
"""Select database-free CLI initialization before importing the airflow package."""

from __future__ import annotations

import atexit
import os
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from tempfile import TemporaryDirectory


def is_no_db_run(arguments: list[str]) -> bool:
    """Recognize the explicit run mode, leaving argument validation to the CLI parser."""
    options = arguments[: arguments.index("--")] if "--" in arguments else arguments
    return options[:1] == ["run"] and any(option in {"--no-db", "--no-d"} for option in options)


@contextmanager
def isolate_no_db_environment() -> Iterator[None]:
    original = os.environ.copy()
    with TemporaryDirectory(prefix="airflow-no-db-cli-") as home:
        try:
            for name in list(os.environ):
                if name in {"AIRFLOW_HOME", "AIRFLOW_CONFIG"} or name.startswith(
                    ("AIRFLOW__", "_AIRFLOW", "__AIRFLOW")
                ):
                    if not name.startswith("AIRFLOW__SECRETS__BACKEND_KWARG__"):
                        del os.environ[name]
            os.environ.update(
                AIRFLOW_HOME=home,
                _AIRFLOW__LOCAL_NO_DB="1",
                AIRFLOW__CORE__LOAD_EXAMPLES="False",
            )
            yield
        finally:
            os.environ.clear()
            os.environ.update(original)


def prepare_module_execution() -> None:
    """Isolate ``python -m airflow`` before its package imports configuration."""
    if sys.argv[:1] != ["-m"] or not is_no_db_run(sys.argv[1:]):
        return
    original = sys.orig_argv
    if not any(
        flag == "-m" and module in {"airflow", "airflow.__main__"}
        for flag, module in zip(original, original[1:], strict=False)
    ):
        return
    with ExitStack() as cleanup:
        cleanup.enter_context(isolate_no_db_environment())
        atexit.register(cleanup.pop_all().close)


def main() -> None:
    if not is_no_db_run(sys.argv[1:]):
        from airflow.__main__ import main as airflow_main

        airflow_main()
        return
    with isolate_no_db_environment():
        from airflow.__main__ import main as airflow_main

        airflow_main()
