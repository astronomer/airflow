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

"""Independently check the re-review's blocking claim.

Claim: the `uri` check added at PR head 6dd30dfa20 rejects a construction that
apache/main accepts, specifically an explicit storage_type with a valid
table_name and no uri.

config.py imports only dataclasses/enum/typing, so both revisions can be exec'd
side by side in one process.
"""

from __future__ import annotations

MAIN = "/opt/airflow/dev/pr73273/config_main.py"
HEAD = "/opt/airflow/dev/pr73273/config_author.py"


def load(path: str) -> dict:
    ns: dict = {}
    with open(path) as fh:
        exec(compile(fh.read(), path, "exec"), ns)
    return ns


def run(ns: dict, kwargs: dict) -> str:
    cfg_cls = ns["DataSourceConfig"]
    try:
        cfg = cfg_cls(**kwargs)
        return f"ok (storage_type={cfg.storage_type!r})"
    except Exception as exc:
        return f"raise: {exc}"


def main() -> None:
    main_ns = load(MAIN)
    head_ns = load(HEAD)
    st_main = main_ns["StorageType"]
    st_head = head_ns["StorageType"]

    cases = [
        ("plain db table", lambda st: dict(conn_id="pg", table_name="customers")),
        (
            "plain db + explicit storage_type=LOCAL, no uri",
            lambda st: dict(conn_id="pg", table_name="customers", storage_type=st.LOCAL),
        ),
        (
            "plain db + explicit storage_type=S3, no uri",
            lambda st: dict(conn_id="pg", table_name="customers", storage_type=st.S3),
        ),
        (
            "format=parquet + explicit storage_type=LOCAL, no uri",
            lambda st: dict(conn_id="pg", table_name="t", format="parquet", storage_type=st.LOCAL),
        ),
        (
            "format=parquet, no uri, no storage_type",
            lambda st: dict(conn_id="pg", table_name="t", format="parquet"),
        ),
        (
            "iceberg, blank table_name",
            lambda st: dict(conn_id="pg", table_name="", format="iceberg", db_name="default"),
        ),
        (
            "uri=s3://, valid table_name (control)",
            lambda st: dict(conn_id="pg", table_name="t", uri="s3://bucket/path"),
        ),
    ]

    width = max(len(label) for label, _ in cases)
    print(f"{'case'.ljust(width)} | {'apache/main'.ljust(42)} | HEAD 6dd30dfa20")
    print("-" * (width + 3 + 42 + 3 + 20))
    for label, build in cases:
        left = run(main_ns, build(st_main))
        right = run(head_ns, build(st_head))
        flag = "   <== DIFFERS" if left != right else ""
        print(f"{label.ljust(width)} | {left.ljust(42)} | {right}{flag}")


if __name__ == "__main__":
    main()
