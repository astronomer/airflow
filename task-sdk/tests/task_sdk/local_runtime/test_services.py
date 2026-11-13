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

from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

import pytest

from airflow.sdk.bases.secrets_backend import BaseSecretsBackend
from airflow.sdk.exceptions import AirflowSecretsBackendAccessDenied, ErrorType
from airflow.sdk.execution_time import comms
from airflow.sdk.local_runtime.runner import build_startup
from airflow.sdk.local_runtime.services import LocalTaskServices, MissingLocalInput, UnsupportedLocalOperation
from airflow.sdk.local_runtime.state import LocalStateStore


@pytest.fixture
def services(tmp_path):
    startup = build_startup(
        SimpleNamespace(dag_id="example"),
        SimpleNamespace(task_id="selected", queue="default"),
        tmp_path / "agent.py",
        tmp_path,
        None,
    )
    return LocalTaskServices(
        startup=startup,
        state=LocalStateStore(identity={}, run_id=startup.ti.run_id),
        inputs={("upstream", "return_value"): {"n": 3}},
    )


def get_xcom(services, **kwargs):
    fields = {
        "dag_id": services.startup.ti.dag_id,
        "run_id": services.startup.ti.run_id,
        "task_id": "upstream",
        "key": "return_value",
    }
    fields.update(kwargs)
    return comms.GetXCom(**fields)


def test_only_explicit_local_secrets_are_resolved(services, monkeypatch):
    monkeypatch.setenv("AIRFLOW_CONN_DEMO", '{"conn_type": "http", "host": "example.test"}')
    monkeypatch.setenv("AIRFLOW_VAR_REGION", "eu")
    assert services.handle(comms.GetConnection(conn_id="demo")).host == "example.test"
    assert services.handle(comms.GetVariable(key="region")).value == "eu"
    assert (
        services.handle(comms.GetConnection(conn_id="missing-local-connection")).error
        == ErrorType.CONNECTION_NOT_FOUND
    )
    assert (
        services.handle(comms.GetVariable(key="missing-local-variable")).error == ErrorType.VARIABLE_NOT_FOUND
    )


def test_secrets_backend_denial_does_not_fall_through(services):
    denied = mock.Mock(spec=BaseSecretsBackend)
    denied.get_connection.side_effect = AirflowSecretsBackendAccessDenied("denied")
    later = mock.Mock(spec=BaseSecretsBackend)
    services.backends = [denied, later]
    with pytest.raises(AirflowSecretsBackendAccessDenied, match="denied"):
        services.handle(comms.GetConnection(conn_id="demo"))
    later.get_connection.assert_not_called()


@pytest.mark.parametrize(
    "overrides",
    [
        {"dag_id": "other"},
        {"run_id": "other"},
        {"map_index": 0},
        {"include_prior_dates": True},
        {"previous_iteration": True},
    ],
)
def test_xcom_scope_and_history_are_rejected(services, overrides):
    with pytest.raises(UnsupportedLocalOperation):
        services.handle(get_xcom(services, **overrides))


def test_xcom_write_read_and_delete(services):
    request = get_xcom(services, task_id="selected")
    services.handle(
        comms.SetXCom(
            **request.model_dump(exclude={"type", "previous_iteration", "include_prior_dates"}), value=[1, 2]
        )
    )
    assert services.handle(request).value == [1, 2]
    assert services.outputs == {"return_value": [1, 2]}
    services.handle(
        comms.DeleteXCom(**request.model_dump(exclude={"type", "previous_iteration", "include_prior_dates"}))
    )
    assert services.outputs == {}
    with pytest.raises(MissingLocalInput):
        services.handle(request)


def test_cannot_write_an_upstream_output(services):
    request = get_xcom(services)
    with pytest.raises(UnsupportedLocalOperation, match="selected task"):
        services.handle(
            comms.SetXCom(
                **request.model_dump(exclude={"type", "previous_iteration", "include_prior_dates"}), value=4
            )
        )


def test_xcom_count_and_index_use_the_single_explicit_value(services):
    fields = get_xcom(services).model_dump(exclude={"type", "map_index", "include_prior_dates"})
    assert services.handle(comms.GetXComCount(**fields)).len == 1
    assert services.handle(comms.GetXComSequenceItem(**fields, offset=0)).root == {"n": 3}
    with pytest.raises(UnsupportedLocalOperation):
        services.handle(comms.GetXComSequenceItem(**fields, offset=1))


def test_state_is_scoped_to_the_selected_instance(services):
    with pytest.raises(UnsupportedLocalOperation, match="selected task"):
        services.handle(comms.GetTaskStateStore(ti_id=uuid4(), key="value"))


def test_variable_writes_fail_at_use(services):
    with pytest.raises(UnsupportedLocalOperation, match="PutVariable is not supported"):
        services.handle(comms.PutVariable(key="region", value="other", description=None))
