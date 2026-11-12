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

import subprocess

import pytest

from airflow_dev.repo import (
    DevError,
    find_member,
    find_repo_root,
    get_pinned_requirements,
    get_supported_db_versions,
)


@pytest.mark.parametrize(
    ("target", "member"),
    [
        ("airflow-core/tests/unit/models/test_x.py", "airflow-core"),
        ("airflow-core/tests/unit", "airflow-core"),
        ("task-sdk/tests/test_y.py", "task-sdk"),
        ("providers/standard/tests", "providers/standard"),
    ],
)
def test_find_member(fake_repo, target, member):
    assert find_member(fake_repo, fake_repo / target) == member


def test_find_member_rejects_paths_outside_the_checkout(fake_repo, tmp_path):
    with pytest.raises(DevError, match="outside the checkout"):
        find_member(fake_repo, tmp_path)


def test_find_member_rejects_files_in_no_member(fake_repo):
    (fake_repo / "dev" / "loose.py").write_text("")

    with pytest.raises(DevError, match="does not belong"):
        find_member(fake_repo, fake_repo / "dev" / "loose.py")


def test_get_pinned_requirements_uses_locked_versions(fake_repo):
    assert get_pinned_requirements(fake_repo, ["psycopg", "pymysql"]) == ["psycopg==3.3.8", "pymysql==1.1.3"]


def test_get_pinned_requirements_reports_missing_packages(fake_repo):
    with pytest.raises(DevError, match="mysqlclient not found in uv.lock"):
        get_pinned_requirements(fake_repo, ["mysqlclient"])


def test_get_supported_db_versions_reads_breeze_constants(fake_repo):
    assert get_supported_db_versions(fake_repo) == {"postgres": ["14", "15"], "mysql": ["8.0", "8.4"]}


def test_find_repo_root_requires_an_airflow_checkout(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    with pytest.raises(DevError, match="not an Airflow checkout"):
        find_repo_root(tmp_path)
