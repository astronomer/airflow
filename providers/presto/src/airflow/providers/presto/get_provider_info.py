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

# NOTE! THIS FILE IS AUTOMATICALLY GENERATED AND WILL BE OVERWRITTEN!
#
# IF YOU WANT TO MODIFY THIS FILE, YOU SHOULD MODIFY THE TEMPLATE
# `get_provider_info_TEMPLATE.py.jinja2` IN the `dev/breeze/src/airflow_breeze/templates` DIRECTORY


def get_provider_info():
    return {
        "package-name": "apache-airflow-providers-presto",
        "name": "Presto",
        "description": "`Presto <https://prestodb.io/>`__\n",
        "state": "ready",
        "source-date-epoch": 1734536350,
        "versions": [
            "5.8.0",
            "5.7.0",
            "5.6.0",
            "5.5.2",
            "5.5.1",
            "5.5.0",
            "5.4.2",
            "5.4.1",
            "5.4.0",
            "5.3.0",
            "5.2.1",
            "5.2.0",
            "5.1.4",
            "5.1.3",
            "5.1.2",
            "5.1.1",
            "5.1.0",
            "5.0.0",
            "4.2.2",
            "4.2.1",
            "4.2.0",
            "4.1.0",
            "4.0.1",
            "4.0.0",
            "3.1.0",
            "3.0.0",
            "2.2.1",
            "2.2.0",
            "2.1.2",
            "2.1.1",
            "2.1.0",
            "2.0.1",
            "2.0.0",
            "1.0.2",
            "1.0.1",
            "1.0.0",
        ],
        "integrations": [
            {
                "integration-name": "Presto",
                "external-doc-url": "https://prestodb.io/",
                "logo": "/docs/integration-logos/PrestoDB.png",
                "tags": ["software"],
            }
        ],
        "hooks": [
            {"integration-name": "Presto", "python-modules": ["airflow.providers.presto.hooks.presto"]}
        ],
        "transfers": [
            {
                "source-integration-name": "Google Cloud Storage (GCS)",
                "target-integration-name": "Presto",
                "how-to-guide": "/docs/apache-airflow-providers-presto/operators/transfer/gcs_to_presto.rst",
                "python-module": "airflow.providers.presto.transfers.gcs_to_presto",
            }
        ],
        "connection-types": [
            {
                "hook-class-name": "airflow.providers.presto.hooks.presto.PrestoHook",
                "connection-type": "presto",
            }
        ],
        "dependencies": [
            "apache-airflow>=2.9.0",
            "apache-airflow-providers-common-sql>=1.20.0",
            "presto-python-client>=0.8.4",
            "pandas>=2.1.2,<2.2",
        ],
        "optional-dependencies": {"google": ["apache-airflow-providers-google"]},
    }
