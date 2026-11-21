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

`gust` test-runs a Dag, or one task of it, from an Airflow executable Dag bundle, with no Airflow
installation and no Python. It starts the bundle the way an Airflow worker does, plays the
scheduler and the supervisor, answers the tasks' requests from the `--input` mapping, and prints
what the tasks did.

```bash
gust path/to/bundle --dag=my_dag --task=my_task --input='{
  "dag_run": {"logical_date": "2026-01-01T00:00:00Z", "conf": {"region": "eu"}},
  "xcoms": {"my_dag/upstream": {"": {"rows": 3}}},
  "variables": {"greeting": "hello"},
  "connections": {"my_db": "postgres://user:pass@localhost:5432/app"}
}'
```

Without `--task`, gust runs the whole Dag; see [Running a whole Dag](#running-a-whole-dag).

```bash
gust path/to/bundle --dag=my_dag --input='{"variables": {"greeting": "hello"}}'
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
| `--dag` | The Dag to run. Required. |
| `--task` | Run only this task of the Dag, as if the Dag had no other task. Without it, the whole Dag runs. |
| `--input` | Everything else the tasks see, as one JSON object. See [The input mapping](#the-input-mapping), also printed by `gust --help:input`. |
| `--help:input` | Print the format of `--input` and exit. |
| `--runtime` | The program that runs the bundle. See above. |
| `--no-parse` | Do not ask the bundle for its Dags first. Needs `--task`. See [What happens](#what-happens). |
| `--startup-timeout` | Seconds to wait for the bundle to connect back. Default 10. |
| `--quiet` | Do not echo the task's logs while it runs. |
| `--json` | Print the summary as JSON on stdout. |

## The input mapping

<!-- input-help:start -->
`--input` takes one JSON object in a format of gust's own. Every key is
optional, and leaving out `--input` is the same as `--input='{}'`. In the
tables below, Default is what gust uses when a key is left out. Unknown keys
are errors at every level, reported with where they are, such as
``dag_run.consumed_asset_events[0]: unknown field `extras` ``. Dates are RFC
3339 strings with a time zone, such as `2026-01-01T00:00:00Z`.

Each fact has one key. The Dag and task ids come only from `--dag` and
`--task`, and the run id only from `dag_run.run_id`, so there are no
`dag_id`, `task_id` or `run_id` keys elsewhere; gust copies them to wherever
the task needs them. There is no map index either: gust works out a mapped
task's instances itself.

Anything a task writes (XComs, Variables, state store values) is kept for the
rest of the run, so a task that writes a value, and every task after it, sees
that value. Each task instance has its own task state store and keeps its
XComs under its own map index. Nothing is written back to the input, and the
summary lists every write.

A whole Dag run needs no input beyond what its tasks read. Some keys describe
one task instance, or values the run itself produces, so they only work with
`--task`:

| Key           | With `--task` | Whole Dag           |
|---------------|---------------|---------------------|
| `dag_run`     | yes           | yes                 |
| `ti`          | yes           | error (see 1)       |
| `variables`   | yes           | yes                 |
| `connections` | yes           | yes                 |
| `xcoms`       | yes           | other Dags' (see 2) |
| `task_state`  | yes           | error (see 3)       |
| `asset_state` | yes           | yes                 |

1. Each task starts at try 1, with `max_tries` from its `retries`.
2. This Dag's XComs come from the run, so giving them is an error.
3. Each task instance starts with an empty store.

### `dag_run`

The Dag run the task instance belongs to. Its state is always `running`.

| Key                     | Type                 | Default          |
|-------------------------|----------------------|------------------|
| `run_id`                | string               | see 1            |
| `run_type`              | see 2                | `manual`         |
| `logical_date`          | date, or `null`      | when gust starts |
| `data_interval`         | see 3                | see 3            |
| `run_after`             | date                 | see 4            |
| `start_date`            | date                 | when gust starts |
| `conf`                  | object               | `null`           |
| `partition_key`         | string               | `null`           |
| `triggering_user`       | string               | `null`           |
| `note`                  | string               | `null`           |
| `consumed_asset_events` | list of asset events | `[]`             |

1. `<run_type>__<logical_date>`, or `<run_type>__<run_after>` when
   `logical_date` is `null`.
2. `manual`, `scheduled`, `backfill`, `operator_triggered`, `asset_triggered`
   or `asset_materialization`.
3. `{"start": date, "end": date}`, or `null` for none. Defaults to starting and
   ending at `logical_date`, or `null` when `logical_date` is `null`.
4. `logical_date`, or when gust starts when `logical_date` is `null`.

`start_date` is also the task instances' start date.

An asset event in `consumed_asset_events`:

| Key             | Type                      | Default          |
|-----------------|---------------------------|------------------|
| `asset`         | object (see 1); required  |                  |
| `extra`         | object                    | `{}`             |
| `timestamp`     | date                      | when gust starts |
| `source`        | object (see 2)            | see 2            |
| `aliases`       | list of asset alias names | `[]`             |
| `partition_key` | string                    | `null`           |

1. `{"name": string, "uri": string, "group": string, "extra": object}`, where
   `name` or `uri` is required. A missing `uri` is the `name`, or the other way
   round, as `Asset(...)` does; `group` defaults to `asset`, and `extra` to
   `{}`.
2. `{"dag_id": string, "task_id": string, "run_id": string, "map_index":
   integer}`. Each key defaults to `null`.

These events are the run's triggering events, and also the events gust knows
about:

- `GetAssetEventByAsset` and `GetAssetEventByAssetAlias` search them, with the
  request's `after`, `before`, `partition_key`,
  `partition_key_regexp_pattern`, `extra`, `ascending` and `limit` applied.
  Events get ids 1, 2, ... in the order given, and their `created_dagruns`
  list is empty.
- `GetAssetByName`, `GetAssetByUri` and `GetAssetsByAlias` answer from the
  assets these events name. Two events naming the same asset must describe it
  the same way.

### `ti`

The task instance's try. Only with `--task`.

| Key          | Type    | Default |
|--------------|---------|---------|
| `try_number` | integer | `1`     |
| `max_tries`  | integer | see 1   |

1. The task's `retries` from its Dag, or `0` when gust has no Dag for it.

### `variables`

`{"key": value}`. Answers `GetVariable` and `GetVariableKeys`. A string value
is passed as is. Any other value is passed as JSON text, so
`Variable.get(..., deserialize_json=True)` gets it back. `null` is an error.
Default: `{}`, no Variables.

### `connections`

`{"conn_id": connection}`. Answers `GetConnection`. Each connection is either
an Airflow connection URI, such as
`"postgres://user:pass@host:5432/db?sslmode=require"` (including
`?__extra__=<json>`), or an object with `conn_type` (required), `host`,
`schema`, `login`, `password`, `port` and `extra` (an object or a JSON
string), the same as the JSON form of `AIRFLOW_CONN_*`. Default: `{}`, no
Connections.

### `xcoms`

`{"dag_id/task_id": {"key": value}}`. Answers `GetXCom` for that Dag, task and
key, whatever run the task asks for. The key `""` is short for
`return_value`; giving both for one task is an error. Default: `{}`, no
XComs.

A mapped upstream task's XComs are given as one JSON array, holding the value
of each map index in order: `{"my_dag/mapped": {"": [10, 20, 30]}}`. When the
bundle's Dag marks the task as mapped, `GetXCom` with a map index answers with
that element, and without one (or with -1) with the whole array. An unmapped
task's value answers any map index. The requests that read XComs as a
sequence answer from that array: `GetXComCount` with its length,
`GetXComSequenceItem` with one item (negative offsets count from the end),
and `GetXComSequenceSlice` with `[start:stop:step]` as Python slices it. A
missing XCom counts as empty; a value that is not an array is an error for
these requests.

### `task_state`

`{"key": value}`. The task's state store, which answers `GetTaskStateStore`
and takes `SetTaskStateStore`, `DeleteTaskStateStore` and
`ClearTaskStateStore`. Each instance of a mapped task starts with its own
copy. Only with `--task`. Default: `{}`, empty.

### `asset_state`

`{"asset": {"key": value}}`, where `asset` is an asset's name or URI. The
assets' state stores, which answer `GetAssetStateStoreByName`/`ByUri` and
take the matching set, delete and clear requests. An asset named by an event
in `dag_run.consumed_asset_events` can be reached by either its name or its
URI; any other asset only by the string given. Default: `{}`, all empty.

### Example

For a run with `--task`, since it sets `ti` and `task_state`:

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
        "source": {
          "dag_id": "ingest",
          "task_id": "load",
          "run_id": "scheduled__2026-11-20T07:00:00Z"
        }
      }
    ]
  },
  "ti": {"try_number": 2},
  "variables": {"env": "staging", "limits": {"max": 10}},
  "connections": {
    "warehouse": {
      "conn_type": "postgres",
      "host": "localhost",
      "port": 5432,
      "login": "etl",
      "password": "p@ss"
    }
  },
  "xcoms": {"report/extract": {"": [1, 2, 3], "count": 3}},
  "task_state": {"cursor": 41},
  "asset_state": {"orders": {"last_seen_id": 9000}}
}
```
<!-- input-help:end -->

## Running a whole Dag

Without `--task`, gust runs every task of the Dag, one at a time, as the scheduler would schedule
them, and stops when the Dag run reaches a finished state. The Dag must be one the bundle defines
natively: a Python Dag's tasks and edges live in the Python file, so only one of its task handlers
can run at a time.

- **Order.** gust takes the first task, in the order the serialized Dag lists them, whose upstream
  tasks are all done, and repeats until every task is done.
- **Trigger rules.** Once a task's upstream task instances are all done, its `trigger_rule` decides
  whether it runs, or is marked `skipped` or `upstream_failed` without running, with the
  scheduler's own rules. Every rule is supported. A mapped upstream counts once per instance, and
  `all_done_setup_success` looks at the upstream setup tasks.
- **XComs.** A task reads what earlier tasks pushed. A mapped upstream's output is every
  instance's value, in map index order.
- **Branching.** The tasks (or map indexes) a task asks to skip are marked `skipped` before they
  run, and their downstream tasks follow their trigger rules.
- **Retries.** A task that ends `up_for_retry` runs again at once with the next try number,
  ignoring `retry_delay`, until `max_tries` (its `retries`) is used up. Each try starts without the
  XComs the last one pushed, and keeps its task state store.
- **Suspended tasks.** gust cannot resume a task that defers, reschedules or waits for human
  input, so in a whole Dag run such a task counts as `failed`.
- **The Dag run state** follows `DagRun.update_state`: `failed` when a leaf task instance failed or
  was `upstream_failed`, else `success`. A teardown is not a leaf unless it sets
  `on_failure_fail_dagrun`.

With `--task`, gust runs the task as if the Dag held only that task: no upstream tasks, no trigger
rule to wait for, and no retries, so a try can be tested on its own with `ti`. The Dag run state is
the one that one-task Dag would end in: `running` when the task ended `up_for_retry`, deferred or
in another state that is not finished.

## Mapped tasks

When a task is mapped in the bundle's Dag, gust runs every instance, one after another in map
index order, following [ADR-0016](../airflow-core/adr/lang-sdk/0016-mapped-tasks-across-lang-sdks.md).
Nothing extra goes in `--input`: what the task expands over is in the serialized Dag, and an
upstream output it expands over is an XCom from the run, or from [`xcoms`](#xcoms) with `--task`.

- **How many.** A literal list or dict expands over its items (a dict's as `[key, value]` pairs),
  and an upstream XCom over its value the same way, so a mapped upstream's array gives one
  instance per element. `expand()` takes the cross product of its arguments; `expand_kwargs()` one
  instance per dict. `zip()` stops at the shortest argument, or runs to the longest with a
  `fillvalue`; `concat()` adds the lengths; `map()` keeps the length it wraps. An XCom that is
  missing, or not a list or an object, fails the task in a whole Dag run; with `--task` it is an
  error before anything runs.
- **What each instance gets.** `ti.map_index` and `ti_context.expanded_ti_count` are set, and each
  `param` argument binding is resolved, as the API server and supervisor would, into a `literal`:
  from the expand input first, then `partial()`, then the parameter's default. A `partial()`
  argument from a mapped upstream is a `sequence`. A `kwargs` binding becomes this instance's dict
  with `spread` set. A `map()` argument keeps `apply_map` set, so the runtime applies its own
  callables; for `expand_kwargs()` with `map()`, `kwarg` and `fallback` are left to the runtime too.
  Other bindings are passed as they are. These fields are newer than the supervisor schema gust
  was generated from, so they are written into the encoded message directly.
- **Results.** Every instance runs, whatever the others' states, and has its own entry in the
  summary. A task that expands to nothing runs nothing and is `skipped`, as Airflow marks it.

gust only knows a task is mapped from the parse step, so with `--no-parse` it runs the task once,
unmapped. No SDK emits a mapped task in its own Dags yet, so this follows the ADR rather than a
working SDK. A task inside a mapped task group, and a `param` binding naming a group argument, are
errors.

## What happens

1. **Parse.** gust starts the bundle and sends it a `DagFileParseRequest`, as the Dag processor
   does. From a Dag the bundle defines natively, gust reads each task's edges, trigger rule,
   TaskFlow argument bindings, `retries`, `execution_timeout` and expansion, the way the scheduler
   and API server would. A task handler for a Python Dag gets no bindings: those live in the
   Python Dag file. `--no-parse` skips this step.
2. **Run.** For each task instance try, gust starts the bundle again with `--comm` and `--logs`,
   sends `StartupDetails`, and answers the task's requests until it disconnects. The execution
   timeout is enforced.
3. **Summary.** gust prints the Dag run with its final state, then every task instance in the
   order gust ran or decided it: its state, and for one that ran, its arguments, the XComs pushed,
   the Variables and state store values written, the rendered fields, every request it made and
   whether it was answered, and its error log lines. With `--json`, the summary is an object with
   `dag_run` (the Dag run the tasks saw, with its final `state` and an `end_date` once finished)
   and `instances` (one entry per try or decided instance, with `task_id`, `map_index`,
   `try_number`, `state` and, for a try, its exit code, duration, arguments and record).

The exit status is 0 when the Dag run succeeded, 1 when it failed or did not finish, and 2 when
gust could not run it.

## Not supported

Tasks in a mapped task group, task loops, a Python Dag's `map()` callables (`ApplyMap`), resuming
a deferred or rescheduled task, human-in-the-loop answers, callbacks, stub tasks, triggering other
Dag runs, and the requests that read other task instances or Dag runs. The task gets an
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
