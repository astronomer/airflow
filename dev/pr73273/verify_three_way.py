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

"""Three-way comparison: apache/main, the author's head, and the fork's suggestion.

Checks whether the suggested block actually restores main's behaviour, or only
restores part of it.
"""

from __future__ import annotations

REVS = {
    "apache/main": "/opt/airflow/dev/pr73273/config_main.py",
    "author 6dd30dfa20": "/opt/airflow/dev/pr73273/config_author.py",
    "with suggestion": "/opt/airflow/dev/pr73273/config_suggested.py",
}


def load(path: str) -> dict:
    ns: dict = {}
    with open(path) as fh:
        exec(compile(fh.read(), path, "exec"), ns)
    return ns


def run(ns: dict, build) -> str:
    try:
        cfg = ns["DataSourceConfig"](**build(ns["StorageType"]))
        st = cfg.storage_type
        return f"ok({st.value if st else None})"
    except Exception as exc:
        msg = str(exc)
        return f"raise: {msg[:34]}"


CASES = [
    ("plain db", lambda st: dict(conn_id="pg", table_name="t")),
    ("plain db + storage_type, no uri", lambda st: dict(conn_id="pg", table_name="t", storage_type=st.LOCAL)),
    (
        "format + storage_type, no uri",
        lambda st: dict(conn_id="pg", table_name="t", format="parquet", storage_type=st.LOCAL),
    ),
    ("format, no uri", lambda st: dict(conn_id="pg", table_name="t", format="parquet")),
    (
        "iceberg, blank table_name",
        lambda st: dict(conn_id="pg", table_name="", format="iceberg", db_name="d"),
    ),
    (
        "uri + format (control)",
        lambda st: dict(conn_id="pg", table_name="t", uri="s3://b/p", format="parquet"),
    ),
    ("uri only (control)", lambda st: dict(conn_id="pg", table_name="t", uri="s3://b/p")),
]


def main() -> None:
    spaces = {name: load(path) for name, path in REVS.items()}
    w = max(len(label) for label, _ in CASES)
    header = f"{'case'.ljust(w)} | " + " | ".join(n.ljust(41) for n in REVS)
    print(header)
    print("-" * len(header))
    for label, build in CASES:
        cells = [run(spaces[n], build) for n in REVS]
        flag = ""
        if cells[0] != cells[2]:
            flag = "   <== suggestion still differs from main"
        print(f"{label.ljust(w)} | " + " | ".join(c.ljust(41) for c in cells) + flag)


if __name__ == "__main__":
    main()
