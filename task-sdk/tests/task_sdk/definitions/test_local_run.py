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

import base64
import json
import pickle
import runpy
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import types
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
import time_machine

from airflow.sdk.definitions.local_run import (
    CHILD_MODULE,
    INTERRUPT_GRACE_SECONDS,
    PROJECT_SECRETS_BACKEND,
    PROTOCOL_VERSION,
    DagRunResult,
    build_child_environment,
    build_result,
    find_project_root,
    is_unguarded_module_level_call,
    prepare_project_home,
    read_or_create_fernet_key,
    run_dag_file,
    wait_for_child,
)
from airflow.sdk.exceptions import (
    DagExecutionError,
    LocalRunConfigError,
    LocalRunDagFileError,
    LocalRunError,
    LocalRunUsageError,
)

REAL_POPEN = subprocess.Popen


def make_result(**kwargs) -> DagRunResult:
    values: dict[str, Any] = {
        "dag_id": "example",
        "run_id": "manual__1",
        "state": "success",
        "task_states": {("numbers", -1): "success", ("double", 0): "success", ("skipped", -1): "skipped"},
        "project_home": Path("/project/.airflow"),
        "outputs": {("numbers", -1, "return_value"): [1, 2], ("double", 0, "return_value"): 2},
    }
    values.update(kwargs)
    return DagRunResult(**values)


def make_payload(**kwargs) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": PROTOCOL_VERSION,
        "dag_id": "example",
        "run_id": "manual__1",
        "state": "success",
        "task_states": {("numbers", -1): "success"},
        "outputs": {("numbers", -1, "return_value"): pickle.dumps([1, 2])},
        "output_reprs": {("numbers", -1, "return_value"): "[1, 2]"},
        "output_errors": {},
        "dag_module": None,
        "ran": frozenset({("numbers", -1)}),
        "cancelled": False,
    }
    payload.update(kwargs)
    return payload


def define_summary_class(module_name: str, file: str | None = None) -> types.ModuleType:
    module = types.ModuleType(module_name)
    if file is not None:
        module.__file__ = file
    exec("class Summary:\n    def __init__(self, rows):\n        self.rows = rows\n", module.__dict__)
    return module


class TestDagRunResult:
    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            pytest.param(("numbers",), [1, 2], id="unmapped"),
            pytest.param(("double", 0), 2, id="mapped"),
            pytest.param(("double", 0, "return_value"), 2, id="explicit-key"),
        ],
    )
    def test_output_returns_pushed_value(self, args, expected):
        assert make_result().output(*args) == expected

    def test_output_is_none_for_succeeded_task_without_xcom(self):
        result = make_result(task_states={("noop", -1): "success"}, outputs={})

        assert result.output("noop") is None

    @pytest.mark.parametrize(
        ("args", "match"),
        [
            pytest.param(("missing",), "has no task 'missing'", id="unknown-task"),
            pytest.param(("double", 5), r"no map index 5; available: \[0\]", id="unknown-map-index"),
            pytest.param(("skipped",), r"task state: skipped", id="not-succeeded"),
            pytest.param(("numbers", -1, "custom"), "has no output 'custom'", id="unknown-key"),
        ],
    )
    def test_output_raises_key_error(self, args, match):
        with pytest.raises(KeyError, match=match):
            make_result().output(*args)

    def test_output_of_mapped_task_lists_its_instances(self):
        result = make_result(
            task_states={("double", 0): "success", ("double", 1): "success"},
            outputs={("double", 1, "return_value"): 4, ("double", 0, "return_value"): 2},
        )

        assert result.output("double") == [2, 4]

    def test_output_raises_value_error_for_untransferable_value(self):
        result = make_result(output_errors={("numbers", -1, "return_value"): "TypeError: nope"})

        with pytest.raises(ValueError, match="could not be transferred: TypeError: nope"):
            result.output("numbers")

    @pytest.mark.parametrize(("state", "expected"), [("success", True), ("failed", False)])
    def test_succeeded(self, state, expected):
        assert make_result(state=state).succeeded is expected


class TestProjectHome:
    def test_find_project_root_uses_nearest_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "pkg" / "inner").mkdir(parents=True)
        (tmp_path / "pkg" / "pyproject.toml").touch()

        assert find_project_root(tmp_path / "pkg" / "inner" / "pipeline.py") == tmp_path / "pkg"

    def test_find_project_root_falls_back_to_file_directory(self, tmp_path):
        source = tmp_path / "pipeline.py"

        assert find_project_root(source) == tmp_path

    def test_prepare_project_home_ignores_its_contents(self, tmp_path):
        home = prepare_project_home(tmp_path)
        prepare_project_home(tmp_path)

        assert home == tmp_path / ".airflow"
        assert (home / ".gitignore").read_text() == "*\n"

    def test_fernet_key_is_created_once(self, tmp_path):
        key = read_or_create_fernet_key(tmp_path)

        assert read_or_create_fernet_key(tmp_path) == key
        assert len(base64.urlsafe_b64decode(key)) == 32
        assert [p.name for p in tmp_path.iterdir()] == ["fernet.key"]

    def test_fernet_key_keeps_concurrent_winner(self, tmp_path):
        (tmp_path / "fernet.key").write_text("winner")

        with mock.patch("pathlib.Path.exists", return_value=False):
            assert read_or_create_fernet_key(tmp_path) == "winner"
        assert [p.name for p in tmp_path.iterdir()] == ["fernet.key"]


class TestBuildChildEnvironment:
    def test_replaces_airflow_configuration_and_keeps_resources(self, tmp_path):
        base = {
            "PATH": "/bin",
            "AIRFLOW_HOME": "/ambient",
            "AIRFLOW_CONFIG": "/ambient/airflow.cfg",
            "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN": "postgresql://prod",
            "_AIRFLOW__AS_LIBRARY": "1",
            "__AIRFLOW_SUPERVISOR_FD": "3",
            "AIRFLOW_CONN_WAREHOUSE": "sqlite://",
            "AIRFLOW_VAR_REGION": "eu",
        }

        env = build_child_environment(base, home=prepare_project_home(tmp_path), root=tmp_path)

        assert env["PATH"] == "/bin"
        assert env["AIRFLOW_CONN_WAREHOUSE"] == "sqlite://"
        assert env["AIRFLOW_VAR_REGION"] == "eu"
        assert env["AIRFLOW_HOME"] == str(tmp_path / ".airflow")
        assert (
            env["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"] == f"sqlite:///{tmp_path / '.airflow' / 'airflow.db'}"
        )
        assert env["AIRFLOW__CORE__DAGS_FOLDER"] == str(tmp_path)
        assert env["AIRFLOW__CORE__LOAD_EXAMPLES"] == "False"
        assert env["AIRFLOW__CORE__HOSTNAME_CALLABLE"] == "socket.gethostname"
        assert env["AIRFLOW__CORE__MIN_SERIALIZED_DAG_UPDATE_INTERVAL"] == "0"
        assert env["AIRFLOW__CORE__FERNET_KEY"] == read_or_create_fernet_key(tmp_path / ".airflow")
        assert len(env["AIRFLOW__API_AUTH__JWT_SECRET"]) >= 64
        assert not {"AIRFLOW_CONFIG", "_AIRFLOW__AS_LIBRARY", "__AIRFLOW_SUPERVISOR_FD"} & env.keys()
        assert "AIRFLOW__SECRETS__BACKEND" not in env

    @pytest.mark.parametrize(
        ("files", "expected_kwargs"),
        [
            pytest.param(
                {"connections_file": Path("/c.yaml")}, {"connections_file_path": "/c.yaml"}, id="conn"
            ),
            pytest.param({"variables_file": Path("/v.json")}, {"variables_file_path": "/v.json"}, id="var"),
            pytest.param(
                {"connections_file": Path("/c.yaml"), "variables_file": Path("/v.json")},
                {"connections_file_path": "/c.yaml", "variables_file_path": "/v.json"},
                id="both",
            ),
        ],
    )
    def test_resource_files_select_local_filesystem_backend(self, tmp_path, files, expected_kwargs):
        env = build_child_environment({}, home=tmp_path, root=tmp_path, **files)

        assert env["AIRFLOW__SECRETS__BACKEND"] == "airflow.secrets.local_filesystem.LocalFilesystemBackend"
        assert json.loads(env["AIRFLOW__SECRETS__BACKEND_KWARGS"]) == expected_kwargs

    @pytest.mark.parametrize(
        ("files", "file_kwargs"),
        [
            pytest.param({}, {}, id="no-files"),
            pytest.param(
                {"connections_file": Path("/c.yaml"), "variables_file": Path("/v.json")},
                {"connections_file_path": "/c.yaml", "variables_file_path": "/v.json"},
                id="files",
            ),
        ],
    )
    def test_project_secrets_backend_is_looked_in_after_the_resource_files(
        self, tmp_path, files, file_kwargs
    ):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.airflow.secrets]\nbackend = "vault.Backend"\nbackend_kwargs = { url = "https://dev" }\n'
        )
        base = {
            "AIRFLOW__SECRETS__BACKEND": "deployment.Backend",
            "AIRFLOW__SECRETS__BACKEND_KWARGS": '{"url": "https://prod"}',
            "AIRFLOW__SECRETS__BACKEND_KWARG__ROLE_ID": "developer",
        }

        env = build_child_environment(base, home=tmp_path, root=tmp_path, **files)

        assert env["AIRFLOW__SECRETS__BACKEND"] == PROJECT_SECRETS_BACKEND
        assert json.loads(env["AIRFLOW__SECRETS__BACKEND_KWARGS"]) == {
            "backend": "vault.Backend",
            "backend_kwargs": {"url": "https://dev"},
            **file_kwargs,
        }
        assert env["AIRFLOW__SECRETS__BACKEND_KWARG__ROLE_ID"] == "developer"

    @pytest.mark.parametrize(
        ("pyproject", "error"),
        [
            pytest.param("[tool.airflow.secrets\n", "is not valid TOML", id="invalid-toml"),
            pytest.param('[tool.airflow]\nsecrets = "vault.Backend"\n', "takes backend", id="not-a-table"),
            pytest.param("[tool.airflow.secrets]\nbackend_kwargs = {}\n", "takes backend", id="no-backend"),
            pytest.param("[tool.airflow.secrets]\nbackend = 1\n", "takes backend", id="backend-not-a-string"),
            pytest.param(
                '[tool.airflow.secrets]\nbackend = "vault.Backend"\nbackend_kwargs = "url"\n',
                "takes backend",
                id="kwargs-not-a-table",
            ),
            pytest.param(
                '[tool.airflow.secrets]\nbackend = "vault.Backend"\nbackend_kwarg = {}\n',
                "takes backend",
                id="unknown-key",
            ),
        ],
    )
    def test_invalid_project_secrets_backend_is_refused(self, tmp_path, pyproject, error):
        (tmp_path / "pyproject.toml").write_text(pyproject)

        with pytest.raises(LocalRunConfigError, match=error):
            build_child_environment({}, home=tmp_path, root=tmp_path)

    def test_project_classes_are_allowed_on_top_of_airflows_own(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.airflow]\nallowed_deserialization_classes = ["unusual_prefix_*_pipeline.Summary", "models.*"]\n'
        )

        env = build_child_environment(
            {"AIRFLOW__CORE__ALLOWED_DESERIALIZATION_CLASSES": "deployment.*"}, home=tmp_path, root=tmp_path
        )

        assert (
            env["AIRFLOW__CORE__ALLOWED_DESERIALIZATION_CLASSES"]
            == "airflow.* unusual_prefix_*_pipeline.Summary models.*"
        )

    @pytest.mark.parametrize(
        "value",
        [pytest.param('"models.*"', id="not-a-list"), pytest.param("[1]", id="not-names")],
    )
    def test_invalid_project_classes_are_refused(self, tmp_path, value):
        (tmp_path / "pyproject.toml").write_text(
            f"[tool.airflow]\nallowed_deserialization_classes = {value}\n"
        )

        with pytest.raises(LocalRunConfigError, match="takes a list of class names"):
            build_child_environment({}, home=tmp_path, root=tmp_path)


class TestWaitForChild:
    def test_returns_exit_code(self):
        process = mock.create_autospec(subprocess.Popen, instance=True)
        process.wait.return_value = 1

        assert wait_for_child(process) == 1
        process.send_signal.assert_not_called()

    def test_interrupt_lets_child_finish_then_reraises(self):
        process = mock.create_autospec(subprocess.Popen, instance=True)
        process.wait.side_effect = [KeyboardInterrupt, 130]

        with pytest.raises(KeyboardInterrupt):
            wait_for_child(process)

        process.send_signal.assert_called_once_with(signal.SIGINT)
        assert process.wait.call_args_list == [mock.call(), mock.call(timeout=INTERRUPT_GRACE_SECONDS)]
        process.kill.assert_not_called()

    def test_second_interrupt_kills_child(self):
        process = mock.create_autospec(subprocess.Popen, instance=True)
        process.wait.side_effect = [KeyboardInterrupt, KeyboardInterrupt, -9]

        with pytest.raises(KeyboardInterrupt):
            wait_for_child(process)

        process.kill.assert_called_once_with()

    def test_child_exceeding_grace_period_is_killed(self):
        process = mock.create_autospec(subprocess.Popen, instance=True)
        process.wait.side_effect = [KeyboardInterrupt, subprocess.TimeoutExpired("cmd", 30), -9]

        with pytest.raises(KeyboardInterrupt):
            wait_for_child(process)

        process.kill.assert_called_once_with()


class TestBuildResult:
    def test_success(self, tmp_path):
        result = build_result(make_payload(), 0, tmp_path, tmp_path / "dag.py")

        assert result.output("numbers") == [1, 2]
        assert result.project_home == tmp_path
        assert result.ran == {("numbers", -1)}

    def test_failed_run_raises_with_result(self, tmp_path):
        payload = make_payload(
            state="failed",
            task_states={("numbers", -1): "failed", ("double", 1): "failed"},
            failures={("double", 1): "ValueError: boom"},
        )

        with pytest.raises(
            DagExecutionError, match=r"failed tasks: double\[1\] \(ValueError: boom\), numbers$"
        ) as ctx:
            build_result(payload, 1, tmp_path, tmp_path / "dag.py")

        assert ctx.value.result.task_states[("numbers", -1)] == "failed"
        assert ctx.value.result.failures == {("double", 1): "ValueError: boom"}

    @pytest.mark.parametrize(
        ("payload", "error", "match"),
        [
            pytest.param(
                None, LocalRunError, "exited with code 1 without reporting a result", id="no-result"
            ),
            pytest.param(
                {"version": 99}, LocalRunConfigError, "Unsupported local run result version 99", id="version"
            ),
            pytest.param(
                {"version": PROTOCOL_VERSION, "error": "Dag 'x' has no task 'y'", "error_kind": "usage"},
                LocalRunUsageError,
                "has no task",
                id="usage",
            ),
            pytest.param(
                {"version": PROTOCOL_VERSION, "error": "No Dags found", "error_kind": "dag_file"},
                LocalRunDagFileError,
                "No Dags found",
                id="dag-file",
            ),
            pytest.param(
                {"version": PROTOCOL_VERSION, "error": "The secrets backend", "error_kind": "config"},
                LocalRunConfigError,
                "The secrets backend",
                id="config",
            ),
            pytest.param(
                {"version": PROTOCOL_VERSION, "error": "No Dags found"},
                LocalRunError,
                "No Dags",
                id="no-kind",
            ),
        ],
    )
    def test_setup_problems_raise_what_the_user_has_to_fix(self, tmp_path, payload, error, match):
        with pytest.raises(error, match=match) as ctx:
            build_result(payload, 1, tmp_path, tmp_path / "dag.py")

        assert type(ctx.value) is error

    def test_cancelled_run_raises_keyboard_interrupt(self, tmp_path):
        with pytest.raises(KeyboardInterrupt):
            build_result({"version": PROTOCOL_VERSION, "cancelled": True}, 130, tmp_path, tmp_path / "dag.py")

    def test_classes_from_the_dag_file_load_from_this_process_module_for_it(self, tmp_path, monkeypatch):
        source = (tmp_path / "dag.py").resolve()
        imported_by_run = define_summary_class("unusual_prefix_0_dag")
        with monkeypatch.context() as m:
            m.setitem(sys.modules, "unusual_prefix_0_dag", imported_by_run)
            data = pickle.dumps(imported_by_run.Summary(3))
        callers = define_summary_class("callers_dag", file=str(source))
        monkeypatch.setitem(sys.modules, "callers_dag", callers)
        payload = make_payload(
            task_states={("summary", -1): "success"},
            outputs={("summary", -1, "return_value"): data},
            dag_module="unusual_prefix_0_dag",
        )

        summary = build_result(payload, 0, tmp_path, source).output("summary")

        assert type(summary) is callers.Summary
        assert summary.rows == 3

    def test_output_that_cannot_load_here_spares_the_others_and_keeps_its_repr(self, tmp_path, monkeypatch):
        imported_by_run = define_summary_class("unusual_prefix_0_dag")
        with monkeypatch.context() as m:
            m.setitem(sys.modules, "unusual_prefix_0_dag", imported_by_run)
            data = pickle.dumps(imported_by_run.Summary(3))
        reprs = {
            ("numbers", -1, "return_value"): "[1, 2]",
            ("summary", -1, "return_value"): "Summary(rows=3)",
        }
        payload = make_payload(
            task_states={("numbers", -1): "success", ("summary", -1): "success"},
            outputs={
                ("numbers", -1, "return_value"): pickle.dumps([1, 2]),
                ("summary", -1, "return_value"): data,
            },
            output_reprs=reprs,
            dag_module="unusual_prefix_0_dag",
        )

        result = build_result(payload, 0, tmp_path, tmp_path / "dag.py")

        assert result.output("numbers") == [1, 2]
        with pytest.raises(
            ValueError, match="Summary is defined in dag.py, which this process has not imported"
        ):
            result.output("summary")
        assert result.output_reprs == reprs


class TestIsUnguardedModuleLevelCall:
    @pytest.mark.parametrize(
        ("statement", "expected"),
        [
            pytest.param("check()", True, id="top-level"),
            pytest.param("result = [check()]", True, id="assignment"),
            pytest.param('if __name__ == "__main__":\n    check()', False, id="guarded"),
            pytest.param('check() if __name__ == "__main__" else None', False, id="conditional-expression"),
            pytest.param("def main():\n    check()\n\nmain()", False, id="inside-a-function"),
            pytest.param("try:\n    check()\nexcept Exception:\n    pass", False, id="compound-statement"),
        ],
    )
    def test_detects_calls_that_importing_the_file_also_makes(self, tmp_path, statement, expected):
        path = tmp_path / "dag.py"
        path.write_text(
            textwrap.dedent(
                """\
                import sys

                found = []

                def check():
                    found.append(is_unguarded_module_level_call(__file__, sys._getframe(1)))

                """
            )
            + statement
            + "\n"
        )

        namespace = runpy.run_path(
            str(path),
            init_globals={"is_unguarded_module_level_call": is_unguarded_module_level_call},
            run_name="__main__",
        )

        assert namespace["found"] == [expected]


SELECTION_KEYS = (
    "task_ids",
    "task_group_ids",
    "include_upstream",
    "include_downstream",
    "run_id",
    "inputs",
    "keep_task_state",
)


class TestRunDagFile:
    @pytest.fixture
    def source(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "pipeline.py"
        source.touch()
        return source

    @time_machine.travel("2026-11-09T10:00:00Z", tick=False)
    @mock.patch("airflow.sdk.definitions.local_run.subprocess.Popen", autospec=True)
    def test_runs_child_with_request_and_project_environment(self, mock_popen, source, tmp_path):
        seen = {}

        def fake_child(command, env):
            request = json.loads(Path(command[-1]).read_text())
            seen.update(command=command, env=env, request=request)
            Path(request["result_path"]).write_bytes(pickle.dumps(make_payload()))
            process = mock.create_autospec(REAL_POPEN, instance=True)
            process.wait.return_value = 0
            return process

        mock_popen.side_effect = fake_child

        before = time.monotonic()
        result = run_dag_file(
            source, dag_id="example", run_conf={"n": 1}, triggered_by="cli", debug=True, retries=False
        )
        after = time.monotonic()

        assert result.output("numbers") == [1, 2]
        assert result.project_home == tmp_path / ".airflow"
        assert seen["command"][:3] == [sys.executable, "-m", CHILD_MODULE]
        assert seen["env"]["AIRFLOW_HOME"] == str(tmp_path / ".airflow")
        assert seen["request"] == {
            "version": PROTOCOL_VERSION,
            "source": str(source),
            "dag_id": "example",
            "run_conf": {"n": 1},
            "triggered_by": "cli",
            "debug": True,
            "keep_history": True,
            "retries": False,
            "result_path": seen["request"]["result_path"],
            "started_at": mock.ANY,
        }
        assert before <= seen["request"]["started_at"] <= after
        assert not Path(seen["request"]["result_path"]).parent.exists()

    @mock.patch(
        "airflow.sdk.definitions.local_run.tempfile.TemporaryDirectory",
        autospec=True,
        side_effect=tempfile.TemporaryDirectory,
    )
    @mock.patch("airflow.sdk.definitions.local_run.subprocess.Popen", autospec=True)
    def test_run_without_history_gets_a_home_of_its_own(self, mock_popen, mock_tmp, source, tmp_path):
        seen = {}

        def fake_child(command, env):
            request = json.loads(Path(command[-1]).read_text())
            seen.update(env=env, request=request)
            Path(request["result_path"]).write_bytes(pickle.dumps(make_payload()))
            process = mock.create_autospec(REAL_POPEN, instance=True)
            process.wait.return_value = 0
            return process

        mock_popen.side_effect = fake_child

        result = run_dag_file(source, keep_history=False)

        run_dir = Path(seen["request"]["result_path"]).parent
        assert seen["env"]["AIRFLOW_HOME"] == str(run_dir / "home")
        assert seen["request"]["keep_history"] is False
        assert result.project_home is None
        assert not (tmp_path / ".airflow").exists()
        assert not run_dir.exists()
        mock_tmp.assert_called_once_with(prefix="airflow-run-", ignore_cleanup_errors=True)

    @mock.patch("airflow.sdk.definitions.local_run.sys.platform", "win32")
    def test_refuses_windows_before_anything_else(self, tmp_path):
        # Any other check would refuse this file first.
        with pytest.raises(LocalRunConfigError, match="needs Linux or macOS; on Windows, run it in WSL2"):
            run_dag_file(tmp_path / "missing.txt")

    def test_rejects_non_python_file(self, tmp_path):
        source = tmp_path / "pipeline.txt"
        source.touch()

        with pytest.raises(LocalRunUsageError, match="needs a Python Dag file"):
            run_dag_file(source)

    def test_rejects_non_dict_run_conf(self, source):
        with pytest.raises(TypeError, match="run_conf must be a dict, not list"):
            run_dag_file(source, run_conf=[1])

    def test_rejects_a_number_of_retries(self, source):
        with pytest.raises(TypeError, match="retries takes True, .* or False, for one attempt; not 1$"):
            run_dag_file(source, retries=1)

    @mock.patch("airflow.sdk.definitions.local_run.subprocess.Popen", autospec=True)
    def test_task_selection_reaches_the_request(self, mock_popen, source):
        seen = {}

        def fake_child(command, env):
            seen.update(json.loads(Path(command[-1]).read_text()))
            Path(seen["result_path"]).write_bytes(pickle.dumps(make_payload()))
            process = mock.create_autospec(REAL_POPEN, instance=True)
            process.wait.return_value = 0
            return process

        mock_popen.side_effect = fake_child

        run_dag_file(
            source,
            task_ids=["total", ("double", 1)],
            task_group_ids=["transform"],
            include_downstream=True,
            run_id="manual__1",
            keep_task_state=True,
        )

        # JSON carries the (task_id, map_index) tuple as a list.
        assert {key: seen[key] for key in SELECTION_KEYS} == {
            "task_ids": ["total", ["double", 1]],
            "task_group_ids": ["transform"],
            "include_upstream": False,
            "include_downstream": True,
            "run_id": "manual__1",
            "inputs": None,
            "keep_task_state": True,
        }

    @mock.patch("airflow.sdk.definitions.local_run.subprocess.Popen", autospec=True)
    def test_inputs_reach_the_request_serialized_as_xcom_values(self, mock_popen, source):
        seen = {}

        def fake_child(command, env):
            seen.update(json.loads(Path(command[-1]).read_text()))
            Path(seen["result_path"]).write_bytes(pickle.dumps(make_payload()))
            process = mock.create_autospec(REAL_POPEN, instance=True)
            process.wait.return_value = 0
            return process

        mock_popen.side_effect = fake_child

        run_dag_file(source, task_ids=["total"], inputs={"double": [2, 4], "pair": (1, 2)})

        # A tuple is serialized with its class, as a task's return value is for XCom.
        assert seen["inputs"] == {
            "double": [2, 4],
            "pair": {"__classname__": "builtins.tuple", "__version__": 1, "__data__": [1, 2]},
        }

    @pytest.mark.parametrize(
        ("kwargs", "error", "match"),
        [
            pytest.param({"task_ids": "total"}, TypeError, "take a list", id="string-task-ids"),
            pytest.param({"task_group_ids": "group"}, TypeError, "take a list", id="string-group-ids"),
            pytest.param(
                {"task_ids": [("double", "1")]}, TypeError, "not \\('double', '1'\\)", id="bad-index"
            ),
            pytest.param(
                {"task_ids": [("double", True)]}, TypeError, "not \\('double', True\\)", id="bool-index"
            ),
            pytest.param(
                {"include_upstream": True}, ValueError, "apply to selected tasks", id="no-selection"
            ),
            pytest.param({"run_id": "manual__1"}, ValueError, "apply to selected tasks", id="run-id-alone"),
            pytest.param(
                {"task_ids": ["total"], "run_id": "manual__1", "run_conf": {"n": 1}},
                ValueError,
                "Run manual__1 keeps the conf it ran with",
                id="conf-for-an-earlier-run",
            ),
            pytest.param(
                {"task_ids": ["total"], "run_id": "manual__1", "keep_history": False},
                ValueError,
                "run_id names a run in the project's history",
                id="run-id-without-history",
            ),
            pytest.param(
                {"inputs": {"double": [2]}}, ValueError, "apply to selected tasks", id="inputs-alone"
            ),
            pytest.param(
                {"task_ids": ["total"], "inputs": [("double", [2])]},
                TypeError,
                "inputs takes a dict of task IDs to their outputs",
                id="inputs-not-a-dict",
            ),
            pytest.param(
                {"task_ids": ["total"], "inputs": {"double": [2]}, "run_id": "manual__1"},
                ValueError,
                "inputs run the selected tasks in a new run; leave out run_id",
                id="inputs-for-an-earlier-run",
            ),
            pytest.param(
                {"task_ids": ["total"], "inputs": {"double": [2]}, "include_upstream": True},
                ValueError,
                "so those tasks do not run; leave out include_upstream",
                id="inputs-with-upstream",
            ),
            pytest.param(
                {"keep_task_state": True},
                LocalRunUsageError,
                "a run of the whole Dag is a new run, which has none; pass task_ids or task_group_ids",
                id="keep-task-state-alone",
            ),
            pytest.param(
                {"task_ids": ["total"], "keep_task_state": True, "keep_history": False},
                LocalRunUsageError,
                "keep_task_state keeps task state from a run in the project's history",
                id="keep-task-state-without-history",
            ),
            pytest.param(
                {"task_ids": ["total"], "keep_task_state": True, "run_conf": {"n": 1}},
                LocalRunUsageError,
                "run_conf runs the selected tasks in a new run, which has no task state to keep",
                id="keep-task-state-with-conf",
            ),
            pytest.param(
                {"task_ids": ["total"], "keep_task_state": True, "inputs": {"double": [2]}},
                LocalRunUsageError,
                "inputs run the selected tasks in a new run, which has no task state to keep",
                id="keep-task-state-with-inputs",
            ),
            pytest.param(
                {"task_ids": ["total"], "inputs": {"double": object()}},
                TypeError,
                "The input for double cannot be stored as an XCom: ",
                id="input-not-serializable",
            ),
        ],
    )
    @mock.patch("airflow.sdk.definitions.local_run.subprocess.Popen", autospec=True)
    def test_invalid_task_selection_is_refused_before_the_run_starts(
        self, mock_popen, source, kwargs, error, match
    ):
        with pytest.raises(error, match=match):
            run_dag_file(source, **kwargs)

        mock_popen.assert_not_called()

    @pytest.mark.parametrize(
        ("argument", "resource"), [("connections_file", "connections"), ("variables_file", "variables")]
    )
    def test_missing_resource_file_is_refused(self, source, tmp_path, argument, resource):
        with pytest.raises(LocalRunUsageError, match=f"The {resource} file .*missing.yaml does not exist$"):
            run_dag_file(source, **{argument: tmp_path / "missing.yaml"})

    @mock.patch("airflow.sdk.definitions.local_run.importlib.util.find_spec", return_value=None)
    def test_requires_airflow_core(self, _, source):
        with pytest.raises(LocalRunConfigError, match="needs apache-airflow-core"):
            run_dag_file(source)
