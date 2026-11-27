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

# gust

gust test-runs an Airflow Dag, or one task of it, with no scheduler, API server or database. It
starts the Dag file the way an Airflow worker does, answers the tasks' requests from one JSON
input, and prints what each task did.

It runs Dags written with any Task SDK: a Go executable, a TypeScript bundle, a Java fat Jar, or
a Python file.

## Examples

Run a whole Dag:

```bash
gust bin/my_dags --dag=my_dag
gust dist/bundle.min.mjs --runtime=node --dag=my_dag
gust build/libs/my-dags-all.jar --runtime='java -jar' --dag=my_dag
gust dags/my_dag.py --runtime=python3 --dag=my_dag
```

Give the tasks what they read from Airflow:

```bash
gust dags/my_dag.py --runtime=python3 --dag=my_dag --input='{
  "dag_run": {"logical_date": "2026-01-01T00:00:00Z", "conf": {"region": "eu"}},
  "variables": {"greeting": "hello"},
  "connections": {"my_db": "postgres://user:pass@localhost:5432/app"}
}'
```

Run one task, with its upstream results given as XComs:

```bash
gust dags/my_dag.py --runtime=python3 --dag=my_dag --task=load \
  --input='{"xcoms": {"my_dag/extract": {"": {"rows": 3}}}}'
```

The exit status is 0 when the Dag run succeeded, 1 when it failed or did not finish, and 2 when
gust could not run it.

## Flags

| Flag | |
|---|---|
| `DAG_FILE` | The Dag file. Required. See [Dag files and runtimes](docs/dag-files.md). |
| `--dag` | The Dag to run. Required. |
| `--task` | Run only this task, as if the Dag had no other task. |
| `--runtime` | The program that starts the Dag file, such as `node`, `java -jar` or `python3`. |
| `--input` | What the tasks see from Airflow, as one JSON object. See [The input mapping](docs/input.md), also printed by `gust --help:input`. |
| `--no-parse` | Do not ask the Dag file for its Dags first. Needs `--task`. |
| `--startup-timeout` | Seconds to wait for the Dag file to connect back. Default 10. |
| `--quiet` | Do not echo the tasks' logs while they run. |
| `--json` | Print the summary as JSON on stdout. |

A Python interpreter can take several seconds to import Airflow, so a larger `--startup-timeout`
may be needed for Python Dag files.

## Building

```bash
cargo build --release
```

The binary is `target/release/gust`.

## More

- [Dag files and runtimes](docs/dag-files.md): what gust accepts, and how it starts each kind.
- [How gust runs a Dag](docs/running.md): scheduling, trigger rules, retries, mapped tasks, and
  what is not supported.
- [The input mapping](docs/input.md): the format of `--input`.
- [Developing gust](DEVELOPMENT.md).
