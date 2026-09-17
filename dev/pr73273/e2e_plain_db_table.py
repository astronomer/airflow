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

"""E2E for PR #73273: DataSourceConfig representing a plain database table.

Runs inside breeze against a real Postgres backend. Creates two real tables,
registers a real Airflow connection, and exercises every consumer of a
plain-DB DataSourceConfig.
"""

from __future__ import annotations

import os
import traceback

os.environ["AIRFLOW_CONN_PG_E2E"] = "postgresql://postgres:airflow@postgres:5432/airflow"
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "False")

SEP = "=" * 78


def banner(text: str) -> None:
    print(f"\n{SEP}\n{text}\n{SEP}")


def show_exc(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def setup_tables() -> None:
    from airflow.providers.postgres.hooks.postgres import PostgresHook

    hook = PostgresHook(postgres_conn_id="pg_e2e")
    hook.run(
        [
            "DROP TABLE IF EXISTS e2e_order_items",
            "DROP TABLE IF EXISTS e2e_orders_v1",
            "DROP TABLE IF EXISTS e2e_orders_v2",
            """
            CREATE TABLE e2e_orders_v1 (
                order_id   integer PRIMARY KEY,
                customer   varchar(64) NOT NULL,
                amount     numeric(10,2),
                created_at timestamp
            )
            """,
            """
            CREATE TABLE e2e_orders_v2 (
                order_id    bigint PRIMARY KEY,
                customer    text NOT NULL,
                amount      double precision,
                created_at  timestamptz,
                currency    varchar(3)
            )
            """,
            """
            CREATE TABLE e2e_order_items (
                item_id  integer PRIMARY KEY,
                order_id integer REFERENCES e2e_orders_v1(order_id),
                sku      varchar(32)
            )
            """,
            "CREATE INDEX e2e_orders_v1_customer_idx ON e2e_orders_v1 (customer)",
        ]
    )
    print("created tables: e2e_orders_v1, e2e_orders_v2, e2e_order_items")


def leg_a_construction() -> None:
    banner("LEG A -- construct a plain-DB DataSourceConfig (the PR's stated purpose)")
    from airflow.providers.common.sql.config import DataSourceConfig

    try:
        cfg = DataSourceConfig(conn_id="pg_e2e", table_name="e2e_orders_v1")
        print(f"OK   constructed: storage_type={cfg.storage_type!r} uri={cfg.uri!r} format={cfg.format!r}")
    except Exception as exc:
        print(f"RAISED {show_exc(exc)}")


def leg_b_schema_compare() -> None:
    banner("LEG B -- LLMSchemaCompareOperator introspects two real plain-DB tables")
    from airflow.providers.common.ai.operators.llm_schema_compare import LLMSchemaCompareOperator
    from airflow.providers.common.sql.config import DataSourceConfig

    op = LLMSchemaCompareOperator(
        task_id="compare",
        prompt="Compare these schemas.",
        llm_conn_id="unused_in_this_leg",
        data_sources=[
            DataSourceConfig(conn_id="pg_e2e", table_name="e2e_orders_v1"),
            DataSourceConfig(conn_id="pg_e2e", table_name="e2e_orders_v2"),
        ],
        context_strategy="full",
    )
    try:
        print(op._build_schema_context())
    except Exception as exc:
        print(f"RAISED {show_exc(exc)}")
        traceback.print_exc()


def leg_c_analytics_operator() -> None:
    banner("LEG C -- AnalyticsOperator path (ungated register_datasource), same config")
    from airflow.providers.common.sql.config import DataSourceConfig
    from airflow.providers.common.sql.datafusion.engine import DataFusionEngine

    cfg = DataSourceConfig(conn_id="pg_e2e", table_name="e2e_orders_v1")
    try:
        DataFusionEngine().register_datasource(cfg)
        print("OK   register_datasource accepted the plain-DB config")
    except Exception as exc:
        print(f"RAISED {show_exc(exc)}")


def leg_d_validation_gap() -> None:
    banner("LEG D -- table_name validation bypassed by the new early return")
    from airflow.providers.common.sql.config import DataSourceConfig, StorageType

    cases = [
        ("plain DB, blank table_name", dict(conn_id="pg_e2e", table_name="")),
        ("plain DB, whitespace table_name", dict(conn_id="pg_e2e", table_name="   ")),
        (
            "explicit storage_type=S3, blank table_name, no uri",
            dict(conn_id="pg_e2e", table_name="", storage_type=StorageType.S3),
        ),
        (
            "uri set, blank table_name (control: must still raise)",
            dict(conn_id="pg_e2e", table_name="", uri="s3://bucket/path"),
        ),
    ]
    for label, kwargs in cases:
        try:
            cfg = DataSourceConfig(**kwargs)
            print(f"ACCEPTED  {label}  -> storage_type={cfg.storage_type!r}")
        except Exception as exc:
            print(f"RAISED    {label}  -> {show_exc(exc)}")


def leg_e_blank_table_downstream() -> None:
    banner("LEG E -- downstream effect of an accepted blank table_name")
    from airflow.providers.common.ai.operators.llm_schema_compare import LLMSchemaCompareOperator
    from airflow.providers.common.sql.config import DataSourceConfig

    op = LLMSchemaCompareOperator(
        task_id="compare_blank",
        prompt="Compare these schemas.",
        llm_conn_id="unused_in_this_leg",
        data_sources=[
            DataSourceConfig(conn_id="pg_e2e", table_name="e2e_orders_v1"),
            DataSourceConfig(conn_id="pg_e2e", table_name=""),
        ],
        context_strategy="basic",
    )
    try:
        ctx = op._build_schema_context()
        print("--- schema context handed to the LLM ---")
        print(ctx)
        print("--- end ---")
    except Exception as exc:
        print(f"RAISED {show_exc(exc)}")


def main() -> None:
    from airflow.providers.common.sql import config as config_mod

    print(f"config module: {config_mod.__file__}")
    setup_tables()
    leg_a_construction()
    leg_b_schema_compare()
    leg_c_analytics_operator()
    leg_d_validation_gap()
    leg_e_blank_table_downstream()


if __name__ == "__main__":
    main()
