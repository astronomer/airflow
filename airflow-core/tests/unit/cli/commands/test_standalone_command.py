#
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
import os
import subprocess
import sys
from collections import deque
from importlib import reload
from unittest import mock

import pytest

from airflow.cli import cli_parser
from airflow.cli.commands import standalone_command
from airflow.cli.commands.standalone_command import StandaloneCommand, SubCommand
from airflow.configuration import conf
from airflow.executors import executor_loader
from airflow.executors.executor_constants import (
    CELERY_EXECUTOR,
    KUBERNETES_EXECUTOR,
    LOCAL_EXECUTOR,
)

from tests_common.test_utils.config import conf_vars


def default_dag_discovery_config():
    """Dag discovery options at their defaults, as the generated airflow.cfg writes them."""
    return {
        ("dag_processor", key): conf.get_default_value("dag_processor", key)
        for key in ("refresh_interval", "dag_bundle_config_list")
    }


class TestStandaloneCommand:
    @pytest.mark.parametrize(
        "conf_executor_name",
        [LOCAL_EXECUTOR, CELERY_EXECUTOR, KUBERNETES_EXECUTOR],
    )
    def test_calculate_env(self, conf_executor_name):
        """Should always force a local executor compatible with the db."""
        with mock.patch.dict(
            "os.environ",
            {
                "AIRFLOW__CORE__EXECUTOR": conf_executor_name,
            },
        ):
            reload(executor_loader)
            env = StandaloneCommand().calculate_env()
            # all non local executors will fall back to localesecutor
            assert env["AIRFLOW__CORE__EXECUTOR"] == LOCAL_EXECUTOR

    @mock.patch("airflow.cli.commands.standalone_command.ExecutorLoader.import_default_executor_cls")
    @mock.patch("airflow.cli.commands.standalone_command.conf.get")
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_calculate_env_force_executor_and_auth(self, mock_conf_get, mock_import):
        class FakeExecutor:
            is_local = False

        mock_import.return_value = (FakeExecutor, None)
        mock_conf_get.return_value = "wrong.auth.manager"
        cmd = StandaloneCommand()
        env = cmd.calculate_env()

        assert env["AIRFLOW__CORE__EXECUTOR"] == "LocalExecutor"
        assert "AIRFLOW__CORE__AUTH_MANAGER" in env

    @mock.patch("airflow.cli.commands.standalone_command.ExecutorLoader.import_default_executor_cls")
    @mock.patch("airflow.cli.commands.standalone_command.conf.get")
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_calculate_env_does_not_override_auth_if_already_set(self, mock_conf_get, mock_import):
        class FakeExecutor:
            is_local = True

        mock_import.return_value = (FakeExecutor, None)
        mock_conf_get.return_value = (
            "airflow.api_fastapi.auth.managers.simple.simple_auth_manager.SimpleAuthManager"
        )
        cmd = StandaloneCommand()
        env = cmd.calculate_env()

        assert "AIRFLOW__CORE__AUTH_MANAGER" not in env

    def test_calculate_env_refreshes_dags_folder_on_every_bundle_check_by_default(self):
        """The generated airflow.cfg spells out every default, which must not count as a user choice."""
        config = {**default_dag_discovery_config(), ("dag_processor", "bundle_refresh_check_interval"): "5"}
        with conf_vars(config), mock.patch.dict(os.environ):
            env = StandaloneCommand().calculate_env()

        assert env["AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL"] == "5"

    @pytest.mark.parametrize(
        ("config", "environ"),
        [
            pytest.param({("dag_processor", "refresh_interval"): "60"}, {}, id="interval-in-airflow-cfg"),
            pytest.param({}, {"AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL": "60"}, id="interval-in-env"),
            pytest.param(
                {}, {"AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL": "300"}, id="default-interval-in-env"
            ),
            pytest.param(
                {
                    ("dag_processor", "dag_bundle_config_list"): json.dumps(
                        [
                            {
                                "name": "my-git-repo",
                                "classpath": "airflow.providers.git.bundles.git.GitDagBundle",
                                "kwargs": {},
                            }
                        ]
                    )
                },
                {},
                id="custom-bundles",
            ),
        ],
    )
    def test_calculate_env_keeps_user_chosen_dag_discovery(self, config, environ):
        with conf_vars({**default_dag_discovery_config(), **config}), mock.patch.dict(os.environ, environ):
            env = StandaloneCommand().calculate_env()

        assert env.get("AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL") == environ.get(
            "AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL"
        )

    @mock.patch("airflow.cli.commands.standalone_command.os.path.exists", return_value=False)
    @mock.patch("airflow.cli.commands.standalone_command.create_auth_manager")
    @mock.patch("airflow.cli.commands.standalone_command.conf.get")
    def test_find_user_info_generates_password(self, mock_conf, mock_auth, mock_exists):
        def conf_side(section, key):
            if key == "simple_auth_manager_all_admins":
                return "false"
            if key == "simple_auth_manager_users":
                return "admin:admin"
            return ""

        mock_conf.side_effect = conf_side
        am = mock.Mock()
        am.get_generated_password_file.return_value = "/tmp/fake"
        mock_auth.return_value = am
        cmd = StandaloneCommand()
        cmd.find_user_info()

        am.init.assert_called_once()

    @mock.patch("airflow.cli.commands.standalone_command.create_auth_manager")
    @mock.patch("airflow.cli.commands.standalone_command.conf.get")
    def test_find_user_info_skips_when_all_admins_true(self, mock_conf_get, mock_create_auth):
        def conf_side(section, key):
            if key == "simple_auth_manager_all_admins":
                return "true"
            return ""

        mock_conf_get.side_effect = conf_side
        cmd = StandaloneCommand()
        cmd.find_user_info()

        mock_create_auth.assert_not_called()

    @mock.patch("airflow.cli.commands.standalone_command.create_auth_manager")
    @mock.patch("airflow.cli.commands.standalone_command.conf.get")
    def test_find_user_info_skips_when_users_already_configured(self, mock_conf_get, mock_create_auth):
        def conf_side(section, key):
            if key == "simple_auth_manager_all_admins":
                return "false"
            if key == "simple_auth_manager_users":
                return "custom:password"
            return ""

        mock_conf_get.side_effect = conf_side
        cmd = StandaloneCommand()
        cmd.find_user_info()

        mock_create_auth.assert_not_called()

    @mock.patch("airflow.cli.commands.standalone_command.os.path.exists", return_value=True)
    @mock.patch("airflow.cli.commands.standalone_command.create_auth_manager")
    @mock.patch("airflow.cli.commands.standalone_command.conf.get")
    def test_find_user_info_skips_when_password_file_exists(
        self, mock_conf_get, mock_create_auth, mock_exists
    ):
        def conf_side(section, key):
            if key == "simple_auth_manager_all_admins":
                return "false"
            if key == "simple_auth_manager_users":
                return "admin:admin"
            return ""

        mock_conf_get.side_effect = conf_side
        am = mock.Mock()
        am.get_generated_password_file.return_value = "/tmp/fake"
        mock_create_auth.return_value = am
        cmd = StandaloneCommand()
        cmd.find_user_info()

        am.init.assert_not_called()

    @mock.patch("airflow.cli.commands.standalone_command.db.initdb")
    def test_initialize_database(self, mock_initdb, monkeypatch):
        cmd = StandaloneCommand()
        monkeypatch.setattr(cmd, "print_output", lambda *a: None)
        cmd.initialize_database()

        mock_initdb.assert_called_once()

    @mock.patch("builtins.print")
    def test_print_output(self, mock_print):
        cmd = StandaloneCommand()
        cmd.print_output("scheduler", "hello\nworld")

        assert mock_print.call_count == 2

    @mock.patch(
        "airflow.cli.commands.standalone_command.most_recent_job",
        return_value=None,
    )
    def test_job_running_returns_false_if_no_recent_job(self, mock_most_recent_job):
        result = StandaloneCommand().job_running(mock.Mock(job_type="scheduler"))
        assert result is False

    @mock.patch("airflow.cli.commands.standalone_command.most_recent_job")
    def test_job_running_returns_false_if_job_not_alive(self, mock_most_recent_job):
        fake_job = mock.Mock()
        fake_job.is_alive.return_value = False
        mock_most_recent_job.return_value = fake_job

        result = StandaloneCommand().job_running(mock.Mock(job_type="scheduler"))
        assert result is False

    @mock.patch("airflow.cli.commands.standalone_command.most_recent_job")
    def test_job_running_returns_true_if_alive(self, mock_most_recent_job):
        fake_job = mock.Mock()
        fake_job.is_alive.return_value = True
        mock_most_recent_job.return_value = fake_job

        result = StandaloneCommand().job_running(mock.Mock(job_type="scheduler"))
        assert result is True

    @pytest.mark.parametrize(
        ("api_server_listening", "jobs_running", "expected"),
        [
            pytest.param(True, [True, True, True], True, id="every-component-ready"),
            pytest.param(True, [True, False], False, id="component-not-heartbeating"),
            pytest.param(False, [], False, id="api-server-port-closed"),
        ],
    )
    def test_is_ready(self, monkeypatch, api_server_listening, jobs_running, expected):
        cmd = StandaloneCommand()
        cmd.api_server_port = 9999
        port_open = mock.Mock(return_value=api_server_listening)
        jobs = iter(jobs_running)
        monkeypatch.setattr(cmd, "port_open", port_open)
        monkeypatch.setattr(cmd, "job_running", lambda *_: next(jobs))

        assert cmd.is_ready() is expected
        port_open.assert_called_once_with(9999)

    @conf_vars({("api", "port"): "9999"})
    @mock.patch("airflow.cli.commands.standalone_command.SubCommand", autospec=True)
    @mock.patch.object(StandaloneCommand, "initialize_database")
    @mock.patch.object(StandaloneCommand, "find_user_info")
    @mock.patch.object(StandaloneCommand, "calculate_env", return_value={})
    @mock.patch.object(StandaloneCommand, "print_output")
    def test_run_resolves_the_api_server_port_from_config(self, *_):
        cmd = StandaloneCommand()
        with mock.patch.object(cmd, "update_output", side_effect=KeyboardInterrupt):
            cmd.run()

        assert cmd.api_server_port == 9999

    @pytest.mark.parametrize("exc", [OSError, ValueError])
    def test_port_open_returns_false_on_errors(self, monkeypatch, exc):
        cmd = StandaloneCommand()

        class FakeSocket:
            def settimeout(self, *_):
                pass

            def connect(self, *_):
                raise exc()

            def close(self):
                pass

        monkeypatch.setattr(
            "airflow.cli.commands.standalone_command.socket.socket",
            lambda *a, **k: FakeSocket(),
        )
        assert cmd.port_open(1234) is False

    def test_port_open_returns_true_when_connect_succeeds(self, monkeypatch):
        cmd = StandaloneCommand()

        class FakeSocket:
            def settimeout(self, *_):
                pass

            def connect(self, *_):
                pass

            def close(self):
                pass

        monkeypatch.setattr(
            "airflow.cli.commands.standalone_command.socket.socket",
            lambda *a, **k: FakeSocket(),
        )

        assert cmd.port_open(1234) is True

    def test_update_output_drains_queue_and_prints(self, monkeypatch):
        cmd = StandaloneCommand()
        printed = deque()
        monkeypatch.setattr(cmd, "print_output", lambda name, msg: printed.append((name, msg)))
        cmd.output_queue.append(("scheduler", b"hello\n"))
        cmd.output_queue.append(("api-server", b"world\n"))
        cmd.update_output()

        assert printed == deque(
            [
                ("scheduler", "hello"),
                ("api-server", "world"),
            ]
        )
        assert len(cmd.output_queue) == 0

    def test_print_error_calls_print_output(self, monkeypatch):
        cmd = StandaloneCommand()
        called = []
        monkeypatch.setattr(cmd, "print_output", lambda name, msg: called.append((name, msg)))
        cmd.print_error("scheduler", "boom")

        assert called

    def test_subcommand_run_appends_output(self, monkeypatch):
        parent = mock.Mock()
        parent.output_queue = deque()
        fake_process = mock.Mock()
        fake_process.stdout = [b"line1\n", b"line2\n"]
        monkeypatch.setattr(
            "airflow.cli.commands.standalone_command.subprocess.Popen",
            lambda *a, **k: fake_process,
        )
        cmd = SubCommand(parent, "scheduler", ["scheduler"], {})
        cmd.run()

        assert parent.output_queue == deque(
            [
                ("scheduler", b"line1\n"),
                ("scheduler", b"line2\n"),
            ]
        )

    def test_subcommand_stop_calls_terminate(self, monkeypatch):
        parent = mock.Mock()
        fake_process = mock.Mock()
        monkeypatch.setattr(
            "airflow.cli.commands.standalone_command.subprocess.Popen",
            lambda *a, **k: fake_process,
        )
        cmd = SubCommand(parent, "scheduler", ["scheduler"], {})
        cmd.process = fake_process
        cmd.stop()

        fake_process.terminate.assert_called_once()

    def test_subcommand_stop_does_not_block_siblings_when_a_process_never_started(self):
        """Shutdown stops each component in turn, so one that never spawned must not abort the loop."""
        never_started = SubCommand(mock.Mock(spec=StandaloneCommand), "scheduler", ["scheduler"], {})
        running = SubCommand(mock.Mock(spec=StandaloneCommand), "triggerer", ["triggerer"], {})
        running.process = mock.Mock(spec=subprocess.Popen)

        assert never_started.process is None
        for command in (never_started, running):
            command.stop()

        running.process.terminate.assert_called_once()

    @mock.patch("airflow.cli.commands.standalone_command.ExecutorLoader.import_default_executor_cls")
    @mock.patch("airflow.cli.commands.standalone_command.conf.get")
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_calculate_env_does_not_force_executor_when_already_local(self, mock_conf_get, mock_import):
        class LocalExecutor:
            is_local = True

        mock_import.return_value = (LocalExecutor, None)
        mock_conf_get.return_value = (
            "airflow.api_fastapi.auth.managers.simple.simple_auth_manager.SimpleAuthManager"
        )
        cmd = StandaloneCommand()
        env = cmd.calculate_env()

        assert "AIRFLOW__CORE__EXECUTOR" not in env


class TestStandaloneEntrypoint:
    @classmethod
    def setup_class(cls):
        cls.parser = cli_parser.get_parser()

    @mock.patch.object(StandaloneCommand, "run", autospec=True)
    @mock.patch.object(standalone_command, "serve_project_history", autospec=True)
    def test_without_project_runs_every_component(self, mock_serve_project_history, mock_run):
        args = self.parser.parse_args(["standalone"])

        args.func(args)

        mock_run.assert_called_once()
        mock_serve_project_history.assert_not_called()

    @mock.patch.object(StandaloneCommand, "run", autospec=True)
    def test_port_without_project_is_refused(self, mock_run):
        args = self.parser.parse_args(["standalone", "--port", "8091"])

        with pytest.raises(SystemExit, match="--port needs --project"):
            args.func(args)

        mock_run.assert_not_called()


class TestStandaloneProject:
    @classmethod
    def setup_class(cls):
        cls.parser = cli_parser.get_parser()

    @pytest.mark.parametrize(
        ("has_pyproject", "cwd"),
        [
            pytest.param(True, "pipelines", id="pyproject-above"),
            pytest.param(False, ".", id="history-without-pyproject"),
        ],
    )
    @mock.patch.object(standalone_command.os, "execve", autospec=True)
    def test_starts_the_server_for_the_project_around_the_current_directory(
        self, mock_execve, tmp_path, monkeypatch, has_pyproject, cwd
    ):
        if has_pyproject:
            (tmp_path / "pyproject.toml").touch()
        else:
            (tmp_path / ".airflow").mkdir()
        (tmp_path / cwd).mkdir(exist_ok=True)
        monkeypatch.chdir(tmp_path / cwd)
        args = self.parser.parse_args(["standalone", "--project"])

        args.func(args)

        mock_execve.assert_called_once_with(
            sys.executable, [sys.executable, "-m", "airflow.local_run.ui_server"], mock.ANY
        )
        env = mock_execve.call_args.args[2]
        assert env["AIRFLOW_HOME"] == str(tmp_path / ".airflow")
        assert env["AIRFLOW__CORE__DAGS_FOLDER"] == str(tmp_path)
        assert env.items() >= standalone_command.PROJECT_SERVER_ENVIRONMENT.items()

    @mock.patch.object(standalone_command.os, "execve", autospec=True)
    def test_port_is_passed_to_the_server(self, mock_execve, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").touch()
        monkeypatch.chdir(tmp_path)
        args = self.parser.parse_args(["standalone", "--project", "--port", "8091"])

        args.func(args)

        assert mock_execve.call_args.args[1] == [sys.executable, "-m", "airflow.local_run.ui_server", "8091"]

    @mock.patch.object(standalone_command.os, "execve", autospec=True)
    @mock.patch.object(standalone_command, "read_live_ui_url", autospec=True)
    def test_running_ui_is_reused(self, mock_read_live_ui_url, mock_execve, tmp_path, monkeypatch, capsys):
        (tmp_path / "pyproject.toml").touch()
        monkeypatch.chdir(tmp_path)
        mock_read_live_ui_url.return_value = "http://127.0.0.1:8080/"
        args = self.parser.parse_args(["standalone", "--project"])

        args.func(args)

        mock_execve.assert_not_called()
        assert (
            capsys.readouterr().out == f"The UI for {tmp_path} is already running: http://127.0.0.1:8080/\n"
        )

    @mock.patch.object(standalone_command.os, "execve", autospec=True)
    def test_folder_outside_a_project_is_refused(self, mock_execve, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        args = self.parser.parse_args(["standalone", "--project"])

        with pytest.raises(
            SystemExit, match=f"No project in {tmp_path}: run airflow standalone --project in"
        ):
            args.func(args)

        mock_execve.assert_not_called()
        assert not (tmp_path / ".airflow").exists()
