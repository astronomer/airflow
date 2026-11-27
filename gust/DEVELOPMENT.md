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

# Developing gust

## Building and testing

```bash
cargo build
cargo test
cargo clippy --all-targets
cargo fmt
```

The unit tests need nothing outside the crate. Running real Dag files needs their toolchains; see
[Testing with real Dag files](#testing-with-real-dag-files).

## How gust is put together

gust plays three parts of Airflow at once: the Dag processor that asks a Dag file for its Dags,
the scheduler that decides which task instance runs next, and the supervisor that starts a task
and answers its requests. It speaks the same protocol as Airflow's supervisor: length-prefixed
msgpack frames over a TCP socket (`--comm`), with JSON log lines on a second one (`--logs`).

| Module | |
|---|---|
| `main.rs` | The run: recognise the Dag file, parse it, pick the tasks, run them, and build the summary. |
| `cli.rs` | Command-line flags, and `--help:input`, which prints part of `docs/input.md`. |
| `artifact.rs` | Recognising the Dag file's kind, checking it, and building the command that starts it. |
| `executable.rs`, `node.rs`, `jar.rs` | Reading and verifying the metadata each built kind carries. |
| `bridge.py` | The Python side of gust, run with the interpreter's `-c`. |
| `runtime.rs` | Starting a Dag file, accepting its two connections, collecting its logs, and enforcing timeouts. |
| `frame.rs` | Encoding and decoding frames. |
| `dag.rs` | Reading what gust needs from a serialized Dag. |
| `scheduler.rs` | Ordering task instances, trigger rules, branching, retries, and the Dag run state. |
| `expand.rs` | Expanding mapped tasks and resolving their argument bindings (ADR-0016). |
| `services.rs` | Answering the task's requests from the input, and recording what it wrote. |
| `input.rs` | Parsing `--input`. |
| `summary.rs` | The printed and JSON summary. |
| `models.rs` | The supervisor messages, generated; see [The supervisor models](#the-supervisor-models). |

### Recognising a Dag file

`Artifact::inspect` tries one test per kind, in a fixed order, and commits to the first that
matches; `docs/dag-files.md` lists them. A new kind must keep that order working:

- Its test reads only the Dag file: its content or its name, never the result of running it.
- Its test does not overlap an earlier one, or is placed before it on purpose.
- Once it matches, a failed check is an error, not a reason to try the next kind.

A file that packs in an `AFBNDL01` trailer needs no change at all, whatever its language.

### The Python bridge

A Python Dag file does not speak the supervisor protocol, so gust starts it through `bridge.py`,
which `artifact.rs` embeds with `include_str!` and passes with `-c`. gust adds `parse` or `run` to
the command line, so the bridge knows what to do before the first frame arrives.

The bridge:

1. connects to `--comm` and `--logs`, moves the comm socket onto fd 0 (where the Task SDK's
   `CommsDecoder` expects it), and sends logs as JSON with the supervisor's
   `_configure_logs_over_json_channel`;
2. sets `sys.path[0]` and `sys.argv` as `python <path>` would;
3. runs the Dag file with `runpy.run_path` under the module name `__gust_dag__`, collecting the
   top-level Dags and the autoregistered ones, as `airflow.sdk.importers.python_importer` does;
4. to parse, answers the `DagFileParseRequest` with the Dag processor's own `DagFileParsingResult`
   and `_serialize_dags`;
5. to run, replaces `task_runner.parse` with one that loads the Dags from the Dag file instead of
   a Dag bundle, then calls `task_runner.main()`.

It uses private parts of the Task SDK and Airflow core: `_configure_logs_over_json_channel`,
`CommsDecoder._get_response`, `DagContext.current_autoregister_module_name`, `_serialize_dags`,
`task_runner.parse` and `_register_deserialization_allowed_classes`. A change to any of them can
break the bridge. Check it against the installed Airflow version when it fails at startup.

Two of gust's answers exist because the Python Task SDK relies on them:

- The Dag processor acknowledges a `DagFileParsingResult` with an empty frame, and the Task SDK
  waits for it before it exits.
- An out-of-range `GetXComSequenceItem` is answered with the `ErrorResponse` as the body, not in
  the error slot. The Task SDK ends the iteration over a mapped task's results on it.

### Stub tasks

A Lang-SDK Dag marks every task `is_stub`, since to Airflow its body lives in the Dag file rather
than in Python. So gust refuses stub tasks only in a Python Dag file, where a stub's task handler
comes from somewhere else.

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

gust speaks the one schema it was generated from. A built Dag file declares its own, and the
summary notes a difference; converting messages between schemas is not done yet.

## Testing with real Dag files

Each language has examples in this repository that build Dag files gust can run.

**Go.** With the Go toolchain:

```bash
cd go-sdk/example/native
go tool airflow-go-pack --output /tmp/gust/go_native
gust /tmp/gust/go_native --dag=go_native_pipeline --input='{
  "variables": {"go_native_greeting": "hi", "go_native_cadence": "daily"},
  "connections": {"test_http": {"conn_type": "http", "host": "example.com"}}
}'
```

`go-sdk/example/bundle` builds only task handlers for Python Dags, so it has no Dags of its own.

**TypeScript.** Build `ts-sdk/example` with its `build` script, then:

```bash
gust ts-sdk/example/dist/bundle.min.mjs --runtime=node --dag=typescript_native_example
```

Its `trigger_downstream` task fails, since gust does not trigger Dag runs.

**Java.** Build `java-sdk/example` with Gradle's `bundle` task, then:

```bash
gust java-sdk/example/build/libs/airflow-java-sdk-example-all.jar --runtime='java -jar' --dag=<dag_id>
```

**Python.** Any interpreter that can import the Task SDK and Airflow core works. From this
repository's workspace:

```bash
gust path/to/dag.py --runtime="uv run --project task-sdk python" --startup-timeout=120 --dag=<dag_id>
```

Starting through `uv run` takes several seconds for each task instance, hence the timeout.
