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
"""Python DAG importer - delegates to DagBag for backward compatibility."""

from __future__ import annotations

from pathlib import Path

from airflow.dag_processing.importers.base import (
    AbstractDagImporter,
    DagImportError,
    DagImportResult,
)


class PythonDagImporter(AbstractDagImporter):
    """
    Importer for Python DAG files.

    Delegates to DagBag to preserve all existing behavior including
    signal handling, warnings capture, and import error formatting.
    """

    @classmethod
    def supported_extensions(cls) -> list[str]:
        # Empty string handles files without extension (backward compatibility)
        return [".py", ".zip", ""]

    def import_file(
        self,
        file_path: str | Path,
        *,
        bundle_path: Path | None = None,
        bundle_name: str | None = None,
        safe_mode: bool = True,
    ) -> DagImportResult:
        """Import DAGs from a Python file using DagBag."""
        from airflow.dag_processing.dagbag import DagBag

        filepath = str(file_path)
        relative_path = self.get_relative_path(filepath, bundle_path)

        bag = DagBag(
            dag_folder=filepath,
            bundle_path=bundle_path,
            bundle_name=bundle_name,
            include_examples=False,
            safe_mode=safe_mode,
        )

        result = DagImportResult(file_path=relative_path)
        result.dags.extend(bag.dags.values())

        for fileloc, error_msg in bag.import_errors.items():
            result.errors.append(DagImportError(file_path=fileloc, message=error_msg))

        return result
