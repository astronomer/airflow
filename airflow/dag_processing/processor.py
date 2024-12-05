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
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Callable, Literal, Union

import attrs
import pydantic
from sqlalchemy import event

from airflow.models.dagbag import DagBag
from airflow.models.serialized_dag import DagInfo
from airflow.sdk.execution_time.comms import GetConnection, GetVariable
from airflow.sdk.execution_time.supervisor import WatchedSubprocess
from airflow.stats import Stats
from airflow.utils import timezone

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm.session import Session

    from airflow.models.taskinstance import TaskInstance


@dataclass
class _QueryCounter:
    queries_number: int = 0

    def inc(self):
        self.queries_number += 1


@contextmanager
def count_queries(session: Session) -> Generator[_QueryCounter, None, None]:
    # using list allows to read the updated counter from what context manager returns
    counter: _QueryCounter = _QueryCounter()

    @event.listens_for(session, "do_orm_execute")
    def _count_db_queries(orm_execute_state):
        nonlocal counter
        counter.inc()

    yield counter
    event.remove(session, "do_orm_execute", _count_db_queries)


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

    result = _parse_file(msg)
    comms_decoder.send_request(log, result)


def _parse_file(msg: DagFileParseRequest):
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
    return result


class DagFileParseRequest(pydantic.BaseModel):
    """
    Request for DAG File Parsing.

    This is the request that the manager will send to the DAG parser with the dag file and
    any other necessary metadata.
    """

    file: str
    requests_fd: int
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
        cls, path: str | os.PathLike[str], ti: TaskInstance,
        target: Callable[[], None] = _parse_file_as_process, **kwargs
    ) -> TaskSDKDagFileProcessor:
        return super().start(path, ti, target=target, **kwargs)  # type:ignore[return-value]

    def _on_started(self):
        # Override base class.
        pass

    def _send_startup_message(self, what, path: str | os.PathLike[str],
                              child_comms_fd: int):  # type: ignore[override]
        # TODO: Ash: make this a Workload type!

        # TODO: We should include things like "dag code checksum" so that the parser doesn't have to send it
        # if it hasn't changed.
        msg = DagFileParseRequest(file=os.fspath(path), requests_fd=child_comms_fd)
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


def collect_dag_results(start_time: float, run_count: int, path: str,
                        parsing_result: DagFileParsingResult | None):
    result = CollectionResult()
    now_epoch = time.time()
    stat = DagFileStat(
        last_finish_time=timezone.utcnow(),
        last_duration=now_epoch - start_time,
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
    return result
