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

from pathlib import Path
from unittest import mock

import pytest

from airflow.cli import cli_parser
from airflow.cli.commands import run_command
from airflow.sdk.definitions.local_run import DagRunResult
from airflow.sdk.exceptions import (
    DagExecutionError,
    LocalRunConfigError,
    LocalRunDagFileError,
    LocalRunError,
    LocalRunUsageError,
)


def make_result(state: str = "success", outputs: dict | None = None, ran: set | None = None) -> DagRunResult:
    if outputs is None:
        outputs = {("total", -1, "return_value"): 12}
    return DagRunResult(
        dag_id="example",
        run_id="manual__1",
        state=state,
        task_states={("total", -1): state},
        project_home=Path("/project/.airflow"),
        outputs=outputs,
        output_reprs={key: repr(value) for key, value in outputs.items()},
        ran=frozenset(ran) if ran is not None else frozenset((t, m) for t, m, _ in outputs),
    )


class TestRunCommand:
    @classmethod
    def setup_class(cls):
        cls.parser = cli_parser.get_parser()

    @mock.patch.object(run_command, "run_dag_file", autospec=True)
    def test_passes_no_db_checkpoint_options(self, mock_run_dag_file):
        mock_run_dag_file.return_value = make_result()
        args = self.parser.parse_args(
            [
                "run",
                "agent.py",
                "--no-db",
                "--task",
                "agent",
                "--state-file",
                "state.json",
                "--keep-task-state",
                "--input",
                "upstream=3",
                "--conf",
                '{"limit": 4}',
            ]
        )
        args.func(args)
        options = mock_run_dag_file.call_args.kwargs
        assert options["no_db"] is True
        assert options["state_file"] == "state.json"
        assert options["keep_task_state"] is True
        assert options["inputs"] == {"upstream": 3}

    @pytest.mark.parametrize(
        ("extra_args", "debug", "keep_history", "retries"),
        [
            ([], False, True, True),
            (["--debug"], True, True, True),
            (["--no-history"], False, False, True),
            (["--no-retries"], False, True, False),
        ],
    )
    @mock.patch.object(run_command, "run_dag_file", autospec=True)
    def test_passes_arguments_to_launcher(
        self, mock_run_dag_file, capsys, extra_args, debug, keep_history, retries
    ):
        mock_run_dag_file.return_value = make_result()
        args = self.parser.parse_args(
            [
                "run",
                "pipeline.py",
                "--dag-id",
                "example",
                "--conf",
                '{"n": 1}',
                "--connections-file",
                "conns.yaml",
                "--variables-file",
                "vars.json",
                *extra_args,
            ]
        )

        args.func(args)

        mock_run_dag_file.assert_called_once_with(
            "pipeline.py",
            dag_id="example",
            run_conf={"n": 1},
            connections_file="conns.yaml",
            variables_file="vars.json",
            task_ids=None,
            task_group_ids=None,
            include_upstream=False,
            include_downstream=False,
            run_id=None,
            inputs=None,
            keep_task_state=False,
            triggered_by="cli",
            debug=debug,
            keep_history=keep_history,
            retries=retries,
        )
        assert capsys.readouterr().out.splitlines() == ["Outputs:", "  total = 12"]

    @mock.patch.object(run_command, "run_dag_file", autospec=True)
    def test_passes_task_selection_to_launcher(self, mock_run_dag_file):
        mock_run_dag_file.return_value = make_result()
        args = self.parser.parse_args(
            [
                "run",
                "pipeline.py",
                "--task",
                "total",
                "--task",
                "double[1]",
                "--group",
                "transform",
                "--upstream",
                "--downstream",
                "--run-id",
                "manual__1",
                "--keep-task-state",
            ]
        )

        args.func(args)

        assert mock_run_dag_file.call_args.kwargs == {
            "dag_id": None,
            "run_conf": None,
            "connections_file": None,
            "variables_file": None,
            "task_ids": ["total", ("double", 1)],
            "task_group_ids": ["transform"],
            "include_upstream": True,
            "include_downstream": True,
            "run_id": "manual__1",
            "inputs": None,
            "keep_task_state": True,
            "triggered_by": "cli",
            "debug": False,
            "keep_history": True,
            "retries": True,
        }

    @mock.patch.object(run_command, "run_dag_file", autospec=True)
    def test_passes_inputs_to_launcher(self, mock_run_dag_file):
        mock_run_dag_file.return_value = make_result()
        args = self.parser.parse_args(
            [
                "run",
                "pipeline.py",
                "--task",
                "total",
                "--input",
                "double=[2, 4]",
                "--input",
                'label={"text": "a=b"}',
                "--downstream",
                "--no-history",
            ]
        )

        args.func(args)

        kwargs = mock_run_dag_file.call_args.kwargs
        assert kwargs["inputs"] == {"double": [2, 4], "label": {"text": "a=b"}}
        assert (kwargs["include_downstream"], kwargs["keep_history"]) == (True, False)

    @pytest.mark.parametrize(
        ("extra_args", "message"),
        [
            pytest.param(["--upstream"], "apply to the tasks chosen with --task or --group", id="upstream"),
            pytest.param(
                ["--downstream"], "apply to the tasks chosen with --task or --group", id="downstream"
            ),
            pytest.param(
                ["--run-id", "manual__1"], "apply to the tasks chosen with --task or --group", id="run-id"
            ),
            pytest.param(
                ["--task", "total", "--run-id", "manual__1", "--no-history"],
                "--run-id names a run in the project's history",
                id="run-id-without-history",
            ),
            pytest.param(
                ["--input", "double=[2]"], "apply to the tasks chosen with --task or --group", id="input"
            ),
            pytest.param(
                ["--task", "total", "--input", "double=[2"],
                "--input double is not valid JSON: ",
                id="input-not-json",
            ),
            pytest.param(
                ["--task", "total", "--input", "[2, 4]"],
                "--input takes TASK_ID=JSON, not '[2, 4]'",
                id="input-no-id",
            ),
            pytest.param(
                ["--task", "total", "--input", "double=[2]", "--input", "double=[4]"],
                "--input gives double more than once",
                id="input-twice",
            ),
            pytest.param(
                ["--task", "total", "--input", "double=[2]", "--run-id", "manual__1"],
                "--input runs the selected tasks in a new run, so it does not take --run-id",
                id="input-with-run-id",
            ),
            pytest.param(
                ["--task", "total", "--input", "double=[2]", "--upstream"],
                "so it does not take --upstream",
                id="input-with-upstream",
            ),
            pytest.param(
                ["--keep-task-state"],
                "apply to the tasks chosen with --task or --group",
                id="keep-task-state",
            ),
            pytest.param(
                ["--task", "total", "--keep-task-state", "--no-history"],
                "--no-history runs the selected tasks in a new run, which has no task state to keep, so it "
                "does not take --keep-task-state",
                id="keep-task-state-without-history",
            ),
            pytest.param(
                ["--task", "total", "--keep-task-state", "--conf", "{}"],
                "--conf runs the selected tasks in a new run, which has no task state to keep",
                id="keep-task-state-with-conf",
            ),
            pytest.param(
                ["--task", "total", "--keep-task-state", "--input", "double=[2]"],
                "--input runs the selected tasks in a new run, which has no task state to keep",
                id="keep-task-state-with-input",
            ),
            pytest.param(["--conf", "{not json"], "--conf is not valid JSON", id="conf-not-json"),
            pytest.param(["--conf", "[1]"], "--conf must be a JSON object", id="conf-not-object"),
        ],
    )
    @mock.patch.object(run_command, "run_dag_file", autospec=True)
    def test_wrong_arguments_are_refused_before_running(self, mock_run_dag_file, capsys, extra_args, message):
        args = self.parser.parse_args(["run", "pipeline.py", *extra_args])

        with pytest.raises(SystemExit) as ctx:
            args.func(args)

        assert ctx.value.code == 2
        err = capsys.readouterr().err
        assert err.startswith("Error: ")
        assert message in err
        mock_run_dag_file.assert_not_called()

    @pytest.mark.parametrize(
        ("error", "expected_code"),
        [
            pytest.param(DagExecutionError(make_result("failed", ran={("total", -1)})), 1, id="failed"),
            pytest.param(None, 0, id="succeeded"),
        ],
    )
    @mock.patch.object(run_command, "run_dag_file", autospec=True)
    def test_selection_prints_only_the_outputs_it_ran(self, mock_run_dag_file, capsys, error, expected_code):
        outputs = {("total", -1, "return_value"): 12, ("numbers", -1, "return_value"): [1, 2, 3]}
        mock_run_dag_file.return_value = make_result(outputs=outputs, ran={("total", -1)})
        mock_run_dag_file.side_effect = error
        args = self.parser.parse_args(["run", "pipeline.py", "--task", "total"])

        if expected_code:
            with pytest.raises(SystemExit) as ctx:
                args.func(args)
            assert ctx.value.code == expected_code
        else:
            args.func(args)

        assert capsys.readouterr().out.splitlines() == ["Outputs:", "  total = 12"]

    @pytest.mark.parametrize(
        ("error", "expected_code", "expected_out", "expected_err"),
        [
            pytest.param(
                DagExecutionError(make_result("failed")),
                1,
                "Outputs:\n  total = 12\n",
                "",
                id="failed-run",
            ),
            pytest.param(
                LocalRunUsageError("has no task 'totl'"), 2, "", "Error: has no task 'totl'\n", id="usage"
            ),
            pytest.param(
                FileNotFoundError("no python3.12"),
                4,
                "",
                "Error: no python3.12\n",
                id="file-missing-for-the-run",
            ),
            pytest.param(
                ValueError("keep its conf"), 2, "", "Error: keep its conf\n", id="invalid-selection"
            ),
            pytest.param(
                LocalRunDagFileError("No Dags found"), 3, "", "Error: No Dags found\n", id="dag-file"
            ),
            pytest.param(
                LocalRunConfigError("needs Linux or macOS"),
                4,
                "",
                "Error: needs Linux or macOS\n",
                id="config",
            ),
            pytest.param(
                PermissionError("cannot create .airflow"),
                4,
                "",
                "Error: cannot create .airflow\n",
                id="environment",
            ),
            pytest.param(
                LocalRunError("exited without reporting a result"),
                1,
                "",
                "Error: exited without reporting a result\n",
                id="no-result",
            ),
            pytest.param(KeyboardInterrupt(), 130, "", "", id="interrupt"),
        ],
    )
    @mock.patch.object(run_command, "run_dag_file", autospec=True)
    def test_exit_codes(self, mock_run_dag_file, capsys, error, expected_code, expected_out, expected_err):
        mock_run_dag_file.side_effect = error
        args = self.parser.parse_args(["run", "pipeline.py"])

        with pytest.raises(SystemExit) as ctx:
            args.func(args)

        assert ctx.value.code == expected_code
        # The run itself already reported failure or cancellation.
        assert capsys.readouterr() == (expected_out, expected_err)

    def test_print_outputs_prints_return_values_only_and_is_bounded(self, capsys):
        outputs: dict[tuple[str, int, str], object] = {
            (f"task_{i:02}", -1, "return_value"): i for i in range(12)
        }
        outputs[("agent", -1, "usage")] = {"requests": 1}
        outputs[("mapped", 3, "return_value")] = 3
        outputs[("mapped", 3, "custom")] = 1

        run_command.print_outputs(make_result(outputs=outputs))

        lines = capsys.readouterr().out.splitlines()
        assert lines[:3] == ["Outputs:", "  mapped[3] = 3", "  task_00 = 0"]
        assert lines[-1] == "  ... 3 more outputs"
        assert len(lines) == 12

    def test_print_outputs_shows_outputs_this_process_cannot_load_as_the_run_showed_them(self, capsys):
        result = DagRunResult(
            dag_id="example",
            run_id="manual__1",
            state="success",
            task_states={("report", -1): "success", ("summary", -1): "success", ("total", -1): "success"},
            project_home=Path("/project/.airflow"),
            outputs={("total", -1, "return_value"): 12},
            output_reprs={
                ("summary", -1, "return_value"): "Summary(rows=3)",
                ("total", -1, "return_value"): "12",
            },
            output_errors={
                ("report", -1, "return_value"): "ModuleNotFoundError: No module named 'reports'",
                ("summary", -1, "return_value"): "LocalRunError: Summary is defined in dag.py",
            },
        )

        run_command.print_outputs(result)

        assert capsys.readouterr().out.splitlines() == [
            "Outputs:",
            "  report: not loaded (ModuleNotFoundError: No module named 'reports')",
            "  summary = Summary(rows=3)",
            "  total = 12",
        ]

    def test_print_outputs_prints_nothing_without_outputs(self, capsys):
        run_command.print_outputs(make_result(outputs={}))

        assert capsys.readouterr().out == ""
