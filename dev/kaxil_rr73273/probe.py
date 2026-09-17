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

"""Compare DataSourceConfig acceptance between released common.sql 2.1.1 and PR #73273 HEAD."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses' field-type resolution reads sys.modules
    spec.loader.exec_module(mod)
    return mod


pre = load("config_211")
head = load("config_head")

CASES = [
    ("plain db table", lambda m: dict(conn_id="pg", table_name="customers")),
    (
        "plain + explicit storage_type",
        lambda m: dict(conn_id="pg", table_name="customers", storage_type=m.StorageType.LOCAL),
    ),
    ("format, no uri", lambda m: dict(conn_id="pg", table_name="customers", format="parquet")),
    (
        "format + explicit storage_type, no uri",
        lambda m: dict(
            conn_id="pg", table_name="customers", format="parquet", storage_type=m.StorageType.LOCAL
        ),
    ),
    (
        "s3 uri + format",
        lambda m: dict(conn_id="pg", table_name="customers", uri="s3://b/p", format="parquet"),
    ),
    ("iceberg, blank table_name", lambda m: dict(conn_id="ic", table_name="", format="iceberg", db_name="d")),
]


def outcome(mod, kwargs_fn) -> str:
    try:
        cfg = mod.DataSourceConfig(**kwargs_fn(mod))
    except ValueError as exc:
        return f"raise: {exc}"
    return f"ok (storage_type={cfg.storage_type})"


print(f"{'case':40} | {'2.1.1 (released)':50} | HEAD 6dd30dfa20")
print("-" * 138)
for label, fn in CASES:
    before, after = outcome(pre, fn), outcome(head, fn)
    flag = "   <== CHANGED" if (before.startswith("ok") != after.startswith("ok")) else ""
    print(f"{label:40} | {before:50} | {after}{flag}")
