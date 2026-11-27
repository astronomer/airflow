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

# How gust runs a Dag

## What happens

1. **Parse.** gust starts the Dag file and sends it a `DagFileParseRequest`, as the Dag processor
   does. From the Dag named by `--dag`, gust reads each task's edges, trigger rule, TaskFlow
   argument bindings, `retries`, `execution_timeout` and expansion, the way the scheduler and API
   server would. `--no-parse` skips this step; it needs `--task`.
2. **Run.** For each task instance try, gust starts the Dag file again, sends `StartupDetails`,
   and answers the task's requests until it disconnects. The execution timeout is enforced.
3. **Summary.** gust prints the Dag run with its final state, then every task instance in the
   order gust ran or decided it: its state, and for one that ran, its arguments, the XComs pushed,
   the Variables and state store values written, the rendered fields, every request it made and
   whether it was answered, and its error log lines.

The exit status is 0 when the Dag run succeeded, 1 when it failed or did not finish, and 2 when
gust could not run it.

With `--json`, the summary is an object with `dag_run` (the Dag run the tasks saw, with its final
`state` and an `end_date` once finished) and `instances` (one entry per try or decided instance,
with `task_id`, `map_index`, `try_number`, `state` and, for a try, its exit code, duration,
arguments and record).

## A whole Dag

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

## One task

With `--task`, gust runs the task as if the Dag held only that task: no upstream tasks, no trigger
rule to wait for, and no retries, so a try can be tested on its own with `ti`. Upstream results
come from [`xcoms`](input.md#xcoms). The Dag run state is the one that one-task Dag would end in:
`running` when the task ended `up_for_retry`, deferred or in another state that is not finished.

## Mapped tasks

When a task is mapped, gust runs every instance, one after another in map index order, following
[ADR-0016](../../airflow-core/adr/lang-sdk/0016-mapped-tasks-across-lang-sdks.md). Nothing extra
goes in `--input`: what the task expands over is in the serialized Dag, and an upstream output it
expands over is an XCom from the run, or from [`xcoms`](input.md#xcoms) with `--task`.

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
  Other bindings are passed as they are. A Python task has no bindings; the Task SDK resolves its
  arguments itself, by reading the upstream XComs.
- **Results.** Every instance runs, whatever the others' states, and has its own entry in the
  summary. A task that expands to nothing runs nothing and is `skipped`, as Airflow marks it.

gust only knows a task is mapped from the parse step, so with `--no-parse` it runs the task once,
unmapped. A task inside a mapped task group, and a `param` binding naming a group argument, are
errors.

## Not supported

- Tasks in a mapped task group, and task loops.
- `map()` callables of a Python Dag in another language's runtime (`ApplyMap`).
- Resuming a deferred or rescheduled task, and human-in-the-loop answers.
- Callbacks.
- Stub tasks in a Python Dag file, and task handlers.
- Triggering other Dag runs, and the requests that read other task instances or Dag runs.
- Converting messages between supervisor schemas.

A task gets an `API_SERVER_ERROR` for a request gust does not support, and the summary lists it as
unsupported.
