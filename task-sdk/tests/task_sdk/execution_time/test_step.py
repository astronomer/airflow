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

from unittest import mock

import pytest
import time_machine

from airflow.sdk.execution_time import step as step_module
from airflow.sdk.execution_time.step import STEP_HEADER_PREFIX, STEP_STATE_KEY, Step, step


class FakeTaskStore:
    """In-memory stand-in for ``TaskStoreAccessor`` that mirrors its get/set contract."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.set_calls: list[str] = []  # keys written, in order -- lets tests assert write volume

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value, *, retention=None) -> None:
        if value is None:
            raise ValueError("Cannot set value as None")
        self.set_calls.append(key)
        self.data[key] = value


@pytest.fixture
def store_in_context():
    """Patch the current task context so steps see a fresh in-memory task store."""
    store = FakeTaskStore()
    with mock.patch.object(step_module, "_current_task_store", return_value=store):
        yield store


@pytest.fixture
def captured_log():
    with mock.patch.object(step_module, "log") as log:
        yield log


def _markers(captured_log) -> list[tuple[str, dict]]:
    return [(call.args[0], call.kwargs) for call in captured_log.info.call_args_list]


def test_step_emits_group_start_and_end_markers(store_in_context, captured_log):
    # Act
    with step("extract"):
        pass

    # Assert: the start marker is a clean event (becomes the header); the end marker carries the
    # outcome as structured fields (it is consumed by the UI, never rendered).
    markers = _markers(captured_log)
    start_event, start_kwargs = markers[0]
    end_event, end_kwargs = markers[-1]
    assert start_event == f"::group::{STEP_HEADER_PREFIX}extract"
    assert start_kwargs == {}
    assert end_event == "::endgroup::"
    assert end_kwargs["airflow_step"] == "end"
    assert end_kwargs["step_status"] == "success"
    assert isinstance(end_kwargs["step_duration_ms"], int)
    assert "step_outputs" not in end_kwargs  # none set


def test_once_runs_then_caches_across_retries(store_in_context):
    calls = []

    def work():
        calls.append(1)
        return {"rows": 10}

    # First attempt: miss -> fn runs, value stored under the explicit key.
    with step("extract") as s1:
        result1 = s1.once(work, key="extract")
    assert result1 == {"rows": 10}
    assert s1.misses == 1
    assert s1.cache_hits == 0

    # Second attempt (same key = same checkpoint): hit -> fn NOT called.
    with step("extract") as s2:
        result2 = s2.once(work, key="extract")
    assert result2 == {"rows": 10}
    assert s2.cache_hits == 1
    assert s2.misses == 0
    assert len(calls) == 1, "fn must run exactly once across attempts"


def test_once_default_key_uses_call_site(store_in_context):
    # Two once() calls on different source lines get different (call-site) keys.
    with step("x") as s:
        s.once(lambda: "a")
        s.once(lambda: "b")
    once_keys = [k for k in store_in_context.data if ".once." in k]
    assert len(once_keys) == 2
    assert once_keys[0] != once_keys[1]
    # Keys are used as a URL path segment by the task-store API, so they must not contain "/".
    assert all("/" not in key for key in store_in_context.data)


def test_once_key_independent_of_call_order_across_retries(store_in_context):
    """Regression: a retry whose once() call order/count differs must not return another checkpoint's value."""
    # Attempt 1: two checkpoints, cfg then rows.
    with step("etl") as s1:
        s1.once(lambda: {"cfg": 1}, key="cfg")
        s1.once(lambda: [1, 2, 3], key="rows")

    # Attempt 2 (retry): a branch skips the cfg checkpoint, so rows is now the *first* once() call.
    with step("etl") as s2:
        rows = s2.once(lambda: [1, 2, 3], key="rows")

    # Keyed by identity, not position: the retry gets rows' value, never cfg's.
    assert rows == [1, 2, 3]
    assert s2.cache_hits == 1


def test_once_supports_none_and_falsy_return_values(store_in_context):
    calls = []

    def returns_none():
        calls.append(1)
        return None

    with step("s") as s1:
        assert s1.once(returns_none, key="k") is None
    with step("s") as s2:
        assert s2.once(returns_none, key="k") is None  # cached None, not re-run
    assert len(calls) == 1


def test_validate_recomputes_when_cache_invalid(store_in_context):
    produced = ["/tmp/repo-v1", "/tmp/repo-v2"]
    calls = []

    def clone():
        calls.append(1)
        return produced[len(calls) - 1]

    with step("checkout") as s1:
        path1 = s1.once(clone, key="checkout", validate=lambda p: False)
    assert path1 == "/tmp/repo-v1"

    # Retry: validate returns False -> cache treated as stale -> clone re-runs.
    with step("checkout") as s2:
        path2 = s2.once(clone, key="checkout", validate=lambda p: False)
    assert path2 == "/tmp/repo-v2"
    assert len(calls) == 2
    assert s2.cache_hits == 0
    assert s2.misses == 1


def test_validate_uses_cache_when_valid(store_in_context):
    calls = []

    def clone():
        calls.append(1)
        return "/tmp/repo"

    with step("checkout") as s1:
        s1.once(clone, key="checkout", validate=lambda p: True)
    with step("checkout") as s2:
        path = s2.once(clone, key="checkout", validate=lambda p: True)
    assert path == "/tmp/repo"
    assert len(calls) == 1
    assert s2.cache_hits == 1


def test_step_status_cached_when_all_hits(store_in_context, captured_log):
    with step("x") as s1:
        s1.once(lambda: 1, key="k")
    captured_log.reset_mock()
    with step("x") as s2:
        s2.once(lambda: 1, key="k")
    _, end_kwargs = _markers(captured_log)[-1]
    assert end_kwargs["step_status"] == "cached"


def test_step_status_failed_and_exception_propagates(store_in_context, captured_log):
    with pytest.raises(RuntimeError, match="boom"):
        with step("x"):
            raise RuntimeError("boom")
    _, end_kwargs = _markers(captured_log)[-1]
    assert end_kwargs["step_status"] == "failed"


def test_output_recorded_in_end_marker(store_in_context, captured_log):
    with step("extract") as s:
        s.output("rows", 8630)
        s.output("source", "api://orders")
    _, end_kwargs = _markers(captured_log)[-1]
    assert end_kwargs["step_outputs"] == {"rows": 8630, "source": "api://orders"}


def test_output_rejects_non_json_value(store_in_context):
    with pytest.raises(TypeError, match="JSON-serializable"):
        with step("x") as s:
            s.output("bad", object())


def test_no_context_disables_cache_and_always_runs(captured_log):
    calls = []
    with mock.patch.object(step_module, "_current_task_store", return_value=None):
        with step("x") as s1:
            s1.once(lambda: calls.append(1), key="k")
        with step("x") as s2:
            s2.once(lambda: calls.append(1), key="k")
    assert len(calls) == 2  # no caching without a task context


def test_cache_false_disables_persistence(store_in_context):
    calls = []
    with step("x", cache=False) as s1:
        s1.once(lambda: calls.append(1), key="k")
    with step("x", cache=False) as s2:
        s2.once(lambda: calls.append(1), key="k")
    assert len(calls) == 2
    assert store_in_context.data == {}


def test_explicit_key_with_unsafe_chars_is_url_safe_and_caches(store_in_context):
    calls = []

    def work():
        calls.append(1)
        return "v"

    # A "/" in an explicit key would break the task-store URL; it must be normalised, and caching
    # must still work consistently across attempts.
    with step("x") as s1:
        assert s1.once(work, key="extract/orders") == "v"
    with step("x") as s2:
        assert s2.once(work, key="extract/orders") == "v"
    assert len(calls) == 1
    assert all("/" not in key for key in store_in_context.data)


def test_explicit_keys_differing_only_in_unsafe_chars_do_not_collide(store_in_context):
    with step("x") as s:
        s.once(lambda: "b", key="a/b")
        s.once(lambda: "c", key="a/c")
    once_keys = [key for key in store_in_context.data if ".once." in key]
    assert len(set(once_keys)) == 2


@pytest.mark.parametrize(
    "bad_value",
    [
        object(),
        (1, 2, 3),  # tuple -- json.dumps would coerce to a list, but the task store rejects it
        {1: "a"},  # non-string dict key
        float("nan"),
        float("inf"),
        [object()],  # nested
        {"k": (1,)},  # nested
    ],
)
def test_once_rejects_non_json_values_with_clear_error(store_in_context, bad_value):
    with pytest.raises(TypeError, match="JSON-serializable"):
        with step("x") as s:
            s.once(lambda: bad_value, key="k")


def test_progress_emits_first_and_final_markers_and_throttles_the_rest(store_in_context, captured_log):
    # Calls happen microseconds apart (well within the 1s throttle), so only the first and the final
    # tick emit; the middle one is throttled.
    with step("load") as s:
        s.progress(1, 3)
        s.progress(2, 3)
        s.progress(3, 3)
    progress = [(event, kwargs) for event, kwargs in _markers(captured_log) if event == "::step-progress::"]
    assert [kwargs["step_progress_done"] for _, kwargs in progress] == [1, 3]
    assert all(kwargs["step_progress_total"] == 3 for _, kwargs in progress)
    assert all(kwargs["airflow_step"] == "progress" for _, kwargs in progress)


def test_progress_supports_indeterminate_message(store_in_context, captured_log):
    with step("x") as s:
        s.progress(5, message="page 5")
    _, kwargs = next((e, k) for e, k in _markers(captured_log) if e == "::step-progress::")
    assert kwargs["step_progress_done"] == 5
    assert kwargs["step_progress_message"] == "page 5"
    assert "step_progress_total" not in kwargs


def test_step_writes_running_then_terminal_state_for_grid_hover(store_in_context):
    # The grid hover reads STEP_STATE_KEY (a single, overwritten key) instead of parsing the log.
    with step("transform") as s:
        # Mid-step: the hover should see the step as running.
        assert store_in_context.data[STEP_STATE_KEY] == {"name": "transform", "status": "running"}
        s.output("rows", 10)  # outputs are not part of the hover state
    # After exit: the terminal outcome, with a duration.
    final = store_in_context.data[STEP_STATE_KEY]
    assert final["name"] == "transform"
    assert final["status"] == "success"
    assert isinstance(final["duration_ms"], int)


def test_step_state_records_latest_progress(store_in_context):
    with step("load") as s:
        s.progress(5, 8, message="copying orders_2026_05.parquet")
        # The hover reflects the latest tick while the step is still running.
        running = store_in_context.data[STEP_STATE_KEY]
        assert running == {
            "name": "load",
            "status": "running",
            "done": 5,
            "total": 8,
            "message": "copying orders_2026_05.parquet",
        }
    # The final state keeps the last progress and flips to the terminal status.
    final = store_in_context.data[STEP_STATE_KEY]
    assert final["status"] == "success"
    assert final["done"] == 5
    assert final["total"] == 8


def test_step_state_writes_are_throttled_not_one_per_progress_call(store_in_context):
    # The hot-path safety claim: a tight progress loop must NOT write the step-state key once per
    # iteration. With time frozen, only the first tick and the final (done == total) tick emit, so
    # the step-state key is written enter + first-progress + final-progress + exit = 4 times, never
    # once-per-call -- regardless of how many progress() calls the loop makes.
    with time_machine.travel("2026-01-01", tick=False):
        with step("load") as s:
            for done in range(1, 101):
                s.progress(done, 100)
    state_writes = [key for key in store_in_context.set_calls if key == STEP_STATE_KEY]
    assert len(state_writes) == 4  # enter + first + final + exit, not 100+


def test_degenerate_zero_total_progress_does_not_bypass_throttle(store_in_context):
    # progress(0, 0) must not be treated as "final" on every call (which would defeat the throttle).
    with time_machine.travel("2026-01-01", tick=False):
        with step("scan") as s:
            for _ in range(50):
                s.progress(0, 0)
    state_writes = [key for key in store_in_context.set_calls if key == STEP_STATE_KEY]
    # enter + first progress + exit; the remaining 49 ticks are throttled (never "final").
    assert len(state_writes) == 3


def test_failed_step_writes_failed_state(store_in_context):
    with pytest.raises(RuntimeError, match="boom"):
        with step("validate"):
            raise RuntimeError("boom")
    assert store_in_context.data[STEP_STATE_KEY]["status"] == "failed"


def test_cache_false_writes_no_step_state(store_in_context):
    # cache=False opts out of all task-store interaction, including the hover state.
    with step("display-only", cache=False):
        pass
    assert STEP_STATE_KEY not in store_in_context.data


def test_reused_step_object_resets_state_on_reentry(store_in_context, captured_log):
    # Reusing the same Step object across two `with` blocks must start each block clean.
    s = step("x")
    with s:
        s.once(lambda: 1, key="k")  # miss
        s.output("a", 1)
        s.progress(1, 10)
    assert s.misses == 1

    with s:  # re-enter the SAME object
        s.once(lambda: 1, key="k")  # now a cache hit
        s.progress(1, 10)  # first call of this block -> emits (not throttled by the prior block)

    assert s.cache_hits == 1
    assert s.misses == 0  # reset, not carried over from the first block
    done_ones = [
        kwargs
        for event, kwargs in _markers(captured_log)
        if event == "::step-progress::" and kwargs["step_progress_done"] == 1
    ]
    assert len(done_ones) == 2  # one per block; the second was not throttled away


def test_empty_name_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        Step("")
