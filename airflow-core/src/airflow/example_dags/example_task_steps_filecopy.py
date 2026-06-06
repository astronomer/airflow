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
Example Dag showing in-step live progress (AIP-103 Task Steps).

A ``copy`` step transfers a set of files and calls ``s.progress(done, total, message=...)`` after
each one. While the task runs, the log view renders a live progress bar on the step with the
percentage and the file currently being copied -- the long-requested "how far along is my transfer"
indicator. The same latest tick is mirrored (throttled, into a single overwritten task-store key,
never one row per tick) so the grid hover shows the running step and its progress without parsing
the log. Hover the running ``sync`` cell in the grid to see it.
"""

from __future__ import annotations

import time
from datetime import datetime

from airflow.sdk import DAG, step, task

# Pretend these are large files being synced from a remote system.
_FILES = [f"orders_2026_{month:02d}.parquet" for month in range(1, 13)]


def _copy_file(name: str) -> int:
    """Simulate copying one file; returns the bytes written."""
    time.sleep(1)
    return 8_000_000


with DAG(
    dag_id="example_task_steps_filecopy",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["example", "task-steps", "aip-103"],
    doc_md=__doc__,
):

    @task
    def sync():
        with step("copy") as s:
            total_bytes = 0
            for index, name in enumerate(_FILES):
                total_bytes += _copy_file(name)
                # Live progress: percent done + the file currently being copied.
                s.progress(index + 1, len(_FILES), message=f"copying {name}")
            s.output("files", len(_FILES))
            s.output("bytes", total_bytes)

        with step("verify"):
            print(f"verified {len(_FILES)} files, {total_bytes} bytes")

        return len(_FILES)

    sync()
