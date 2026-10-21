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
from datetime import UTC, datetime, timedelta
from unittest import mock
from uuid import UUID, uuid4

import pytest

from airflow.providers.standard.triggers.temporal import DateTimeTrigger
from airflow.sdk import DAG, BaseOperator, get_current_context, task
from airflow.sdk._shared.state import TaskScope
from airflow.sdk.api.datamodels._generated import (
    TaskInstanceState,
    TaskStateStoreResponse,
    XComResponse,
    XComSequenceIndexResponse,
    XComSequenceSliceResponse,
)
from airflow.sdk.bases.xcom import BaseXCom
from airflow.sdk.definitions.asset import Asset
from airflow.sdk.exceptions import AirflowRescheduleException, ErrorType, TaskAwaitingInput
from airflow.sdk.execution_time.comms import ErrorResponse, SkipDownstreamTasks, XComCountResponse
from airflow.sdk.execution_time.local_client import (
    LocalClient,
    LocalRunStore,
    LocalUnsupportedOperationError,
)
from airflow.sdk.execution_time.supervisor import run_task_in_process
from airflow.sdk.timezone import utcnow

from tests_common.test_utils.config import conf_vars

UNSUPPLIED_DIAGNOSTIC = (
    "Task read unsupplied upstream XCom for task {task_id!r}, key {key!r}, and received no value. "
    "Supply upstream XCom values explicitly; upstream tasks are not executed locally."
)


@pytest.fixture
def client(tmp_path):
    store = LocalRunStore(tmp_path)
    run = store.prepare_run("local", "run")
    return LocalClient(store=store, dag_run=run, attempt=store.begin_attempt(run, "task"))


def test_run_dates_conf_and_attempt_identity_survive_restart(tmp_path, time_machine):
    time_machine.move_to("2026-01-01T00:00:00Z")
    store = LocalRunStore(tmp_path)
    run = store.prepare_run("local", "run", params={"limit": 7})
    first = store.begin_attempt(run, "task")
    time_machine.shift(timedelta(hours=1))

    restarted = LocalRunStore(tmp_path)
    reused = restarted.prepare_run("local", "run")
    second = restarted.begin_attempt(reused, "task")
    other_task = restarted.begin_attempt(reused, "other")

    assert reused == run
    assert run.conf == {"limit": 7}
    assert run.run_type == "manual"
    assert run.logical_date == run.run_after == run.data_interval_start == run.data_interval_end
    assert run.logical_date == datetime(2026, 1, 1, tzinfo=UTC)
    assert second.ti.id != first.ti.id
    assert second.start_date > first.start_date
    assert first.ti.try_number == other_task.ti.try_number == 1
    assert second.ti.try_number == 2
    assert restarted.prepare_run("local", "run", params={"limit": 7}) == run
    with pytest.raises(ValueError, match="new run ID"):
        restarted.prepare_run("local", "run", params={})
    new_run = restarted.prepare_run("local", "different", params={})
    assert new_run.conf == {}
    assert new_run.logical_date > run.logical_date


def test_begin_attempt_requires_saved_run(client, tmp_path):
    with pytest.raises(ValueError, match="Prepare the local run"):
        LocalRunStore(tmp_path / "other").begin_attempt(client.dag_run, "task")


def test_changed_parameter_types_require_a_new_run(tmp_path):
    store = LocalRunStore(tmp_path)
    store.prepare_run("local", "run", {"enabled": True})
    with pytest.raises(ValueError, match="different params"):
        store.prepare_run("local", "run", {"enabled": 1})


def test_start_has_no_retries_and_preserves_attempt_start(client):
    context = client.task_instances.start(client.attempt.ti.id, 123, utcnow())
    assert context.dag_run == client.dag_run
    assert context.max_tries == 0
    assert context.should_retry is False
    assert context.start_date == client.attempt.start_date
    assert client.task_instances.heartbeat(client.attempt.ti.id, 123) is None
    assert client.outcome is None


@pytest.mark.parametrize(
    ("method", "state", "diagnostic"),
    [
        ("defer", "deferred", "Deferral and triggers"),
        ("reschedule", "up_for_reschedule", "Rescheduling"),
        ("await_input", "awaiting_input", "Human-in-the-loop approval"),
        ("retry", "up_for_retry", "Automatic retries"),
    ],
)
def test_unsupported_terminal_outcomes_are_recorded_without_raising(client, method, state, diagnostic):
    getattr(client.task_instances, method)(client.attempt.ti.id, utcnow())
    assert client.outcome.state == state
    assert diagnostic in client.outcome.diagnostic


@pytest.mark.parametrize("state", [TaskInstanceState.FAILED, TaskInstanceState.SKIPPED])
def test_finish_records_failure_and_skip(client, state):
    client.task_instances.finish(client.attempt.ti.id, state, utcnow())
    assert client.outcome.state == state.value
    assert state.value in client.outcome.diagnostic


def test_finish_preserves_failure_reason(client):
    client.task_instances.finish(client.attempt.ti.id, "failed", utcnow(), retry_reason="Could not import")
    assert client.outcome.diagnostic == "Could not import"


def test_success_retains_asset_outputs_and_rendered_fields(client, caplog):
    outlets = [{"name": "orders", "uri": "file:///orders"}]
    events = [{"name": "orders", "extra": {"count": 3}}]
    client.task_instances.set_rtif(client.attempt.ti.id, {"sql": "select 1"})
    assert client.task_instances.validate_inlets_and_outlets(client.attempt.ti.id).inactive_assets == []
    client.task_instances.validate_inlets_and_outlets(client.attempt.ti.id)
    client.task_instances.succeed(client.attempt.ti.id, utcnow(), outlets, events)
    assert client.outcome.state == "success"
    assert client.outcome.task_outlets == outlets
    assert client.outcome.outlet_events == events
    assert client.rendered_fields == {"sql": "select 1"}
    assert len(client.diagnostics) == 1
    assert client.diagnostics[0] in caplog


@pytest.mark.parametrize(
    ("resource", "operation", "args"),
    [
        ("variables", "set", ("name", "value")),
        ("variables", "delete", ("name",)),
        ("assets", "get", ()),
        ("asset_events", "get", ()),
        ("asset_state_store", "set", ("key", "value")),
        ("dag_runs", "trigger", ("another",)),
        ("dag_runs", "get_previous", ()),
        ("dags", "get", ("another",)),
        ("hitl", "add_response", ()),
        ("task_instances", "get_previous_successful_dagrun", (uuid4(),)),
    ],
)
def test_unsupported_operations_name_the_feature(client, resource, operation, args):
    with pytest.raises(LocalUnsupportedOperationError, match=rf"{resource}\.{operation}"):
        getattr(getattr(client, resource), operation)(*args)
    assert f"{resource}.{operation}" in client.diagnostics[-1]


def test_skip_downstream_tasks_records_task_ids(client):
    msg = SkipDownstreamTasks(tasks=["short_circuited", ("unfollowed_branch", -1)])
    assert client.task_instances.skip_downstream_tasks(client.attempt.ti.id, msg) is None
    assert client.skipped_downstream_tasks == ["short_circuited", "unfollowed_branch"]
    assert client.outcome is None
    assert client.diagnostics == []


@pytest.mark.parametrize(
    ("resource", "error_type", "environment_prefix"),
    [
        ("connections", ErrorType.CONNECTION_NOT_FOUND, "AIRFLOW_CONN_"),
        ("variables", ErrorType.VARIABLE_NOT_FOUND, "AIRFLOW_VAR_"),
    ],
)
def test_missing_secrets_identify_checked_sources(client, resource, error_type, environment_prefix):
    result = getattr(client, resource).get("missing")
    assert result.error == error_type
    assert "missing" in result.detail["message"]
    assert "configured secrets backend" in result.detail["message"]
    assert environment_prefix in result.detail["message"]
    assert "files" in result.detail["message"]
    assert client.diagnostics == [result.detail["message"]]


@pytest.mark.parametrize("values", [{}, {"return_value": "supplied"}, {"custom": "supplied"}])
def test_upstream_xcoms_cannot_supply_selected_task_outputs(client, values):
    with pytest.raises(ValueError, match="Upstream XComs cannot include selected task 'task'"):
        LocalClient(
            store=client.store,
            dag_run=client.dag_run,
            attempt=client.attempt,
            upstream_xcoms={"task": values},
        )


def test_xcoms_round_trip_supplied_and_published_values(client):
    client = LocalClient(
        store=client.store,
        dag_run=client.dag_run,
        attempt=client.attempt,
        upstream_xcoms={"upstream": {"return_value": {"count": 3}}},
    )
    assert client.xcoms.get("local", "run", "upstream", "return_value").value == {"count": 3}
    client.xcoms.set("local", "run", "task", "return_value", [1, 2])
    assert client.xcoms.get("local", "run", "task", "return_value", -1).value == [1, 2]
    client.xcoms.delete("local", "run", "task", "return_value")
    assert ("local", "run", "task", "return_value") not in client.xcom_values
    assert client.xcoms.get("local", "run", "other", "return_value") == XComResponse(
        key="return_value", value=None
    )
    assert client.diagnostics == [UNSUPPLIED_DIAGNOSTIC.format(task_id="other", key="return_value")]
    client.xcoms.set("local", "run", "task", "null", None)
    assert client.xcoms.get("local", "run", "task", "null").value is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"map_index": 0},
        {"run_id": "previous"},
        {"dag_id": "other"},
        {"include_prior_dates": True},
        {"previous_iteration": True},
    ],
)
def test_mapped_and_history_xcoms_are_unsupported(client, kwargs):
    arguments = {"dag_id": "local", "run_id": "run", "task_id": "task", "key": "key"} | kwargs
    with pytest.raises(LocalUnsupportedOperationError, match="unsupported"):
        client.xcoms.get(**arguments)


def build_xcom_item_not_found(task_id, key, offset):
    detail = {"dag_id": "local", "run_id": "run", "task_id": task_id, "key": key, "offset": offset}
    return ErrorResponse(error=ErrorType.XCOM_NOT_FOUND, detail=detail)


@pytest.mark.parametrize(
    ("method", "args", "missing", "expected"),
    [
        ("head", (), XComCountResponse(len=0), XComCountResponse(len=1)),
        (
            "get_sequence_item",
            (0,),
            build_xcom_item_not_found("upstream", "return_value", 0),
            XComSequenceIndexResponse(root=[1, 2]),
        ),
        (
            "get_sequence_item",
            (-1,),
            build_xcom_item_not_found("upstream", "return_value", -1),
            XComSequenceIndexResponse(root=[1, 2]),
        ),
        (
            "get_sequence_slice",
            (None, None, None),
            XComSequenceSliceResponse(root=[]),
            XComSequenceSliceResponse(root=[[1, 2]]),
        ),
    ],
)
def test_xcom_sequence_contains_one_unmapped_value(client, method, args, missing, expected):
    operation = getattr(client.xcoms, method)
    coordinates = ("local", "run", "upstream", "return_value")
    assert operation(*coordinates, *args) == missing
    assert operation(*coordinates, *args) == missing
    assert client.diagnostics == [UNSUPPLIED_DIAGNOSTIC.format(task_id="upstream", key="return_value")]
    client.xcoms.set(*coordinates, [1, 2])
    assert operation(*coordinates, *args) == expected
    with pytest.raises(LocalUnsupportedOperationError, match="run-history"):
        operation(*coordinates, *args, previous_iteration=True)


def test_xcom_sequence_item_outside_singleton_is_missing(client):
    client.xcoms.set("local", "run", "upstream", "return_value", 7)
    response = client.xcoms.get_sequence_item("local", "run", "upstream", "return_value", 1)
    assert response == build_xcom_item_not_found("upstream", "return_value", 1)
    assert client.diagnostics == []


@pytest.mark.parametrize(
    ("method", "args", "missing", "stored_none"),
    [
        ("get", (), XComResponse(key="scratch", value=None), XComResponse(key="scratch", value=None)),
        ("head", (), XComCountResponse(len=0), XComCountResponse(len=1)),
        (
            "get_sequence_item",
            (0,),
            build_xcom_item_not_found("task", "scratch", 0),
            XComSequenceIndexResponse(root=None),
        ),
        (
            "get_sequence_item",
            (-1,),
            build_xcom_item_not_found("task", "scratch", -1),
            XComSequenceIndexResponse(root=None),
        ),
        (
            "get_sequence_slice",
            (None, None, None),
            XComSequenceSliceResponse(root=[]),
            XComSequenceSliceResponse(root=[None]),
        ),
    ],
)
def test_own_xcom_missing_and_stored_none_rows(client, method, args, missing, stored_none):
    coordinates = ("local", "run", "task", "scratch")
    operation = getattr(client.xcoms, method)
    assert operation(*coordinates, *args) == missing
    client.xcoms.set(*coordinates, None)
    assert operation(*coordinates, *args) == stored_none
    client.xcoms.delete(*coordinates)
    assert operation(*coordinates, *args) == missing
    assert client.diagnostics == []


@pytest.mark.parametrize("task_id", [None, "task"])
@pytest.mark.parametrize("map_indexes", [None, -1])
def test_real_task_own_xcom_defaults_and_delete(client, task_id, map_indexes):
    with DAG("local", schedule=None):

        @task(task_id="task")
        def scratch():
            ti = get_current_context()["ti"]
            kwargs = {"task_ids": task_id, "key": "scratch", "map_indexes": map_indexes, "default": "fresh"}
            initial = ti.xcom_pull(**kwargs)
            coordinates = {"dag_id": ti.dag_id, "run_id": ti.run_id, "task_id": ti.task_id, "key": "scratch"}
            BaseXCom.delete(**coordinates)
            ti.xcom_push(key="scratch", value="saved")
            BaseXCom.delete(**coordinates)
            return [initial, ti.xcom_pull(**kwargs)]

        selected = scratch().operator

    result = run_task_in_process(client.attempt.ti, selected, client=client)

    assert result.error is None
    assert result.state == client.outcome.state == "success"
    assert client.xcom_values["local", "run", "task", "return_value"] == ["fresh", "fresh"]
    assert ("local", "run", "task", "scratch") not in client.xcom_values
    assert client.diagnostics == []


@pytest.mark.parametrize(("supplied", "do_xcom_push"), [(False, True), (True, True), (True, False)])
def test_real_task_xcom_pull_without_map_indexes(client, supplied, do_xcom_push):
    with DAG("local", schedule=None):

        @task(task_id="task", do_xcom_push=do_xcom_push)
        def pull():
            return get_current_context()["ti"].xcom_pull(task_ids="producer")

        selected = pull().operator

    if supplied:
        client = LocalClient(
            store=client.store,
            dag_run=client.dag_run,
            attempt=client.attempt,
            upstream_xcoms={"producer": {"return_value": [1, 2]}},
        )
    result = run_task_in_process(client.attempt.ti, selected, client=client)
    assert result.error is None
    assert result.state == client.outcome.state == "success"
    if supplied:
        if do_xcom_push:
            assert client.xcom_values["local", "run", "task", "return_value"] == [1, 2]
        else:
            assert ("local", "run", "task", "return_value") not in client.xcom_values
        assert client.diagnostics == []
    else:
        # The task returned None, which is not published as an XCom.
        assert ("local", "run", "task", "return_value") not in client.xcom_values
        assert client.diagnostics == [UNSUPPLIED_DIAGNOSTIC.format(task_id="producer", key="return_value")]


@pytest.mark.parametrize("map_indexes", [None, -1])
def test_real_task_unsupplied_upstream_xcom_uses_pull_default(client, map_indexes):
    with DAG("local", schedule=None):

        @task(task_id="task")
        def pull():
            ti = get_current_context()["ti"]
            return ti.xcom_pull(task_ids="producer", map_indexes=map_indexes, default="fallback")

        selected = pull().operator

    result = run_task_in_process(client.attempt.ti, selected, client=client)
    assert result.error is None
    assert result.state == client.outcome.state == "success"
    assert client.xcom_values["local", "run", "task", "return_value"] == "fallback"
    assert client.diagnostics == [UNSUPPLIED_DIAGNOSTIC.format(task_id="producer", key="return_value")]


def test_task_state_recovers_across_attempts_and_handles_missing_keys(client):
    ti_id = client.attempt.ti.id
    assert client.task_state_store.get(ti_id, "journal").error == ErrorType.TASK_STORE_NOT_FOUND
    client.task_state_store.set(ti_id, "journal", {"steps": [1, 2]})
    client.task_state_store.set(ti_id, "null", None)

    store = LocalRunStore(client.store.state_dir)
    run = store.prepare_run("local", "run")
    restarted = LocalClient(store=store, dag_run=run, attempt=store.begin_attempt(run, "task"))
    new_id = restarted.attempt.ti.id
    assert new_id != ti_id
    assert restarted.task_state_store.get(new_id, "journal").value == {"steps": [1, 2]}
    assert restarted.task_state_store.get(new_id, "null") == TaskStateStoreResponse(value=None)
    restarted.task_state_store.delete(new_id, "journal")
    restarted.task_state_store.delete(new_id, "missing")
    assert restarted.task_state_store.get(new_id, "journal").error == ErrorType.TASK_STORE_NOT_FOUND
    restarted.task_state_store.clear(new_id)
    assert restarted.task_state_store.get(new_id, "null").error == ErrorType.TASK_STORE_NOT_FOUND
    with pytest.raises(ValueError, match="Unknown local task instance"):
        restarted.task_state_store.get(ti_id, "journal")


def test_task_state_expiration(client, time_machine):
    time_machine.move_to("2026-01-01T00:00:00Z")
    ti_id = client.attempt.ti.id
    client.task_state_store.set(ti_id, "key", "value", utcnow() + timedelta(minutes=1))
    assert client.task_state_store.get(ti_id, "key").value == "value"
    time_machine.shift(timedelta(minutes=1))
    assert client.task_state_store.get(ti_id, "key").error == ErrorType.TASK_STORE_NOT_FOUND
    time_machine.shift(timedelta(minutes=-1))
    assert client.task_state_store.get(ti_id, "key").error == ErrorType.TASK_STORE_NOT_FOUND


@pytest.mark.parametrize(
    "difference",
    [
        {"dag_id": "different"},
        {"run_id": "different"},
        {"task_id": "different"},
        {"region_id": UUID(int=1)},
        {"region_index": 0},
    ],
)
def test_task_state_is_scoped_to_all_task_coordinates(client, difference):
    scope = {"dag_id": "local", "run_id": "run", "task_id": "task"}
    client.store.set_task_state(TaskScope(**scope), "key", "original")
    other = TaskScope(**(scope | difference))
    assert client.store.get_task_state(other, "key").error == ErrorType.TASK_STORE_NOT_FOUND
    client.store.set_task_state(other, "key", "other")
    client.store.clear_task_state(other)
    assert client.store.get_task_state(TaskScope(**scope), "key").value == "original"


def test_state_keys_and_task_ids_cannot_escape_storage_directory(tmp_path):
    store = LocalRunStore(tmp_path / "state")
    run = store.prepare_run("../../dag", "../../run")
    attempt = store.begin_attempt(run, "../../task")
    client = LocalClient(store=store, dag_run=run, attempt=attempt)
    client.task_state_store.set(attempt.ti.id, "../../value", {"value": 1})
    assert client.task_state_store.get(attempt.ti.id, "../../value").value == {"value": 1}
    assert list(tmp_path.iterdir()) == [tmp_path / "state"]


@pytest.mark.parametrize("contents", ["{broken", "[]"])
def test_invalid_saved_state_is_reported_without_overwriting(client, contents):
    path = next(client.store.state_dir.rglob("run.json"))
    path.write_text(contents)
    with pytest.raises(ValueError, match="Cannot read local recovery state"):
        client.store.prepare_run("local", "run")
    assert path.read_text() == contents


@mock.patch(
    "airflow.sdk.execution_time.local_client.os.replace", autospec=True, side_effect=OSError("interrupted")
)
def test_interrupted_attempt_write_keeps_existing_recovery_state(replace, client):
    path = next(client.store.state_dir.rglob("run.json"))
    before = json.loads(path.read_text())
    with pytest.raises(OSError, match="interrupted"):
        client.store.begin_attempt(client.dag_run, "task")
    assert json.loads(path.read_text()) == before
    assert not list(client.store.state_dir.rglob(".state-*"))


@conf_vars({("core", "dag_run_conf_overrides_params"): "true"})
def test_real_task_with_outlets_and_parameter_date_templates(client):
    with DAG("local", schedule=None, params={"limit": 2}):

        @task(task_id="task", outlets=[Asset("orders", uri="file:///orders")])
        def emit(limit, logical, start, end):
            return {"limit": limit, "dates": [logical, start, end]}

        selected = emit(
            "{{ params.limit }}",
            "{{ logical_date.isoformat() }}",
            "{{ data_interval_start.isoformat() }}",
            "{{ data_interval_end.isoformat() }}",
        ).operator

    client.dag_run.conf = {"limit": 7}
    result = run_task_in_process(client.attempt.ti, selected, client=client)
    assert result.error is None
    assert result.state == client.outcome.state == "success"
    assert client.outcome.task_outlets
    value = client.xcom_values["local", "run", "task", "return_value"]
    assert value["limit"] == "7"
    assert value["dates"] == [client.dag_run.logical_date.isoformat()] * 3
    assert client.rendered_fields


def test_failed_task_recovers_saved_state_through_supervisor(client):
    with DAG("local", schedule=None):

        @task(task_id="task")
        def recover():
            state = get_current_context()["task_state_store"]
            if (saved := state.get("result")) is not None:
                state.clear()
                return saved
            state.set("result", {"order_count": 3})
            raise RuntimeError("Stopped after saving progress")

        selected = recover().operator

    failed = run_task_in_process(client.attempt.ti, selected, client=client)
    assert failed.state == client.outcome.state == "failed"
    assert isinstance(failed.error, RuntimeError)

    store = LocalRunStore(client.store.state_dir)
    run = store.prepare_run("local", "run")
    recovered = LocalClient(store=store, dag_run=run, attempt=store.begin_attempt(run, "task"))
    result = run_task_in_process(recovered.attempt.ti, selected, client=recovered)
    assert result.state == recovered.outcome.state == "success"
    assert recovered.xcom_values["local", "run", "task", "return_value"] == {"order_count": 3}
    assert (
        recovered.task_state_store.get(recovered.attempt.ti.id, "result").error
        == ErrorType.TASK_STORE_NOT_FOUND
    )


@pytest.mark.parametrize(
    ("requested", "expected", "diagnostic"),
    [
        ("defer", "deferred", "Deferral and triggers"),
        ("reschedule", "up_for_reschedule", "Rescheduling"),
        ("await_input", "awaiting_input", "Human-in-the-loop"),
    ],
)
def test_real_task_unsupported_terminal_outcomes(client, requested, expected, diagnostic):
    class SuspendOperator(BaseOperator):
        def execute(self, context):
            if requested == "defer":
                self.defer(trigger=DateTimeTrigger(moment=utcnow()), method_name="execute_complete")
            if requested == "reschedule":
                raise AirflowRescheduleException(utcnow() + timedelta(minutes=1))
            raise TaskAwaitingInput(method_name="execute_complete")

    with DAG("local", schedule=None):
        selected = SuspendOperator(task_id="task")
    result = run_task_in_process(client.attempt.ti, selected, client=client)
    assert result.state == expected
    assert client.outcome.state == expected
    assert diagnostic in client.outcome.diagnostic
