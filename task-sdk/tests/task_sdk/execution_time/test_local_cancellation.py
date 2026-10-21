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
import signal
import subprocess
import sys
import textwrap
import time
from contextlib import suppress

import psutil
import pytest


@pytest.fixture
def cancellation_dag(tmp_path):
    path = tmp_path / "cancellation.py"
    path.write_text(
        textwrap.dedent(
            """
            import json
            import os
            import signal
            import subprocess
            import sys
            import time
            from pathlib import Path

            from airflow.sdk import DAG, get_current_context, task

            def start_process_tree():
                def exit_leader(signum, frame):
                    Path(os.environ['LOCAL_TEST_LEADER_EXIT']).write_text(str(signum))
                    os._exit(0)

                signal.signal(signal.SIGINT, exit_leader)
                signal.signal(signal.SIGTERM, exit_leader)
                child_code = '\\n'.join([
                    'import os, signal, time',
                    'from pathlib import Path',
                    'signal.signal(signal.SIGINT, signal.SIG_IGN)',
                    'signal.signal(signal.SIGTERM, signal.SIG_IGN)',
                    "Path(os.environ['LOCAL_TEST_CHILD_READY']).write_text(str(os.getpid()))",
                    'time.sleep(120)',
                ])
                child = subprocess.Popen([sys.executable, '-c', child_code])
                while not Path(os.environ['LOCAL_TEST_CHILD_READY']).exists():
                    time.sleep(0.01)
                ready = Path(os.environ['LOCAL_TEST_READY'])
                pending = ready.with_suffix('.pending')
                pending.write_text(json.dumps({'leader': os.getpid(), 'descendant': child.pid}))
                pending.replace(ready)
                time.sleep(120)

            if os.environ['LOCAL_TEST_PHASE'] == 'startup':
                start_process_tree()

            with DAG('local_cancellation', schedule=None):
                @task
                def work():
                    context = get_current_context()
                    state = context['task_state_store']
                    if os.environ.get('LOCAL_TEST_RESUME') == '1':
                        return state.get('checkpoint')
                    state.set('checkpoint', {'completed_call': 42, 'run_id': context['run_id']})
                    start_process_tree()
                work()
            """
        )
    )
    return path


@pytest.mark.parametrize(
    ("phase", "signum"),
    [
        pytest.param("startup", signal.SIGTERM, id="terminate-during-import"),
        pytest.param("execution", signal.SIGINT, id="interrupt-and-resume"),
        pytest.param("execution", signal.SIGTERM, id="terminate-and-resume"),
    ],
)
def test_command_cancels_process_tree_and_preserves_recovery(cancellation_dag, tmp_path, phase, signum):
    ready = tmp_path / "ready.json"
    leader_exit = tmp_path / "leader-exited"
    output_path = tmp_path / "command.log"
    environment = os.environ | {
        "AIRFLOW_HOME": str(tmp_path / "airflow"),
        "AIRFLOW__CORE__LOAD_EXAMPLES": "false",
        "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN": f"sqlite:///{tmp_path / 'must_not_exist.db'}",
        "LOCAL_TEST_PHASE": phase,
        "LOCAL_TEST_READY": str(ready),
        "LOCAL_TEST_CHILD_READY": str(tmp_path / "child-ready"),
        "LOCAL_TEST_LEADER_EXIT": str(leader_exit),
    }
    environment.pop("_AIRFLOW__AS_LIBRARY", None)
    command = [
        sys.executable,
        "-m",
        "airflow",
        "tasks",
        "run-local",
        str(cancellation_dag),
        "work",
        "--dag-id",
        "local_cancellation",
        "--run-id",
        "resume",
        "--state-dir",
        str(tmp_path / "state"),
    ]
    task_pids = {}
    with output_path.open("w") as output:
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 25
            while not ready.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    pytest.fail(f"Local task did not become ready:\n{output_path.read_text()}")
                time.sleep(0.05)
            task_pids = json.loads(ready.read_text())
            assert os.getpgid(task_pids["descendant"]) == task_pids["leader"]

            process.send_signal(signum)
            assert process.wait(timeout=20) == 1, output_path.read_text()
            assert leader_exit.read_text() == str(signum)
            assert not psutil.pid_exists(task_pids["leader"])
            with suppress(psutil.NoSuchProcess):
                assert psutil.Process(task_pids["descendant"]).status() == psutil.STATUS_ZOMBIE
        finally:
            with suppress(psutil.NoSuchProcess):
                for descendant in psutil.Process(process.pid).children(recursive=True):
                    with suppress(psutil.NoSuchProcess):
                        descendant.kill()
            if not task_pids and ready.exists():
                task_pids = json.loads(ready.read_text())
            if task_pids:
                with suppress(ProcessLookupError):
                    os.killpg(task_pids["leader"], signal.SIGKILL)
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)

    output = output_path.read_text()
    assert "Final state: cancelled" in output
    assert f"Task was cancelled by {signum.name}" in output
    assert not (tmp_path / "must_not_exist.db").exists()

    if phase == "execution":
        resumed = subprocess.run(
            command,
            env=environment | {"LOCAL_TEST_RESUME": "1"},
            capture_output=True,
            check=False,
            text=True,
            timeout=45,
        )
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        return_line = next(line for line in resumed.stdout.splitlines() if line.startswith("Return value: "))
        assert json.loads(return_line.removeprefix("Return value: ")) == {
            "completed_call": 42,
            "run_id": "resume",
        }
        assert "(attempt 2)" in resumed.stdout
        assert "Final state: success" in resumed.stdout
        assert not (tmp_path / "must_not_exist.db").exists()


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize("ignore_signals", [False, True])
def test_command_cancels_bash_operator_session(tmp_path, signum, ignore_signals):
    dag_file = tmp_path / "bash_cancellation.py"
    dag_file.write_text(
        textwrap.dedent(
            """
            import os

            from airflow.providers.standard.operators.bash import BashOperator
            from airflow.sdk import DAG

            command = 'echo $$ > "$LOCAL_BASH_PID"; exec sleep 120'
            if os.environ['LOCAL_BASH_IGNORE_SIGNALS'] == '1':
                command = "trap '' INT TERM; " + command
            with DAG('bash_cancellation', schedule=None):
                BashOperator(task_id='sleep', bash_command=command)
            """
        )
    )
    pid_file = tmp_path / "bash.pid"
    output_path = tmp_path / "command.log"
    environment = os.environ | {
        "AIRFLOW_HOME": str(tmp_path / "airflow"),
        "AIRFLOW__CORE__LOAD_EXAMPLES": "false",
        "LOCAL_BASH_PID": str(pid_file),
        "LOCAL_BASH_IGNORE_SIGNALS": str(int(ignore_signals)),
    }
    environment.pop("_AIRFLOW__AS_LIBRARY", None)
    command = [
        sys.executable,
        "-m",
        "airflow",
        "tasks",
        "run-local",
        str(dag_file),
        "sleep",
        "--dag-id",
        "bash_cancellation",
        "--state-dir",
        str(tmp_path / "state"),
    ]
    descendant = None
    unrelated = subprocess.Popen(["sleep", "120"], start_new_session=True)
    try:
        with output_path.open("w") as output:
            process = subprocess.Popen(
                command,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 25
                while not pid_file.exists() or not pid_file.read_text().strip():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        pytest.fail(f"BashOperator did not become ready:\n{output_path.read_text()}")
                    time.sleep(0.05)
                descendant = psutil.Process(int(pid_file.read_text()))
                task_process = descendant.parent()
                assert task_process is not None
                assert os.getpgid(descendant.pid) == descendant.pid
                assert os.getpgid(task_process.pid) == task_process.pid

                process.send_signal(signum)
                assert process.wait(timeout=20) == 1, output_path.read_text()
                assert not task_process.is_running()
                with suppress(psutil.NoSuchProcess):
                    assert descendant.status() == psutil.STATUS_ZOMBIE
                assert unrelated.poll() is None
            finally:
                if descendant is not None:
                    with suppress(psutil.NoSuchProcess):
                        descendant.kill()
                with suppress(psutil.NoSuchProcess):
                    for child in psutil.Process(process.pid).children(recursive=True):
                        with suppress(psutil.NoSuchProcess):
                            child.kill()
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
    finally:
        unrelated.kill()
        unrelated.wait(timeout=5)

    output = output_path.read_text()
    assert "Final state: cancelled" in output
    assert f"Task was cancelled by {signum.name}" in output
