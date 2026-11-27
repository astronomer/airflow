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

# The input mapping

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
| `args`        | see 4         | error (see 4)       |

1. Each task starts at try 1, with `max_tries` from its `retries`.
2. This Dag's XComs come from the run, so giving them is an error.
3. Each task instance starts with an empty store.
4. Only with `--task-handler`, or `--task` with `--no-parse`: a parsed Dag gives
   its tasks' arguments itself.

## `dag_run`

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

## `ti`

The task instance's try. Only with `--task`.

| Key          | Type    | Default |
|--------------|---------|---------|
| `try_number` | integer | `1`     |
| `max_tries`  | integer | see 1   |

1. The task's `retries` from its Dag, or `0` when gust has no Dag for it.

## `variables`

`{"key": value}`. Answers `GetVariable` and `GetVariableKeys`. A string value
is passed as is. Any other value is passed as JSON text, so
`Variable.get(..., deserialize_json=True)` gets it back. `null` is an error.
Default: `{}`, no Variables.

## `connections`

`{"conn_id": connection}`. Answers `GetConnection`. Each connection is either
an Airflow connection URI, such as
`"postgres://user:pass@host:5432/db?sslmode=require"` (including
`?__extra__=<json>`), or an object with `conn_type` (required), `host`,
`schema`, `login`, `password`, `port` and `extra` (an object or a JSON
string), the same as the JSON form of `AIRFLOW_CONN_*`. Default: `{}`, no
Connections.

## `xcoms`

`{"dag_id/task_id": {"key": value}}`, split at the first `/`. Answers
`GetXCom` for that Dag, task and key, whatever run the task asks for. The key
`""` is short for `return_value`; giving both for one task is an error.
Default: `{}`, no XComs.

A mapped upstream task's XComs are given as one JSON array, holding the value
of each map index in order: `{"my_dag/mapped": {"": [10, 20, 30]}}`. When the
parsed Dag marks the task as mapped, `GetXCom` with a map index answers with
that element, and without one (or with -1) with the whole array. An unmapped
task's value answers any map index. The requests that read XComs as a
sequence answer from that array: `GetXComCount` with its length,
`GetXComSequenceItem` with one item (negative offsets count from the end),
and `GetXComSequenceSlice` with `[start:stop:step]` as Python slices it. A
missing XCom counts as empty; a value that is not an array is an error for
these requests.

## `args`

`{"name": value}`. The task's arguments, sent as literal argument bindings, as
the API server sends a stub task's arguments to its task handler. Give every
argument the handler reads, including those with a default in the Python stub:
the API server sends defaults too. Only for a task gust does not parse a Dag
for (see 4 above). Default: no bindings.

## `task_state`

`{"key": value}`. The task's state store, which answers `GetTaskStateStore`
and takes `SetTaskStateStore`, `DeleteTaskStateStore` and
`ClearTaskStateStore`. Each instance of a mapped task starts with its own
copy. Only with `--task`. Default: `{}`, empty.

## `asset_state`

`{"asset": {"key": value}}`, where `asset` is an asset's name or URI. The
assets' state stores, which answer `GetAssetStateStoreByName`/`ByUri` and
take the matching set, delete and clear requests. An asset named by an event
in `dag_run.consumed_asset_events` can be reached by either its name or its
URI; any other asset only by the string given. Default: `{}`, all empty.

## Example

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
