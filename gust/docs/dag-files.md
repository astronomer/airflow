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

# Dag files and runtimes

gust takes one Dag file and runs it. There is no Dag bundle: gust does not look for other files
next to it, and packages the Dag file depends on are found the way its own language finds them.

## What gust accepts

gust recognises a Dag file by one test per kind, tried in this order. The first test that matches
decides the kind, and a file that then fails that kind's checks is an error: gust never falls
through to the next kind.

| # | Test | Kind | Checks |
|---|------|------|--------|
| 1 | The file ends with the `AFBNDL01` trailer | Executable | The trailer's SHA-256 matches the binary, and the file is executable (on Unix) |
| 2 | The name ends with `.min.mjs` | TypeScript | The bundle header, every section's SHA-256, and the metadata version |
| 3 | The name ends with `.py` or `.pyc` | Python | |
| 4 | The file is a zip whose `META-INF/MANIFEST.MF` sets `Main-Class` | Java | The manifest also sets `Airflow-Supervisor-Schema-Version` |
| 5 | The file is a zip with `__main__.py` or `__main__.pyc` at its root | Python | |
| 6 | The path is a directory with `__main__.py` or `__main__.pyc` | Python | |

Anything else is refused before any process starts. In particular:

- An executable without the trailer is refused, even if it is a valid program. Build it with the
  SDK's packer, such as the Go SDK's `airflow-go-pack`.
- A `.mjs` that `airflow-ts-pack` did not build, a `.ts` file, and a `.java` file are refused.
- A thin Jar, one built with the Gradle plugin's `fatJar = false`, is refused: its dependencies,
  and the schema version, are in other Jars. Build the fat Jar, which is the plugin's default.

The trailer and the bundle header are specified in `task-sdk/docs/executable-bundle-spec.rst` and
`task-sdk/docs/ts-bundle-spec.rst`. gust checks a TypeScript bundle the way Airflow's own reader
does, which already allows one source section per Dag file.

A built Dag file declares the supervisor schema it was built against. When that differs from the
schema gust speaks, the summary notes it. gust does not convert messages between schemas.

## Runtimes

`--runtime` is the program that starts the Dag file, split like a shell command line. gust adds
the Dag file's path, then `--comm` and `--logs`, as Airflow's coordinators do.

| Kind | `--runtime` | gust runs |
|------|-------------|-----------|
| Executable | none | `<file> --comm=… --logs=…` |
| TypeScript | `node` | `node <file> --comm=… --logs=…` |
| Java | `java -jar`, with any JVM options before `-jar` | `java -jar <file> --comm=… --logs=…` |
| Python | an interpreter, such as `python3` or `uv run python` | see below |

An executable can be given a runtime too, such as `env FOO=1`; gust puts it in front.

For Java, the runtime must end with `-jar`: `java` takes a class name as its main argument, not a
Jar path, so gust refuses the run instead of letting the JVM fail to find a class.

## Python

A Python Dag file has nothing in it that talks to Airflow's supervisor, so gust starts it through
a small bridge of its own, passed to the interpreter with `-c`:

```text
<runtime> -c <bridge> parse|run <path> --comm=… --logs=…
```

The interpreter must be able to import `airflow.sdk` and Airflow core, as a Dag processor or
worker can. The bridge runs `<path>` the way `python <path>` would:

- A `.py` or `.pyc` file runs as a script, with its directory first on `sys.path`.
- A directory or zip file runs its `__main__.py`, with the directory or zip first on `sys.path`.

Interpreter options in the runtime, such as `-P` or `-X dev`, apply as usual. The code runs as a
module named `__gust_dag__`, not `__main__`, so a Dag file's `if __name__ == "__main__":` block
does not run, as in Airflow.

gust finds the same Dags Airflow's Python importer would: those at the top level of the module
that ran, and every Dag created in a `with DAG(...)` block or by `@dag`, whichever module created
it. A `__main__.py` that imports the modules defining its Dags therefore finds them. A Dag made
without a context manager and kept only in another module's globals is not found.

To run a task, the bridge hands the task instance to the Task SDK's own task runner, so the task
runs as on an Airflow worker: the same operators, templating, XCom handling and requests. What a
Python task reads before asking the supervisor still applies, such as `AIRFLOW_VAR_*` and
`AIRFLOW_CONN_*` environment variables, a secrets backend, and a custom XCom backend.

gust does not run stub tasks (`@task.stub`) of a Python Dag file, since their task handlers live
elsewhere. A whole Dag run is refused when any of the Dag's tasks is a stub, and a `--task` run when
that task is one; other tasks of the Dag can still run with `--task`.

## Task handlers

A Dag file can also hold task handlers: the bodies of a Python Dag's stub tasks, written with
another SDK. `--task-handler=DAG_ID/TASK_ID` runs one of them, in place of `--dag` and `--task`.
The ids are split at the first `/`, which a Dag id cannot contain.

```bash
gust bin/my_handlers --task-handler=my_dag/summarize --input='{"args": {"region": "eu"}}'
gust dist/handlers.min.mjs --runtime=node --task-handler=my_dag/summarize
```

The Python Dag is not involved, so gust does not parse anything. Before starting the Dag file,
gust checks that it declares the handler: an executable lists its handlers in its manifest's
`dags`, and a TypeScript bundle in its metadata's `task_handlers`. A Jar lists none, so for Java
only running it tells. gust does not run Python task handlers yet.

What the API server would take from the Python Dag is not there either:

- The task's arguments come from [`args`](input.md#args) in `--input`. Give every argument the
  handler reads, including those with a default in the Python stub.
- The task runs once, with no retries and no execution timeout, unmapped.
