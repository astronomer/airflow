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
"""
Run a Python Dag file for gust as if it were a Lang-SDK bundle.

gust starts this with the interpreter's ``-c``, as
``-c <this> parse|run <path> --comm=<host:port> --logs=<host:port>``. It connects back to gust,
then answers the Dag parse request or runs the task instance with the Task SDK's own entry points,
loading the Dags from ``<path>`` the way ``python <path>`` would run it instead of through a Dag
bundle. It uses private parts of the Task SDK and Airflow core, so it follows their changes.
"""

from __future__ import annotations

import os
import runpy
import socket
import sys
import traceback
import types
import zipfile

# The module name the Dag file runs as. It is not __main__, so a Dag file's
# ``if __name__ == "__main__": dag.test()`` block does not run, as in Airflow.
MODULE_NAME = "__gust_dag__"


def connect(address):
    host, _, port = address.rpartition(":")
    return socket.create_connection((host, int(port)))


def set_script_path(path):
    """Put on ``sys.path`` what ``python <path>`` puts there, in place of ``-c``'s current directory."""
    if sys.flags.safe_path:
        return
    if os.path.isdir(path) or zipfile.is_zipfile(path):
        sys.path[0] = path
    else:
        sys.path[0] = os.path.dirname(os.path.realpath(path))


def load_dags(path):
    """
    Run *path* and return its Dags by ID.

    Like Airflow's Python importer, this finds the Dags at the module's top level and every Dag
    created in a ``with DAG(...)`` block or by ``@dag``, whichever module created it.
    """
    from airflow.sdk import DAG
    from airflow.sdk.definitions._internal.contextmanager import DagContext

    DagContext.autoregistered_dags.clear()
    # Dags are only autoregistered while this names the module being run, which runpy registers
    # in sys.modules for as long as the code runs.
    DagContext.current_autoregister_module_name = MODULE_NAME
    try:
        namespace = runpy.run_path(path, run_name=MODULE_NAME)
    finally:
        DagContext.current_autoregister_module_name = None
    # runpy drops its module when the code finishes. Keep one, so that classes defined in the Dag
    # file can still be found by module name, as they can in Airflow.
    module = types.ModuleType(MODULE_NAME)
    module.__dict__.update(namespace)
    sys.modules[MODULE_NAME] = module

    found = [value for value in namespace.values() if isinstance(value, DAG)]
    found.extend(dag for dag, _ in DagContext.autoregistered_dags)
    DagContext.autoregistered_dags.clear()
    root = sys.path[0] or os.getcwd()
    dags = {}
    for dag in found:
        if dags.setdefault(dag.dag_id, dag) is not dag:
            raise ValueError(f"Dag {dag.dag_id!r} is defined more than once")
        if dag.fileloc:
            dag.relative_fileloc = os.path.relpath(dag.fileloc, root)
    return dags


def parse(path):
    import structlog
    from pydantic import TypeAdapter

    from airflow.dag_processing.processor import (
        DagFileParseRequest,
        DagFileParsingResult,
        ToDagProcessor,
        ToManager,
        _serialize_dags,
    )
    from airflow.sdk.execution_time import comms, task_runner

    decoder = comms.CommsDecoder[ToDagProcessor, ToManager](body_decoder=TypeAdapter(ToDagProcessor))
    request = decoder._get_response()
    if not isinstance(request, DagFileParseRequest):
        raise RuntimeError(f"Required first message to be a DagFileParseRequest, it was {request}")
    task_runner.SUPERVISOR_COMMS = decoder
    log = structlog.get_logger(logger_name="task")
    try:
        dags = load_dags(path)
    except Exception:
        result = DagFileParsingResult(
            fileloc=request.file,
            serialized_dags=[],
            import_errors={request.file: traceback.format_exc()},
        )
    else:
        serialized, errors = _serialize_dags(types.SimpleNamespace(dags=dags), log)
        result = DagFileParsingResult(fileloc=request.file, serialized_dags=serialized, import_errors=errors)
    decoder.send(result)


class Bundle:
    """What the task runner reads of a Dag bundle. gust has none, so there is no version to lock."""

    name = "gust"
    version = None

    def __init__(self, path):
        self.path = path


def run(path):
    from airflow.sdk.bases.operator import BaseOperator
    from airflow.sdk.definitions.mappedoperator import MappedOperator
    from airflow.sdk.execution_time import task_runner
    from airflow.sdk.execution_time.task_runner import RuntimeTaskInstance, TaskInstanceState

    def parse_task(what, log):
        dags = load_dags(path)
        if (dag := dags.get(what.ti.dag_id)) is None:
            log.error("Dag not found during start up", dag_id=what.ti.dag_id, path=path)
            sys.exit(1)
        if (task := dag.task_dict.get(what.ti.task_id)) is None:
            log.error("Task not found in Dag during start up", dag_id=dag.dag_id, task_id=what.ti.task_id)
            sys.exit(1)
        if not isinstance(task, (BaseOperator, MappedOperator)):
            raise TypeError(f"task is of the wrong type, got {type(task)}")
        # gust refuses stubs after parsing; with --no-parse, this is the first place that knows.
        if task.is_stub:
            log.error(
                "gust does not run task handlers for stub tasks", dag_id=dag.dag_id, task_id=task.task_id
            )
            sys.exit(1)
        task_runner.check_xcom_backend_supports_loops(dag)
        task_runner._register_deserialization_allowed_classes(dag, log)
        return RuntimeTaskInstance.model_construct(
            **what.ti.model_dump(exclude_unset=True),
            task=task,
            bundle_instance=Bundle(sys.path[0] or os.getcwd()),
            _ti_context_from_server=what.ti_context,
            max_tries=what.ti_context.max_tries,
            start_date=what.start_date,
            state=TaskInstanceState.RUNNING,
            sentry_integration=what.sentry_integration,
        )

    task_runner.parse = parse_task
    task_runner.main()


def main():
    mode, path, *options = sys.argv[1:]
    addresses = dict(o[2:].split("=", 1) for o in options if o.startswith("--") and "=" in o)
    comm = connect(addresses["comm"])
    logs = connect(addresses["logs"])
    # The Task SDK reads and writes its supervisor messages on fd 0.
    os.dup2(comm.fileno(), 0)
    comm.close()
    os.environ["_AIRFLOW_PROCESS_CONTEXT"] = "client"

    from airflow.sdk.execution_time.supervisor import _configure_logs_over_json_channel

    _configure_logs_over_json_channel(logs.detach())
    sys.argv = [path]
    set_script_path(path)
    {"parse": parse, "run": run}[mode](path)


main()
