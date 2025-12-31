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
"""Abstract base class for DAG importers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from airflow.sdk import DAG


@dataclass
class DagImportError:
    """
    Structured error information for DAG import failures.

    Provides detailed error context including line numbers for formats that support it.
    """

    file_path: str
    """Path to the file that caused the error."""

    message: str
    """Human-readable error message."""

    error_type: str = "import"
    """Type of error: 'syntax', 'schema', 'reference', 'import'."""

    line_number: int | None = None
    """Line number where the error occurred (if available)."""

    column_number: int | None = None
    """Column number where the error occurred (if available)."""

    context: str | None = None
    """Snippet of code/content around the error location."""

    suggestion: str | None = None
    """Suggested fix for the error."""

    stacktrace: str | None = None
    """Full stacktrace for debugging (for Python errors)."""

    def format_message(self) -> str:
        """Format the error as a human-readable string."""
        parts = [f"Error in {self.file_path}"]

        if self.line_number is not None:
            loc = f"line {self.line_number}"
            if self.column_number is not None:
                loc += f", column {self.column_number}"
            parts.append(f"Location: {loc}")

        parts.append(f"Error ({self.error_type}): {self.message}")

        if self.context:
            parts.append(f"Context:\n{self.context}")

        if self.suggestion:
            parts.append(f"Suggestion: {self.suggestion}")

        return "\n".join(parts)


@dataclass
class DagImportWarning:
    """Warning information for non-fatal issues during DAG import."""

    file_path: str
    """Path to the file that caused the warning."""

    message: str
    """Human-readable warning message."""

    warning_type: str = "general"
    """Type of warning: 'deprecation', 'best_practice', 'performance'."""

    line_number: int | None = None
    """Line number where the warning applies (if available)."""


@dataclass
class DagImportResult:
    """
    Result of importing DAGs from a file.

    Contains the successfully imported DAGs along with any errors or warnings.
    """

    file_path: str
    """Path to the file that was imported."""

    dags: list[DAG] = field(default_factory=list)
    """List of successfully imported DAG objects."""

    errors: list[DagImportError] = field(default_factory=list)
    """List of errors encountered during import."""

    warnings: list[DagImportWarning] = field(default_factory=list)
    """List of warnings encountered during import."""

    @property
    def success(self) -> bool:
        """Return True if no fatal errors occurred."""
        return len(self.errors) == 0


class AbstractDagImporter(ABC):
    """
    Abstract base class for DAG importers.

    DAG importers are responsible for parsing files in a specific format and
    producing DAG objects. Each importer handles one or more file extensions.

    To create a custom importer:
    1. Subclass AbstractDagImporter
    2. Implement supported_extensions() to return the extensions you handle
    3. Implement import_file() to parse a file and return DagImportResult
    """

    @classmethod
    @abstractmethod
    def supported_extensions(cls) -> list[str]:
        """
        Return the list of file extensions this importer handles.

        Extensions should include the leading dot, e.g., [".py", ".pyw"].

        :return: List of supported file extensions.
        """

    @abstractmethod
    def import_file(
        self,
        file_path: str | Path,
        *,
        bundle_path: Path | None = None,
        bundle_name: str | None = None,
        safe_mode: bool = True,
    ) -> DagImportResult:
        """
        Import DAGs from a file.

        :param file_path: Path to the file to import.
        :param bundle_path: Path to the bundle root (for relative path calculation).
        :param bundle_name: Name of the bundle this file belongs to.
        :param safe_mode: If True, skip files that don't appear to contain DAGs.
        :return: DagImportResult containing DAGs, errors, and warnings.
        """

    def can_handle(self, file_path: str | Path) -> bool:
        """
        Check if this importer can handle the given file.

        :param file_path: Path to check.
        :return: True if this importer can handle the file.
        """
        path = Path(file_path) if isinstance(file_path, str) else file_path
        return path.suffix.lower() in self.supported_extensions()

    def get_relative_path(self, file_path: str | Path, bundle_path: Path | None) -> str:
        """
        Get the relative file path from the bundle root.

        :param file_path: Absolute path to the file.
        :param bundle_path: Path to the bundle root.
        :return: Relative path string, or absolute path if no bundle_path.
        """
        if bundle_path is None:
            return str(file_path)
        try:
            return str(Path(file_path).relative_to(bundle_path))
        except ValueError:
            return str(file_path)


class DagImporterRegistry:
    """
    Registry for DAG importers.

    Manages a collection of importers and provides lookup by file extension.
    This is the single source of truth for which importers handle which file types.

    Currently supports:
    - Python files (.py)

    Additional importers can be registered via:

        from airflow.dag_processing.importers import get_importer_registry
        registry = get_importer_registry()
        registry.register(MyCustomImporter())

    To add custom importers, get the registry and call register():

        from airflow.dag_processing.importers import get_importer_registry
        registry = get_importer_registry()
        registry.register(MyCustomImporter())
    """

    _instance: DagImporterRegistry | None = None
    _importers: dict[str, AbstractDagImporter]

    def __new__(cls) -> DagImporterRegistry:
        """Singleton pattern - one registry per process."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._importers = {}
            cls._instance._register_default_importers()
        return cls._instance

    def _register_default_importers(self) -> None:
        """Register the built-in importers."""
        # Import here to avoid circular imports
        from airflow.dag_processing.importers.python_importer import PythonDagImporter

        self.register(PythonDagImporter())

    def register(self, importer: AbstractDagImporter) -> None:
        """
        Register an importer for its supported extensions.

        :param importer: The importer instance to register.
        """
        for ext in importer.supported_extensions():
            self._importers[ext.lower()] = importer

    def get_importer(self, file_path: str | Path) -> AbstractDagImporter | None:
        """
        Get the appropriate importer for a file.

        :param file_path: Path to the file.
        :return: The importer that handles this file type, or None.
        """
        path = Path(file_path) if isinstance(file_path, str) else file_path
        ext = path.suffix.lower()
        return self._importers.get(ext)

    def can_handle(self, file_path: str | Path) -> bool:
        """
        Check if any registered importer can handle this file.

        :param file_path: Path to check.
        :return: True if an importer exists for this file type.
        """
        return self.get_importer(file_path) is not None

    def supported_extensions(self) -> list[str]:
        """Return all registered file extensions."""
        return list(self._importers.keys())

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (mainly for testing)."""
        cls._instance = None


def get_importer_registry() -> DagImporterRegistry:
    """Get the global importer registry instance."""
    return DagImporterRegistry()
