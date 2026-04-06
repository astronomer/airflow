#!/usr/bin/env python3
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
Analyze an OTEL trace JSON export (Honeycomb format).

Prints all spans in chronological order by start time, then a summary of
spans >= 10 ms grouped by category.

Usage:
    python dev/analyze_trace.py /path/to/trace.json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Annotations for known span names (matched against the leaf segment of the full name)
ANNOTATIONS: dict[str, list[str]] = {
    "hook.on_starting": [
        "get_listener_manager().hook.on_starting(component)",
    ],
    "listener.on_task_instance_running": [
        "get_listener_manager().hook.on_task_instance_running(...)",
    ],
    "listener.success_callback": [
        "get_listener_manager().hook.on_task_instance_success(...)",
    ],
    "listener.before_stopping": [
        "get_listener_manager().hook.before_stopping(component)",
    ],
    "get_bundle": [
        "DagBundlesManager().get_bundle()",
    ],
    "bundle_init": [
        "BundleDagBag(...) / dag bundle initialization",
    ],
    "set_rendered_fields": [
        "_serialize_rendered_fields(ti.task)",
        "SUPERVISOR_COMMS.send(msg=SetRenderedFields(rendered_fields=rendered_fields))",
    ],
    "handle success": [
        "_handle_current_task_success(context, ti)",
    ],
    "close_socket": ["task end (scheduler lag)"],
}

# Leaf span names that are listener-related
LISTENER_SPANS = {
    "hook.on_starting",
    "listener.on_task_instance_running",
    "listener.success_callback",
    "listener.before_stopping",
    "get_template_context",  # always called from within a listener span
}


def parse_ts(ts: str) -> float:
    """Return Unix timestamp in milliseconds. Handles nanosecond precision."""
    from datetime import datetime

    ts = ts.replace("Z", "+00:00")
    if "." in ts:
        dot = ts.index(".")
        plus = ts.index("+", dot)
        frac = ts[dot + 1 : plus]
        ts = ts[: dot + 1] + frac[:6].ljust(6, "0") + ts[plus:]
    return datetime.fromisoformat(ts).timestamp() * 1000.0


def full_name(span: dict, by_id: dict) -> str:
    parts = []
    s = span
    while s:
        parts.append(s["name"])
        s = by_id.get(s.get("trace.parent_id"))
    return " | ".join(reversed(parts))


def ancestor_names(span: dict, by_id: dict) -> set[str]:
    """Return the set of ancestor span names (not including span itself)."""
    names = set()
    s = by_id.get(span.get("trace.parent_id"))
    while s:
        names.add(s["name"])
        s = by_id.get(s.get("trace.parent_id"))
    return names


def is_listener_span(span: dict, by_id: dict) -> bool:
    if span["name"] in LISTENER_SPANS:
        return True
    # get_template_context is only a listener span when inside a listener ancestor
    return bool(ancestor_names(span, by_id) & LISTENER_SPANS)


def task_run_ancestor(span: dict, by_id: dict, root_id: str) -> str | None:
    """Return the span_id of the task_run ancestor of span, or None if span is at/above root."""
    s = span
    while s:
        pid = s.get("trace.parent_id")
        if pid == root_id:
            return s["trace.span_id"]
        s = by_id.get(pid)
    return None


def print_summary(spans: list[dict], durations: list[float], by_id: dict, threshold_ms: float) -> None:
    notable = [(s, d) for s, d in zip(spans, durations) if d >= threshold_ms]
    if not notable:
        return

    root = spans[0]  # already sorted; root is first
    root_id = root["trace.span_id"]
    root_start = parse_ts(root["Timestamp"])

    # Build a map of span index -> task_run ancestor id
    task_run_of = [task_run_ancestor(s, by_id, root_id) for s in spans]

    sched_delay_items: list[tuple[str, float]] = []
    inter_task_span_ids: set[str] = set()

    # dag_run start -> first task_run start
    task_runs = [s for s in spans if s.get("trace.parent_id") == root_id]
    if task_runs:
        first_task_start = parse_ts(min(task_runs, key=lambda s: parse_ts(s["Timestamp"]))["Timestamp"])
        d = first_task_start - root_start
        if d >= threshold_ms:
            sched_delay_items.append(("dag run set to running to first task", d))

    # Any span whose computed duration crosses into a different (sequential) task_run.
    # We only count a transition once per task_run pair to avoid double-counting
    # when tasks run in parallel and their spans interleave.
    seen_transitions: set[tuple[str | None, str | None]] = set()
    for i, (s, d) in enumerate(zip(spans, durations)):
        if i + 1 >= len(spans) or d < threshold_ms:
            continue
        tr_cur = task_run_of[i]
        tr_next = task_run_of[i + 1]
        if tr_cur == tr_next or tr_cur is None or tr_next is None:
            continue
        # Only count forward transitions (next task started after current task)
        if parse_ts(by_id[tr_next]["Timestamp"]) <= parse_ts(by_id[tr_cur]["Timestamp"]):
            continue
        transition = (tr_cur, tr_next)
        if transition in seen_transitions:
            continue
        seen_transitions.add(transition)
        cur_task_name = by_id[tr_cur]["name"]
        next_task_name = by_id[tr_next]["name"]
        sched_delay_items.append((f"{cur_task_name} -> {next_task_name}", d))
        inter_task_span_ids.add(s["trace.span_id"])

    listener_items = [
        (s, d)
        for s, d in notable
        if is_listener_span(s, by_id) and s["trace.span_id"] not in inter_task_span_ids
    ]
    misc_items = [
        (s, d)
        for s, d in notable
        if not is_listener_span(s, by_id)
        and "trace.parent_id" in s  # exclude root span
        and s["trace.span_id"] not in inter_task_span_ids
        and s["name"] != "execute"
    ]

    print()
    print("=" * 72)
    print("SUMMARY  (spans >= {:.0f} ms)".format(threshold_ms))
    print("=" * 72)

    if sched_delay_items:
        print()
        print("scheduler delay:")
        for label, d in sched_delay_items:
            print(f"     * {round(d)} ms  {label}")

    if listener_items:
        print()
        print("listeners:")
        for s, d in listener_items:
            print(f"     * {round(d)} ms:  {full_name(s, by_id)}")
            for note in ANNOTATIONS.get(s["name"], []):
                print(f"          * {note}")

    if misc_items:
        print()
        print("misc:")
        for s, d in misc_items:
            print(f"     * {round(d)} ms:  {full_name(s, by_id)}")
            for note in ANNOTATIONS.get(s["name"], []):
                print(f"          * {note}")


def analyze(data: list[dict[str, Any]], summary_threshold_ms: float) -> None:
    by_id = {s["trace.span_id"]: s for s in data}
    spans = sorted(data, key=lambda s: parse_ts(s["Timestamp"]))

    roots = [s for s in spans if "trace.parent_id" not in s]
    if not roots:
        print("No root span found.", file=sys.stderr)
        sys.exit(1)
    origin = parse_ts(roots[0]["Timestamp"])

    durations: list[float] = []
    print(f"{'Offset (ms)':>14}  {'Duration (ms)':>14}  Name")
    print(f"{'----------':>14}  {'------------':>14}  ----")
    for i, s in enumerate(spans):
        offset = parse_ts(s["Timestamp"]) - origin
        if i + 1 < len(spans):
            duration = parse_ts(spans[i + 1]["Timestamp"]) - parse_ts(s["Timestamp"])
        else:
            duration = s["duration_ms"]
        durations.append(duration)
        print(f"{offset:>14.3f}  {round(duration):>14}  {full_name(s, by_id)}")

    print_summary(spans, durations, by_id, summary_threshold_ms)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_file", help="Path to the Honeycomb trace JSON export")
    parser.add_argument(
        "--summary-threshold-ms",
        type=float,
        default=10.0,
        help="Minimum duration in ms to include in summary (default: 10)",
    )
    args = parser.parse_args()

    with open(args.trace_file) as f:
        data = json.load(f)

    analyze(data, args.summary_threshold_ms)


if __name__ == "__main__":
    main()
