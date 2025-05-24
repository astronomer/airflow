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

# Airflow Task SDK for Rust

This crate provides a minimal set of helpers for executing Airflow tasks written in Rust.
It mirrors the basic concepts of the Python and Go implementations.

## Example

```
use airflow_task_sdk::{execute, Task, TaskRequest, TaskResult};
use async_trait::async_trait;

struct Echo;

#[async_trait]
impl Task for Echo {
    async fn run(&self, req: TaskRequest) -> TaskResult {
        TaskResult { result: req.params }
    }
}

#[tokio::main]
async fn main() {
    let req = TaskRequest {
        task_id: "hello".to_string(),
        dag_id: "example".to_string(),
        run_id: "run1".to_string(),
        params: serde_json::json!({"msg": "world"}),
    };
    let result = execute(Echo, req).await;
    println!("{:?}", result);
}
```

## Celery worker example

A minimal worker using the [`rusty-celery`](https://github.com/rusty-celery/rusty-celery) crate is provided in
`examples/worker.rs`. It connects to a Redis broker and executes tasks
received from an Airflow Celery queue.

Run it with:

```bash
cargo run --example worker -- --broker redis://localhost:6379/0 --queue default
```

The example uses the `Echo` task defined in the source file and prints the
result returned by the task.

## OpenAPI client

The Execution API client is generated from the OpenAPI specification using
[`oapi-codegen`](https://github.com/deepmap/oapi-codegen). After updating the
API spec, run:

```bash
cargo run --package oapi-codegen -- path/to/openapi.yaml > src/api/client.gen.rs
```

The generated module is included at compile time from `src/api/client.gen.rs`.
