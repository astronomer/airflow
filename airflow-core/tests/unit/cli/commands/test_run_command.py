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

import runpy
from pathlib import Path
from unittest import mock

import pytest

from airflow.cli import cli_parser
from airflow.cli.commands import run_command
from airflow.sdk.definitions.local_run import DagRunResult
from airflow.sdk.exceptions import DagExecutionError, LocalRunError


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
        ran=frozenset(ran) if ran is not None else frozenset((t, m) for t, m, _ in outputs),
    )


class TestRunCommand:
    @classmethod
    def setup_class(cls):
        cls.parser = cli_parser.get_parser()

    @mock.patch.object(run_command.reprlib, "Repr", autospec=True)
    def test_import_supports_python_311_repr_constructor(self, mock_repr, capsys):
        # Python 3.11's Repr constructor accepts no arguments.
        mock_repr.side_effect = lambda: run_command._output_repr

        namespace = runpy.run_path(run_command.__file__)
        namespace["print_outputs"](make_result())

        assert capsys.readouterr().out == "Outputs:\n  total = 12\n"

    @pytest.mark.parametrize(("extra_args", "debug"), [([], False), (["--debug"], True)])
    @mock.patch.object(run_command, "run_dag_file", autospec=True)
    def test_passes_arguments_to_launcher(self, mock_run_dag_file, capsys, extra_args, debug):
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
            triggered_by="cli",
            debug=debug,
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
            "triggered_by": "cli",
            "debug": False,
        }

    @pytest.mark.parametrize("flag", [["--upstream"], ["--downstream"], ["--run-id", "manual__1"]])
    @mock.patch.object(run_command, "run_dag_file", autospec=True)
    def test_selection_options_need_a_selection(self, mock_run_dag_file, flag):
        args = self.parser.parse_args(["run", "pipeline.py", *flag])

        with pytest.raises(SystemExit, match="apply to the tasks chosen with --task or --group"):
            args.func(args)

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
            pytest.param(LocalRunError("No Dags found"), 2, "", "Error: No Dags found\n", id="setup-error"),
            pytest.param(
                FileNotFoundError("missing.yaml"), 2, "", "Error: missing.yaml\n", id="missing-file"
            ),
            pytest.param(
                ValueError("keep its conf"), 2, "", "Error: keep its conf\n", id="invalid-selection"
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

    @pytest.mark.parametrize(
        ("conf", "match"),
        [
            pytest.param("{not json", "--conf is not valid JSON", id="not-json"),
            pytest.param("[1]", "--conf must be a JSON object", id="not-object"),
        ],
    )
    @mock.patch.object(run_command, "run_dag_file", autospec=True)
    def test_invalid_conf_is_rejected_before_running(self, mock_run_dag_file, conf, match):
        args = self.parser.parse_args(["run", "pipeline.py", "--conf", conf])

        with pytest.raises(SystemExit, match=match):
            args.func(args)

        mock_run_dag_file.assert_not_called()

    def test_print_outputs_is_bounded(self, capsys):
        outputs = {(f"task_{i:02}", -1, "return_value"): "x" * 200 for i in range(12)}
        outputs[("mapped", 3, "custom")] = 1

        run_command.print_outputs(make_result(outputs=outputs))

        lines = capsys.readouterr().out.splitlines()
        assert lines[:2] == ["Outputs:", "  mapped[3] custom = 1"]
        assert len(lines[2]) < 100
        assert lines[-1] == "  ... 3 more outputs"

    def test_print_outputs_lists_outputs_it_could_not_load(self, capsys):
        result = DagRunResult(
            dag_id="example",
            run_id="manual__1",
            state="success",
            task_states={("summary", -1): "success", ("total", -1): "success"},
            project_home=Path("/project/.airflow"),
            outputs={("total", -1, "return_value"): 12},
            output_errors={("summary", -1, "return_value"): "LocalRunError: Summary is defined in dag.py"},
        )

        run_command.print_outputs(result)

        assert capsys.readouterr().out.splitlines() == [
            "Outputs:",
            "  summary: not loaded (LocalRunError: Summary is defined in dag.py)",
            "  total = 12",
        ]

    def test_print_outputs_prints_nothing_without_outputs(self, capsys):
        run_command.print_outputs(make_result(outputs={}))

        assert capsys.readouterr().out == ""
