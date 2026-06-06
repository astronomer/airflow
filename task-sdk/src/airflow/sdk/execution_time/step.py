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
"""
Task Steps (AIP-103 Steps v1).

A ``step`` is a named block of work inside a task. It does two things:

* **Display** -- emits log markers so the UI renders the block as a collapsible group with a
  status icon and a duration, interleaved with the task's other log lines.
* **Checkpointing** -- ``step.once(fn)`` runs ``fn`` exactly once across task retries. Its return
  value is persisted in the AIP-103 *task store* (which survives retries within a run), so a retry
  returns the cached value instead of re-running the work.

Pitch: *authoring model of N steps, runtime cost of one -- retry the failed step, not the whole
task.*

Example::

    from airflow.sdk import step, task
    from pathlib import Path


    @task(retries=3)
    def etl():
        with step("extract") as s:
            data = s.once(lambda: fetch_from_api())  # cached across retries
        with step("transform"):  # grouping + timing only
            rows = transform(data)
        with step("load") as s:
            s.once(lambda: load(rows))

For work that produces a filesystem side effect (a git checkout, a downloaded file) the cached
*value* is available on retry but the *files* may not be (a retry can land on a fresh worker).
Pass ``validate`` so a cache hit is revalidated and the work re-runs if the side effect is gone::

    with step("checkout") as s:
        repo = s.once(lambda: clone(url, dest), validate=lambda p: Path(p).is_dir())
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import sys
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from pydantic import JsonValue

    from airflow.sdk.execution_time.context import TaskStoreAccessor

__all__ = ["step", "Step"]

log = structlog.get_logger(logger_name="task")

#: Header prefix for the ``::group::`` start marker. The UI matches this prefix to tell a step
#: group apart from a plain log group (e.g. "Pre Execute"). Reserved -- do not name a plain group
#: with this prefix.
STEP_HEADER_PREFIX = "Step: "

#: Task-store keys written by steps are namespaced under this prefix. Reserved -- do not write your
#: own task-store keys under it.
STEP_KEY_PREFIX = "__step__"

#: Single reserved task-store key holding the latest step lifecycle/progress for the task instance
#: (overwritten on each step enter/progress/exit). The grid hover reads this one key so it can show
#: "which step is this task on, and how far along" WITHOUT fetching and parsing the log -- the
#: structured worker->server channel, not log scraping. Prototype: a production build would write a
#: dedicated, queryable ``task_step`` row instead of reusing the task store.
STEP_STATE_KEY = f"{STEP_KEY_PREFIX}.state"

#: Characters that are unsafe in a task-store key. The key is used as a URL path segment by the
#: task-store API, which does not percent-encode it, so "/", "?", "#", spaces etc. would corrupt the
#: request. ``:``, ``.``, ``_`` and ``-`` are safe in a path segment and are kept for readability.
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9._:-]")

#: Minimum seconds between ``step.progress()`` log markers. Progress is display-only (a log marker,
#: not stored), so this throttle just bounds log volume for tight loops; the final tick and the first
#: call always emit so the UI bar reaches 100% and appears promptly.
_PROGRESS_MIN_INTERVAL = 1.0


class Step(AbstractContextManager):
    """
    Handle for a single :func:`step` block. Obtained via ``with step(name) as s:``.

    Not instantiated directly -- use :func:`step`.
    """

    def __init__(
        self,
        name: str,
        *,
        cache: bool = True,
        retention: timedelta | None = None,
    ) -> None:
        if not name or not name.strip():
            raise ValueError("step() name must be a non-empty string")
        self.name = name
        self._cache = cache
        self._retention = retention
        self._task_store: TaskStoreAccessor | None = None
        self.cache_hits = 0
        self.misses = 0
        self._outputs: dict[str, JsonValue] = {}
        self._started_at = 0.0
        self._last_progress_at = 0.0
        # Latest progress, mirrored into the step-state task-store key so the grid hover can show it.
        self._progress_done: int | None = None
        self._progress_total: int | None = None
        self._progress_message: str | None = None

    def __enter__(self) -> Step:
        # Reset per-run state so a Step object that is entered more than once (an unusual but legal
        # `s = step("x"); with s: ...; with s: ...`) starts each block clean rather than carrying the
        # previous block's counters, outputs and progress-throttle timestamp.
        self.cache_hits = 0
        self.misses = 0
        self._outputs = {}
        self._last_progress_at = 0.0
        self._progress_done = None
        self._progress_total = None
        self._progress_message = None
        self._task_store = _current_task_store() if self._cache else None
        self._started_at = time.monotonic()
        # The start marker becomes the visible group header in the UI, so keep its payload in the
        # event string only -- structured kwargs would render inline after the event and corrupt the
        # step name. The ``Step: `` prefix is what tells the UI this group is a step.
        start_marker = f"::group::{STEP_HEADER_PREFIX}{self.name}"
        log.info(start_marker)
        # Mirror "this task is now running step <name>" into the step-state key for the grid hover.
        self._write_step_state("running")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        duration_ms = int((time.monotonic() - self._started_at) * 1000)
        if exc_type is not None:
            status = "failed"
        elif self.misses == 0 and self.cache_hits > 0:
            # Every checkpoint was a cache hit -- the step did no new work this attempt.
            status = "cached"
        else:
            status = "success"
        # The end marker closes the group: the UI consumes it (never renders it as a visible line),
        # so it is safe to carry the step outcome as structured fields here. Older UIs that only fold
        # ``::group::``/``::endgroup::`` ignore the extra fields.
        fields: dict[str, Any] = {
            "airflow_step": "end",
            "step_status": status,
            "step_duration_ms": duration_ms,
        }
        if self._outputs:
            fields["step_outputs"] = self._outputs
        log.info("::endgroup::", **fields)
        # Mirror the terminal outcome into the step-state key so a hover right after the step ends
        # shows it as done (success/cached/failed) rather than stuck "running".
        self._write_step_state(status, duration_ms=duration_ms)
        # Never suppress the exception -- a failing step is a failing task (normal retry path).
        return False

    def _write_step_state(self, status: str, *, duration_ms: int | None = None) -> None:
        """
        Overwrite the single step-state task-store key with the current step's status and progress.

        Read by the grid hover so it can show the running step (and how far along) without parsing
        logs. Gated on ``self._task_store`` -- a ``cache=False`` step touches the task store for
        nothing, including this -- and best-effort: state is display-only, so a write failure must
        never fail the task.
        """
        store = self._task_store
        if store is None:
            return
        state: dict[str, Any] = {"name": self.name, "status": status}
        if self._progress_done is not None:
            state["done"] = self._progress_done
        if self._progress_total is not None:
            state["total"] = self._progress_total
        if self._progress_message is not None:
            state["message"] = self._progress_message
        if duration_ms is not None:
            state["duration_ms"] = duration_ms
        try:
            store.set(STEP_STATE_KEY, state, retention=self._retention)
        except Exception:
            log.debug("Failed to write step state to task store", step_name=self.name, exc_info=True)

    def output(self, key: str, value: JsonValue) -> None:
        """
        Attach a metadata value to this step, shown as a chip on the step's header in the UI.

        For example ``s.output("rows", len(df))`` makes the UI render a ``rows: 1,234`` chip on the
        ``extract`` step. Values must be JSON-serializable. If the same key is set more than once,
        the last value wins; the values from the attempt that closes the step are the ones shown.
        """
        _ensure_json_serializable(value, key, self.name)
        self._outputs[key] = value

    def progress(self, done: int, total: int | None = None, *, message: str | None = None) -> None:
        """
        Report live progress for this step; the UI shows a progress bar on the running step.

        Call it inside a loop, e.g. ``for i, part in enumerate(parts): load(part); s.progress(i + 1,
        len(parts))``. Pass ``message`` instead of ``total`` for indeterminate progress.

        Progress shows up in two places, both **display only**: the log view reads it from a
        ``::step-progress::`` log marker, and the grid hover reads the latest tick from a single
        reserved task-store key (overwritten in place, never one row per tick). Emission is throttled
        to roughly once a second to bound both log volume and task-store writes in tight loops; the
        first call and the final tick (``done == total``) always emit.
        """
        now = time.monotonic()
        # ``total > 0`` guards a degenerate ``progress(0, 0)`` loop: without it ``done >= total`` is
        # always true, so every call would count as "final" and bypass the throttle (one write/iter).
        is_final = total is not None and total > 0 and done >= total
        first = self._last_progress_at == 0.0
        if not (first or is_final) and now - self._last_progress_at < _PROGRESS_MIN_INTERVAL:
            return
        self._last_progress_at = now
        self._progress_done = done
        self._progress_total = total
        self._progress_message = message

        # A control-token marker (consumed by the UI, not rendered as a visible line); the payload is
        # in structured fields, read from the raw datum like the end marker's fields.
        fields: dict[str, Any] = {
            "airflow_step": "progress",
            "step_name": self.name,
            "step_progress_done": done,
        }
        if total is not None:
            fields["step_progress_total"] = total
        if message is not None:
            fields["step_progress_message"] = message
        log.info("::step-progress::", **fields)
        # Mirror the latest tick into the step-state key (same throttle) for the grid hover.
        self._write_step_state("running")

    def once(
        self,
        fn: Callable[..., JsonValue],
        *args: Any,
        key: str | None = None,
        validate: Callable[[Any], bool] | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Run ``fn`` once across task retries and cache its return value in the task store.

        On the first attempt ``fn(*args, **kwargs)`` runs and its return value is persisted; on a
        later attempt the cached value is returned without calling ``fn``.

        Each checkpoint is identified by ``key``. When ``key`` is omitted it defaults to the call
        site (source file and line) -- stable across retries and unique per ``once()`` call -- so
        caching does not depend on how many ``once()`` calls ran before it, and a branch that
        changes the call order between attempts cannot return another checkpoint's value. Pass an
        explicit ``key`` when calling ``once()`` in a loop or from a shared helper (where one call
        site runs more than once). Keys are scoped to the task instance; keep them unique within it.
        Any key is normalised to a URL-safe form before use (the task store keys it as a URL path
        segment), so ``"extract/orders"`` and the like are handled rather than silently breaking.

        ``validate`` is called with the cached value on a cache hit. If it returns falsy, the cache
        is treated as stale and ``fn`` re-runs. Use it for steps with filesystem side effects, e.g.
        ``validate=lambda path: Path(path).is_dir()``.

        ``fn`` must return a JSON-serializable value (the task store holds JSON). Caching also
        requires running inside a task with ``cache=True``; otherwise ``fn`` always runs.
        """
        if key is None:
            # Default to the call site: stable across retries and unique per textual once() call, so
            # the key never depends on execution order. sys._getframe(1) is this method's caller.
            # The key is the basename + line + a short hash of the full path: the hash disambiguates
            # same-named files in different packages, while staying URL-safe (the task-store key is a
            # URL path segment, so it must not contain "/").
            frame = sys._getframe(1)
            path = frame.f_code.co_filename
            path_hash = hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]
            key = f"{os.path.basename(path)}:{frame.f_lineno}:{path_hash}"
        # Normalise the key (explicit or default) so it is always a safe task-store/URL path segment.
        store_key = f"{STEP_KEY_PREFIX}.once.{_url_safe_key(key)}"
        store = self._task_store

        if store is not None:
            envelope = store.get(store_key)
            if isinstance(envelope, dict) and envelope.get("__airflow_step_once__"):
                value = envelope.get("v")
                if validate is None or validate(value):
                    self.cache_hits += 1
                    log.info("Step checkpoint cache hit, skipping work", step_name=self.name, key=store_key)
                    return value
                log.info("Step checkpoint cache invalid, recomputing", step_name=self.name, key=store_key)

        value = fn(*args, **kwargs)
        self.misses += 1
        if store is not None:
            _ensure_json_serializable(value, store_key, self.name)
            store.set(store_key, {"__airflow_step_once__": True, "v": value}, retention=self._retention)
        return value


def step(name: str, *, cache: bool = True, retention: timedelta | None = None) -> Step:
    """
    Open a named step inside a task.

    :param name: human-readable step name shown in the UI as the step's group label. Used for
        display only -- ``once()`` checkpoints are keyed by call site or an explicit key, not by
        the step name -- but keeping it unique within a task makes the log easiest to read.
    :param cache: when ``True`` (default), ``step.once()`` persists results in the task store and
        skips re-running on retry. Set ``False`` for a pure display/timing group.
    :param retention: how long ``once()`` results are kept in the task store. ``None`` uses the
        ``[state_store] default_retention_days`` config.
    """
    return Step(name, cache=cache, retention=retention)


def _current_task_store() -> TaskStoreAccessor | None:
    """Return the current task's ``task_store`` accessor, or ``None`` outside a task context."""
    # Imported lazily (like the rest of execution_time, e.g. cache.py): this module is itself a lazy
    # re-export of airflow.sdk, so importing the facade at module load risks an init-order cycle.
    from airflow.sdk import get_current_context

    try:
        context = get_current_context()
    except RuntimeError:
        return None
    return context.get("task_store")


def _url_safe_key(key: str) -> str:
    """
    Return a task-store-safe form of ``key`` (the store keys it as a URL path segment).

    Keys with no unsafe characters are returned unchanged, so the readable call-site default and
    simple explicit keys are preserved. Otherwise unsafe characters are replaced and a short hash of
    the original is appended, so two keys that differ only in unsafe characters stay distinct.
    """
    if _UNSAFE_KEY_CHARS.search(key) is None:
        return key
    sanitized = _UNSAFE_KEY_CHARS.sub("_", key)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    return f"{sanitized}.{digest}"


def _ensure_json_serializable(value: Any, key: str, step_name: str) -> None:
    """
    Fail with a clear, step-scoped message if a value cannot be stored (the task store holds JSON).

    Validates against the same contract the store enforces (pydantic ``JsonValue``): only
    ``None``/``bool``/``int``/finite ``float``/``str``/``list``/``dict`` with string keys. This
    deliberately rejects things ``json.dumps`` would silently coerce (tuples, int-keyed dicts) or
    accept (``NaN``/``Infinity``) so the clear error fires here instead of an opaque comms error.
    """

    def _check(node: Any) -> None:
        if node is None or isinstance(node, (str, bool, int)):  # bool/int both valid JSON scalars
            return
        if isinstance(node, float):
            if math.isnan(node) or math.isinf(node):
                raise TypeError("NaN and Infinity are not valid JSON")
            return
        if isinstance(node, list):
            for item in node:
                _check(item)
            return
        if isinstance(node, dict):
            for dict_key, dict_value in node.items():
                if not isinstance(dict_key, str):
                    raise TypeError(f"dict keys must be strings, got {type(dict_key).__name__}")
                _check(dict_value)
            return
        raise TypeError(f"{type(node).__name__} is not JSON-serializable")

    try:
        _check(value)
    except TypeError as exc:
        raise TypeError(
            f"step value for key {key!r} in step {step_name!r} must be JSON-serializable "
            f"(the task store holds JSON): {exc}"
        ) from exc
