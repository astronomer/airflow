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

import json
from unittest import mock

import pytest

from airflow.cli.cli_parser import get_parser
from airflow.cli.commands.local_task_command import task_run_local
from airflow.sdk._shared.secrets_masker import mask_secret
from airflow.sdk.api.datamodels._generated import AssetProfile
from airflow.sdk.execution_time.local_runner import LocalTaskResult


@pytest.mark.parametrize("option", ["--params", "--upstream-xcoms"])
@pytest.mark.parametrize("value", ["null", "[]", "12", "invalid"])
@mock.patch("airflow.cli.commands.local_task_command.run_task_local", autospec=True)
def test_invalid_json_arguments_fail_before_execution(run, option, value, capsys):
    args = get_parser().parse_args(
        ["tasks", "run-local", "task.py", "work", "--dag-id", "example", option, value]
    )
    with pytest.raises(SystemExit) as error:
        task_run_local(args)
    assert error.value.code == 1
    run.assert_not_called()
    assert "Local task failed:" in capsys.readouterr().err


@mock.patch("airflow.cli.commands.local_task_command.run_task_local", autospec=True)
def test_cancellation_cleanup_failure_is_reported_without_traceback(run, capsys):
    run.side_effect = RuntimeError("Local task descendants did not stop after SIGKILL")
    args = get_parser().parse_args(["tasks", "run-local", "task.py", "work", "--dag-id", "example"])
    with pytest.raises(SystemExit) as error:
        task_run_local(args)
    assert error.value.code == 1
    output = capsys.readouterr()
    assert output.err == "Local task failed: Local task descendants did not stop after SIGKILL\n"
    assert output.out == ""


@pytest.mark.parametrize(
    ("state", "exit_code", "xcoms", "diagnostic"),
    [
        ("success", 0, {"return_value": None}, None),
        ("failed", 1, {}, "Unsupported feature"),
        ("cancelled", 1, {}, "Task was cancelled by SIGINT"),
    ],
)
@mock.patch("airflow.cli.commands.local_task_command.run_task_local", autospec=True)
def test_prints_published_return_and_propagates_outcome(run, state, exit_code, xcoms, diagnostic, capsys):
    run.return_value = LocalTaskResult(
        run_id="local-test",
        task_instance_id="instance",
        try_number=1,
        state=state,
        exit_code=exit_code,
        process_exit_code=0,
        diagnostic=diagnostic,
        rendered_fields={"op_args": "[]"},
        xcoms=xcoms,
        asset_outputs={"outlets": ["s3://local/output"]},
        skipped_downstream_tasks=[],
        diagnostics=["Asset registry validation skipped"],
    )
    args = get_parser().parse_args(
        ["tasks", "run-local", "task.py", "work", "--dag-id", "example", "--params", '{"count": 3}']
    )
    with pytest.raises(SystemExit) as error:
        task_run_local(args)
    assert error.value.code == exit_code
    output = capsys.readouterr()
    assert f"Final state: {state}" in output.out
    assert ("Return value: null" if xcoms else "no return value published") in output.out
    assert "Asset outputs (not recorded locally)" in output.out
    assert "Downstream tasks that would be skipped" not in output.out
    assert "Asset registry validation skipped" in output.err
    if diagnostic:
        assert diagnostic in output.err
    assert run.call_args.kwargs["params"] == {"count": 3}


@mock.patch("airflow.cli.commands.local_task_command.run_task_local", autospec=True)
def test_prints_downstream_tasks_that_would_be_skipped(run, capsys):
    run.return_value = LocalTaskResult(
        run_id="local-test",
        task_instance_id="instance",
        try_number=1,
        state="success",
        exit_code=0,
        process_exit_code=0,
        diagnostic=None,
        rendered_fields={},
        xcoms={"skipmixin_key": {"followed": ["followed_branch"]}},
        asset_outputs={},
        skipped_downstream_tasks=["unfollowed_branch", "after_check"],
        diagnostics=[],
    )
    args = get_parser().parse_args(["tasks", "run-local", "task.py", "choose", "--dag-id", "example"])
    with pytest.raises(SystemExit) as error:
        task_run_local(args)
    assert error.value.code == 0
    assert (
        'Downstream tasks that would be skipped: ["unfollowed_branch", "after_check"]'
        in capsys.readouterr().out
    )


@pytest.mark.enable_redact
@mock.patch("airflow.cli.commands.local_task_command.run_task_local", autospec=True)
def test_redacts_asset_models_before_printing(run, capsys):
    secret = "registered-asset-connection-password"
    mask_secret(secret)
    run.return_value = LocalTaskResult(
        run_id="local-test",
        task_instance_id="instance",
        try_number=1,
        state="success",
        exit_code=0,
        process_exit_code=0,
        diagnostic=None,
        rendered_fields={},
        xcoms={},
        asset_outputs={
            "outlets": [AssetProfile(name="report", uri=f"s3://reports/{secret}", type="Asset")],
            "events": [{"extra": {"password": "unregistered-sensitive-value", "count": 3}}],
        },
        skipped_downstream_tasks=[],
        diagnostics=[],
    )
    args = get_parser().parse_args(["tasks", "run-local", "task.py", "work", "--dag-id", "example"])

    with pytest.raises(SystemExit) as error:
        task_run_local(args)

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert secret not in output
    assert "unregistered-sensitive-value" not in output
    asset_line = next(line for line in output.splitlines() if line.startswith("Asset outputs"))
    assert json.loads(asset_line.split(": ", 1)[1]) == {
        "outlets": [{"name": "report", "uri": "s3://reports/***", "type": "Asset"}],
        "events": [{"extra": {"password": "***", "count": 3}}],
    }
