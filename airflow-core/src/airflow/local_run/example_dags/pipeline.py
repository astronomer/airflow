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
"""The example Dag ``airflow bootstrap`` writes into a new project: the part between the markers."""

from __future__ import annotations

# [START run_dags_locally_pipeline]
from airflow.sdk import dag, task


@task
def numbers():
    return [1, 2, 3]


@task
def double(number: int):
    return number * 2


@task
def total(values):
    return sum(values)


@dag(tags=["example"])
def example():
    total(double.expand(number=numbers()))


workflow = example()

if __name__ == "__main__":
    result = workflow.run()
    print("total:", result.output("total"))
# [END run_dags_locally_pipeline]
