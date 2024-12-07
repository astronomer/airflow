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

import os
import sys
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Callable, Literal, Union

import attrs
import pydantic

from airflow.callbacks.callback_requests import (
    CallbackRequest,
    DagCallbackRequest,
    TaskCallbackRequest,
)
from airflow.models.dagbag import DagBag
from airflow.models.serialized_dag import DagInfo
from airflow.sdk.execution_time.comms import GetConnection, GetVariable
from airflow.sdk.execution_time.supervisor import WatchedSubprocess
from airflow.stats import Stats

if TYPE_CHECKING:
    from datetime import datetime

    from airflow.typing_compat import Self
    from airflow.utils.context import Context


def _parse_file_as_process():
    import os

    import structlog

    from airflow.sdk.execution_time import task_runner
    # Parse DAG file, send JSON back up!

    comms_decoder = task_runner.CommsDecoder[DagFileParseRequest, DagFileParsingResult](
        input=sys.stdin,
        decoder=pydantic.TypeAdapter[DagFileParseRequest](DagFileParseRequest),
    )
    msg = comms_decoder.get_message()
    comms_decoder.request_socket = os.fdopen(msg.requests_fd, "wb", buffering=0)

    log = structlog.get_logger(logger_name="task")

    result = _parse_file(msg, log)
    comms_decoder.send_request(log, result)


def _parse_file(msg: DagFileParseRequest, log):
    from airflow.serialization.serialized_objects import SerializedDAG

    bag = DagBag(
        dag_folder=msg.file,
        include_examples=False,
        safe_mode=True,
        load_op_links=False,
    )
    dags = [DagInfo(data=SerializedDAG.to_dict(dag)) for dag in bag.dags.values()]
    result = DagFileParsingResult(
        fileloc=msg.file,
        serialized_dags=dags,
        import_errors=bag.import_errors,
    )

    if msg.callback_requests:
        _execute_callbacks(bag, msg.callback_requests, log)
    return result


def _execute_callbacks(dagbag: DagBag, callback_requests: list[CallbackRequest], log):
    for request in callback_requests:
        log.debug("Processing Callback Request", request=request)
        if isinstance(request, TaskCallbackRequest):
            raise NotImplementedError("Haven't coded Task callback yet!")
            # _execute_task_callbacks(dagbag, request)
        elif isinstance(request, DagCallbackRequest):
            _execute_dag_callbacks(dagbag, request, log)


def _execute_dag_callbacks(dagbag: DagBag, request: DagCallbackRequest, log):
    dag = dagbag.dags[request.dag_id]

    callbacks = dag.on_failure_callback if request.is_failure_callback else dag.on_success_callback
    if not callbacks:
        log.warning("Callback requested, but dag didn't have any", dag_id=request.dag_id)
        return

    callbacks = callbacks if isinstance(callbacks, list) else [callbacks]
    # TODO:We need a proper context object!
    context: Context = {}

    for callback in callbacks:
        log.info(
            "Executing on_%s dag callback",
            "failure" if request.is_failure_callback else "success",
            fn=callback,
            dag_id=request.dag_id,
        )
        try:
            callback(context)
        except Exception:
            log.exception("Callback failed", dag_id=request.dag_id)
            Stats.incr("dag.callback_exceptions", tags={"dag_id": request.dag_id})


class DagFileParseRequest(pydantic.BaseModel):
    """
    Request for DAG File Parsing.

    This is the request that the manager will send to the DAG parser with the dag file and
    any other necessary metadata.
    """

    file: str
    requests_fd: int
    callback_requests: list[CallbackRequest] = pydantic.Field(default_factory=list)
    type: Literal["DagFileParseRequest"] = "DagFileParseRequest"


class DagFileParsingResult(pydantic.BaseModel):
    """
    Result of DAG File Parsing.

    This is the result of a successful DAG parse, in this class, we gather all serialized DAGs,
    import errorsand warnings to send back to the scheduler to store in the DB.
    """

    fileloc: str
    serialized_dags: list[DagInfo]
    warnings: list | None = None
    import_errors: dict[str, str] | None = None
    type: Literal["DagFileParsingResult"] = "DagFileParsingResult"


ToParent = Annotated[
    Union[DagFileParsingResult, GetConnection, GetVariable],
    pydantic.Field(discriminator="type"),
]


@attrs.define()
class TaskSDKDagFileProcessor(WatchedSubprocess):
    """
    Parses dags with Task SDK API.

    Since DAGs are written with the Task SDK, we need to parse them in a task SDK process s.t.
    we can use the Task SDK definitions when serializing. This prevents potential conflicts with classes
    in core Airflow.
    """

    parsing_result: DagFileParsingResult | None = None

    @classmethod
    def start(  # type: ignore[override]
        cls,
        path: str | os.PathLike[str],
        callbacks: list[CallbackRequest],
        target: Callable[[], None] = _parse_file_as_process,
        **kwargs,
    ) -> Self:
        return super().start(path, callbacks, target=target, client=None, **kwargs)  # type:ignore[arg-type]

    def _on_started(self):
        # Override base class -- we don't need to tell anything we've started
        pass

    def _send_startup_message(  # type: ignore[override]
        self, callbacks: list[CallbackRequest], path: str | os.PathLike[str], child_comms_fd: int
    ):
        msg = DagFileParseRequest(
            file=os.fspath(path),
            requests_fd=child_comms_fd,
            callback_requests=callbacks,
        )
        self.stdin.write(msg.model_dump_json().encode() + b"\n")
        ...

    def handle_requests(self, log) -> Generator[None, bytes, None]:
        # TODO: Make decoder an instance variable, then this can live in the base class
        decoder = pydantic.TypeAdapter[ToParent](ToParent)

        while True:
            line = yield

            try:
                msg = decoder.validate_json(line)
            except Exception:
                log.exception("Unable to decode message", line=line)
                continue

            self._handle_request(msg, log)  # type: ignore[arg-type]

    def _handle_request(self, msg: ToParent, log):  # type: ignore[override]
        if isinstance(msg, DagFileParsingResult):
            self.parsing_result = msg
            return
        # GetVariable etc -- parsing a dag can run top level code that asks for an Airflow Variable
        super()._handle_request(msg, log)

    @property
    def exit_code(self) -> int | None:
        self._check_subprocess_exit()
        return self._exit_code

    @property
    def start_time(self) -> float:
        return self._process.create_time()

    def wait(self) -> int:
        raise NotImplementedError(f"Don't call wait on {type(self).__name__} objects")


@attrs.define
class DagFileStat:
    """Information about single processing of one file."""

    num_dags: int = 0
    import_errors: int = 0
    last_finish_time: datetime | None = None
    last_duration: float | None = None
    run_count: int = 0
    last_num_of_db_queries: int = 0


@attrs.define
class CollectionResult:
    """Result of collecting a DAG file."""

    stat: DagFileStat | None = None
    collected_dags: list[DagInfo] = []
    import_errors: dict[str, str] = {}


def collect_dag_results(
    run_duration: float,
    finish_time: datetime,
    run_count: int,
    path: str,
    parsing_result: DagFileParsingResult | None,
):
    result = CollectionResult()
    stat = DagFileStat(
        last_finish_time=finish_time,
        last_duration=run_duration,
        run_count=run_count + 1,
    )

    file_name = Path(path).stem
    Stats.timing(f"dag_processing.last_duration.{file_name}", stat.last_duration)
    Stats.timing("dag_processing.last_duration", stat.last_duration, tags={"file_name": file_name})

    if parsing_result is None:
        stat.import_errors = 1
    else:
        # record DAGs and import errors to database
        result.collected_dags = parsing_result.serialized_dags or []
        result.import_errors = parsing_result.import_errors or {}
        stat.num_dags = len(parsing_result.serialized_dags)
        if parsing_result.import_errors:
            stat.import_errors = len(parsing_result.import_errors)
    result.stat = stat
    return result
