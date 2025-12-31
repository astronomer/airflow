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
"""Python DAG importer - imports DAGs from Python files."""

from __future__ import annotations

import contextlib
import importlib
import importlib.machinery
import importlib.util
import logging
import os
import signal
import sys
import traceback
import warnings
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from airflow import settings
from airflow.configuration import conf
from airflow.dag_processing.importers.base import (
    AbstractDagImporter,
    DagImportError,
    DagImportResult,
    DagImportWarning,
)
from airflow.exceptions import (
    AirflowClusterPolicyError,
    AirflowClusterPolicySkipDag,
    AirflowClusterPolicyViolation,
    AirflowDagDuplicatedIdException,
    UnknownExecutorException,
)
from airflow.executors.executor_loader import ExecutorLoader
from airflow.listeners.listener import get_listener_manager
from airflow.utils.docs import get_docs_url
from airflow.utils.file import get_unique_dag_module_name, might_contain_dag

if TYPE_CHECKING:
    from types import ModuleType

    from airflow.sdk import DAG

log = logging.getLogger(__name__)


@contextlib.contextmanager
def _timeout(seconds: float = 1, error_message: str = "Timeout"):
    """Context manager for timing out operations."""
    error_message = error_message + ", PID: " + str(os.getpid())

    def handle_timeout(signum, frame):
        log.error("Process timed out, PID: %s", str(os.getpid()))
        from airflow.sdk.exceptions import AirflowTaskTimeout

        raise AirflowTaskTimeout(error_message)

    try:
        try:
            signal.signal(signal.SIGALRM, handle_timeout)
            signal.setitimer(signal.ITIMER_REAL, seconds)
        except ValueError:
            log.warning("timeout can't be used in the current context", exc_info=True)
        yield
    finally:
        with contextlib.suppress(ValueError):
            signal.setitimer(signal.ITIMER_REAL, 0)


def _executor_exists(executor_name: str, team_name: str | None) -> bool:
    """Check if executor exists, with global fallback for teams."""
    try:
        ExecutorLoader.lookup_executor_name_by_str(executor_name, team_name=team_name)
        return True
    except UnknownExecutorException:
        if team_name:
            try:
                ExecutorLoader.lookup_executor_name_by_str(executor_name, team_name=None)
                return True
            except UnknownExecutorException:
                pass
    return False


def _validate_executor_fields(dag: DAG, bundle_name: str | None = None) -> None:
    """Validate that executors specified in tasks are available."""
    dag_team_name = None

    if conf.getboolean("core", "multi_team"):
        if bundle_name:
            from airflow.dag_processing.bundles.manager import DagBundlesManager

            bundle_manager = DagBundlesManager()
            bundle_config = bundle_manager._bundle_config[bundle_name]
            dag_team_name = bundle_config.team_name

    for task in dag.tasks:
        if not task.executor:
            continue

        if not _executor_exists(task.executor, dag_team_name):
            if dag_team_name:
                raise UnknownExecutorException(
                    f"Task '{task.task_id}' specifies executor '{task.executor}', which is not available "
                    f"for team '{dag_team_name}' (the team associated with DAG '{dag.dag_id}') or as a global executor."
                )
            raise UnknownExecutorException(
                f"Task '{task.task_id}' specifies executor '{task.executor}', which is not available."
            )


class PythonDagImporter(AbstractDagImporter):
    """
    Importer for Python DAG files.

    This importer handles .py files and zip files containing Python modules.
    It imports Python modules and extracts DAG objects defined within them.
    """

    def __init__(self) -> None:
        self.dagbag_import_error_tracebacks = conf.getboolean("core", "dagbag_import_error_tracebacks")
        self.dagbag_import_error_traceback_depth = conf.getint("core", "dagbag_import_error_traceback_depth")

    @classmethod
    def supported_extensions(cls) -> list[str]:
        """Return supported file extensions."""
        return [".py", ".zip"]

    def import_file(
        self,
        file_path: str | Path,
        *,
        bundle_path: Path | None = None,
        bundle_name: str | None = None,
        safe_mode: bool = True,
    ) -> DagImportResult:
        """
        Import DAGs from a Python file or zip archive.

        :param file_path: Path to the Python file to import.
        :param bundle_path: Path to the bundle root.
        :param bundle_name: Name of the bundle.
        :param safe_mode: If True, skip files that don't appear to contain DAGs.
        :return: DagImportResult with imported DAGs and any errors.
        """
        from airflow.sdk.definitions._internal.contextmanager import DagContext

        filepath = str(file_path)
        relative_path = self.get_relative_path(filepath, bundle_path)
        result = DagImportResult(file_path=relative_path)

        if not os.path.isfile(filepath):
            result.errors.append(
                DagImportError(
                    file_path=relative_path,
                    message=f"File not found: {filepath}",
                    error_type="file_not_found",
                )
            )
            return result

        # Clear any autoregistered dags from previous imports
        DagContext.autoregistered_dags.clear()

        # Capture warnings during import
        captured_warnings: list[warnings.WarningMessage] = []

        try:
            with warnings.catch_warnings(record=True) as captured_warnings:
                if filepath.endswith(".py") or not zipfile.is_zipfile(filepath):
                    modules = self._load_modules_from_file(filepath, safe_mode, result)
                else:
                    modules = self._load_modules_from_zip(filepath, safe_mode, result)
        except Exception as e:
            result.errors.append(
                DagImportError(
                    file_path=relative_path,
                    message=str(e),
                    error_type="import",
                    stacktrace=traceback.format_exc(),
                )
            )
            return result

        # Convert captured warnings to DagImportWarning
        for warn_msg in captured_warnings:
            category = warn_msg.category.__name__
            if (module := warn_msg.category.__module__) != "builtins":
                category = f"{module}.{category}"
            result.warnings.append(
                DagImportWarning(
                    file_path=relative_path,
                    message=str(warn_msg.message),
                    warning_type=category,
                    line_number=warn_msg.lineno,
                )
            )

        # Process imported modules to extract DAGs
        self._process_modules(filepath, modules, bundle_name, bundle_path, result)

        return result

    def _load_modules_from_file(
        self, filepath: str, safe_mode: bool, result: DagImportResult
    ) -> list[ModuleType]:
        """Load Python modules from a .py file."""
        from airflow.sdk.definitions._internal.contextmanager import DagContext

        def sigsegv_handler(signum, frame):
            msg = f"Received SIGSEGV signal while processing {filepath}."
            log.error(msg)
            result.errors.append(
                DagImportError(
                    file_path=result.file_path,
                    message=msg,
                    error_type="segfault",
                )
            )

        try:
            signal.signal(signal.SIGSEGV, sigsegv_handler)
        except ValueError:
            log.warning("SIGSEGV signal handler registration failed. Not in the main thread")

        if not might_contain_dag(filepath, safe_mode):
            log.debug("File %s assumed to contain no DAGs. Skipping.", filepath)
            return []

        log.debug("Importing %s", filepath)
        mod_name = get_unique_dag_module_name(filepath)

        if mod_name in sys.modules:
            del sys.modules[mod_name]

        DagContext.current_autoregister_module_name = mod_name

        def parse(mod_name: str, filepath: str) -> list[ModuleType]:
            try:
                loader = importlib.machinery.SourceFileLoader(mod_name, filepath)
                spec = importlib.util.spec_from_loader(mod_name, loader)
                new_module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
                sys.modules[spec.name] = new_module  # type: ignore[union-attr]
                loader.exec_module(new_module)
                return [new_module]
            except KeyboardInterrupt:
                raise
            except BaseException as e:
                DagContext.autoregistered_dags.clear()
                log.exception("Failed to import: %s", filepath)
                if self.dagbag_import_error_tracebacks:
                    stacktrace = traceback.format_exc(limit=-self.dagbag_import_error_traceback_depth)
                else:
                    stacktrace = None
                result.errors.append(
                    DagImportError(
                        file_path=result.file_path,
                        message=str(e),
                        error_type="import",
                        stacktrace=stacktrace,
                    )
                )
                return []

        dagbag_import_timeout = settings.get_dagbag_import_timeout(filepath)

        if not isinstance(dagbag_import_timeout, (int, float)):
            raise TypeError(
                f"Value ({dagbag_import_timeout}) from get_dagbag_import_timeout must be int or float"
            )

        if dagbag_import_timeout <= 0:
            return parse(mod_name, filepath)

        timeout_msg = (
            f"DagBag import timeout for {filepath} after {dagbag_import_timeout}s.\n"
            "Please take a look at these docs to improve your DAG import time:\n"
            f"* {get_docs_url('best-practices.html#top-level-python-code')}\n"
            f"* {get_docs_url('best-practices.html#reducing-dag-complexity')}"
        )
        with _timeout(dagbag_import_timeout, error_message=timeout_msg):
            return parse(mod_name, filepath)

    def _load_modules_from_zip(
        self, filepath: str, safe_mode: bool, result: DagImportResult
    ) -> list[ModuleType]:
        """Load Python modules from a zip archive."""
        from airflow.sdk.definitions._internal.contextmanager import DagContext

        mods: list[ModuleType] = []
        with zipfile.ZipFile(filepath) as current_zip_file:
            for zip_info in current_zip_file.infolist():
                zip_path = Path(zip_info.filename)
                if zip_path.suffix not in [".py", ".pyc"] or len(zip_path.parts) > 1:
                    continue

                if zip_path.stem == "__init__":
                    log.warning("Found %s at root of %s", zip_path.name, filepath)

                log.debug("Reading %s from %s", zip_info.filename, filepath)

                if not might_contain_dag(zip_info.filename, safe_mode, current_zip_file):
                    continue

                mod_name = zip_path.stem
                if mod_name in sys.modules:
                    del sys.modules[mod_name]

                DagContext.current_autoregister_module_name = mod_name
                try:
                    sys.path.insert(0, filepath)
                    current_module = importlib.import_module(mod_name)
                    mods.append(current_module)
                except Exception as e:
                    DagContext.autoregistered_dags.clear()
                    fileloc = os.path.join(filepath, zip_info.filename)
                    log.exception("Failed to import: %s", fileloc)
                    if self.dagbag_import_error_tracebacks:
                        stacktrace = traceback.format_exc(limit=-self.dagbag_import_error_traceback_depth)
                    else:
                        stacktrace = None
                    result.errors.append(
                        DagImportError(
                            file_path=result.file_path,
                            message=str(e),
                            error_type="import",
                            stacktrace=stacktrace,
                        )
                    )
                finally:
                    if sys.path[0] == filepath:
                        del sys.path[0]
        return mods

    def _process_modules(
        self,
        filepath: str,
        mods: list[Any],
        bundle_name: str | None,
        bundle_path: Path | None,
        result: DagImportResult,
    ) -> None:
        """Process imported modules to extract DAG objects."""
        from airflow._shared.timezones import timezone
        from airflow.sdk import DAG
        from airflow.sdk.definitions._internal.contextmanager import DagContext
        from airflow.sdk.exceptions import AirflowDagCycleException

        top_level_dags: set[tuple[DAG, Any]] = {
            (o, m) for m in mods for o in m.__dict__.values() if isinstance(o, DAG)
        }
        top_level_dags.update(DagContext.autoregistered_dags)

        DagContext.current_autoregister_module_name = None
        DagContext.autoregistered_dags.clear()

        seen_dag_ids: dict[str, str] = {}

        for dag, mod in top_level_dags:
            dag.fileloc = mod.__file__
            relative_fileloc = self.get_relative_path(dag.fileloc, bundle_path)
            dag.relative_fileloc = relative_fileloc

            try:
                dag.validate()
                _validate_executor_fields(dag, bundle_name)
                dag.check_cycle()
                dag.resolve_template_files()
                dag.last_loaded = timezone.utcnow()

                # Check policies
                try:
                    settings.dag_policy(dag)
                    for task in dag.tasks:
                        if getattr(task, "end_from_trigger", False) and get_listener_manager().has_listeners:
                            raise AirflowClusterPolicyViolation(
                                f"Listeners are not supported with end_from_trigger=True. "
                                f"Task {task.task_id} in DAG {dag.dag_id} has end_from_trigger=True."
                            )
                        settings.task_policy(task)
                except (AirflowClusterPolicyViolation, AirflowClusterPolicySkipDag):
                    raise
                except Exception as e:
                    raise AirflowClusterPolicyError(e)

                # Check for duplicate dag_id
                if dag.dag_id in seen_dag_ids:
                    raise AirflowDagDuplicatedIdException(
                        dag_id=dag.dag_id,
                        incoming=dag.fileloc,
                        existing=seen_dag_ids[dag.dag_id],
                    )
                seen_dag_ids[dag.dag_id] = dag.fileloc
                result.dags.append(dag)
                log.debug("Loaded DAG %s", dag)

            except AirflowClusterPolicySkipDag:
                log.debug("DAG %s skipped by cluster policy", dag.dag_id)
            except (AirflowDagCycleException, AirflowDagDuplicatedIdException) as e:
                log.exception("Exception processing dag: %s", dag.dag_id)
                result.errors.append(
                    DagImportError(
                        file_path=relative_fileloc,
                        message=f"{type(e).__name__}: {e}",
                        error_type="validation",
                    )
                )
            except Exception as e:
                log.exception("Failed to process DAG: %s", dag.fileloc)
                result.errors.append(
                    DagImportError(
                        file_path=relative_fileloc,
                        message=f"{type(e).__name__}: {e}",
                        error_type="validation",
                    )
                )
