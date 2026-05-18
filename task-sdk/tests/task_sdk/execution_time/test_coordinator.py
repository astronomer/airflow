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
from unittest.mock import MagicMock

import pytest

from airflow.sdk.execution_time.coordinator import (
    BaseCoordinator,
    CoordinatorManager,
    get_coordinator_manager,
    reset_coordinator_manager,
)


class TestCoordinatorNamedTuples:
    def test_dag_parsing_info_defaults(self):
        info = BaseCoordinator.DagParsingInfo(
            dag_file_path="/dag.jar",
            bundle_name="my-bundle",
            bundle_path="/bundles/my-bundle",
        )
        assert info.mode == "dag-parsing"
        assert info.dag_file_path == "/dag.jar"
        assert info.bundle_name == "my-bundle"
        assert info.bundle_path == "/bundles/my-bundle"

    def test_task_execution_info_defaults(self):
        mock_ti = MagicMock()
        mock_bundle = MagicMock()
        mock_startup = MagicMock()
        info = BaseCoordinator.TaskExecutionInfo(
            what=mock_ti,
            dag_rel_path="dags/example.jar",
            bundle_info=mock_bundle,
            startup_details=mock_startup,
        )
        assert info.mode == "task-execution"
        assert info.what is mock_ti
        assert info.dag_rel_path == "dags/example.jar"


class _CoordinatorA(BaseCoordinator):
    sdk = "a"
    file_extension = ".a"

    def __init__(self, *, label: str = "a"):
        self.label = label


class _CoordinatorB(BaseCoordinator):
    sdk = "b"
    file_extension = ".b"


class TestCoordinatorManager:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        reset_coordinator_manager()
        yield
        reset_coordinator_manager()

    def test_from_config_loads_instances(self, monkeypatch):
        coordinators_json = json.dumps(
            [
                {
                    "name": "alpha",
                    "classpath": f"{_CoordinatorA.__module__}._CoordinatorA",
                    "kwargs": {"label": "alpha-label"},
                },
                {
                    "name": "beta",
                    "classpath": f"{_CoordinatorB.__module__}._CoordinatorB",
                },
            ]
        )
        queue_json = json.dumps({"queue-a": "alpha"})

        monkeypatch.setenv("AIRFLOW__SDK__COORDINATORS", coordinators_json)
        monkeypatch.setenv("AIRFLOW__SDK__QUEUE_TO_COORDINATOR", queue_json)

        from airflow.sdk.configuration import conf

        conf.invalidate_cache()

        manager = CoordinatorManager.from_config()
        assert manager._queue_to_coordinator == {"queue-a": _CoordinatorA}

        coordinator_for_queue_a = manager.for_queue("queue-a")
        assert isinstance(coordinator_for_queue_a, _CoordinatorA)
        assert coordinator_for_queue_a.label == "alpha-label"

    def test_from_config_empty(self, monkeypatch):
        monkeypatch.delenv("AIRFLOW__SDK__COORDINATORS", raising=False)
        monkeypatch.delenv("AIRFLOW__SDK__QUEUE_TO_COORDINATOR", raising=False)

        from airflow.sdk.configuration import conf

        conf.invalidate_cache()

        manager = CoordinatorManager.from_config()
        assert manager._queue_to_coordinator == {}

    def test_for_queue_resolves_via_mapping(self):
        coordinator_a = _CoordinatorA()
        coordinator_b = _CoordinatorB()
        manager = CoordinatorManager(
            {"alpha": _CoordinatorA, "beta": _CoordinatorB},
            {"queue-a": "alpha", "queue-b": "beta"},
        )

        assert manager.for_queue("queue-a") is coordinator_a
        assert manager.for_queue("queue-b") is coordinator_b
        assert manager.for_queue("queue-missing") is None

    def test_get_coordinator_manager_is_cached(self, monkeypatch):
        monkeypatch.delenv("AIRFLOW__SDK__COORDINATORS", raising=False)

        from airflow.sdk.configuration import conf

        conf.invalidate_cache()

        m1 = get_coordinator_manager()
        m2 = get_coordinator_manager()
        assert m1 is m2
