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

"""Add generalization.callers and the corrected fix_scope to the review findings sidecar."""

from __future__ import annotations

import json

PATH = "/tmp/pr-73273/review.json.findings.json"
KEY = "providers/common/sql/src/airflow/providers/common/sql/config.py:110"

with open(PATH) as fh:
    data = json.load(fh)

finding = data["findings"][KEY]

finding["fix_scope"] = [
    "providers/common/sql/src/airflow/providers/common/sql/config.py#DataSourceConfig.__post_init__",
    "providers/common/sql/tests/unit/common/sql/datafusion/test_format_handlers.py#test_missing_mandatory_fields",
    "providers/common/sql/tests/unit/common/sql/test_config.py#test_explicit_storage_type_without_uri_raises_error",
    "providers/common/sql/tests/unit/common/sql/test_config.py"
    "#test_explicit_storage_type_without_uri_raises_error_with_format",
]

finding["generalization"] = {
    "callers": {
        "symbol": "DataSourceConfig.__post_init__ (runs on every DataSourceConfig(...) construction)",
        "pattern": "grep -rn 'DataSourceConfig(' --include='*.py' providers/ | grep -v isinstance",
        "hits": 57,
        "breakdown": {
            "outside tests (production plus example Dags)": 9,
            "outside providers/ (airflow-core, task-sdk, devel-common)": 0,
            "sites the proposed reordering changes": 3,
        },
        "note": (
            "All 3 affected sites are the tests named in fix_scope: test_config.py:70 becomes an "
            "accepted case, test_config.py:75 and test_format_handlers.py:143-146 move to the new "
            "message. No production or example-Dag construction passes an explicit storage_type, and "
            "none omits uri while setting format, so the proposed diff changes no shipped call site."
        ),
    }
}

with open(PATH, "w") as fh:
    json.dump(data, fh, indent=2)

print("generalization.callers added as dict; fix_scope entries:", len(finding["fix_scope"]))
