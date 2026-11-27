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

from unittest import mock

import pytest

from airflow.dag_processing.lang_sdk_processor import LangSDKDagFileProcessorProcess
from airflow.dag_processing.processor import DagFileParsingResult
from airflow.local_run.runtimes import parse_native_dag_file
from airflow.sdk.exceptions import LocalRunDagFileError


@mock.patch.object(LangSDKDagFileProcessorProcess, "run", autospec=True)
def test_a_bundle_that_declares_no_dags_is_refused(run, tmp_path):
    source = tmp_path / "dist" / "handlers.min.mjs"
    run.return_value = DagFileParsingResult(fileloc=str(source), serialized_dags=[])

    with pytest.raises(
        LocalRunDagFileError,
        match=r"No Dags found in .*handlers\.min\.mjs\. A bundle that only implements stub tasks runs through "
        r"the Python Dag file that declares them\.$",
    ):
        parse_native_dag_file(source, tmp_path)
    run.assert_called_once_with(
        path=str(source),
        bundle_path=tmp_path,
        bundle_name="dags-folder",
        dag_file_rel_path="dist/handlers.min.mjs",
        logger=mock.ANY,
    )
