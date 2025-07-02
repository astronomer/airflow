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
import sys
from importlib.abc import MetaPathFinder
from importlib.util import spec_from_file_location
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import ModuleType

class NonVendoredAirflowCommonFinder(MetaPathFinder):
    """
    A Python import PathFinder designed to load "airflow" and it's submodules from
    `airflow_task_sdk.shims.airflow` instead
    """

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ):
        if fullname != f"{__name__}.airflow_common":
            return

        for dir in sys.path:
            if not dir.endswith("airflow-common/src"):
                continue
            spec = spec_from_file_location(fullname, os.path.join(dir, "airflow_common", "__init__.py"))
            if spec:
                return spec


def _install_loader():
    # Add a new module Finder to find the imports when the vendored sources aren't found. Since we add it at the end, this will only be hit when the _vendor/ folder is
    # not already populated. I.e. when we are running in a repo checkout
    sys.meta_path.append(NonVendoredAirflowCommonFinder())


_install_loader()
