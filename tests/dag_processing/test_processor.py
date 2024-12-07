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
from __future__ import annotations

import datetime
import os
import pathlib
import sys
from zipfile import ZipFile

import pytest
import structlog

from airflow.callbacks.callback_requests import DagCallbackRequest
from airflow.dag_processing.processor import (
    CollectionResult,
    DagFileParseRequest,
    _parse_file,
    collect_dag_results,
)
from airflow.models import DagBag
from airflow.utils import timezone

from tests_common.test_utils.config import conf_vars, env_vars
from tests_common.test_utils.db import (
    clear_db_dags,
    clear_db_import_errors,
    clear_db_jobs,
    clear_db_pools,
    clear_db_runs,
    clear_db_serialized_dags,
)
from tests_common.test_utils.mock_executor import MockExecutor

pytestmark = pytest.mark.db_test

DEFAULT_DATE = timezone.datetime(2016, 1, 1)
PY311 = sys.version_info >= (3, 11)

# Include the words "airflow" and "dag" in the file contents,
# tricking airflow into thinking these
# files contain a DAG (otherwise Airflow will skip them)
PARSEABLE_DAG_FILE_CONTENTS = '"airflow DAG"'
UNPARSEABLE_DAG_FILE_CONTENTS = "airflow DAG"
INVALID_DAG_WITH_DEPTH_FILE_CONTENTS = "def something():\n    return airflow_DAG\nsomething()"

# Filename to be used for dags that are created in an ad-hoc manner and can be removed/
# created at runtime
TEMP_DAG_FILENAME = "temp_dag.py"
TEST_DAG_FOLDER = pathlib.Path(__file__).parents[1].resolve() / "dags"


@pytest.fixture(scope="class")
def disable_load_example():
    with conf_vars({("core", "load_examples"): "false"}):
        with env_vars({"AIRFLOW__CORE__LOAD_EXAMPLES": "false"}):
            yield


@pytest.mark.usefixtures("disable_load_example")
class TestTaskSDKFileProcess:
    @staticmethod
    def clean_db():
        clear_db_runs()
        clear_db_pools()
        clear_db_dags()
        clear_db_import_errors()
        clear_db_jobs()
        clear_db_serialized_dags()

    def setup_class(self):
        self.clean_db()

    def setup_method(self):
        # Speed up some tests by not running the tasks, just look at what we
        # enqueue!
        self.null_exec = MockExecutor()
        self.scheduler_job = None

    def teardown_method(self) -> None:
        if self.scheduler_job and self.scheduler_job.job_runner.processor_agent:
            self.scheduler_job.job_runner.processor_agent.end()
            self.scheduler_job = None
        self.clean_db()

    def _process_file(self, file_path) -> CollectionResult:
        parsed_file = _parse_file(
            DagFileParseRequest(file=file_path, requests_fd=1), log=structlog.get_logger()
        )
        return collect_dag_results(
            datetime.datetime.now().timestamp(),
            timezone.utcnow(),
            1,
            file_path,
            parsing_result=parsed_file,
        )

    # @patch.object(TaskInstance, "handle_failure")
    # def test_execute_on_failure_callbacks(self, mock_ti_handle_failure):
    #     dagbag = DagBag(dag_folder="/dev/null", include_examples=True, read_dags_from_db=False)
    #     dag_file_processor = TaskSDKDagFileProcessor(id=0, pid=0, stdin=None, client=None, process=None)
    #     with create_session() as session:
    #         session.query(TaskInstance).delete()
    #         dag = dagbag.get_dag("example_branch_operator")
    #         dagrun = dag.create_dagrun(
    #             state=DagRunState.RUNNING,
    #             logical_date=DEFAULT_DATE,
    #             run_type=DagRunType.SCHEDULED,
    #             data_interval=dag.infer_automated_data_interval(DEFAULT_DATE),
    #             session=session,
    #             triggered_by=DagRunTriggeredByType.TEST,
    #         )
    #         task = dag.get_task(task_id="run_this_first")
    #         ti = TaskInstance(task, run_id=dagrun.run_id, state=State.RUNNING)
    #         session.add(ti)
    #
    #     requests = [
    #         TaskCallbackRequest(
    #             full_filepath="A", simple_task_instance=SimpleTaskInstance.from_ti(ti), msg="Message"
    #         )
    #     ]
    #     dag_file_processor.execute_callbacks(dagbag, requests, dag_file_processor.UNIT_TEST_MODE, session)
    #     mock_ti_handle_failure.assert_called_once_with(
    #         error="Message", test_mode=conf.getboolean("core", "unit_test_mode"), session=session
    #     )
    #
    # @pytest.mark.parametrize(
    #     ["has_serialized_dag"],
    #     [pytest.param(True, id="dag_in_db"), pytest.param(False, id="no_dag_found")],
    # )
    # @patch.object(TaskInstance, "handle_failure")
    # def test_execute_on_failure_callbacks_without_dag(self, mock_ti_handle_failure, has_serialized_dag):
    #     dagbag = DagBag(dag_folder="/dev/null", include_examples=True, read_dags_from_db=False)
    #     dag_file_processor = TaskSDKDagFileProcessor(dag_directory=TEST_DAGS_FOLDER, log=mock.MagicMock())
    #     with create_session() as session:
    #         session.query(TaskInstance).delete()
    #         dag = dagbag.get_dag("example_branch_operator")
    #         dag.sync_to_db()
    #         dagrun = dag.create_dagrun(
    #             state=State.RUNNING,
    #             logical_date=DEFAULT_DATE,
    #             run_type=DagRunType.SCHEDULED,
    #             data_interval=dag.infer_automated_data_interval(DEFAULT_DATE),
    #             triggered_by=DagRunTriggeredByType.TEST,
    #             session=session,
    #         )
    #         task = dag.get_task(task_id="run_this_first")
    #         ti = TaskInstance(task, run_id=dagrun.run_id, state=State.QUEUED)
    #         session.add(ti)
    #
    #         if has_serialized_dag:
    #             assert SerializedDagModel.write_dag(dag, session=session) is True
    #             session.flush()
    #
    #     requests = [
    #         TaskCallbackRequest(
    #             full_filepath="A", simple_task_instance=SimpleTaskInstance.from_ti(ti), msg="Message"
    #         )
    #     ]
    #     dag_file_processor.execute_callbacks_without_dag(requests, True, session)
    #     mock_ti_handle_failure.assert_called_once_with(
    #         error="Message", test_mode=conf.getboolean("core", "unit_test_mode"), session=session
    #     )
    #
    # def test_failure_callbacks_should_not_drop_hostname(self):
    #     dagbag = DagBag(dag_folder="/dev/null", include_examples=True, read_dags_from_db=False)
    #     dag_file_processor = TaskSDKDagFileProcessor(dag_directory=TEST_DAGS_FOLDER, log=mock.MagicMock())
    #     dag_file_processor.UNIT_TEST_MODE = False
    #
    #     with create_session() as session:
    #         dag = dagbag.get_dag("example_branch_operator")
    #         task = dag.get_task(task_id="run_this_first")
    #         dagrun = dag.create_dagrun(
    #             state=State.RUNNING,
    #             logical_date=DEFAULT_DATE,
    #             run_type=DagRunType.SCHEDULED,
    #             data_interval=dag.infer_automated_data_interval(DEFAULT_DATE),
    #             triggered_by=DagRunTriggeredByType.TEST,
    #             session=session,
    #         )
    #         ti = TaskInstance(task, run_id=dagrun.run_id, state=State.RUNNING)
    #         ti.hostname = "test_hostname"
    #         session.add(ti)
    #
    #     requests = [
    #         TaskCallbackRequest(
    #             full_filepath="A", simple_task_instance=SimpleTaskInstance.from_ti(ti), msg="Message"
    #         )
    #     ]
    #     dag_file_processor.execute_callbacks(dagbag, requests, False)
    #
    #     with create_session() as session:
    #         tis = session.query(TaskInstance)
    #         assert tis[0].hostname == "test_hostname"
    #
    # def test_process_file_should_failure_callback(self, monkeypatch, tmp_path, get_test_dag):
    #     callback_file = tmp_path.joinpath("callback.txt")
    #     callback_file.touch()
    #     monkeypatch.setenv("AIRFLOW_CALLBACK_FILE", str(callback_file))
    #     dag_file_processor = TaskSDKDagFileProcessor(dag_directory=TEST_DAGS_FOLDER, log=mock.MagicMock())
    #
    #     dag = get_test_dag("test_on_failure_callback")
    #     task = dag.get_task(task_id="test_on_failure_callback_task")
    #     with create_session() as session:
    #         dagrun = dag.create_dagrun(
    #             state=State.RUNNING,
    #             logical_date=DEFAULT_DATE,
    #             run_type=DagRunType.SCHEDULED,
    #             data_interval=dag.infer_automated_data_interval(DEFAULT_DATE),
    #             triggered_by=DagRunTriggeredByType.TEST,
    #             session=session,
    #         )
    #         ti = dagrun.get_task_instance(task.task_id)
    #         ti.refresh_from_task(task)
    #
    #         requests = [
    #             TaskCallbackRequest(
    #                 full_filepath=dag.fileloc,
    #                 simple_task_instance=SimpleTaskInstance.from_ti(ti),
    #                 msg="Message",
    #             )
    #         ]
    #         dag_file_processor.process_file(dag.fileloc, requests)
    #
    #     ti.refresh_from_db()
    #     msg = " ".join([str(k) for k in ti.key.primary]) + " fired callback"
    #     assert msg in callback_file.read_text()

    @conf_vars({("core", "dagbag_import_error_tracebacks"): "False"})
    def test_add_unparseable_file_before_sched_start_creates_import_error(self, tmp_path):
        unparseable_filename = tmp_path.joinpath(TEMP_DAG_FILENAME).as_posix()
        with open(unparseable_filename, "w") as unparseable_file:
            unparseable_file.writelines(UNPARSEABLE_DAG_FILE_CONTENTS)
        collected_results = self._process_file(unparseable_filename)
        import_errors = collected_results.import_errors
        assert len(import_errors) == 1
        assert import_errors[unparseable_filename] == f"invalid syntax ({TEMP_DAG_FILENAME}, line 1)"

    @conf_vars({("core", "dagbag_import_error_tracebacks"): "False"})
    def test_add_unparseable_zip_file_creates_import_error(self, tmp_path):
        zip_filename = (tmp_path / "test_zip.zip").as_posix()
        invalid_dag_filename = os.path.join(zip_filename, TEMP_DAG_FILENAME)
        with ZipFile(zip_filename, "w") as zip_file:
            zip_file.writestr(TEMP_DAG_FILENAME, UNPARSEABLE_DAG_FILE_CONTENTS)

        collected_results = self._process_file(invalid_dag_filename)
        import_errors = collected_results.import_errors
        assert len(import_errors) == 1
        assert import_errors[invalid_dag_filename] == f"invalid syntax ({TEMP_DAG_FILENAME}, line 1)"

    def test_no_import_errors_with_parseable_dag(self, tmp_path):
        parseable_filename = tmp_path / TEMP_DAG_FILENAME
        parseable_filename.write_text(PARSEABLE_DAG_FILE_CONTENTS)
        collected_results = self._process_file(parseable_filename.name)
        import_errors = collected_results.import_errors

        assert len(import_errors) == 0

    def test_no_import_errors_with_parseable_dag_in_zip(self, tmp_path):
        zip_filename = (tmp_path / "test_zip.zip").as_posix()
        with ZipFile(zip_filename, "w") as zip_file:
            zip_file.writestr(TEMP_DAG_FILENAME, PARSEABLE_DAG_FILE_CONTENTS)
        collected_results = self._process_file(zip_filename)
        import_errors = collected_results.import_errors

        assert len(import_errors) == 0

    @conf_vars({("core", "dagbag_import_error_tracebacks"): "False"})
    def test_new_import_error_replaces_old(self, tmp_path):
        unparseable_filename = tmp_path / TEMP_DAG_FILENAME
        # Generate original import error
        unparseable_filename.write_text(UNPARSEABLE_DAG_FILE_CONTENTS)

        collected_results = self._process_file(unparseable_filename.as_posix())
        import_errors = collected_results.import_errors

        assert len(import_errors) == 1
        assert (
            import_errors[unparseable_filename.as_posix()] == f"invalid syntax ({TEMP_DAG_FILENAME}, line 1)"
        )
        # Generate replacement import error (the error will be on the second line now)
        unparseable_filename.write_text(
            PARSEABLE_DAG_FILE_CONTENTS + os.linesep + UNPARSEABLE_DAG_FILE_CONTENTS
        )
        collected_results = self._process_file(unparseable_filename.as_posix())
        import_errors = collected_results.import_errors

        assert len(import_errors) == 1
        assert (
            import_errors[unparseable_filename.as_posix()] == f"invalid syntax ({TEMP_DAG_FILENAME}, line 2)"
        )

    def test_remove_error_clears_import_error(self, tmp_path):
        filename_to_parse = tmp_path.joinpath(TEMP_DAG_FILENAME).as_posix()

        # Generate original import error
        with open(filename_to_parse, "w") as file_to_parse:
            file_to_parse.writelines(UNPARSEABLE_DAG_FILE_CONTENTS)
        collected_results = self._process_file(filename_to_parse)
        assert len(collected_results.import_errors) == 1

        # Remove the import error from the file
        with open(filename_to_parse, "w") as file_to_parse:
            file_to_parse.writelines(PARSEABLE_DAG_FILE_CONTENTS)
        collected_results = self._process_file(filename_to_parse)
        assert len(collected_results.import_errors) == 0

    def test_remove_error_clears_import_error_zip(self, tmp_path):
        # Generate original import error
        zip_filename = (tmp_path / "test_zip.zip").as_posix()
        with ZipFile(zip_filename, "w") as zip_file:
            zip_file.writestr(TEMP_DAG_FILENAME, UNPARSEABLE_DAG_FILE_CONTENTS)
        collected_results = self._process_file(zip_filename)
        assert len(collected_results.import_errors) == 1
        # Remove the import error from the file
        with ZipFile(zip_filename, "w") as zip_file:
            zip_file.writestr(TEMP_DAG_FILENAME, "import os # airflow DAG")
        collected_results = self._process_file(zip_filename)
        assert len(collected_results.import_errors) == 0

    def test_import_error_tracebacks(self, tmp_path):
        unparseable_filename = (tmp_path / TEMP_DAG_FILENAME).as_posix()
        with open(unparseable_filename, "w") as unparseable_file:
            unparseable_file.writelines(INVALID_DAG_WITH_DEPTH_FILE_CONTENTS)

        import_errors = self._process_file(unparseable_filename).import_errors
        assert len(import_errors) == 1

        if PY311:
            expected_stacktrace = (
                "Traceback (most recent call last):\n"
                '  File "{}", line 3, in <module>\n'
                "    something()\n"
                '  File "{}", line 2, in something\n'
                "    return airflow_DAG\n"
                "           ^^^^^^^^^^^\n"
                "NameError: name 'airflow_DAG' is not defined\n"
            )
        else:
            expected_stacktrace = (
                "Traceback (most recent call last):\n"
                '  File "{}", line 3, in <module>\n'
                "    something()\n"
                '  File "{}", line 2, in something\n'
                "    return airflow_DAG\n"
                "NameError: name 'airflow_DAG' is not defined\n"
            )
        assert import_errors[unparseable_filename] == expected_stacktrace.format(
            unparseable_filename, unparseable_filename
        )

    @conf_vars({("core", "dagbag_import_error_traceback_depth"): "1"})
    def test_import_error_traceback_depth(self, tmp_path):
        unparseable_filename = tmp_path.joinpath(TEMP_DAG_FILENAME).as_posix()
        with open(unparseable_filename, "w") as unparseable_file:
            unparseable_file.writelines(INVALID_DAG_WITH_DEPTH_FILE_CONTENTS)
        import_errors = self._process_file(unparseable_filename).import_errors
        assert len(import_errors) == 1
        if PY311:
            expected_stacktrace = (
                "Traceback (most recent call last):\n"
                '  File "{}", line 2, in something\n'
                "    return airflow_DAG\n"
                "           ^^^^^^^^^^^\n"
                "NameError: name 'airflow_DAG' is not defined\n"
            )
        else:
            expected_stacktrace = (
                "Traceback (most recent call last):\n"
                '  File "{}", line 2, in something\n'
                "    return airflow_DAG\n"
                "NameError: name 'airflow_DAG' is not defined\n"
            )
        assert import_errors[unparseable_filename] == expected_stacktrace.format(unparseable_filename)

    def test_import_error_tracebacks_zip(self, tmp_path):
        invalid_zip_filename = (tmp_path / "test_zip_invalid.zip").as_posix()
        invalid_dag_filename = os.path.join(invalid_zip_filename, TEMP_DAG_FILENAME)
        with ZipFile(invalid_zip_filename, "w") as invalid_zip_file:
            invalid_zip_file.writestr(TEMP_DAG_FILENAME, INVALID_DAG_WITH_DEPTH_FILE_CONTENTS)
        import_errors = self._process_file(invalid_zip_filename).import_errors

        assert len(import_errors) == 1
        if PY311:
            expected_stacktrace = (
                "Traceback (most recent call last):\n"
                '  File "{}", line 3, in <module>\n'
                "    something()\n"
                '  File "{}", line 2, in something\n'
                "    return airflow_DAG\n"
                "           ^^^^^^^^^^^\n"
                "NameError: name 'airflow_DAG' is not defined\n"
            )
        else:
            expected_stacktrace = (
                "Traceback (most recent call last):\n"
                '  File "{}", line 3, in <module>\n'
                "    something()\n"
                '  File "{}", line 2, in something\n'
                "    return airflow_DAG\n"
                "NameError: name 'airflow_DAG' is not defined\n"
            )
        assert import_errors[invalid_dag_filename] == expected_stacktrace.format(
            invalid_dag_filename, invalid_dag_filename
        )

    @conf_vars({("core", "dagbag_import_error_traceback_depth"): "1"})
    def test_import_error_tracebacks_zip_depth(self, tmp_path):
        invalid_zip_filename = (tmp_path / "test_zip_invalid.zip").as_posix()
        invalid_dag_filename = os.path.join(invalid_zip_filename, TEMP_DAG_FILENAME)
        with ZipFile(invalid_zip_filename, "w") as invalid_zip_file:
            invalid_zip_file.writestr(TEMP_DAG_FILENAME, INVALID_DAG_WITH_DEPTH_FILE_CONTENTS)
        import_errors = self._process_file(invalid_zip_filename).import_errors

        assert len(import_errors) == 1
        if PY311:
            expected_stacktrace = (
                "Traceback (most recent call last):\n"
                '  File "{}", line 2, in something\n'
                "    return airflow_DAG\n"
                "           ^^^^^^^^^^^\n"
                "NameError: name 'airflow_DAG' is not defined\n"
            )
        else:
            expected_stacktrace = (
                "Traceback (most recent call last):\n"
                '  File "{}", line 2, in something\n'
                "    return airflow_DAG\n"
                "NameError: name 'airflow_DAG' is not defined\n"
            )
        assert import_errors[invalid_dag_filename] == expected_stacktrace.format(invalid_dag_filename)

    # @conf_vars({("core", "dagbag_import_error_tracebacks"): "False"})
    # def test_dag_model_has_import_error_is_true_when_import_error_exists(self, tmp_path, session):
    #     from airflow.configuration import TEST_DAGS_FOLDER
    #     dag_file = os.path.join(TEST_DAGS_FOLDER, "test_example_bash_operator.py")
    #     temp_dagfile = tmp_path.joinpath(TEMP_DAG_FILENAME).as_posix()
    #     with open(dag_file) as main_dag, open(temp_dagfile, "w") as next_dag:
    #         for line in main_dag:
    #             next_dag.write(line)
    #     # first we parse the dag
    #     collection_results = self._process_file(temp_dagfile)
    #     dm = collection_results.collected_dags[0]
    #     # assert DagModel.has_import_errors is false
    #     assert not dm.has_import_errors
    #
    #     # corrupt the file
    #     with open(temp_dagfile, "a") as file:
    #         file.writelines(UNPARSEABLE_DAG_FILE_CONTENTS)
    #
    #     collection_results = self._process_file(temp_dagfile)
    #     import_errors = collection_results.import_errors
    #
    #     assert len(import_errors) == 1
    #     assert import_errors[temp_dagfile]


#


#
#     def test_import_error_record_is_updated_not_deleted_and_recreated(self, tmp_path):
#         """
#         Test that existing import error is updated and new record not created
#         for a dag with the same filename
#         """
#         filename_to_parse = tmp_path.joinpath(TEMP_DAG_FILENAME).as_posix()
#         # Generate original import error
#         with open(filename_to_parse, "w") as file_to_parse:
#             file_to_parse.writelines(UNPARSEABLE_DAG_FILE_CONTENTS)
#         session = settings.Session()
#         self._process_file(filename_to_parse, dag_directory=tmp_path, session=session)
#
#         import_error_1 = (
#             session.query(ParseImportError).filter(ParseImportError.filename == filename_to_parse).one()
#         )
#
#         # process the file multiple times
#         for _ in range(10):
#             self._process_file(filename_to_parse, dag_directory=tmp_path, session=session)
#
#         import_error_2 = (
#             session.query(ParseImportError).filter(ParseImportError.filename == filename_to_parse).one()
#         )
#
#         # assert that the ID of the import error did not change
#         assert import_error_1.id == import_error_2.id
#
#
#     @conf_vars({("logging", "dag_processor_log_target"): "stdout"})
#     @mock.patch("airflow.dag_processing.processor.settings.dispose_orm", MagicMock)
#     @mock.patch("airflow.dag_processing.processor.redirect_stdout")
#     def test_dag_parser_output_when_logging_to_stdout(self, mock_redirect_stdout_for_file):
#         processor = DagFileProcessorProcess(
#             file_path="abc.txt",
#             dag_directory=[],
#             callback_requests=[],
#         )
#         processor._run_file_processor(
#             result_channel=MagicMock(),
#             parent_channel=MagicMock(),
#             file_path="fake_file_path",
#             thread_name="fake_thread_name",
#             callback_requests=[],
#             dag_directory=[],
#         )
#         mock_redirect_stdout_for_file.assert_not_called()
#
#     @conf_vars({("logging", "dag_processor_log_target"): "file"})
#     @mock.patch("airflow.dag_processing.processor.settings.dispose_orm", MagicMock)
#     @mock.patch("airflow.dag_processing.processor.redirect_stdout")
#     def test_dag_parser_output_when_logging_to_file(self, mock_redirect_stdout_for_file):
#         processor = DagFileProcessorProcess(
#             file_path="abc.txt",
#             dag_directory=[],
#             callback_requests=[],
#         )
#         processor._run_file_processor(
#             result_channel=MagicMock(),
#             parent_channel=MagicMock(),
#             file_path="fake_file_path",
#             thread_name="fake_thread_name",
#             callback_requests=[],
#             dag_directory=[],
#         )
#         mock_redirect_stdout_for_file.assert_called_once()
#
#     @mock.patch("airflow.dag_processing.processor.settings.dispose_orm", MagicMock)
#     @mock.patch.object(DagFileProcessorProcess, "_get_multiprocessing_context")
#     def test_no_valueerror_with_parseable_dag_in_zip(self, mock_context, tmp_path):
#         mock_context.return_value.Pipe.return_value = (MagicMock(), MagicMock())
#         zip_filename = (tmp_path / "test_zip.zip").as_posix()
#         with ZipFile(zip_filename, "w") as zip_file:
#             zip_file.writestr(TEMP_DAG_FILENAME, PARSEABLE_DAG_FILE_CONTENTS)
#
#         processor = DagFileProcessorProcess(
#             file_path=zip_filename,
#             dag_directory=[],
#             callback_requests=[],
#         )
#         processor.start()
#
#     @mock.patch("airflow.dag_processing.processor.settings.dispose_orm", MagicMock)
#     @mock.patch.object(DagFileProcessorProcess, "_get_multiprocessing_context")
#     def test_nullbyte_exception_handling_when_preimporting_airflow(self, mock_context, tmp_path):
#         mock_context.return_value.Pipe.return_value = (MagicMock(), MagicMock())
#         dag_filename = (tmp_path / "test_dag.py").as_posix()
#         with open(dag_filename, "wb") as file:
#             file.write(b"hello\x00world")
#
#         processor = DagFileProcessorProcess(
#             file_path=dag_filename,
#             dag_directory=[],
#             callback_requests=[],
#         )
#         processor.start()


def test_dag_info():
    from airflow import DAG
    from airflow.models.baseoperator import BaseOperator
    from airflow.models.serialized_dag import DagInfo
    from airflow.serialization.serialized_objects import SerializedDAG

    with DAG(dag_id="a") as dag:
        BaseOperator(task_id="task1")

    DagInfo(data=SerializedDAG.to_dict(dag))


def test_parse_file_with_callbacks(spy_agency):
    from airflow import DAG

    called = False

    def on_failure(context):
        nonlocal called
        called = True

    dag = DAG(dag_id="a", on_failure_callback=on_failure)

    def fake_collect_dags(self, *args, **kwargs):
        self.dags[dag.dag_id] = dag

    spy_agency.spy_on(DagBag.collect_dags, call_fake=fake_collect_dags, owner=DagBag)

    requests = [
        DagCallbackRequest(
            full_filepath="A",
            msg="Message",
            dag_id="a",
            run_id="b",
        )
    ]
    _parse_file(
        DagFileParseRequest(file="A", requests_fd=1, callback_requests=requests), log=structlog.get_logger()
    )

    assert called is True
