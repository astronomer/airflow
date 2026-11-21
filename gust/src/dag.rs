// Licensed to the Apache Software Foundation (ASF) under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied.  See the License for the
// specific language governing permissions and limitations
// under the License.

//! Reading what a task needs from the bundle's own serialized Dags.

use serde::Serialize;
use serde_json::Value as Json;

/// The parts of a serialized task that the API server would put into the task's run context.
#[derive(Debug, Default, Serialize)]
pub struct TaskSpec {
    pub arg_bindings: Option<Vec<Json>>,
    pub retries: Option<i64>,
    pub execution_timeout: Option<f64>,
    pub queue: Option<String>,
}

#[derive(Debug, PartialEq)]
pub enum Lookup<T> {
    Found(T),
    NoDag { available: Vec<String> },
    NoTask { available: Vec<String> },
}

fn unwrap_var(value: &Json) -> &Json {
    value.get("__var").unwrap_or(value)
}

/// Find `dag_id`/`task_id` in a `DagFileParsingResult` body.
pub fn find_task(result: &Json, dag_id: &str, task_id: &str) -> Lookup<TaskSpec> {
    let dags: Vec<&Json> = result
        .get("serialized_dags")
        .and_then(Json::as_array)
        .into_iter()
        .flatten()
        .filter_map(|d| d.pointer("/data/dag"))
        .collect();
    let Some(dag) = dags
        .iter()
        .find(|d| d.get("dag_id").and_then(Json::as_str) == Some(dag_id))
    else {
        return Lookup::NoDag {
            available: dags
                .iter()
                .filter_map(|d| d.get("dag_id")?.as_str().map(str::to_owned))
                .collect(),
        };
    };
    let tasks: Vec<&Json> = dag
        .get("tasks")
        .and_then(Json::as_array)
        .into_iter()
        .flatten()
        .map(unwrap_var)
        .collect();
    let Some(task) = tasks
        .iter()
        .find(|t| t.get("task_id").and_then(Json::as_str) == Some(task_id))
    else {
        return Lookup::NoTask {
            available: tasks
                .iter()
                .filter_map(|t| t.get("task_id")?.as_str().map(str::to_owned))
                .collect(),
        };
    };
    Lookup::Found(TaskSpec {
        arg_bindings: task.get("_arg_bindings").and_then(Json::as_array).cloned(),
        retries: task.get("retries").map(unwrap_var).and_then(Json::as_i64),
        execution_timeout: task
            .get("execution_timeout")
            .map(unwrap_var)
            .and_then(Json::as_f64),
        queue: task.get("queue").and_then(Json::as_str).map(str::to_owned),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn result() -> Json {
        json!({"serialized_dags": [{"data": {"__version": 3, "dag": {"dag_id": "d", "tasks": [
            {"__type": "operator", "__var": {"task_id": "up"}},
            {"__type": "operator", "__var": {
                "task_id": "down", "retries": 2, "execution_timeout": 30.0, "queue": "go",
                "_arg_bindings": [{"name": "n", "kind": "xcom", "task_id": "up"}],
            }},
        ]}}}]})
    }

    #[test]
    fn finds_task_spec() {
        let Lookup::Found(spec) = find_task(&result(), "d", "down") else {
            panic!()
        };
        assert_eq!(spec.retries, Some(2));
        assert_eq!(spec.execution_timeout, Some(30.0));
        assert_eq!(spec.queue.as_deref(), Some("go"));
        assert_eq!(spec.arg_bindings.unwrap()[0]["task_id"], "up");
    }

    #[test]
    fn reports_what_exists() {
        let Lookup::NoDag { available } = find_task(&result(), "x", "down") else {
            panic!()
        };
        assert_eq!(available, ["d"]);
        let Lookup::NoTask { available } = find_task(&result(), "d", "x") else {
            panic!()
        };
        assert_eq!(available, ["up", "down"]);
    }
}
