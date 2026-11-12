<!--
 Licensed to the Apache Software Foundation (ASF) under one
 or more contributor license agreements.  See the NOTICE file
 distributed with this work for additional information
 regarding copyright ownership.  The ASF licenses this file
 to you under the Apache License, Version 2.0 (the
 "License"); you may not use this file except in compliance
 with the License.  You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing,
 software distributed under the License is distributed on an
 "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 KIND, either express or implied.  See the License for the
 specific language governing permissions and limitations
 under the License.
 -->

# airflow-dev (proof of concept)

Run Airflow's source tests on SQLite, Postgres or MySQL, and start a source instance on any of them,
without Docker or Breeze. Breeze stays the way to reproduce CI.

The tool is small on purpose. It starts database servers you already have installed, gives every
test run its own database, and hands off to what the repository already uses:

- `uv run --project <member> pytest`, the same command AGENTS.md recommends;
- the repository's pytest plugin (`tests_common.pytest_plugin`) for database setup, markers and
  `--skip-db-tests`;
- plain `airflow standalone` for a running instance;
- `scripts/ci/prek/compile_ui_assets.py` for the UI.

It downloads nothing and installs nothing outside the checkout. Database drivers come from the
versions pinned in the root `uv.lock`.

## Use

From any directory inside an Airflow checkout:

```bash
alias airflow-dev='uv run --project "$(git rev-parse --show-toplevel)/dev/airflow-dev" airflow-dev'
```

```bash
airflow-dev doctor                                  # what this machine can run, and how to install the rest

airflow-dev test task-sdk/tests/task_sdk/definitions/test_param.py
airflow-dev test airflow-core/tests/unit/models/test_variable.py                      # SQLite
airflow-dev test airflow-core/tests/unit/models/test_variable.py --backend postgres
airflow-dev test airflow-core/tests/unit/models/test_dagrun.py --backend mysql --db-version 8.4
airflow-dev test airflow-core/tests/unit/models/test_dagrun.py --backend postgres --workers 4 -- -x
airflow-dev test providers/standard/tests/unit/standard/operators/test_branch.py --backend postgres

airflow-dev start --backend postgres --examples      # foreground; Ctrl+C stops it
airflow-dev start --backend postgres --background    # returns once every component is healthy
airflow-dev status --backend postgres
airflow-dev logs scheduler --backend postgres --follow
airflow-dev stop --backend postgres

airflow-dev db status                               # servers, ports, leftover test databases
airflow-dev db url --backend postgres                # a URL for your own tools
airflow-dev db prune                                # clean up after a run that was killed
airflow-dev db stop --backend postgres
```

Every command takes `--json` and then prints one JSON document on stdout.

## How it works

**Servers.** `airflow-dev` looks for `postgres`/`initdb`/`pg_ctl`/`psql` and `mysqld`/`mysql`/`mysqladmin`
on `PATH`, in Homebrew's `opt/postgresql@*` and `opt/mysql*`, Postgres.app and the usual Linux
locations, plus any directory listed in `AIRFLOW_DEV_TOOL_DIRS`. Without `--db-version` it picks the
first version Breeze tests against (read from `dev/breeze/.../global_constants.py`) that is installed,
and it refuses versions Airflow does not support, such as MySQL 9.x.

Each release line gets one private server under `.build/airflow-dev/db/<engine>-<version>/`, on a free
loopback port, with local trust authentication. Postgres also runs with `fsync=off`: it is a
throwaway development database. Servers stay up between runs; `airflow-dev db stop` stops them.

**Tests.** Each run creates `airflow_test_<id>_main`, plus `_gw0`, `_gw1`, … with `--workers`, and a
home per worker under `.build/airflow-dev/runs/`. The repository's test plugin turns
`AIRFLOW_DEV_DB_URL_TEMPLATE` and `AIRFLOW_DEV_HOME_TEMPLATE` into each xdist worker's own database
and home before Airflow reads its configuration. Inherited `AIRFLOW_*` variables are dropped. The
databases and homes are removed when the run ends, including on Ctrl+C; `--keep-db` keeps them.
pytest's exit code is the command's exit code, and the JUnit report and log stay under
`files/airflow-dev/runs/<id>/`.

**Instances.** `airflow-dev start` builds the UI if its sources changed, creates `airflow_instance` on
the selected server (or uses SQLite in the instance home), and runs
`uv run --project providers/standard airflow standalone` with LocalExecutor and no login. Each
backend and version has its own home under `.build/airflow-dev/instances/` and keeps its data across
stops. `--dags-folder` points it at your Dags; otherwise it uses an empty folder in its home.

The screen shows only standalone's own messages, component errors, and a ready banner with the URL
and login. Each component's output goes to its own file in `logs/standalone/` in the instance home
(`scheduler.log`, `dag-processor.log`, `api-server.log`, `triggerer.log`, and `standalone.log` for
database setup); the previous run's files are kept with a `.1` suffix. `airflow-dev logs` shows them
all, `airflow-dev logs scheduler --follow` one of them, and `start --verbose` streams everything to the
screen instead. The UI build output and, in the background, standalone's own output go to
`console.log` in the instance home.

## Differences from CI

- MySQL uses PyMySQL and aiomysql, so nothing has to compile; CI uses mysqlclient. The URL asks for
  multi-statement support, which some migrations need and mysqlclient enables by default.
- Postgres uses psycopg 3, as Breeze does by default.
- Only the test dependencies a member declares are installed. When CI's image provides something a
  member forgot to declare, the tool adds it at its `uv.lock` version (`EXTRA_TEST_REQUIREMENTS` in
  `testing.py`; today only `rfc3339-validator` for `task-sdk`).
- Each run starts from a fresh database, so the first test of a run pays for the schema creation.
- Tests and instances use the checkout's shared `.venv`, like any `uv run --project`. `uv run` adds
  what a member needs but removes nothing, so an instance also loads every provider a previous full
  `uv sync` installed there.

## Not included

No installer for databases, Node or pnpm (`doctor` prints the install command; a missing pnpm
version comes from Node's corepack); no external database servers; no picking tests from changed
files; no Linux verification yet; no executors or auth managers other than standalone's.

## Develop

```bash
uv run --project dev/airflow-dev pytest dev/airflow-dev/tests
```
