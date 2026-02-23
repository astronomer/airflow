#!/usr/bin/env bash
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

set -euo pipefail

# Wait for DB to be reachable
for i in $(seq 1 "${CONNECTION_CHECK_MAX_COUNT:-20}"); do
    if airflow db check 2>/dev/null; then break; fi
    echo "Waiting for DB... ($i)"
    sleep 2
done

if [[ -n "${_AIRFLOW_DB_MIGRATE=}" ]]; then
    echo "Running DB migration..."
    airflow db migrate || true
fi

if [[ -n "${_AIRFLOW_WWW_USER_CREATE=}" ]]; then
    echo "Creating admin user..."
    airflow users create \
       --username "${_AIRFLOW_WWW_USER_USERNAME:-admin}" \
       --firstname "Airflow" --lastname "Admin" \
       --email "admin@example.com" --role "Admin" \
       --password "${_AIRFLOW_WWW_USER_PASSWORD:-airflow}" 2>/dev/null || true
fi

exec airflow "${@}"
