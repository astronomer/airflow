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

use std::collections::BTreeSet;

use serde::Serialize;
use serde_json::Value as Json;

/// The parts of a serialized task that the API server would put into the task's run context.
#[derive(Debug, Default, Serialize)]
pub struct TaskSpec {
    pub arg_bindings: Option<Vec<Json>>,
    pub retries: Option<i64>,
    pub execution_timeout: Option<f64>,
    pub queue: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mapped: Option<MappedSpec>,
    /// Every mapped task in the Dag, this one included.
    #[serde(skip)]
    pub mapped_tasks: BTreeSet<String>,
    /// The task sits in a mapped task group, so it expands with the group.
    #[serde(skip)]
    pub in_mapped_group: bool,
}

/// What a mapped task expands over, still in the serialized Dag's encoding.
#[derive(Clone, Debug, Default, Serialize)]
pub struct MappedSpec {
    /// `{"type": "dict-of-lists" | "list-of-dicts", "value": ...}`.
    pub expand_input: Json,
    pub partial_kwargs: Json,
    /// The expand input is a decorated task's `op_kwargs_expand_input`, so its `partial()`
    /// arguments are under `partial_kwargs.op_kwargs`.
    pub op_kwargs: bool,
}

fn is_mapped(task: &Json) -> bool {
    task.get("_is_mapped").and_then(Json::as_bool) == Some(true)
}

fn find_mapped_spec(task: &Json) -> Option<MappedSpec> {
    if !is_mapped(task) {
        return None;
    }
    let attr = task
        .get("_expand_input_attr")
        .and_then(Json::as_str)
        .unwrap_or("expand_input");
    Some(MappedSpec {
        expand_input: task.get(attr).cloned().unwrap_or(Json::Null),
        partial_kwargs: task.get("partial_kwargs").cloned().unwrap_or(Json::Null),
        op_kwargs: attr == "op_kwargs_expand_input",
    })
}

/// Whether `task_id` sits, at any depth, inside a mapped task group under `group`.
fn is_in_mapped_group(group: &Json, task_id: &str) -> bool {
    fn walk(group: &Json, task_id: &str, mapped_above: bool) -> Option<bool> {
        let mapped = mapped_above
            || group.get("is_mapped").and_then(Json::as_bool) == Some(true)
            || group.get("expand_input").is_some();
        for child in group.get("children")?.as_object()?.values() {
            match child.as_array().and_then(|c| c.get(1)) {
                Some(Json::String(id)) if id == task_id => return Some(mapped),
                Some(sub @ Json::Object(_)) => {
                    if let Some(found) = walk(sub, task_id, mapped) {
                        return Some(found);
                    }
                }
                _ => {}
            }
        }
        None
    }
    walk(group, task_id, false).unwrap_or(false)
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
        mapped: find_mapped_spec(task),
        mapped_tasks: tasks
            .iter()
            .filter(|t| is_mapped(t))
            .filter_map(|t| t.get("task_id")?.as_str().map(str::to_owned))
            .collect(),
        in_mapped_group: dag
            .get("task_group")
            .is_some_and(|g| is_in_mapped_group(g, task_id)),
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

    #[test]
    fn finds_mapped_task_and_group() {
        let result = json!({"serialized_dags": [{"data": {"dag": {"dag_id": "d",
            "tasks": [
                {"__type": "operator", "__var": {"task_id": "m", "_is_mapped": true,
                    "_expand_input_attr": "op_kwargs_expand_input",
                    "op_kwargs_expand_input": {"type": "dict-of-lists", "value": []},
                    "partial_kwargs": {}}},
                {"__type": "operator", "__var": {"task_id": "g.t"}},
            ],
            "task_group": {"_group_id": null, "children": {
                "m": ["operator", "m"],
                "g": ["taskgroup", {"_group_id": "g", "is_mapped": true, "children": {
                    "g.t": ["operator", "g.t"],
                }}],
            }},
        }}}]});
        let Lookup::Found(spec) = find_task(&result, "d", "m") else {
            panic!()
        };
        let mapped = spec.mapped.unwrap();
        assert!(mapped.op_kwargs);
        assert_eq!(mapped.expand_input["type"], "dict-of-lists");
        assert_eq!(spec.mapped_tasks, BTreeSet::from(["m".to_owned()]));
        assert!(!spec.in_mapped_group);
        let Lookup::Found(spec) = find_task(&result, "d", "g.t") else {
            panic!()
        };
        assert!(spec.mapped.is_none());
        assert!(spec.in_mapped_group);
    }
}
