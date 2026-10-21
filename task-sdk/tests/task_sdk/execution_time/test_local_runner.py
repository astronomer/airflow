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

import importlib
import json
import logging
import os
import signal
import subprocess
import sys
import textwrap
from contextlib import nullcontext
from datetime import timedelta
from unittest import mock

import pytest
import structlog

from airflow.dag_processing.bundles.manager import get_configured_bundle_names
from airflow.sdk import log as sdk_log
from airflow.sdk._shared.secrets_masker import mask_secret, redact
from airflow.sdk._shared.state import TaskScope
from airflow.sdk.bases.xcom import BaseXCom
from airflow.sdk.configuration import conf
from airflow.sdk.execution_time.cache import SecretCache
from airflow.sdk.execution_time.context import _get_worker_state_store_backend
from airflow.sdk.execution_time.local_client import LocalRunStore, LocalTaskOutcome
from airflow.sdk.execution_time.local_runner import _configure_local_execution, run_task_local

from tests_common.test_utils.config import conf_vars


@pytest.fixture
def dag_file(tmp_path):
    path = tmp_path / "project" / "nested" / "tasks.py"
    path.parent.mkdir(parents=True)
    (path.parent.parent / "shared_values.py").write_text("VALUE = 42\n")
    path.write_text(
        textwrap.dedent(
            """
            from airflow.sdk import DAG, task, task_group, get_current_context, Asset, Param
            from shared_values import VALUE

            with DAG('local_example', schedule=None, params={'count': Param(1, type='integer')}) as dag:
                @task(outlets=[Asset('s3://local/output')])
                def work():
                    ctx = get_current_context()
                    return {
                        'value': VALUE,
                        'count': ctx['params']['count'],
                        'date': ctx['logical_date'].isoformat(),
                        'interval_start': ctx['data_interval_start'].isoformat(),
                        'interval_end': ctx['data_interval_end'].isoformat(),
                        'run_after': ctx['dag_run'].run_after.isoformat(),
                    }
                work()

                @task(do_xcom_push=False)
                def silent():
                    return 'discarded'
                silent()

                @task
                def consume(value):
                    return value
                consume(work())

                @task
                def mapped(value):
                    return value
                mapped.expand(value=[1, 2])

                @task_group(group_id='loop_body')
                def body():
                    @task
                    def iterate():
                        return 1
                    iterate()
                body.loop(max_iterations=2)
            """
        )
    )
    return path


def run_example(dag_file, tmp_path, task_id="work", **kwargs):
    return run_task_local(
        dag_file,
        task_id,
        dag_id="local_example",
        bundle_root=dag_file.parent.parent,
        state_dir=tmp_path / "state",
        **kwargs,
    )


def test_execute_and_resume_preserves_run_context(dag_file, tmp_path):
    first = run_example(dag_file, tmp_path, run_id="resume", params={"count": 3})
    second = run_example(dag_file, tmp_path, run_id="resume")
    assert first.exit_code == second.exit_code == 0
    value = first.xcoms["return_value"]
    assert value == second.xcoms["return_value"]
    assert value["value"] == 42
    assert value["count"] == 3
    assert value["date"] == value["interval_start"] == value["interval_end"] == value["run_after"]
    assert first.task_instance_id != second.task_instance_id
    assert (first.try_number, second.try_number) == (1, 2)
    assert first.asset_outputs["outlets"]
    with pytest.raises(ValueError, match="new run ID"):
        run_example(dag_file, tmp_path, run_id="resume", params={"count": 9})


def test_do_xcom_push_false(dag_file, tmp_path):
    result = run_example(dag_file, tmp_path, task_id="silent")
    assert result.exit_code == 0
    assert "return_value" not in result.xcoms


@pytest.mark.parametrize("params", [{"count": "wrong"}, {"count": None}])
def test_parameter_validation(dag_file, tmp_path, params):
    result = run_example(dag_file, tmp_path, params=params)
    assert result.exit_code == 1
    assert "return_value" not in result.xcoms


@pytest.mark.parametrize("supplied", [False, True])
def test_explicit_upstream_values(dag_file, tmp_path, supplied):
    result = run_example(
        dag_file,
        tmp_path,
        task_id="consume",
        upstream_xcoms={"work__1": {"return_value": 7}} if supplied else None,
    )
    assert result.exit_code == 0
    unsupplied = [message for message in result.diagnostics if "read unsupplied upstream XCom" in message]
    if supplied:
        assert result.xcoms["return_value"] == 7
        assert unsupplied == []
    else:
        # consume() received None and returned it, which is not published as an XCom.
        assert "return_value" not in result.xcoms
        assert len(unsupplied) == 1
        assert "task 'work__1', key 'return_value'" in unsupplied[0]


@pytest.mark.parametrize(
    ("task_id", "skipped"), [("choose", ["unfollowed_branch"]), ("check", ["after_check"])]
)
def test_branch_and_short_circuit_report_skipped_downstream_tasks(tmp_path, task_id, skipped):
    path = tmp_path / "branching.py"
    path.write_text(
        textwrap.dedent(
            """
            from airflow.sdk import DAG, task

            with DAG('local_branching', schedule=None):
                @task.branch
                def choose():
                    return 'followed_branch'

                @task
                def followed_branch():
                    pass

                @task
                def unfollowed_branch():
                    pass

                choose() >> [followed_branch(), unfollowed_branch()]

                @task.short_circuit
                def check():
                    return False

                @task
                def after_check():
                    pass

                check() >> after_check()
            """
        )
    )
    result = run_task_local(path, task_id, dag_id="local_branching", state_dir=tmp_path / "state")
    assert (result.state, result.exit_code) == ("success", 0)
    assert result.skipped_downstream_tasks == skipped


def test_reject_path_outside_bundle(dag_file, tmp_path):
    (tmp_path / "state").mkdir()
    with pytest.raises(ValueError, match="beneath bundle root"):
        run_task_local(dag_file, "work", dag_id="local_example", bundle_root=tmp_path / "state")


def test_files_available_during_import(tmp_path, monkeypatch):
    monkeypatch.setattr(SecretCache, "_cache", {})
    monkeypatch.setattr(SecretCache, "_ttl", timedelta(minutes=5), raising=False)
    SecretCache.save_connection_uri("local_connection", "http://deployment.example")
    SecretCache.save_variable("local_variable", "deployment")
    previous_secret_cache = SecretCache._cache
    path = tmp_path / "import_secrets.py"
    path.write_text(
        textwrap.dedent(
            """
            from airflow.sdk import DAG, task, Connection, Variable
            host = Connection.get('local_connection').host
            value = Variable.get('local_variable')
            with DAG('local_example', schedule=None):
                @task
                def work():
                    return [host, value]
                work()
            """
        )
    )
    connections = tmp_path / "connections.json"
    connections.write_text(json.dumps({"local_connection": {"conn_type": "http", "host": "example.test"}}))
    variables = tmp_path / "variables.json"
    variables.write_text(json.dumps({"local_variable": "file"}))
    monkeypatch.setenv("AIRFLOW_VAR_LOCAL_VARIABLE", "environment")
    result = run_task_local(
        path,
        "work",
        dag_id="local_example",
        state_dir=tmp_path / "state",
        connections=connections,
        variables=variables,
    )
    assert result.exit_code == 0
    assert result.xcoms["return_value"] == ["example.test", "environment"]
    assert "AIRFLOW_CONN_LOCAL_CONNECTION" not in os.environ
    assert os.environ["AIRFLOW_VAR_LOCAL_VARIABLE"] == "environment"
    assert SecretCache._cache is previous_secret_cache
    assert SecretCache.get_connection_uri("local_connection") == "http://deployment.example"
    assert SecretCache.get_variable("local_variable") == "deployment"


@pytest.mark.enable_redact
@pytest.mark.parametrize("execute_in_new_interpreter", [False, True])
@mock.patch("structlog.dev.ConsoleRenderer.__call__", autospec=True, return_value="")
def test_preserves_existing_secret_masks_and_masks_task_secrets(
    render, tmp_path, monkeypatch, execute_in_new_interpreter
):
    # Exec children need normal initialization, without the SDK test harness's opt-out.
    monkeypatch.delenv("_AIRFLOW__AS_LIBRARY", raising=False)
    parent_secret = "parent-secret-previously-registered"
    task_secret = "task-secret-loaded-from-environment"
    mask_secret(parent_secret)
    assert redact(parent_secret) == "***"
    monkeypatch.setenv(
        "AIRFLOW_CONN_LOCAL_SECRET", json.dumps({"conn_type": "http", "password": task_secret})
    )
    path = tmp_path / "secret_task.py"
    path.write_text(
        textwrap.dedent(
            """
            import logging
            import sys
            import structlog
            from airflow.sdk import DAG, task, Connection

            with DAG('local_example', schedule=None):
                @task
                def work():
                    secret = Connection.get('local_secret').password
                    structlog.get_logger().info('Structured secret', echo=secret)
                    logging.getLogger(__name__).info('Stdlib secret %s', secret)
                    print('stdout secret ' + secret, flush=True)
                    print('stderr secret ' + secret, file=sys.stderr, flush=True)
                    print('parent secret parent-secret-previously-registered', flush=True)
                    return secret
                work()
            """
        )
    )
    previous_structlog = structlog.get_config()
    previous_handlers = tuple(logging.getLogger().handlers)
    with conf_vars({("core", "execute_tasks_new_python_interpreter"): str(execute_in_new_interpreter)}):
        result = run_task_local(path, "work", dag_id="local_example", state_dir=tmp_path / "state")
    assert result.exit_code == 0
    assert result.xcoms["return_value"] == task_secret
    assert redact(parent_secret) == "***"
    assert redact(result.xcoms) == {"return_value": "***"}
    events = [call.args[-1] for call in render.call_args_list]
    assert any(event["event"] == "Structured secret" and event["echo"] == "***" for event in events)
    for expected in (
        "Structured secret",
        "Stdlib secret ***",
        "stdout secret ***",
        "stderr secret ***",
        "parent secret ***",
    ):
        assert sum(event["event"] == expected for event in events) == 1
    assert structlog.get_config() == previous_structlog
    assert tuple(logging.getLogger().handlers) == previous_handlers


@pytest.mark.parametrize("execute_in_new_interpreter", [False, True])
def test_task_state_stays_local_with_cached_deployment_backend(
    tmp_path, monkeypatch, execute_in_new_interpreter
):
    monkeypatch.delenv("_AIRFLOW__AS_LIBRARY", raising=False)
    (tmp_path / "deployment_backend.py").write_text(
        textwrap.dedent(
            """
            class Store:
                def serialize_task_state_store_to_ref(self, *, value, key, scope):
                    raise RuntimeError('Local execution accessed the deployment backend')

                def clear(self, scope):
                    raise RuntimeError('Local execution accessed the deployment backend')
            """
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    path = tmp_path / "state_task.py"
    path.write_text(
        textwrap.dedent(
            """
            from airflow.sdk import DAG, task, get_current_context

            with DAG('local_example', schedule=None):
                @task
                def work():
                    state = get_current_context()['task_state_store']
                    checkpoint = state.get('checkpoint')
                    if checkpoint is None:
                        state.set('checkpoint', {'saved': 42})
                        raise RuntimeError('Stop after the checkpoint')
                    return checkpoint
                work()
            """
        )
    )
    try:
        with conf_vars(
            {
                ("workers", "state_store_backend"): "deployment_backend.Store",
                ("core", "execute_tasks_new_python_interpreter"): str(execute_in_new_interpreter),
            }
        ):
            _get_worker_state_store_backend.cache_clear()
            assert _get_worker_state_store_backend() is not None
            first = run_task_local(
                path, "work", dag_id="local_example", run_id="resume", state_dir=tmp_path / "state"
            )
            assert first.exit_code == 1
            checkpoint = LocalRunStore(tmp_path / "state").get_task_state(
                TaskScope(dag_id="local_example", run_id="resume", task_id="work"), "checkpoint"
            )
            assert checkpoint.value == {"saved": 42}
            assert conf.get("workers", "state_store_backend") == "deployment_backend.Store"
            assert _get_worker_state_store_backend() is not None
            second = run_task_local(
                path, "work", dag_id="local_example", run_id="resume", state_dir=tmp_path / "state"
            )
            assert second.exit_code == 0
            assert second.xcoms["return_value"] == {"saved": 42}
            assert conf.get("workers", "state_store_backend") == "deployment_backend.Store"
            assert _get_worker_state_store_backend() is not None
    finally:
        _get_worker_state_store_backend.cache_clear()


@pytest.mark.parametrize("backend", ["custom", "object_storage"])
@pytest.mark.parametrize("already_loaded", [False, True])
@pytest.mark.parametrize("execute_in_new_interpreter", [False, True])
def test_xcoms_stay_local_with_deployment_backend(
    tmp_path, backend, already_loaded, execute_in_new_interpreter
):
    if backend == "object_storage":
        pytest.importorskip("airflow.providers.common.io.xcom.backend")
        backend_path = "airflow.providers.common.io.xcom.backend.XComObjectStorageBackend"
    else:
        backend_path = "deployment_xcom.ExternalXCom"
        (tmp_path / "deployment_xcom.py").write_text(
            textwrap.dedent(
                """
                import json
                import os
                from pathlib import Path
                from airflow.sdk.bases.xcom import BaseXCom

                class ExternalXCom(BaseXCom):
                    @classmethod
                    def store_value(cls, coordinate, key, value):
                        path = Path(os.environ['EXTERNAL_XCOM_DIRECTORY']) / key
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps(value))
                        return str(path)
                """
            )
        )
    dag_path = tmp_path / "xcom_task.py"
    dag_path.write_text(
        textwrap.dedent(
            """
            from airflow.sdk import DAG, task

            with DAG('local_xcom', schedule=None):
                @task
                def publish():
                    return 42
                publish()
            """
        )
    )
    external_path = tmp_path / "external_xcom"
    environment = os.environ | {
        "AIRFLOW_HOME": str(tmp_path / "airflow"),
        "AIRFLOW__CORE__LOAD_EXAMPLES": "false",
        "AIRFLOW__CORE__XCOM_BACKEND": backend_path,
        "AIRFLOW__CORE__EXECUTE_TASKS_NEW_PYTHON_INTERPRETER": str(execute_in_new_interpreter),
        "AIRFLOW__COMMON_IO__XCOM_OBJECTSTORAGE_PATH": external_path.as_uri(),
        "AIRFLOW__COMMON_IO__XCOM_OBJECTSTORAGE_THRESHOLD": "0",
        "EXTERNAL_XCOM_DIRECTORY": str(external_path),
        "PYTHONPATH": os.pathsep.join(filter(None, [str(tmp_path), os.environ.get("PYTHONPATH")])),
    }
    environment.pop("_AIRFLOW__AS_LIBRARY", None)
    probe = textwrap.dedent(
        """
        import importlib
        import os
        import sys
        from pathlib import Path
        from airflow.sdk.bases.xcom import XComCoordinate
        from airflow.sdk.configuration import conf
        from airflow.sdk.execution_time.local_runner import run_task_local

        modules = (
            'airflow.sdk.execution_time.xcom',
            'airflow.sdk.execution_time.task_runner',
            'airflow.sdk.execution_time.loop',
            'airflow.models',
            'airflow.models.xcom',
        )
        assert modules[0] not in sys.modules
        if sys.argv[3] == 'True':
            for name in modules:
                getattr(importlib.import_module(name), 'XCom')
        backend_path = os.environ['AIRFLOW__CORE__XCOM_BACKEND']
        external_path = Path(os.environ['EXTERNAL_XCOM_DIRECTORY'])
        for _ in range(2):
            result = run_task_local(
                sys.argv[1], 'publish', dag_id='local_xcom', run_id='repeat', state_dir=sys.argv[2]
            )
            assert result.exit_code == 0, result
            assert result.xcoms == {'return_value': 42}, result
            assert not external_path.exists()
            assert conf.get('core', 'xcom_backend') == backend_path
            module_name, class_name = backend_path.rsplit('.', 1)
            original_backend = getattr(importlib.import_module(module_name), class_name)
            for name in modules:
                if name in sys.modules:
                    assert getattr(sys.modules[name], 'XCom') is original_backend, name
        original_backend.store_value(XComCoordinate('other', 'run', 'task'), 'restored', 43)
        assert [path.read_text() for path in external_path.rglob('*') if path.is_file()] == ['43']
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe, str(dag_path), str(tmp_path / "state"), str(already_loaded)],
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("previous_setting", [None, "deployment.xcom.ExternalXCom"])
def test_restores_cached_xcom_aliases_after_error(tmp_path, monkeypatch, previous_setting):
    class ExternalXCom(BaseXCom):
        pass

    eager_modules = [
        importlib.import_module(name)
        for name in (
            "airflow.sdk.execution_time.xcom",
            "airflow.sdk.execution_time.task_runner",
            "airflow.sdk.execution_time.loop",
        )
    ]
    lazy_modules = [importlib.import_module(name) for name in ("airflow.models", "airflow.models.xcom")]
    for module in eager_modules:
        monkeypatch.setitem(module.__dict__, "XCom", ExternalXCom)
    for module in lazy_modules:
        monkeypatch.delitem(module.__dict__, "XCom", raising=False)
    if previous_setting is None:
        monkeypatch.delenv("AIRFLOW__CORE__XCOM_BACKEND", raising=False)
    else:
        monkeypatch.setenv("AIRFLOW__CORE__XCOM_BACKEND", previous_setting)

    def fail():
        with _configure_local_execution(tmp_path, None, None):
            assert conf.get("core", "xcom_backend") == "airflow.sdk.bases.xcom.BaseXCom"
            for module in eager_modules + lazy_modules:
                assert module.XCom is BaseXCom
            raise RuntimeError("stop")

    with pytest.raises(RuntimeError, match="stop"):
        fail()

    assert os.environ.get("AIRFLOW__CORE__XCOM_BACKEND") == previous_setting
    for module in eager_modules:
        assert module.XCom is ExternalXCom
    for module in lazy_modules:
        assert "XCom" not in module.__dict__


@pytest.mark.parametrize("already_loaded", [False, True])
@pytest.mark.parametrize("fail", [False, True])
@conf_vars({("logging", "remote_logging"): "true"})
@mock.patch("airflow.sdk.log._load_logging_config", autospec=True)
def test_scopes_remote_logging_configuration_and_processors(
    load_config, tmp_path, monkeypatch, already_loaded, fail
):
    active = sdk_log._ActiveLoggingConfig
    remote = mock.Mock(spec=["processors"])
    remote_processor = mock.Mock(spec=["__call__"])
    remote.processors = (remote_processor,)
    monkeypatch.setattr(active, "logging_config_loaded", already_loaded)
    monkeypatch.setattr(active, "remote_task_log", remote if already_loaded else None)
    monkeypatch.setattr(active, "default_remote_conn_id", "deployment_logs" if already_loaded else None)
    previous_structlog = structlog.get_config()
    previous_handlers = tuple(logging.getLogger().handlers)

    def load_remote():
        assert conf.getboolean("logging", "remote_logging")
        active.set(remote, "deployment_logs")

    load_config.side_effect = load_remote
    sdk_log.logging_processors.cache_clear()
    try:
        if already_loaded:
            assert remote_processor in sdk_log.logging_processors(json_output=False)
        with pytest.raises(RuntimeError, match="stop") if fail else nullcontext():
            with _configure_local_execution(tmp_path, None, None):
                assert sdk_log.load_remote_log_handler() is None
                assert remote_processor not in sdk_log.logging_processors(json_output=False)
                if fail:
                    raise RuntimeError("stop")
        assert active.logging_config_loaded is already_loaded
        assert active.remote_task_log is (remote if already_loaded else None)
        assert active.default_remote_conn_id == ("deployment_logs" if already_loaded else None)
        assert conf.getboolean("logging", "remote_logging")
        assert sdk_log.load_remote_log_handler() is remote
        assert remote_processor in sdk_log.logging_processors(json_output=False)
        assert load_config.call_count == (0 if already_loaded else 1)
        assert structlog.get_config() == previous_structlog
        assert tuple(logging.getLogger().handlers) == previous_handlers
    finally:
        sdk_log.logging_processors.cache_clear()


@conf_vars({("dag_processor", "dag_bundle_config_list"): "[]", ("core", "load_examples"): "false"})
def test_configuration_refreshes_and_restores_cached_bundles(tmp_path):
    assert get_configured_bundle_names() == frozenset()
    with _configure_local_execution(tmp_path, None, None):
        assert get_configured_bundle_names() == frozenset({"local_task"})
    assert get_configured_bundle_names() == frozenset()


@pytest.mark.parametrize(
    ("outcome", "process_exit_code", "expected"),
    [(None, 0, 1), (LocalTaskOutcome("success"), 1, 1), (LocalTaskOutcome("failed"), 0, 1)],
)
@mock.patch("airflow.sdk.execution_time.supervisor.supervise_task", autospec=True)
def test_requires_recorded_success_and_clean_exit(
    supervise, dag_file, tmp_path, outcome, process_exit_code, expected
):
    def execute(**kwargs):
        kwargs["client"].outcome = outcome
        return process_exit_code

    supervise.side_effect = execute
    result = run_example(dag_file, tmp_path)
    assert result.exit_code == expected
    assert result.diagnostic


@pytest.mark.parametrize(
    ("process_exit_code", "state", "diagnostic"),
    [
        (-signal.SIGINT, "cancelled", "Task was cancelled by SIGINT; saved task state was kept"),
        (-signal.SIGTERM, "cancelled", "Task was cancelled by SIGTERM; saved task state was kept"),
        (-signal.SIGKILL, "failed", "Task process exited with code -9."),
    ],
)
@mock.patch("airflow.sdk.execution_time.supervisor.supervise_task", autospec=True)
def test_signal_cancellation_reports_cancelled_state(
    supervise, dag_file, tmp_path, process_exit_code, state, diagnostic
):
    def execute(**kwargs):
        kwargs["client"].outcome = LocalTaskOutcome("failed")
        return process_exit_code

    supervise.side_effect = execute
    result = run_example(dag_file, tmp_path, run_id="interrupted")
    assert (result.state, result.exit_code, result.process_exit_code) == (state, 1, process_exit_code)
    assert result.diagnostic.startswith(diagnostic)


@pytest.mark.parametrize(
    ("task_id", "dag_id", "expected", "diagnostic"),
    [
        ("missing", "local_example", 1, None),
        ("work", "missing", 1, None),
        ("silent", "local_example", 0, None),
        ("mapped", "local_example", 1, "Mapped tasks are not supported by run-local"),
        (
            "loop_body.iterate",
            "local_example",
            1,
            "Loop tasks require scheduling and are not supported by run-local",
        ),
    ],
)
def test_actual_command(dag_file, tmp_path, task_id, dag_id, expected, diagnostic):
    environment = os.environ | {
        "AIRFLOW_HOME": str(tmp_path / "airflow"),
        "AIRFLOW__CORE__LOAD_EXAMPLES": "false",
        "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN": f"sqlite:///{tmp_path / 'must_not_exist.db'}",
    }
    environment.pop("_AIRFLOW__AS_LIBRARY", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "airflow",
            "tasks",
            "run-local",
            str(dag_file),
            task_id,
            "--dag-id",
            dag_id,
            "--bundle-root",
            str(dag_file.parent.parent),
            "--state-dir",
            str(tmp_path / "state"),
        ],
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=45,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert f"Exit code: {expected}" in result.stdout
    if expected == 0:
        assert "no return value published" in result.stdout
    if diagnostic:
        # stderr carries the command's summary diagnostics; the task log goes to stdout.
        assert f"Task process exited with code 1. {diagnostic}" in result.stderr
    assert not (tmp_path / "must_not_exist.db").exists()


def test_configuration_restored_on_error(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRFLOW__WORKERS__MISSING_DAG_RETRIES", "12")
    previous_secret_cache = {}
    monkeypatch.setattr(SecretCache, "_cache", previous_secret_cache)

    def fail():
        with _configure_local_execution(tmp_path, None, None):
            assert os.environ["AIRFLOW__WORKERS__MISSING_DAG_RETRIES"] == "0"
            assert SecretCache._cache is None
            raise RuntimeError("stop")

    with pytest.raises(RuntimeError):
        fail()
    assert os.environ["AIRFLOW__WORKERS__MISSING_DAG_RETRIES"] == "12"
    assert SecretCache._cache is previous_secret_cache
