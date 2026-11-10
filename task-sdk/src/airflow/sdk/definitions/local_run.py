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
Run a Dag from its source file against a project-owned Airflow environment.

The calling process keeps whatever Airflow configuration it imported with. The run itself happens in
a child interpreter (``python -m airflow.local_run``) whose environment selects the project's home and
database before Airflow is imported, so Airflow's normal initialization applies unchanged.
"""

from __future__ import annotations

import ast
import base64
import contextlib
import importlib.util
import io
import json
import os
import pickle
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType
from typing import Any, NoReturn

from airflow.sdk.exceptions import DagExecutionError, LocalRunError

PROTOCOL_VERSION = 2
PROJECT_HOME_NAME = ".airflow"
CHILD_MODULE = "airflow.local_run"

# How long a child gets to record a cancelled run after Ctrl-C before it is killed.
INTERRUPT_GRACE_SECONDS = 30.0

_DROPPED_ENV_NAMES = frozenset({"AIRFLOW_HOME", "AIRFLOW_CONFIG"})
_DROPPED_ENV_PREFIXES = ("AIRFLOW__", "_AIRFLOW", "__AIRFLOW")


@dataclass(frozen=True)
class DagRunResult:
    """Detached outcome of a local Dag run; it stays usable after the run's resources are released."""

    dag_id: str
    run_id: str
    state: str
    task_states: Mapping[tuple[str, int], str]
    project_home: Path
    outputs: Mapping[tuple[str, int, str], Any] = field(default_factory=dict, repr=False)
    output_errors: Mapping[tuple[str, int, str], str] = field(default_factory=dict, repr=False)
    # The error each failed task instance's last attempt ended with, e.g. "ValueError: boom".
    failures: Mapping[tuple[str, int], str] = field(default_factory=dict, repr=False)
    # The task instances this call ran: in a rerun, the selected ones; otherwise every one that ran.
    ran: frozenset[tuple[str, int]] = field(default_factory=frozenset, repr=False)

    @property
    def succeeded(self) -> bool:
        return self.state == "success"

    def output(self, task_id: str, map_index: int = -1, key: str = "return_value") -> Any:
        """
        Return the XCom value a task instance pushed during this run.

        A task that succeeded without pushing ``return_value`` returned ``None``: Airflow does not
        store ``None`` return values. For a mapped task, the default ``map_index`` returns the values of
        all its instances, in map index order.

        :raises KeyError: the run has no such task instance, or it did not succeed and pushed nothing.
        :raises ValueError: the value exists but could not be transferred out of the run.
        """
        state = self.task_states.get((task_id, map_index))
        if state is None:
            indexes = sorted(i for t, i in self.task_states if t == task_id)
            if not indexes:
                raise KeyError(f"Dag {self.dag_id!r} has no task {task_id!r} in run {self.run_id}")
            if map_index == -1:
                return [self.output(task_id, index, key) for index in indexes]
            raise KeyError(f"Task {task_id!r} has no map index {map_index}; available: {indexes}")
        output_key = (task_id, map_index, key)
        if output_key in self.output_errors:
            raise ValueError(
                f"Output {key!r} of task {task_id!r} could not be transferred: {self.output_errors[output_key]}"
            )
        if output_key in self.outputs:
            return self.outputs[output_key]
        if key == "return_value" and state == "success":
            return None
        raise KeyError(f"Task {task_id!r} has no output {key!r} (task state: {state})")


def find_project_root(source: Path) -> Path:
    """Return the nearest ancestor of ``source`` that holds a ``pyproject.toml``, else its directory."""
    for directory in source.parents:
        if (directory / "pyproject.toml").is_file():
            return directory
    return source.parent


def prepare_project_home(root: Path) -> Path:
    home = root / PROJECT_HOME_NAME
    home.mkdir(exist_ok=True)
    gitignore = home / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    return home


def read_or_create_fernet_key(home: Path) -> str:
    """Return the project's Fernet key, creating it atomically so concurrent first runs agree."""
    key_file = home / "fernet.key"
    if not key_file.exists():
        fd, tmp_name = tempfile.mkstemp(dir=home, prefix=".fernet-")
        try:
            os.write(fd, base64.urlsafe_b64encode(os.urandom(32)))
            os.close(fd)
            with contextlib.suppress(FileExistsError):
                os.link(tmp_name, key_file)
        finally:
            os.unlink(tmp_name)
    return key_file.read_text().strip()


def build_child_environment(
    base: Mapping[str, str],
    *,
    home: Path,
    root: Path,
    connections_file: Path | None = None,
    variables_file: Path | None = None,
) -> dict[str, str]:
    """
    Build the child's environment: the caller's environment without Airflow configuration, plus the project's.

    Environment variables override configuration files, so an inherited ``AIRFLOW__DATABASE__*`` could
    otherwise point a local run at a deployment's database. ``AIRFLOW_CONN_*`` and ``AIRFLOW_VAR_*``
    are kept: they are how a local run receives connections and variables.
    """
    env = {
        name: value
        for name, value in base.items()
        if name not in _DROPPED_ENV_NAMES and not name.startswith(_DROPPED_ENV_PREFIXES)
    }
    env.update(
        {
            "AIRFLOW_HOME": str(home),
            "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN": f"sqlite:///{home / 'airflow.db'}",
            "AIRFLOW__CORE__DAGS_FOLDER": str(root),
            "AIRFLOW__CORE__LOAD_EXAMPLES": "False",
            # The default getfqdn() can block for seconds on macOS resolvers; a local run only needs a label.
            "AIRFLOW__CORE__HOSTNAME_CALLABLE": "socket.gethostname",
            # Otherwise a structural edit rerun within the default 30 seconds keeps the previous Dag version.
            "AIRFLOW__CORE__MIN_SERIALIZED_DAG_UPDATE_INTERVAL": "0",
            "AIRFLOW__CORE__FERNET_KEY": read_or_create_fernet_key(home),
            "AIRFLOW__API_AUTH__JWT_SECRET": secrets.token_urlsafe(64),
        }
    )
    if connections_file or variables_file:
        backend_kwargs = {}
        if connections_file:
            backend_kwargs["connections_file_path"] = str(connections_file)
        if variables_file:
            backend_kwargs["variables_file_path"] = str(variables_file)
        env["AIRFLOW__SECRETS__BACKEND"] = "airflow.secrets.local_filesystem.LocalFilesystemBackend"
        env["AIRFLOW__SECRETS__BACKEND_KWARGS"] = json.dumps(backend_kwargs)
    return env


def run_dag_file(
    source: str | os.PathLike[str],
    *,
    dag_id: str | None = None,
    run_conf: dict[str, Any] | None = None,
    connections_file: str | os.PathLike[str] | None = None,
    variables_file: str | os.PathLike[str] | None = None,
    task_ids: Sequence[str | tuple[str, int]] | None = None,
    task_group_ids: Sequence[str] | None = None,
    include_upstream: bool = False,
    include_downstream: bool = False,
    run_id: str | None = None,
    triggered_by: str = "test",
    debug: bool = False,
) -> DagRunResult:
    """
    Run one Dag defined in ``source`` in its project's environment and wait for it to finish.

    With ``task_ids`` or ``task_group_ids``, rerun only those tasks, as Clear does in the UI, in the latest
    finished run that has the outputs of their upstream tasks, or in ``run_id``. With ``run_conf``, or when no
    earlier run has those outputs, a new run runs them and the tasks they need, and records the others as
    skipped.

    :param dag_id: required when the file defines more than one Dag.
    :param task_ids: task IDs, or ``(task_id, map_index)`` tuples for one mapped task instance.
    :param task_group_ids: task groups whose tasks to rerun.
    :param include_upstream: also rerun the upstream tasks of the selected ones.
    :param include_downstream: also rerun the downstream tasks of the selected ones.
    :param run_id: the run to rerun the selected tasks in.
    :param debug: run task tries inside the run's process rather than each in a process of its own.
    :raises DagExecutionError: the run finished in a failed state.
    :raises LocalRunError: the run could not start or did not report a result.
    :raises KeyboardInterrupt: the run was interrupted; it is recorded as failed.
    """
    # The run locks its project with fcntl and starts task tries by fork in process groups of their own.
    if sys.platform == "win32":
        raise LocalRunError("Running a Dag locally needs Linux or macOS; on Windows, run it in WSL2")
    started_at = time.monotonic()
    source_path = Path(source).resolve()
    if source_path.suffix != ".py" or not source_path.is_file():
        raise LocalRunError(f"A local run needs a Python Dag file; {source_path} is not one")
    if run_conf is not None and not isinstance(run_conf, dict):
        raise TypeError(f"run_conf must be a dict, not {type(run_conf).__name__}")
    selection = build_task_selection(
        task_ids,
        task_group_ids,
        include_upstream=include_upstream,
        include_downstream=include_downstream,
        run_id=run_id,
        run_conf=run_conf,
    )
    connections_path = Path(connections_file).resolve(strict=True) if connections_file else None
    variables_path = Path(variables_file).resolve(strict=True) if variables_file else None
    if importlib.util.find_spec(CHILD_MODULE) is None:
        raise LocalRunError("Running a Dag locally needs apache-airflow-core installed in this environment")

    root = find_project_root(source_path)
    home = prepare_project_home(root)
    env = build_child_environment(
        os.environ,
        home=home,
        root=root,
        connections_file=connections_path,
        variables_file=variables_path,
    )

    with tempfile.TemporaryDirectory(prefix="airflow-run-") as tmp:
        request_path = Path(tmp, "request.json")
        result_path = Path(tmp, "result.pickle")
        request_path.write_text(
            json.dumps(
                {
                    "version": PROTOCOL_VERSION,
                    "source": str(source_path),
                    "dag_id": dag_id,
                    "run_conf": run_conf,
                    **selection,
                    "triggered_by": triggered_by,
                    "debug": debug,
                    "result_path": str(result_path),
                    "started_at": started_at,
                }
            )
        )
        process = subprocess.Popen([sys.executable, "-m", CHILD_MODULE, str(request_path)], env=env)
        return_code = wait_for_child(process)
        payload = pickle.loads(result_path.read_bytes()) if result_path.exists() else None
    return build_result(payload, return_code, home, source_path)


def build_task_selection(
    task_ids: Sequence[str | tuple[str, int]] | None,
    task_group_ids: Sequence[str] | None,
    *,
    include_upstream: bool,
    include_downstream: bool,
    run_id: str | None,
    run_conf: dict[str, Any] | None,
) -> dict[str, Any]:
    """Check a selection of tasks to rerun, and return it as the run's request carries it."""
    if isinstance(task_ids, str) or isinstance(task_group_ids, str):
        raise TypeError("task_ids and task_group_ids take a list, e.g. task_ids=['total']")
    markers: list[str | list[str | int]] = []
    for marker in task_ids or ():
        if isinstance(marker, str):
            markers.append(marker)
        elif (
            isinstance(marker, tuple)
            and len(marker) == 2
            and isinstance(marker[0], str)
            and isinstance(marker[1], int)
            and not isinstance(marker[1], bool)
        ):
            markers.append([marker[0], marker[1]])
        else:
            raise TypeError(f"A task ID or a (task_id, map_index) tuple is expected, not {marker!r}")
    group_ids = list(task_group_ids or ())
    if not markers and not group_ids:
        if include_upstream or include_downstream or run_id is not None:
            raise ValueError(
                "include_upstream, include_downstream and run_id apply to selected tasks; "
                "pass task_ids or task_group_ids"
            )
        return {}
    if run_conf is not None and run_id is not None:
        raise ValueError(
            f"Run {run_id} keeps the conf it ran with; leave out run_id to run the tasks in a new run "
            "with this conf"
        )
    return {
        "task_ids": markers,
        "task_group_ids": group_ids,
        "include_upstream": include_upstream,
        "include_downstream": include_downstream,
        "run_id": run_id,
    }


def wait_for_child(process: subprocess.Popen) -> int:
    """
    Wait for the child, letting it record a cancelled run when interrupted.

    A terminal Ctrl-C reaches the child too, because both share the foreground process group; that keeps
    ``breakpoint()`` in task code usable. The forwarded SIGINT covers an interrupt sent to this process
    only, and the child ignores repeats while it cleans up. A second interrupt kills the child.
    """
    try:
        return process.wait()
    except KeyboardInterrupt:
        pass
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=INTERRUPT_GRACE_SECONDS)
    except (KeyboardInterrupt, subprocess.TimeoutExpired):
        process.kill()
        process.wait()
    raise KeyboardInterrupt


def build_result(payload: dict[str, Any] | None, return_code: int, home: Path, source: Path) -> DagRunResult:
    if payload is None:
        raise LocalRunError(
            f"The local run process exited with code {return_code} without reporting a result"
        )
    if payload.get("version") != PROTOCOL_VERSION:
        raise LocalRunError(f"Unsupported local run result version {payload.get('version')!r}")
    if payload.get("error"):
        raise LocalRunError(payload["error"])
    if payload.get("cancelled"):
        raise KeyboardInterrupt
    outputs: dict[tuple[str, int, str], Any] = {}
    output_errors = dict(payload["output_errors"])
    for key, data in payload["outputs"].items():
        try:
            outputs[key] = _OutputUnpickler(data, dag_module=payload["dag_module"], source=source).load()
        except Exception as e:
            output_errors[key] = f"{type(e).__name__}: {e}"
    result = DagRunResult(
        dag_id=payload["dag_id"],
        run_id=payload["run_id"],
        state=payload["state"],
        task_states=payload["task_states"],
        project_home=home,
        outputs=outputs,
        output_errors=output_errors,
        failures=payload.get("failures", {}),
        ran=payload["ran"],
    )
    if not result.succeeded:
        raise DagExecutionError(result)
    return result


class _OutputUnpickler(pickle.Unpickler):
    """
    Load an output pickled by the run's process.

    That process imported the Dag file under a generated module name, as Airflow does; classes defined in
    the file are looked up in this process's module for the same file instead, e.g. ``__main__``.
    """

    def __init__(self, data: bytes, *, dag_module: str | None, source: Path) -> None:
        super().__init__(io.BytesIO(data))
        self._dag_module = dag_module
        self._source = source

    def find_class(self, module: str, name: str) -> Any:
        if module == self._dag_module:
            local = find_loaded_module(self._source)
            if local is None:
                raise LocalRunError(
                    f"{name} is defined in {self._source.name}, which this process has not imported"
                )
            module = local
        return super().find_class(module, name)


def find_loaded_module(source: Path) -> str | None:
    """Return the name of the module this process imported from ``source``, if any."""
    for name, module in list(sys.modules.items()):
        file = getattr(module, "__file__", None)
        if file and os.path.basename(file) == source.name and Path(file).resolve() == source:
            return name
    return None


def is_unguarded_module_level_call(source: str | os.PathLike[str], caller: FrameType) -> bool:
    """
    Whether ``caller`` is ``source``'s module-level code calling in a statement that also runs on import.

    The run's process imports ``source``, so such a call would only be refused there, after that process
    started. Only a top-level simple statement without a condition is certain to run on import; any other
    call is left to the check made while importing.
    """
    code = caller.f_code
    path = Path(source).resolve()
    if code.co_name != "<module>" or Path(code.co_filename).resolve() != path:
        return False
    try:
        module = ast.parse(path.read_bytes(), filename=str(path))
    except (OSError, SyntaxError, ValueError):
        return False
    line = caller.f_lineno
    statement = next((s for s in module.body if s.lineno <= line <= (s.end_lineno or s.lineno)), None)
    if not isinstance(statement, (ast.Expr, ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return False
    return not any(
        isinstance(node, (ast.IfExp, ast.BoolOp)) or (isinstance(node, ast.Name) and node.id == "__name__")
        for node in ast.walk(statement)
    )


def is_dropped_call_under_main_guard(caller: FrameType) -> bool:
    """
    Whether ``caller`` is a script's ``if __name__ == "__main__":`` block calling in a bare statement.

    A script drops a call's result like that only when it expects the call to do the work itself.
    """
    if caller.f_globals.get("__name__") != "__main__":
        return False
    code = caller.f_code
    # One position per two-byte code unit; the frame's last instruction is the call being made.
    position = list(code.co_positions())[caller.f_lasti // 2]
    if position[0] is None:
        return False
    try:
        module = ast.parse(Path(code.co_filename).read_bytes(), filename=code.co_filename)
    except (OSError, SyntaxError, ValueError):
        return False
    guards = [node for node in module.body if isinstance(node, ast.If) and _is_main_guard(node.test)]
    return any(
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and (node.value.lineno, node.value.end_lineno, node.value.col_offset, node.value.end_col_offset)
        == position
        for guard in guards
        for node in ast.walk(guard)
    )


def _is_main_guard(test: ast.expr) -> bool:
    if not isinstance(test, ast.Compare) or len(test.comparators) != 1:
        return False
    sides = (test.left, test.comparators[0])
    return any(isinstance(side, ast.Name) and side.id == "__name__" for side in sides) and any(
        isinstance(side, ast.Constant) and side.value == "__main__" for side in sides
    )


def refuse_breakpoint(*args: Any, **kwargs: Any) -> NoReturn:
    """
    Stand in for ``breakpoint()`` in a task try that runs in a process of its own.

    That process does not read the terminal, so a debugger started in it could never take input.
    """
    raise RuntimeError(
        "breakpoint() needs the task to run in the run's own process, where the debugger can read the "
        "terminal: run the Dag with .run(debug=True) or airflow run --debug."
    )
