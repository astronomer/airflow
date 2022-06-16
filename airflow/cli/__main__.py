#!/usr/bin/env python
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

from airflow.cli import airflow_cmd
from airflow.cli.commands import celery  # noqa: F401
from airflow.cli.commands import cheat_sheet  # noqa: F401
from airflow.cli.commands import db  # noqa: F401
from airflow.cli.commands import info  # noqa: F401
from airflow.cli.commands import jobs  # noqa: F401
from airflow.cli.commands import kerberos  # noqa: F401
from airflow.cli.commands import scheduler  # noqa: F401
from airflow.cli.commands import standalone  # noqa: F401
from airflow.cli.commands import sync_perm  # noqa: F401
from airflow.cli.commands import triggerer  # noqa: F401
from airflow.cli.commands import users  # noqa: F401
from airflow.cli.commands import version  # noqa: F401
from airflow.cli.commands import webserver  # noqa: F401

if __name__ == '__main__':
    airflow_cmd(obj={})
