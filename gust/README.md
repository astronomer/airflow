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

`gust` test-runs a Dag, or one task of it, from a built Dag file, with no Airflow installation and
no Python. It starts the Dag file the way an Airflow worker does, plays the scheduler and the
supervisor, answers the tasks' requests from the `--input` mapping, and prints what the tasks did.

```bash
gust path/to/my_dags --dag=my_dag --task=my_task --input='{
  "dag_run": {"logical_date": "2026-01-01T00:00:00Z", "conf": {"region": "eu"}},
  "xcoms": {"my_dag/upstream": {"": {"rows": 3}}},
  "variables": {"greeting": "hello"},
  "connections": {"my_db": "postgres://user:pass@localhost:5432/app"}
}'
```

Without `--task`, gust runs the whole Dag; see [Running a whole Dag](#running-a-whole-dag).

```bash
gust path/to/my_dags --dag=my_dag --input='{"variables": {"greeting": "hello"}}'
```

gust takes one Dag file, checks it, and refuses anything it does not recognise before starting a
process:

- an executable with the bundle trailer that native SDKs append (such as the Go SDK's
  `airflow-go-pack`; see `task-sdk/docs/executable-bundle-spec.rst`), with its executable bit set;
- a `.min.mjs` built by `airflow-ts-pack`, run with `--runtime=node`;
- a fat Jar, which the Java SDK's Gradle plugin builds by default, run with `--runtime='java -jar'`.

```bash
gust dist/my_dags.min.mjs --runtime=node --dag=my_dag --task=my_task
gust build/libs/my-dags-all.jar --runtime='java -jar' --dag=my_dag --task=my_task
```

`--runtime` is split like a shell command line, so it can carry interpreter options; gust puts it
in front of the Dag file's path. For Java it must end with `-jar`.

## Building

```bash
cargo build --release
```

The binary is `target/release/gust`.

## Flags

| Flag | |
|---|---|
| `DAG_FILE` | The Dag file. Required. |
| `--dag` | The Dag to run. Required. |
| `--task` | Run only this task of the Dag, as if the Dag had no other task. Without it, the whole Dag runs. |
| `--input` | Everything else the tasks see, as one JSON object. See [The input mapping](docs/input.md), also printed by `gust --help:input`. |
| `--help:input` | Print the format of `--input` and exit. |
| `--runtime` | The program that runs the Dag file. See above. |
| `--no-parse` | Do not ask the Dag file for its Dags first. Needs `--task`. See [What happens](#what-happens). |
| `--startup-timeout` | Seconds to wait for the Dag file to connect back. Default 10. |
| `--quiet` | Do not echo the task's logs while it runs. |
| `--json` | Print the summary as JSON on stdout. |

## The input mapping

`--input` is documented in [docs/input.md](docs/input.md), and `gust --help:input` prints it.

## Running a whole Dag

Without `--task`, gust runs every task of the Dag, one at a time, as the scheduler would schedule
them, and stops when the Dag run reaches a finished state.

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

When a task is mapped in the parsed Dag, gust runs every instance, one after another in map
index order, following [ADR-0016](../airflow-core/adr/lang-sdk/0016-mapped-tasks-across-lang-sdks.md).
Nothing extra goes in `--input`: what the task expands over is in the serialized Dag, and an
upstream output it expands over is an XCom from the run, or from [`xcoms`](docs/input.md#xcoms) with `--task`.

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

1. **Parse.** gust starts the Dag file and sends it a `DagFileParseRequest`, as the Dag processor
   does. From the Dag named by `--dag`, gust reads each task's edges, trigger rule,
   TaskFlow argument bindings, `retries`, `execution_timeout` and expansion, the way the scheduler
   and API server would. `--no-parse` skips this step.
2. **Run.** For each task instance try, gust starts the Dag file again with `--comm` and `--logs`,
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
a deferred or rescheduled task, human-in-the-loop answers, callbacks, task handlers for Python
Dags, triggering other Dag runs, and the requests that read other task instances or Dag runs. The
task gets an `API_SERVER_ERROR` for a request gust does not support, and the summary lists it as
unsupported.

gust speaks the supervisor schema it was generated from and does not migrate messages for a Dag
file built against an older one; it notes the difference in the summary.

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
