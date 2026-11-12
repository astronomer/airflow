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

import argparse
import json
import os
import signal
import subprocess
import sys
from collections import deque
from importlib import reload
from unittest import mock

import pytest

from airflow.api_fastapi.auth.managers.simple.simple_auth_manager import SimpleAuthManager
from airflow.cli.commands.standalone_command import IMPORTANT_LINE, StandaloneCommand, SubCommand
from airflow.configuration import conf
from airflow.executors import executor_loader
from airflow.executors.executor_constants import (
    CELERY_EXECUTOR,
    KUBERNETES_EXECUTOR,
    LOCAL_EXECUTOR,
)
from airflow.jobs.dag_processor_job_runner import DagProcessorJobRunner
from airflow.jobs.scheduler_job_runner import SchedulerJobRunner
from airflow.jobs.triggerer_job_runner import TriggererJobRunner

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
    @mock.patch.object(StandaloneCommand, "open_log_files")
    @mock.patch.object(StandaloneCommand, "record_previous_jobs")
    @mock.patch.object(StandaloneCommand, "initialize_database")
    @mock.patch.object(StandaloneCommand, "find_user_info")
    @mock.patch.object(StandaloneCommand, "calculate_env", return_value={})
    @mock.patch.object(StandaloneCommand, "print_output")
    def test_run_resolves_the_api_server_port_from_config(self, *_):
        cmd = StandaloneCommand()
        # The second call drains what the components print while stopping.
        with mock.patch.object(cmd, "update_output", side_effect=[KeyboardInterrupt, None]):
            cmd.run()

        assert cmd.api_server_port == 9999

    @mock.patch("airflow.cli.commands.standalone_command.most_recent_job")
    def test_job_running_ignores_a_job_from_before_this_start(self, mock_most_recent_job):
        stale_job = mock.Mock(id=7)
        stale_job.is_alive.return_value = True
        mock_most_recent_job.return_value = stale_job
        cmd = StandaloneCommand()
        cmd.record_previous_jobs()

        assert cmd.job_running(SchedulerJobRunner) is False

        mock_most_recent_job.return_value = mock.Mock(id=8, **{"is_alive.return_value": True})
        assert cmd.job_running(SchedulerJobRunner) is True

    @mock.patch("airflow.cli.commands.standalone_command.most_recent_job", return_value=None)
    def test_record_previous_jobs_without_earlier_jobs(self, _):
        cmd = StandaloneCommand()
        cmd.record_previous_jobs()

        assert cmd.previous_job_ids == {
            SchedulerJobRunner.job_type: None,
            DagProcessorJobRunner.job_type: None,
            TriggererJobRunner.job_type: None,
        }

    @mock.patch("airflow.cli.commands.standalone_command.SubCommand", autospec=True)
    @mock.patch.object(StandaloneCommand, "open_log_files")
    @mock.patch.object(StandaloneCommand, "record_previous_jobs")
    @mock.patch.object(StandaloneCommand, "initialize_database")
    @mock.patch.object(StandaloneCommand, "find_user_info")
    @mock.patch.object(StandaloneCommand, "calculate_env", return_value={})
    @mock.patch.object(StandaloneCommand, "print_output")
    def test_run_shuts_down_on_sigterm_and_restores_the_handler(self, *_):
        cmd = StandaloneCommand()
        handlers_during_run = []

        def receive_sigterm():
            handlers_during_run.append(signal.getsignal(signal.SIGTERM))
            cmd.handle_sigterm(signal.SIGTERM, None)

        previous_handler = signal.getsignal(signal.SIGTERM)
        with (
            mock.patch.object(cmd, "update_output", side_effect=receive_sigterm),
            mock.patch.object(cmd, "stop_components") as stop_components,
        ):
            cmd.run()

        assert handlers_during_run == [StandaloneCommand.handle_sigterm]
        assert signal.getsignal(signal.SIGTERM) == previous_handler
        stop_components.assert_called_once()

    @mock.patch("airflow.cli.commands.standalone_command.SubCommand", autospec=True)
    @mock.patch.object(StandaloneCommand, "open_log_files")
    @mock.patch.object(StandaloneCommand, "record_previous_jobs")
    @mock.patch.object(StandaloneCommand, "initialize_database")
    @mock.patch.object(StandaloneCommand, "find_user_info")
    @mock.patch.object(StandaloneCommand, "calculate_env", return_value={})
    @mock.patch.object(StandaloneCommand, "print_output")
    def test_run_stops_and_fails_when_a_component_exits(self, *_):
        cmd = StandaloneCommand()
        exited = mock.Mock(spec=SubCommand)
        exited.name = "scheduler"
        exited.process = mock.Mock(spec=subprocess.Popen, returncode=3)
        exited.process.poll.return_value = 3

        with (
            mock.patch.object(cmd, "update_output"),
            mock.patch.object(cmd, "find_exited_component", return_value=exited),
            mock.patch.object(cmd, "stop_components") as stop_components,
            mock.patch.object(cmd, "print_error") as print_error,
            mock.patch.object(cmd, "print_recent_lines") as print_recent_lines,
            pytest.raises(SystemExit) as exit_info,
        ):
            cmd.run()

        assert exit_info.value.code == 1
        stop_components.assert_called_once()
        print_error.assert_called_once_with("standalone", "The scheduler component exited with code 3")
        print_recent_lines.assert_called_once_with("scheduler")

    def test_find_exited_component(self):
        cmd = StandaloneCommand()
        running = SubCommand(cmd, "api-server", ["api-server"], {})
        running.process = mock.Mock(spec=subprocess.Popen, **{"poll.return_value": None})
        not_started = SubCommand(cmd, "triggerer", ["triggerer"], {})
        cmd.subcommands = {"api-server": running, "triggerer": not_started}

        assert cmd.find_exited_component() is None

        running.process.poll.return_value = 1
        assert cmd.find_exited_component() is running

    def test_stop_components_terminates_then_waits_for_each(self):
        cmd = StandaloneCommand()
        commands = [mock.Mock(spec=SubCommand) for _ in range(2)]
        cmd.subcommands = {str(index): command for index, command in enumerate(commands)}

        with mock.patch.object(cmd, "print_output"), mock.patch.object(cmd, "update_output") as update:
            cmd.stop_components()

        for command in commands:
            command.stop.assert_called_once()
            command.wait_or_kill.assert_called_once()
        update.assert_called_once()

    @pytest.mark.parametrize(
        ("verbose", "shown"),
        [
            pytest.param(False, ["[error    ] Dag import failed"], id="quiet-shows-errors-only"),
            pytest.param(True, ["GET /api/v2/version 200", "[error    ] Dag import failed"], id="verbose"),
        ],
    )
    def test_update_output_logs_each_component_and_shows_what_matters(self, tmp_path, verbose, shown):
        cmd = StandaloneCommand(verbose=verbose)
        cmd.log_files = {name: (tmp_path / f"{name}.log").open("a") for name in ("api-server", "scheduler")}
        printed = []
        cmd.output_queue.extend(
            [
                ("api-server", b"GET /api/v2/version 200\n"),
                ("scheduler", b"\x1b[31m[error    ] Dag import failed\n"),
            ]
        )

        with mock.patch.object(cmd, "print_output", side_effect=lambda name, line: printed.append(line)):
            cmd.update_output()
        for log_file in cmd.log_files.values():
            log_file.close()

        assert printed == shown
        assert (tmp_path / "api-server.log").read_text() == "GET /api/v2/version 200\n"
        assert (tmp_path / "scheduler.log").read_text() == "[error    ] Dag import failed\n"
        assert list(cmd.recent_lines["scheduler"]) == ["[error    ] Dag import failed"]

    def test_update_output_shows_lines_it_has_no_file_for(self):
        cmd = StandaloneCommand()
        cmd.output_queue.append(("scheduler", b"started\n"))

        with mock.patch.object(cmd, "print_output") as print_output:
            cmd.update_output()

        print_output.assert_called_once_with("scheduler", "started")

    @pytest.mark.parametrize(
        "line",
        [
            "2026-11-12T09:18:27Z [critical ] scheduler crashed",
            '{"event": "boom", "level": "error"}',
            "ERROR:    Exception in ASGI application",
        ],
    )
    def test_important_lines(self, line):
        assert IMPORTANT_LINE.search(line)

    def test_info_lines_are_not_important(self):
        assert not IMPORTANT_LINE.search("2026-11-12T09:18:27Z [info     ] Starting the scheduler")

    def test_open_log_files_creates_one_per_component_and_keeps_the_previous_run(self, tmp_path):
        log_dir = tmp_path / "standalone"
        log_dir.mkdir()
        (log_dir / "scheduler.log").write_text("previous run\n")
        cmd = StandaloneCommand()

        with (
            conf_vars({("logging", "base_log_folder"): str(tmp_path)}),
            mock.patch.object(cmd, "print_output"),
        ):
            cmd.open_log_files()
        for log_file in cmd.log_files.values():
            log_file.close()

        assert cmd.log_dir == log_dir
        assert sorted(path.name for path in log_dir.iterdir()) == [
            "api-server.log",
            "dag-processor.log",
            "scheduler.log",
            "scheduler.log.1",
            "standalone.log",
            "triggerer.log",
        ]
        assert (log_dir / "scheduler.log.1").read_text() == "previous run\n"
        assert (log_dir / "scheduler.log").read_text() == ""
        assert cmd.get_log_path("triggerer") == log_dir / "triggerer.log"

    def test_redirect_output_to_log_captures_file_descriptor_writes(self, tmp_path):
        cmd = StandaloneCommand()
        cmd.log_files = {"standalone": (tmp_path / "standalone.log").open("a")}

        with cmd.redirect_output_to_log():
            os.write(1, b"from fd 1\n")
            os.write(2, b"from fd 2\n")
        os.write(1, b"")  # fd 1 is usable again
        cmd.log_files["standalone"].close()

        assert (tmp_path / "standalone.log").read_text() == "from fd 1\nfrom fd 2\n"

    def test_redirect_output_to_log_does_nothing_when_verbose(self, tmp_path):
        cmd = StandaloneCommand(verbose=True)
        cmd.log_files = {"standalone": mock.Mock()}

        with mock.patch("airflow.cli.commands.standalone_command.os.dup2") as dup2:
            with cmd.redirect_output_to_log():
                pass

        dup2.assert_not_called()

    @conf_vars({("core", "simple_auth_manager_all_admins"): "True"})
    def test_get_login_lines_without_login(self):
        assert StandaloneCommand().get_login_lines() == [
            "No login needed: every user is an admin ([core] simple_auth_manager_all_admins)"
        ]

    @conf_vars({("core", "simple_auth_manager_all_admins"): "False"})
    def test_get_login_lines_shows_generated_passwords(self, tmp_path):
        password_file = tmp_path / "passwords.json.generated"
        password_file.write_text('{"admin": "s3cret", "viewer": "v1ew"}\n')

        with mock.patch.object(
            SimpleAuthManager, "get_generated_password_file", return_value=str(password_file)
        ):
            lines = StandaloneCommand().get_login_lines()

        assert lines == ["Log in as admin with password s3cret", "Log in as viewer with password v1ew"]

    def test_get_login_lines_only_names_a_configured_passwords_file(self, tmp_path):
        password_file = tmp_path / "my-passwords.json"
        password_file.write_text('{"admin": "mine"}\n')

        with conf_vars(
            {
                ("core", "simple_auth_manager_all_admins"): "False",
                ("core", "simple_auth_manager_passwords_file"): str(password_file),
            }
        ):
            lines = StandaloneCommand().get_login_lines()

        assert lines == [f"Passwords are in {password_file}"]

    @conf_vars({("core", "simple_auth_manager_all_admins"): "False"})
    def test_get_login_lines_before_passwords_exist(self, tmp_path):
        with mock.patch.object(
            SimpleAuthManager, "get_generated_password_file", return_value=str(tmp_path / "missing")
        ):
            assert StandaloneCommand().get_login_lines() == []

    def test_print_ready_shows_url_login_and_log_path(self, tmp_path):
        cmd = StandaloneCommand()
        cmd.api_server_port = 8080
        cmd.log_dir = tmp_path
        printed = []

        with (
            mock.patch.object(cmd, "get_login_lines", return_value=["Log in as admin with password x"]),
            mock.patch.object(cmd, "print_output", side_effect=lambda name, line: printed.append(line)),
        ):
            cmd.print_ready()

        assert "Airflow is ready at http://localhost:8080" in printed
        assert "Log in as admin with password x" in printed
        assert f"Component logs: {tmp_path}/<component>.log" in printed

    def test_print_recent_lines(self):
        cmd = StandaloneCommand()
        cmd.recent_lines["scheduler"] = deque(["one", "two"])
        printed = []

        with mock.patch.object(
            cmd, "print_output", side_effect=lambda name, line: printed.append((name, line))
        ):
            cmd.print_recent_lines("scheduler")

        assert printed[1:] == [("scheduler", "one"), ("scheduler", "two")]

    @mock.patch.object(StandaloneCommand, "run")
    def test_entrypoint_passes_verbose(self, mock_run):
        with mock.patch.object(StandaloneCommand, "__init__", return_value=None) as init:
            StandaloneCommand.entrypoint(argparse.Namespace(verbose=True))

        init.assert_called_once_with(verbose=True)

    def test_subcommand_wait_or_kill_kills_after_timeout(self):
        parent = mock.Mock(spec=StandaloneCommand)
        cmd = SubCommand(parent, "scheduler", ["scheduler"], {})
        cmd.process = mock.Mock(spec=subprocess.Popen)
        cmd.process.wait.side_effect = [subprocess.TimeoutExpired("scheduler", 1), 0]

        with mock.patch.object(cmd, "join"):
            cmd.wait_or_kill(1)

        cmd.process.kill.assert_called_once()
        parent.print_error.assert_called_once()

    def test_subcommand_wait_or_kill_does_not_kill_a_stopped_process(self):
        cmd = SubCommand(mock.Mock(spec=StandaloneCommand), "scheduler", ["scheduler"], {})
        cmd.process = mock.Mock(spec=subprocess.Popen)

        with mock.patch.object(cmd, "join"):
            cmd.wait_or_kill(1)

        cmd.process.kill.assert_not_called()

    def test_subcommand_runs_airflow_with_the_current_interpreter(self, monkeypatch):
        popen = mock.Mock(return_value=mock.Mock(stdout=[]))
        monkeypatch.setattr("airflow.cli.commands.standalone_command.subprocess.Popen", popen)

        SubCommand(mock.Mock(), "scheduler", ["scheduler"], {}).run()

        assert popen.call_args.args[0] == [sys.executable, "-m", "airflow", "scheduler"]

    def test_update_output_replaces_undecodable_bytes(self, monkeypatch):
        cmd = StandaloneCommand()
        printed = []
        monkeypatch.setattr(cmd, "print_output", lambda name, msg: printed.append((name, msg)))
        cmd.output_queue.append(("scheduler", b"bad \xff byte\n"))

        cmd.update_output()

        assert printed == [("scheduler", "bad \ufffd byte")]

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
