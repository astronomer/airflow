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
"""The fork server's own behaviour; ``test_runner`` runs tries through it end to end."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import threading

from airflow.local_run.fork_server import ForkServer

# Runs in a new interpreter, which has no other thread, so the server can start. Targets are found by name in
# the server, a fork of this script.
SCENARIOS = textwrap.dedent(
    """
    import json, os, signal, socket, sys, time

    from airflow.local_run.fork_server import ForkServer, ForkServerError

    def exit_three():
        sys.exit(3)

    def kill_itself():
        os.kill(os.getpid(), signal.SIGKILL)

    def sleep():
        time.sleep(60)

    def launch(server, target):
        pairs = [socket.socketpair() for _ in range(4)]
        tracker = server.launch(target, *(child for child, _ in pairs), new_process_group=True)
        # As the supervisor does once the child started.
        for child, _ in pairs:
            child.close()
        return tracker, [ours for _, ours in pairs]

    results = {}
    server = ForkServer.start()
    results["server_has_own_group"] = os.getpgid(server.pid) == server.pid

    tracker, (_, _, _, logs) = launch(server, exit_three)
    while logs.recv(4096):
        pass
    try:
        results["exit_code_once_log_ended"] = tracker.wait(0)
    except tracker.TimeoutExpired:
        results["exit_code_once_log_ended"] = "not yet reported"

    tracker, _ = launch(server, kill_itself)
    exit_code = tracker.wait(10)
    results["killed"] = [int(exit_code), exit_code.name]
    try:
        tracker.send_signal(signal.SIGTERM)
    except tracker.ProcessNotFound:
        results["signal_after_exit"] = "refused"

    tracker, _ = launch(server, sleep)
    results["try_has_own_group"] = os.getpgid(tracker.pid) == tracker.pid
    tracker.send_signal(signal.SIGTERM)
    results["terminated"] = int(tracker.wait(10))

    os.kill(server.pid, signal.SIGKILL)
    os.waitpid(server.pid, 0)
    try:
        launch(server, exit_three)
    except ForkServerError:
        results["after_server_ended"] = "ForkServerError"
    print(json.dumps(results))
    """
)


def test_server_starts_tries_and_reports_how_they_ended():
    process = subprocess.run(
        [sys.executable, "-c", SCENARIOS], capture_output=True, text=True, timeout=120, check=True
    )

    assert json.loads(process.stdout.splitlines()[-1]) == {
        "server_has_own_group": True,
        "exit_code_once_log_ended": 3,
        "killed": [-9, "SIGKILL"],
        "signal_after_exit": "refused",
        "try_has_own_group": True,
        "terminated": -15,
        "after_server_ended": "ForkServerError",
    }


def test_server_is_not_forked_from_a_process_running_other_threads():
    stop = threading.Event()
    other = threading.Thread(target=stop.wait)
    other.start()
    try:
        assert ForkServer.start() is None
    finally:
        stop.set()
        other.join()
