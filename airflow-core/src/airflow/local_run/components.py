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
Run one of the components that schedule a project's Dags.

Started as ``python -m airflow.local_run.components NAME`` by the server of ``airflow standalone --project``,
with the server's environment, so each component uses the project's database and the server's JWT secret.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time

from airflow.cli.cli_parser import get_parser
from airflow.jobs.job import Job, run_job
from airflow.local_run.scheduler import LocalSchedulerJobRunner
from airflow.utils.process_utils import set_component_mp_start_method
from airflow.utils.providers_configuration_loader import providers_configuration_loaded

# Started without --queues, the triggerer leaves alone the triggers that local runs' processes run themselves.
# Its log server would take the same port in every project; the UI reads trigger logs from their files.
TRIGGERER_ARGS = ["--skip-serve-logs"]
PARENT_CHECK_INTERVAL = 1.0


def main(argv: list[str]) -> None:
    exit_with_parent(os.getppid())
    name = argv[0]
    if name == "scheduler":
        run_scheduler()
    else:
        # The component's own command, without the configuration file ``python -m airflow`` would write to
        # the project's history.
        args = get_parser().parse_args([name, *(TRIGGERER_ARGS if name == "triggerer" else [])])
        args.func(args)


@providers_configuration_loaded
def run_scheduler() -> None:
    """Run the project's scheduler as ``airflow scheduler`` does, without its log server, as for the triggerer."""
    set_component_mp_start_method("scheduler")
    job_runner = LocalSchedulerJobRunner(job=Job())
    run_job(job=job_runner.job, execute_callable=job_runner._execute)


def exit_with_parent(parent_pid: int, interval: float = PARENT_CHECK_INTERVAL) -> None:
    """Stop this process, as the server would, once the server has gone, e.g. because it was killed."""

    def watch() -> None:
        while os.getppid() == parent_pid:
            time.sleep(interval)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=watch, name="exit-with-parent", daemon=True).start()


if __name__ == "__main__":
    main(sys.argv[1:])
