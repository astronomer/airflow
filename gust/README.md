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

`gust` test-runs one task from an Airflow executable Dag bundle, with no Airflow installation and
no Python. It starts the bundle the way an Airflow worker does, plays the supervisor, answers the
task's requests from the `--input` mapping, and prints what the task did.

```bash
gust path/to/bundle --dag=my_dag --task=my_task --input='{
  "dag_run": {"logical_date": "2026-01-01T00:00:00Z", "conf": {"region": "eu"}},
  "xcoms": {"my_dag/upstream": {"": {"rows": 3}}},
  "variables": {"greeting": "hello"},
  "connections": {"my_db": "postgres://user:pass@localhost:5432/app"}
}'
```

A bundle is whatever file a language SDK packs a project into. gust runs it directly, which suits
the executable bundles that native SDKs build (such as the Go SDK's `airflow-go-pack`; see
`task-sdk/docs/executable-bundle-spec.rst`). A bundle that needs an interpreter is run through
`--runtime`, which gust puts in front of the bundle path:

```bash
gust dist/my_dags.min.mjs --runtime=node --dag=my_dag --task=my_task
gust build/libs/my-dags-all.jar --runtime='java -jar' --dag=my_dag --task=my_task
```

`--runtime` is split like a shell command line, so it can carry interpreter options. gust does not
inspect the file to pick an interpreter. `java -jar` needs the fat JAR the Java SDK's Gradle plugin
builds by default; a JAR built with `fatJar = false` does not carry its dependencies.

## Building

```bash
cargo build --release
```

The binary is `target/release/gust`.

## Flags

| Flag | |
|---|---|
| `BUNDLE` | Path to the bundle. Required. |
| `--dag`, `--task` | The task to run. Required. |
| `--input` | Everything else the task sees, as one JSON object. See [The input mapping](#the-input-mapping). |
| `--runtime` | The program that runs the bundle. See above. |
| `--no-parse` | Do not ask the bundle for its Dags first. See [What happens](#what-happens). |
| `--startup-timeout` | Seconds to wait for the bundle to connect back. Default 10. |
| `--quiet` | Do not echo the task's logs while it runs. |
| `--json` | Print the summary as JSON on stdout. |

## The input mapping

`--input` takes one JSON object in a format of gust's own. Every key is optional, and leaving out
`--input` is the same as `--input='{}'`. Unknown keys are errors at every level, reported with
where they are, such as ``dag_run.consumed_asset_events[0]: unknown field `extras` ``. Dates are RFC
3339 strings with a time zone, such as `2026-01-01T00:00:00Z`.

Each fact has one key. The Dag and task ids come only from `--dag` and `--task`, and the run id only
from `dag_run.run_id`, so there are no `dag_id`, `task_id` or `run_id` keys elsewhere; gust copies
them to wherever the task needs them. The map index is always -1, since mapping is not supported.

Anything the task writes (XComs, Variables, state store values) is kept for the rest of the run, so
a task that writes a value and reads it back sees its own value. Nothing is written back to the
input, and the summary lists every write.

### `dag_run`

The Dag run the task instance belongs to.

| Key | Type | Default |
|---|---|---|
| `run_id` | string | `<run_type>__<logical_date>`, or `<run_type>__<run_after>` when `logical_date` is `null` |
| `run_type` | `manual`, `scheduled`, `backfill`, `operator_triggered`, `asset_triggered` or `asset_materialization` | `manual` |
| `logical_date` | date, or `null` for a run without one | when gust starts |
| `data_interval` | `{"start": date, "end": date}`, or `null` for none | starts and ends at `logical_date`; none when `logical_date` is `null` |
| `run_after` | date | `logical_date`, or when gust starts when that is `null` |
| `start_date` | date | when gust starts. Also the task instance's start date. |
| `conf` | object | none: the run has no `conf` |
| `partition_key` | string | none |
| `triggering_user` | string | none |
| `note` | string | none |
| `consumed_asset_events` | list of asset events | none |

The run's state is always `running`.

An asset event in `consumed_asset_events`:

| Key | Type | Default |
|---|---|---|
| `asset` | `{"name": string, "uri": string, "group": string, "extra": object}`; `name` or `uri` is required | `uri` is the `name`, or the other way round, as `Asset(...)` does; `group` is `asset`; `extra` is `{}` |
| `extra` | object | `{}` |
| `timestamp` | date | when gust starts |
| `source` | `{"dag_id": string, "task_id": string, "run_id": string, "map_index": integer}` | all none |
| `aliases` | list of asset alias names | `[]` |
| `partition_key` | string | none |

These events are the run's triggering events, and also the events gust knows about:

- `GetAssetEventByAsset` and `GetAssetEventByAssetAlias` search them, with the request's
  `after`, `before`, `partition_key`, `partition_key_regexp_pattern`, `extra`, `ascending` and
  `limit` applied. Events get ids 1, 2, ... in the order given, and their `created_dagruns` list
  is empty.
- `GetAssetByName`, `GetAssetByUri` and `GetAssetsByAlias` answer from the assets these events
  name. Two events naming the same asset must describe it the same way.

### `ti`

The task instance.

| Key | Type | Default |
|---|---|---|
| `try_number` | integer | 1 |
| `max_tries` | integer | the task's `retries` from its Dag, or 0 when gust has no Dag for it |

### `variables`

`{"key": value}`. Answers `GetVariable` and `GetVariableKeys`. A string value is passed as is. Any
other value is passed as JSON text, so `Variable.get(..., deserialize_json=True)` gets it back.
`null` is an error. Default: no Variables.

### `connections`

`{"conn_id": connection}`. Answers `GetConnection`. Each connection is either an Airflow connection
URI, such as `"postgres://user:pass@host:5432/db?sslmode=require"` (including
`?__extra__=<json>`), or an object with `conn_type` (required), `host`, `schema`, `login`,
`password`, `port` and `extra` (an object or a JSON string), the same as the JSON form of
`AIRFLOW_CONN_*`. Default: no Connections.

### `xcoms`

`{"dag_id/task_id": {"key": value}}`. Answers `GetXCom` for that Dag, task and key, whatever run
and map index the task asks for. The key `""` is short for `return_value`; giving both for one
task is an error. Default: no XComs.

A mapped upstream task's XComs are given as one JSON array, holding the value of each map index
in order: `{"my_dag/mapped": {"": [10, 20, 30]}}`. The requests that read them as a sequence
answer from that array: `GetXComCount` with its length, `GetXComSequenceItem` with one item
(negative offsets count from the end), and `GetXComSequenceSlice` with `[start:stop:step]` as
Python slices it. A missing XCom counts as empty; a value that is not an array is an error for
these requests.

### `task_state`

`{"key": value}`. The task's state store, which answers `GetTaskStateStore` and takes
`SetTaskStateStore`, `DeleteTaskStateStore` and `ClearTaskStateStore`. Default: empty.

### `asset_state`

`{"asset": {"key": value}}`, where `asset` is an asset's name or URI. The assets' state stores,
which answer `GetAssetStateStoreByName`/`ByUri` and take the matching set, delete and clear
requests. An asset named by an event in `dag_run.consumed_asset_events` can be reached by either
its name or its URI; any other asset only by the string given. Default: all empty.

### Example

```json
{
  "dag_run": {
    "run_type": "asset_triggered",
    "logical_date": null,
    "conf": {"full_refresh": false},
    "consumed_asset_events": [
      {
        "asset": {"name": "orders", "uri": "s3://lake/orders"},
        "extra": {"rows": 120},
        "timestamp": "2026-11-20T08:00:00Z",
        "source": {"dag_id": "ingest", "task_id": "load", "run_id": "scheduled__2026-11-20T07:00:00Z"}
      }
    ]
  },
  "ti": {"try_number": 2},
  "variables": {"env": "staging", "limits": {"max": 10}},
  "connections": {
    "warehouse": {"conn_type": "postgres", "host": "localhost", "port": 5432, "login": "etl", "password": "p@ss"}
  },
  "xcoms": {"report/extract": {"": [1, 2, 3], "count": 3}},
  "task_state": {"cursor": 41},
  "asset_state": {"orders": {"last_seen_id": 9000}}
}
```

## What happens

1. **Parse.** gust starts the bundle and sends it a `DagFileParseRequest`, as the Dag processor
   does. If the task belongs to a Dag the bundle defines natively, gust reads the task's TaskFlow
   argument bindings, `retries` and `execution_timeout` from the serialized Dag, the way the API
   server would before a run. A task handler for a Python Dag gets no bindings: those live in the
   Python Dag file. `--no-parse` skips this step.
2. **Run.** gust starts the bundle again with `--comm` and `--logs`, sends `StartupDetails`, and
   answers the task's requests until it disconnects. The execution timeout is enforced.
3. **Summary.** gust prints the final state, the XComs pushed, the Variables and state store values
   written, the rendered fields, every request the task made and whether it was answered, and the
   error log lines.

The exit status is 0 when the task succeeded, 1 when it did not, and 2 when gust could not run it.

## Not supported

Running a mapped task (a downstream task can still read a mapped upstream's XComs; see
[`xcoms`](#xcoms)), resuming a deferred or
rescheduled task, human-in-the-loop answers, callbacks, stub tasks, and the requests that read other
task instances or Dag runs. The task gets an
`API_SERVER_ERROR` for a request gust does not support, and the summary lists it as unsupported.

gust speaks the supervisor schema it was generated from and does not migrate messages for a bundle
built against an older one; it notes the difference in the summary.

## The supervisor models

`src/models.rs` is generated from the Task SDK's supervisor schema with
[typify](https://github.com/oxidecomputer/typify). It is a one-shot generation for now; to
regenerate it:

```bash
cargo run -p gust-codegen -- ../task-sdk/src/airflow/sdk/execution_time/schema/schema.json src/models.rs
```

The generator maps every `date-time` to `timestamp::Timestamp`, which crosses the comm socket as
a msgpack timestamp as the Python supervisor sends it, and every `JsonValue` to
`serde_json::Value`.
