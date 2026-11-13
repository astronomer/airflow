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

import contextlib
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from termcolor import colored

from airflow.api_fastapi.app import create_auth_manager
from airflow.api_fastapi.auth.managers.simple.simple_auth_manager import SimpleAuthManager
from airflow.configuration import conf
from airflow.executors import executor_constants
from airflow.executors.executor_loader import ExecutorLoader
from airflow.jobs.dag_processor_job_runner import DagProcessorJobRunner
from airflow.jobs.job import most_recent_job
from airflow.jobs.scheduler_job_runner import SchedulerJobRunner
from airflow.jobs.triggerer_job_runner import TriggererJobRunner
from airflow.utils import db
from airflow.utils.providers_configuration_loader import providers_configuration_loaded

if TYPE_CHECKING:
    from airflow.jobs.base_job_runner import BaseJobRunner

FORCE_COLOR = bool(os.environ.get("FORCE_COLOR", ""))
NO_COLOR = bool(os.environ.get("NO_COLOR", ""))

REFRESH_INTERVAL_ENV_VAR = "AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL"
COMPONENT_STOP_TIMEOUT = 30
# How many of a component's latest lines to show on screen when it dies.
RECENT_LINES = 20
# One log file each; "standalone" holds this process's own database setup output.
LOG_NAMES = ("standalone", "scheduler", "dag-processor", "api-server", "triggerer")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# Component lines worth showing on screen without --verbose: structlog's console and JSON renderers,
# and the plain "ERROR:" prefix uvicorn uses.
IMPORTANT_LINE = re.compile(
    r"\[(error|critical)\s*\]|\"level\":\s*\"(error|critical)\"|^(ERROR|CRITICAL)\b", re.IGNORECASE
)


class StandaloneCommand:
    """
    Runs all components of Airflow under a single parent process.

    Useful for local development.
    """

    @classmethod
    def entrypoint(cls, args):
        """CLI entrypoint, called by the main CLI system."""
        StandaloneCommand(verbose=args.verbose).run()

    def __init__(self, verbose: bool = False):
        self.subcommands: dict[str, SubCommand] = {}
        self.output_queue: deque[tuple[str, bytes]] = deque()
        self.ready_time = None
        self.ready_delay = 3
        self.api_server_port = None
        self.previous_job_ids: dict[str, int | None] = {}
        self.verbose = verbose
        self.log_dir: Path | None = None
        self.log_files: dict[str, TextIO] = {}
        self.recent_lines: dict[str, deque[str]] = {}

    @providers_configuration_loaded
    def run(self):
        self.print_output("standalone", "Starting Airflow Standalone")
        # Silence built-in logging at INFO
        logging.getLogger("").setLevel(logging.WARNING)
        # Startup checks and prep
        self.api_server_port = conf.getint("api", "port")
        self.open_log_files()
        env = self.calculate_env()
        self.find_user_info()
        self.initialize_database()
        self.record_previous_jobs()
        # Set up commands to run
        self.subcommands["scheduler"] = SubCommand(
            self,
            name="scheduler",
            command=["scheduler"],
            env=env,
        )
        self.subcommands["dag-processor"] = SubCommand(
            self,
            name="dag-processor",
            command=["dag-processor"],
            env=env,
        )
        self.subcommands["api-server"] = SubCommand(
            self,
            name="api-server",
            command=["api-server"],
            env=env,
        )
        self.subcommands["triggerer"] = SubCommand(
            self,
            name="triggerer",
            command=["triggerer"],
            env=env,
        )

        # Run subcommand threads
        for command in self.subcommands.values():
            command.start()
        # Run output loop
        shown_ready = False
        failed_component = None
        previous_sigterm_handler = signal.signal(signal.SIGTERM, self.handle_sigterm)
        try:
            while True:
                # Print all the current lines onto the screen
                self.update_output()
                if failed_component := self.find_exited_component():
                    break
                # Print info banner when all components are ready and the
                # delay has passed
                if not self.ready_time and self.is_ready():
                    self.ready_time = time.monotonic()
                if (
                    not shown_ready
                    and self.ready_time
                    and time.monotonic() - self.ready_time > self.ready_delay
                ):
                    self.print_ready()
                    shown_ready = True
                # Ensure we idle-sleep rather than fast-looping
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm_handler)
        if failed_component:
            self.print_error(
                "standalone",
                f"The {failed_component.name} component exited with code {failed_component.process.returncode}",
            )
            if not self.verbose:
                self.print_recent_lines(failed_component.name)
        self.stop_components()
        self.print_output("standalone", "Complete")
        for log_file in self.log_files.values():
            log_file.close()
        if failed_component:
            raise SystemExit(1)

    def open_log_files(self):
        """
        Write each component's output to its own file in ``[logging] base_log_folder``/standalone.

        The previous run's files are kept with a ``.1`` suffix.
        """
        self.log_dir = Path(conf.get("logging", "base_log_folder")) / "standalone"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for name in LOG_NAMES:
            path = self.get_log_path(name)
            if path.exists():
                path.replace(path.with_name(f"{path.name}.1"))
            self.log_files[name] = path.open("a", buffering=1)
        if not self.verbose:
            self.print_output(
                "standalone", f"Writing component logs to {self.log_dir} (--verbose shows them here)"
            )

    def get_log_path(self, name: str) -> Path | None:
        return self.log_dir / f"{name}.log" if self.log_dir else None

    @contextlib.contextmanager
    def redirect_output_to_log(self):
        """
        Send this process's own stdout and stderr to the log file.

        Database setup logs through handlers that hold the original streams, so this swaps the
        file descriptors rather than ``sys.stdout``.
        """
        log_file = self.log_files.get("standalone")
        if self.verbose or log_file is None:
            yield
            return
        sys.stdout.flush()
        sys.stderr.flush()
        log_file.flush()
        saved = os.dup(1), os.dup(2)
        try:
            os.dup2(log_file.fileno(), 1)
            os.dup2(log_file.fileno(), 2)
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])

    def print_recent_lines(self, name: str):
        self.print_output("standalone", f"Last lines from {name} (full output in {self.get_log_path(name)}):")
        for line in self.recent_lines.get(name, ()):
            self.print_output(name, line)

    @staticmethod
    def handle_sigterm(signum, frame):
        # Shut down the same way as Ctrl+C, so a supervisor's SIGTERM also stops the components.
        raise KeyboardInterrupt

    def find_exited_component(self) -> SubCommand | None:
        for command in self.subcommands.values():
            if command.process is not None and command.process.poll() is not None:
                return command
        return None

    def stop_components(self):
        """Terminate every component, then kill any that has not exited within the timeout."""
        self.print_output("standalone", "Shutting down components")
        for command in self.subcommands.values():
            command.stop()
        deadline = time.monotonic() + COMPONENT_STOP_TIMEOUT
        for command in self.subcommands.values():
            command.wait_or_kill(max(0.0, deadline - time.monotonic()))
        # Keep what the components logged while stopping.
        self.update_output()

    def update_output(self):
        """
        Drain the output queue into each component's log file.

        Lines reach the screen too with --verbose; otherwise only error and critical lines do.
        """
        while self.output_queue:
            name, line = self.output_queue.popleft()
            line_str = ANSI_ESCAPE.sub("", line.decode("utf8", errors="replace")).strip()
            log_file = self.log_files.get(name)
            if log_file:
                log_file.write(f"{line_str}\n")
            self.recent_lines.setdefault(name, deque(maxlen=RECENT_LINES)).append(line_str)
            if self.verbose or log_file is None or IMPORTANT_LINE.search(line_str):
                self.print_output(name, line_str)

    def print_output(self, name: str, output):
        """
        Print an output line with name and colouring.

        You can pass multiple lines to output if you wish; it will be split for you.
        """
        color: dict[str, str] = {
            "api-server": "magenta",
            "scheduler": "blue",
            "dag-processor": "yellow",
            "triggerer": "cyan",
            "standalone": "white",
        }
        colorised_name = colored(
            f"{name:10}", color.get(name, "white"), no_color=NO_COLOR, force_color=FORCE_COLOR
        )
        for line in output.splitlines():
            print(f"{colorised_name} | {line.strip()}")

    def print_error(self, name: str, output):
        """
        Print an error message to the console.

        This is the same as print_output but with the text red
        """
        self.print_output(name, colored(output, "red"))

    def calculate_env(self):
        """
        Works out the environment variables needed to run subprocesses.

        We override some settings as part of being standalone.
        """
        env = dict(os.environ)

        # Make sure we're using a local executor flavour
        executor_class, _ = ExecutorLoader.import_default_executor_cls()
        if not executor_class.is_local:
            self.print_output("standalone", "Forcing executor to LocalExecutor")
            env["AIRFLOW__CORE__EXECUTOR"] = executor_constants.LOCAL_EXECUTOR

        # Make sure we're using SimpleAuthManager
        simple_auth_manager_classpath = (
            "airflow.api_fastapi.auth.managers.simple.simple_auth_manager.SimpleAuthManager"
        )
        if conf.get("core", "auth_manager") != simple_auth_manager_classpath:
            self.print_output("standalone", "Forcing auth manager to SimpleAuthManager")
            env["AIRFLOW__CORE__AUTH_MANAGER"] = simple_auth_manager_classpath
            os.environ["AIRFLOW__CORE__AUTH_MANAGER"] = simple_auth_manager_classpath  # also in this process!

        # A new Dag file is found only when its bundle refreshes, every few minutes by default. Have the
        # Dag processor refresh the Dags folder each time it checks whether any bundle is due.
        if self.uses_default_dag_discovery():
            refresh_interval = conf.getint("dag_processor", "bundle_refresh_check_interval")
            self.print_output(
                "standalone",
                f"Checking for new Dag files every {refresh_interval} seconds "
                "(set [dag_processor] refresh_interval to change this)",
            )
            env[REFRESH_INTERVAL_ENV_VAR] = str(refresh_interval)

        return env

    def uses_default_dag_discovery(self) -> bool:
        """
        Check that the user left the Dags folder bundle and its refresh interval at their defaults.

        The generated airflow.cfg writes out every default, so a value equal to the default counts as
        unset there; an environment variable counts as a choice whatever its value. Other bundles are
        left alone, since refreshing a remote bundle fetches from it.
        """
        if REFRESH_INTERVAL_ENV_VAR in os.environ:
            return False
        if conf.get("dag_processor", "refresh_interval") != conf.get_default_value(
            "dag_processor", "refresh_interval"
        ):
            return False
        default_bundles = json.loads(conf.get_default_value("dag_processor", "dag_bundle_config_list"))
        return conf.getjson("dag_processor", "dag_bundle_config_list") == default_bundles

    def find_user_info(self):
        if conf.get("core", "simple_auth_manager_all_admins").lower() == "true":
            # If we have no auth anyways, no need to print or do anything
            return
        if conf.get("core", "simple_auth_manager_users") != "admin:admin":
            self.print_output(
                "standalone",
                "Not outputting user passwords - `[core] simple_auth_manager_users` is already set.",
            )
            return

        am = create_auth_manager()

        password_file = am.get_generated_password_file()
        if os.path.exists(password_file):
            # print_ready shows the login once Airflow is up.
            return

        # this generates the password and prints it
        am.init()

    def initialize_database(self):
        """Make sure all the tables are created."""
        # Set up DB tables
        self.print_output("standalone", "Checking database is initialized")
        with self.redirect_output_to_log():
            db.initdb()
        self.print_output("standalone", "Database ready")

    def is_ready(self):
        """
        Detect when all Airflow components are ready to serve.

        Ready means the API server accepts connections and the scheduler, Dag
        processor and triggerer are all heartbeating.
        """
        return (
            self.port_open(self.api_server_port)
            and self.job_running(SchedulerJobRunner)
            and self.job_running(DagProcessorJobRunner)
            and self.job_running(TriggererJobRunner)
        )

    def port_open(self, port):
        """
        Check if the given port is listening on the local machine.

        Used to tell if the API server is alive.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect(("127.0.0.1", port))
            sock.close()
        except (OSError, ValueError):
            # Any exception means the socket is not available
            return False
        return True

    def job_running(self, job_runner_class: type[BaseJobRunner]):
        """
        Check if the given job name is running and heartbeating correctly.

        Used to tell if a component is alive.
        """
        recent = most_recent_job(job_runner_class.job_type)
        if not recent or recent.id == self.previous_job_ids.get(job_runner_class.job_type):
            return False
        return recent.is_alive()

    def record_previous_jobs(self):
        """
        Remember the latest job of each component before starting new ones.

        A job left by an earlier run keeps a recent heartbeat for a while after that run stops, so
        it must not count as this run's component being ready.
        """
        for job_runner_class in (SchedulerJobRunner, DagProcessorJobRunner, TriggererJobRunner):
            recent = most_recent_job(job_runner_class.job_type)
            self.previous_job_ids[job_runner_class.job_type] = recent.id if recent else None

    def print_ready(self):
        """
        Print the banner shown when Airflow is ready to go.

        Include with login details.
        """
        self.print_output("standalone", "")
        self.print_output("standalone", f"Airflow is ready at http://localhost:{self.api_server_port}")
        for line in self.get_login_lines():
            self.print_output("standalone", line)
        if self.log_dir and not self.verbose:
            self.print_output("standalone", f"Component logs: {self.log_dir}/<component>.log")
        self.print_output(
            "standalone",
            "Airflow Standalone is for development purposes only. Do not use this in production!",
        )
        self.print_output("standalone", "")

    def get_login_lines(self) -> list[str]:
        """
        Describe how to log in.

        Passwords are shown only from the file SimpleAuthManager generates; a passwords file the user
        configured is referred to by path.
        """
        if conf.getboolean("core", "simple_auth_manager_all_admins"):
            return ["No login needed: every user is an admin ([core] simple_auth_manager_all_admins)"]
        password_file = SimpleAuthManager.get_generated_password_file()
        if conf.get("core", "simple_auth_manager_passwords_file", fallback=None):
            return [f"Passwords are in {password_file}"]
        try:
            passwords = json.loads(Path(password_file).read_text())
        except (OSError, ValueError):
            return []
        return [f"Log in as {user} with password {password}" for user, password in passwords.items()]


class SubCommand(threading.Thread):
    """
    Execute a subcommand on another thread.

    Thread that launches a process and then streams its output back to the main
    command. We use threads to avoid using select() and raw filehandles, and the
    complex logic that brings doing line buffering.
    """

    def __init__(self, parent, name: str, command: list[str], env: dict[str, str]):
        # A daemon thread, so a grandchild still holding the output pipe cannot block exit.
        super().__init__(daemon=True)
        self.parent = parent
        self.name = name
        self.command = command
        self.env = env
        self.process: subprocess.Popen[bytes] | None = None

    def run(self):
        """Run the actual process and captures it output to a queue."""
        self.process = subprocess.Popen(
            [sys.executable, "-m", "airflow", *self.command],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=self.env,
        )
        for line in self.process.stdout:
            self.parent.output_queue.append((self.name, line))

    def stop(self):
        """Call to stop this process (and thus this thread)."""
        if self.process is not None:
            self.process.terminate()

    def wait_or_kill(self, timeout: float):
        """Wait for the process to exit, killing it once ``timeout`` seconds have passed."""
        if self.process is None:
            return
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.parent.print_error("standalone", f"Killing {self.name}, which did not stop in time")
            self.process.kill()
            self.process.wait()
        self.join(timeout=1)


# Alias for use in the CLI parser
standalone = StandaloneCommand.entrypoint
