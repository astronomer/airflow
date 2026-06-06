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
Example Dag demonstrating AIP-103 Task Steps (Steps v1).

A task is authored as named ``step`` blocks. ``step.once()`` runs a unit of work once and caches
its result in the task store, so a retry resumes from the last successful step instead of redoing
everything. The UI renders each step as a collapsible group with a status icon and duration.

This Dag fails on the first attempt *after* the expensive ``extract`` and ``checkout`` steps have
completed. The retry reuses both (extract from cache, checkout after revalidating the files still
exist on disk) and only re-runs the cheap remaining work.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

from airflow.sdk import DAG, get_current_context, step, task

log = logging.getLogger(__name__)


def _expensive_fetch() -> dict:
    """Simulate a slow API call that returns JSON."""
    time.sleep(2)
    return {"rows": random.randint(100, 10_000), "source": "api://orders"}


def _checkout_repo(dest: str) -> str:
    """Simulate a git checkout: produces files on local disk and returns the path."""
    time.sleep(2)
    repo = Path(dest)
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "build.sh").write_text("echo building\n")
    return str(repo)


def _expensive_untracked_transform() -> None:
    """Simulate slow work done OUTSIDE any step(). The UI flags the gap as 'untracked'."""
    time.sleep(6)


with DAG(
    dag_id="example_task_steps",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["example", "task-steps", "aip-103"],
    doc_md=__doc__,
):

    @task(retries=2, retry_delay=timedelta(seconds=5))
    def build():
        # A plain log line outside any step renders as a normal (loose) log line in the UI,
        # interleaved with the collapsible step groups -- this is "mixed mode".
        log.info("Starting build pipeline")

        # Pure-value step: the result is JSON, safe to cache directly.
        with step("extract") as s:
            data = s.once(_expensive_fetch)
            # Surface metadata on the step header in the UI (renders as `rows: 8,630` chips).
            s.output("rows", data["rows"])
            s.output("source", data["source"])
            log.info("extracted %s rows from %s", data["rows"], data["source"])

        # Side-effect step: the cached value is a path, but the files may not survive a retry on a
        # fresh worker. ``validate`` re-runs the checkout if the directory is gone.
        with step("checkout") as s:
            repo_dir = s.once(
                lambda: _checkout_repo("/tmp/example_task_steps_repo"),
                validate=lambda path: Path(path).is_dir(),
            )
            log.info("repo ready at %s", repo_dir)

        # Plain grouping step (no caching): cheap, deterministic work.
        with step("transform"):
            total = data["rows"] * 2
            log.info("transformed total = %s", total)

        # This step fails on the first attempt, so the UI renders it as a failed (red) step. The
        # retry replays extract+checkout from cache and this step then succeeds.
        with step("validate"):
            try_number = get_current_context()["ti"].try_number
            if try_number == 1:
                raise RuntimeError(
                    "Simulated validation failure on the first attempt. The retry resumes from cached steps."
                )
            log.info("validation passed")

        # Slow work with no step() wrapper. The steps panel surfaces this gap as "untracked": it is
        # not checkpointed, so it re-runs on every retry -- a nudge to wrap it in a step().
        _expensive_untracked_transform()

        with step("load") as s:
            # Load in partitions, reporting live progress -- the UI shows a progress bar on the
            # running step (the classic "how many partitions done" indicator).
            partitions = 8
            for i in range(partitions):
                time.sleep(1)
                s.progress(i + 1, partitions)
            s.once(lambda: {"loaded": total, "repo": repo_dir})
            s.output("loaded", total)
            log.info("load complete")

        return total

    build()
