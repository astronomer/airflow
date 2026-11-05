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
"""Supervised tries' edge cases; ``test_runner`` runs them end to end."""

from __future__ import annotations

import signal
from pathlib import Path
from unittest import mock

import pytest
from sqlalchemy.orm import Session

from airflow.local_run import supervised
from airflow.local_run.supervised import SupervisedTries
from airflow.models.taskinstance import TaskInstance
from airflow.models.trigger import Trigger
from airflow.sdk.execution_time.supervisor import ActivitySubprocess
from airflow.utils.state import TaskInstanceState


@pytest.fixture
def session():
    return mock.create_autospec(Session, instance=True)


@pytest.fixture
def ti():
    return mock.create_autospec(TaskInstance, instance=True)


def test_stop_without_a_running_try_reports_none(session):
    assert SupervisedTries(session=session).stop() is False


@pytest.mark.parametrize(("still_running", "killed"), [(True, True), (False, False)])
@mock.patch.object(supervised.threading, "Timer", autospec=True)
@mock.patch.object(supervised.os, "killpg", autospec=True)
def test_stop_interrupts_the_running_try_and_kills_it_if_it_keeps_running(
    killpg, timer, session, still_running, killed
):
    tries = SupervisedTries(session=session)
    process = mock.create_autospec(ActivitySubprocess, instance=True)
    process.pid = 123
    tries._running = process

    assert tries.stop() is True

    killpg.assert_called_once_with(123, signal.SIGINT)
    timer.assert_called_once_with(supervised.KILL_DELAY, tries._kill_if_running, args=(process,))
    if not still_running:
        tries._running = None
    tries._kill_if_running(process)
    assert (mock.call(123, signal.SIGKILL) in killpg.mock_calls) is killed


@pytest.mark.parametrize(
    ("state_after_error", "marked_failed"),
    [(TaskInstanceState.QUEUED, True), (TaskInstanceState.SUCCESS, False)],
)
@mock.patch.object(supervised.ExecuteTask, "make", autospec=True, side_effect=RuntimeError("no workload"))
def test_try_that_cannot_run_does_not_leave_its_task_waiting(
    _, session, ti, state_after_error, marked_failed
):
    ti.state = state_after_error

    with pytest.raises(RuntimeError, match="no workload"):
        SupervisedTries(session=session).run(ti, mock.sentinel.task)

    session.rollback.assert_called_once_with()
    assert (mock.call(TaskInstanceState.FAILED, session=session) in ti.set_state.mock_calls) is marked_failed


@mock.patch.object(supervised, "_run_inline_trigger", autospec=True, return_value=None)
@mock.patch.object(supervised, "import_string", autospec=True)
@mock.patch.object(supervised, "capture_task_log", autospec=True)
def test_trigger_without_an_event_lets_the_task_resume(_, import_string, run_trigger, session, ti, tmp_path):
    session.get_one.return_value = mock.Mock(spec=Trigger, classpath="pkg.Trigger", kwargs={"n": 1})
    # The workload's fields are pydantic fields, which autospec does not see.
    workload = mock.NonCallableMock(spec=["ti"], ti=mock.sentinel.ti)

    SupervisedTries(session=session)._resume_after_trigger(ti, workload, Path(tmp_path, "attempt=1.log"))

    import_string.return_value.assert_called_once_with(n=1)
    run_trigger.assert_called_once_with(import_string.return_value.return_value, workload.ti)
    assert ti.state == TaskInstanceState.SCHEDULED
    assert ti.trigger_id is None
    session.commit.assert_called_once_with()
