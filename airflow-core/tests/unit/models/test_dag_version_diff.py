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

import pytest
from sqlalchemy import delete

from airflow.models.dag_version_diff import (
    DagVersionNotFoundError,
    build_serialized_dag_diff,
    get_dag_version_diff,
)


def _payload(
    *,
    tasks: list[dict],
    tags: list[str] | None = None,
    schedule: str = "daily",
    dependencies: list[dict] | None = None,
) -> dict:
    return {
        "__version": 3,
        "dag": {
            "dag_id": "example",
            "schedule": schedule,
            "tags": tags or [],
            "tasks": [
                {
                    "__type": "airflow.providers.standard.operators.empty.EmptyOperator",
                    "__var": task,
                }
                for task in tasks
            ],
            "dag_dependencies": dependencies or [],
        },
    }


def test_build_diff_is_deterministic_and_normalizes_order() -> None:
    base = _payload(
        tasks=[{"task_id": "extract", "retries": 1}, {"task_id": "load", "retries": 1}],
        tags=["one", "two"],
        dependencies=[
            {
                "dependency_type": "task",
                "dependency_id": "extract-load",
                "source": "extract",
                "target": "load",
                "label": "extract-load",
            }
        ],
    )
    target = _payload(
        tasks=[{"task_id": "load", "retries": 1}, {"task_id": "extract", "retries": 1}],
        tags=["two", "one"],
        dependencies=[
            {
                "label": "extract-load",
                "target": "load",
                "source": "extract",
                "dependency_id": "extract-load",
                "dependency_type": "task",
            }
        ],
    )

    result = build_serialized_dag_diff(base_data=base, target_data=target)

    assert result["mode"] == "observed_state"
    assert result["serialized_dag_schema_versions"] == {"base": 3, "target": 3}
    assert result["changes"] == []
    assert result["truncated"] is False


def test_build_diff_reports_categories_digests_and_values() -> None:
    base = _payload(tasks=[{"task_id": "extract", "retries": 1}], tags=["old"])
    target = _payload(
        tasks=[
            {"task_id": "extract", "retries": 2},
            {"task_id": "load", "retries": 1},
        ],
        tags=["new"],
        schedule="hourly",
    )

    result = build_serialized_dag_diff(
        base_data=base,
        target_data=target,
        base_provenance={"bundle_version": "one"},
        target_provenance={"bundle_version": "two"},
        include_values=True,
    )

    changes = {change["path"]: change for change in result["changes"]}
    assert changes["/dag/tasks/extract/retries"]["category"] == "task"
    assert changes["/dag/tasks/extract/retries"]["impact"] == "execution"
    assert changes["/dag/tasks/extract/retries"]["before_value"] == 1
    assert changes["/dag/tasks/extract/retries"]["after_value"] == 2
    assert changes["/dag/tasks/extract/retries"]["before_digest"].startswith("sha256:")
    assert changes["/dag/tasks/load"]["operation"] == "added"
    assert changes["/dag/schedule"]["category"] == "schedule"
    assert changes["/dag/tags/old"]["operation"] == "removed"
    assert changes["/dag/tags/new"]["operation"] == "added"
    assert changes["/dag/tags/old"]["category"] == "metadata"
    assert changes["/provenance/bundle_version"]["category"] == "provenance"
    assert changes["/provenance/bundle_version"]["impact"] == "provenance"


def test_build_diff_bounds_changes_and_reports_truncation() -> None:
    result = build_serialized_dag_diff(
        base_data=_payload(tasks=[{"task_id": "extract", "retries": 1}], tags=["old"]),
        target_data=_payload(tasks=[{"task_id": "extract", "retries": 2}], tags=["new"]),
        max_changes=1,
    )

    assert len(result["changes"]) == 1
    assert result["truncated"] is True


def test_build_diff_reports_dependency_changes() -> None:
    dependency = {
        "dependency_type": "sensor",
        "dependency_id": "upstream-task",
        "source": "upstream-dag",
        "target": "example",
        "label": "upstream-task",
    }

    result = build_serialized_dag_diff(
        base_data=_payload(tasks=[], dependencies=[dependency]),
        target_data=_payload(tasks=[]),
    )

    assert len(result["changes"]) == 1
    assert result["changes"][0]["category"] == "dependency"
    assert result["changes"][0]["impact"] == "execution"


def test_build_diff_classifies_fail_fast_as_schedule() -> None:
    base = _payload(tasks=[])
    target = _payload(tasks=[])
    base["dag"]["fail_fast"] = False
    target["dag"]["fail_fast"] = True

    result = build_serialized_dag_diff(base_data=base, target_data=target)

    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert change["path"] == "/dag/fail_fast"
    assert change["operation"] == "changed"
    assert change["category"] == "schedule"
    assert change["impact"] == "execution"


@pytest.mark.parametrize(
    ("base_data", "target_data", "reason"),
    [
        (None, _payload(tasks=[]), "serialized_dag_missing"),
        ({"__version": 99, "dag": {}}, _payload(tasks=[]), "unsupported_serialized_dag_schema_version:99"),
        ({"__version": 3, "dag": []}, _payload(tasks=[]), "serialized_dag_canonicalization_failed"),
        (
            {
                "__version": 1,
                "dag": {
                    "dag_id": "example",
                    "tasks": [],
                    "task_group": {},
                    "schedule_interval": 1,
                },
            },
            _payload(tasks=[]),
            "serialized_dag_canonicalization_failed",
        ),
        (
            {
                "__version": 1,
                "dag": {
                    "dag_id": "example",
                    "tasks": [],
                    "task_group": {},
                    "schedule_interval": {"__type": "timedelta", "__var": 10**20},
                },
            },
            _payload(tasks=[]),
            "serialized_dag_canonicalization_failed",
        ),
    ],
)
def test_build_diff_returns_unavailable_for_unsafe_inputs(base_data, target_data, reason) -> None:
    result = build_serialized_dag_diff(base_data=base_data, target_data=target_data)

    assert result["mode"] == "unavailable"
    assert result["changes"] == []
    assert result["unavailable_reason"] == reason


def test_build_diff_rejects_non_positive_change_bound() -> None:
    with pytest.raises(ValueError, match="max_changes must be a positive integer"):
        build_serialized_dag_diff(base_data=_payload(tasks=[]), target_data=_payload(tasks=[]), max_changes=0)


def test_build_diff_rejects_unbounded_change_bound() -> None:
    with pytest.raises(ValueError, match="max_changes must not exceed 5000"):
        build_serialized_dag_diff(
            base_data=_payload(tasks=[]), target_data=_payload(tasks=[]), max_changes=5001
        )


def test_build_diff_reports_unkeyed_lists_as_one_stable_change() -> None:
    base = _payload(tasks=[])
    target = _payload(tasks=[])
    base["dag"]["custom_list"] = [{"name": "old"}]
    target["dag"]["custom_list"] = [{"name": "new"}]

    result = build_serialized_dag_diff(base_data=base, target_data=target)

    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert change["path"] == "/dag/custom_list"
    assert change["operation"] == "changed"
    assert change["category"] == "unknown"
    assert change["impact"] == "unknown"
    assert change["before_digest"].startswith("sha256:")
    assert change["after_digest"].startswith("sha256:")


def test_build_diff_reports_deadline_lists_as_one_stable_change() -> None:
    base = _payload(tasks=[])
    target = _payload(tasks=[])
    base["dag"]["deadline"] = [{"name": "old", "interval": 60}]
    target["dag"]["deadline"] = [{"name": "new", "interval": 60}]

    result = build_serialized_dag_diff(base_data=base, target_data=target)

    assert result["mode"] == "observed_state"
    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert change["path"] == "/dag/deadline"
    assert change["operation"] == "changed"
    assert change["category"] == "deadline"
    assert change["impact"] == "execution"


def test_build_diff_preserves_order_sensitive_string_lists() -> None:
    base = _payload(tasks=[])
    target = _payload(tasks=[])
    base["dag"]["template_searchpath"] = ["first", "second"]
    target["dag"]["template_searchpath"] = ["second", "first"]

    result = build_serialized_dag_diff(base_data=base, target_data=target)

    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert change["path"] == "/dag/template_searchpath"
    assert change["operation"] == "changed"


@pytest.mark.parametrize(
    ("base_task", "target_task"),
    [
        ({"task_id": "extract", "retries": 2}, {"task_id": "extract"}),
        (
            {"task_id": "extract", "retries": 2, "partial_kwargs": {"retries": 2}},
            {"task_id": "extract", "partial_kwargs": {}},
        ),
    ],
)
def test_build_diff_normalizes_v3_client_defaults(base_task, target_task) -> None:
    base = _payload(tasks=[base_task])
    base["__version"] = 2
    target = _payload(tasks=[target_task])
    target["client_defaults"] = {"tasks": {"retries": 2}}

    result = build_serialized_dag_diff(base_data=base, target_data=target)

    assert result["serialized_dag_schema_versions"] == {"base": 2, "target": 3}
    assert result["mode"] == "observed_state"
    assert result["changes"] == []


@pytest.mark.parametrize(
    "base_data",
    [
        {"__version": 3, "dag": {"tasks": []}, "client_defaults": []},
        {"__version": 3, "dag": {"tasks": []}, "client_defaults": {"tasks": []}},
        {"__version": 3, "dag": {"tasks": {}}, "client_defaults": {"tasks": {}}},
        {"__version": 3, "dag": {"tasks": [{}]}, "client_defaults": {"tasks": {}}},
    ],
)
def test_build_diff_rejects_malformed_client_defaults(base_data) -> None:
    result = build_serialized_dag_diff(base_data=base_data, target_data=_payload(tasks=[]))

    assert result["mode"] == "unavailable"
    assert result["changes"] == []
    assert result["unavailable_reason"] == "serialized_dag_canonicalization_failed"


def test_build_diff_ignores_exact_duplicate_dependencies() -> None:
    dependency = {
        "dependency_type": "task",
        "dependency_id": "extract-load",
        "source": "extract",
        "target": "load",
        "label": "extract-load",
    }

    result = build_serialized_dag_diff(
        base_data=_payload(tasks=[], dependencies=[dependency, dependency]),
        target_data=_payload(tasks=[], dependencies=[dependency]),
    )

    assert result["mode"] == "observed_state"
    assert result["changes"] == []


def test_build_diff_dependency_keys_do_not_collide_on_delimiters() -> None:
    first_dependency = {
        "dependency_type": "trigger",
        "dependency_id": "id",
        "source": "a",
        "target": "b|c",
        "label": "d",
    }
    second_dependency = {
        "dependency_type": "trigger",
        "dependency_id": "id",
        "source": "a",
        "target": "b",
        "label": "c|d",
    }

    result = build_serialized_dag_diff(
        base_data=_payload(tasks=[], dependencies=[first_dependency, second_dependency]),
        target_data=_payload(tasks=[], dependencies=[second_dependency, first_dependency]),
    )

    assert result["mode"] == "observed_state"
    assert result["changes"] == []


@pytest.mark.db_test
class TestGetDagVersionDiff:
    @pytest.fixture
    def dag_id(self, dag_maker, session):
        import datetime

        from airflow.providers.standard.operators.empty import EmptyOperator

        from tests_common.test_utils.db import clear_db_dags, clear_db_serialized_dags

        clear_db_dags()
        clear_db_serialized_dags()
        dag_id = "version_diff_dag"
        for version_number in range(1, 3):
            with dag_maker(dag_id, session=session, bundle_version=f"commit{version_number}"):
                for task_number in range(version_number):
                    EmptyOperator(task_id=f"task{task_number + 1}")
            dag_maker.create_dagrun(
                run_id=f"run{version_number}",
                logical_date=datetime.datetime(2020, 1, version_number, tzinfo=datetime.timezone.utc),
                session=session,
            )
            session.commit()
        # Read versions back from the DB the way the API and CLI callers do, so
        # serialized payloads carry plain JSON keys rather than in-memory Encoding enums.
        session.expunge_all()
        return dag_id

    def test_reports_observed_changes_between_versions(self, dag_id, session):
        result = get_dag_version_diff(dag_id, 1, 2, session=session)

        assert result["mode"] == "observed_state"
        paths = {change["path"]: change for change in result["changes"]}
        assert paths["/dag/tasks/task2"]["operation"] == "added"
        assert paths["/provenance/bundle_version"]["category"] == "provenance"
        assert result["source"] == {"status": "unavailable", "fidelity": "unavailable"}
        assert "values" not in result

    def test_raises_for_missing_version(self, dag_id, session):
        with pytest.raises(DagVersionNotFoundError, match="version_number: `3`"):
            get_dag_version_diff(dag_id, 1, 3, session=session)

    @pytest.mark.parametrize("version_numbers", [(0, 2), (1, 0)])
    def test_rejects_non_positive_version_numbers(self, dag_id, session, version_numbers):
        with pytest.raises(ValueError, match="Dag version numbers must be positive integers"):
            get_dag_version_diff(dag_id, *version_numbers, session=session)

    def test_marks_values_available_for_operator_authority(self, dag_id, session):
        result = get_dag_version_diff(dag_id, 1, 2, include_values=True, session=session)

        assert result["values"] == {"status": "available"}
        assert any("after_value" in change for change in result["changes"])

    def test_marks_values_unavailable_when_status_denied(self, dag_id, session):
        result = get_dag_version_diff(
            dag_id, 1, 2, include_values=True, values_status="unavailable", session=session
        )

        assert result["values"] == {"status": "unavailable"}
        assert all(
            "before_value" not in change and "after_value" not in change for change in result["changes"]
        )

    def test_includes_current_stored_source(self, dag_id, session):
        result = get_dag_version_diff(dag_id, 1, 2, include_source=True, session=session)

        source = result["source"]
        assert source["status"] == "current_stored_code"
        assert isinstance(source["changed"], bool)
        assert source["base"]["digest"].startswith("sha256:")
        assert source["target"]["content"] is not None

    def test_redacts_source_when_status_denied(self, dag_id, session):
        result = get_dag_version_diff(
            dag_id, 1, 2, include_source=True, source_status="redacted", session=session
        )

        assert result["source"] == {"status": "redacted", "fidelity": "redacted"}

    def test_marks_source_unavailable_when_code_missing(self, dag_id, session):
        from airflow.models.dagcode import DagCode

        session.execute(delete(DagCode))
        session.commit()
        session.expunge_all()

        result = get_dag_version_diff(dag_id, 1, 2, include_source=True, session=session)

        assert result["source"] == {"status": "unavailable", "fidelity": "unavailable"}
