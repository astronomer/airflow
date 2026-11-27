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

//! Reading what a task needs from the Dag file's own serialized Dags.

use std::collections::BTreeSet;

use serde::Serialize;
use serde_json::Value as Json;

/// The parts of a serialized task gust needs to schedule and run it.
#[derive(Clone, Debug, Default, Serialize)]
pub struct TaskSpec {
    pub task_id: String,
    pub arg_bindings: Option<Vec<Json>>,
    pub retries: Option<i64>,
    pub execution_timeout: Option<f64>,
    pub queue: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mapped: Option<MappedSpec>,
    pub trigger_rule: String,
    pub is_setup: bool,
    pub is_teardown: bool,
    pub on_failure_fail_dagrun: bool,
    /// The task's body is a task handler supplied elsewhere.
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub is_stub: bool,
    pub upstream: Vec<String>,
    pub downstream: Vec<String>,
    /// The task sits in a mapped task group, so it expands with the group.
    #[serde(skip)]
    pub in_mapped_group: bool,
}

impl TaskSpec {
    /// A task gust knows nothing about beyond its id.
    pub fn bare(task_id: &str) -> Self {
        Self {
            task_id: task_id.to_owned(),
            trigger_rule: "all_success".into(),
            ..Self::default()
        }
    }

    /// This task alone, as a Dag of one task with no edges.
    pub fn isolate(&self) -> DagSpec {
        DagSpec {
            tasks: vec![Self {
                upstream: vec![],
                downstream: vec![],
                ..self.clone()
            }],
        }
    }
}

/// A Dag's tasks, in the order the serialized Dag lists them.
#[derive(Clone, Debug, Default)]
pub struct DagSpec {
    pub tasks: Vec<TaskSpec>,
}

impl DagSpec {
    pub fn get(&self, task_id: &str) -> Option<&TaskSpec> {
        self.tasks.iter().find(|t| t.task_id == task_id)
    }

    pub fn find_stub_task_ids(&self) -> Vec<&str> {
        self.tasks
            .iter()
            .filter(|t| t.is_stub)
            .map(|t| t.task_id.as_str())
            .collect()
    }

    pub fn find_mapped_task_ids(&self) -> BTreeSet<String> {
        self.tasks
            .iter()
            .filter(|t| t.mapped.is_some())
            .map(|t| t.task_id.clone())
            .collect()
    }
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

pub enum Lookup {
    Found(DagSpec),
    NoDag { available: Vec<String> },
}

fn unwrap_var(value: &Json) -> &Json {
    value.get("__var").unwrap_or(value)
}

fn is_true(task: &Json, key: &str) -> bool {
    task.get(key).and_then(Json::as_bool) == Some(true)
}

/// Find `dag_id` in a `DagFileParsingResult` body.
pub fn find_dag(result: &Json, dag_id: &str) -> Lookup {
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
    let raw: Vec<&Json> = dag
        .get("tasks")
        .and_then(Json::as_array)
        .into_iter()
        .flatten()
        .map(unwrap_var)
        .filter(|t| t.get("task_id").and_then(Json::as_str).is_some())
        .collect();
    let ids: BTreeSet<&str> = raw
        .iter()
        .filter_map(|t| t.get("task_id")?.as_str())
        .collect();
    let mut tasks: Vec<TaskSpec> = raw
        .iter()
        .map(|task| {
            let task_id = task["task_id"].as_str().unwrap_or_default();
            TaskSpec {
                task_id: task_id.to_owned(),
                arg_bindings: task.get("_arg_bindings").and_then(Json::as_array).cloned(),
                retries: task.get("retries").map(unwrap_var).and_then(Json::as_i64),
                execution_timeout: task
                    .get("execution_timeout")
                    .map(unwrap_var)
                    .and_then(Json::as_f64),
                queue: task.get("queue").and_then(Json::as_str).map(str::to_owned),
                mapped: find_mapped_spec(task),
                trigger_rule: task
                    .get("trigger_rule")
                    .and_then(Json::as_str)
                    .unwrap_or("all_success")
                    .to_owned(),
                is_setup: is_true(task, "is_setup"),
                is_teardown: is_true(task, "is_teardown"),
                on_failure_fail_dagrun: is_true(task, "on_failure_fail_dagrun"),
                is_stub: is_true(task, "is_stub"),
                upstream: vec![],
                downstream: task
                    .get("downstream_task_ids")
                    .and_then(Json::as_array)
                    .into_iter()
                    .flatten()
                    .filter_map(Json::as_str)
                    .filter(|id| ids.contains(id))
                    .map(str::to_owned)
                    .collect(),
                in_mapped_group: dag
                    .get("task_group")
                    .is_some_and(|g| is_in_mapped_group(g, task_id)),
            }
        })
        .collect();
    let edges: Vec<(String, String)> = tasks
        .iter()
        .flat_map(|t| t.downstream.iter().map(|d| (t.task_id.clone(), d.clone())))
        .collect();
    for (up, down) in edges {
        if let Some(task) = tasks.iter_mut().find(|t| t.task_id == down) {
            task.upstream.push(up);
        }
    }
    Lookup::Found(DagSpec { tasks })
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

    fn found(result: &Json, dag_id: &str) -> DagSpec {
        match find_dag(result, dag_id) {
            Lookup::Found(dag) => dag,
            Lookup::NoDag { .. } => panic!("no Dag {dag_id}"),
        }
    }

    #[test]
    fn finds_task_specs_and_edges() {
        let mut result = result();
        result["serialized_dags"][0]["data"]["dag"]["tasks"][0]["__var"]["downstream_task_ids"] =
            json!(["down", "gone"]);
        let dag = found(&result, "d");
        let down = dag.get("down").unwrap();
        assert_eq!(down.retries, Some(2));
        assert_eq!(down.execution_timeout, Some(30.0));
        assert_eq!(down.queue.as_deref(), Some("go"));
        assert_eq!(down.trigger_rule, "all_success");
        assert_eq!(down.arg_bindings.as_ref().unwrap()[0]["task_id"], "up");
        assert_eq!(down.upstream, ["up"]);
        assert_eq!(dag.get("up").unwrap().downstream, ["down"]);
        let alone = down.isolate();
        assert!(alone.tasks[0].upstream.is_empty());
    }

    #[test]
    fn reports_what_exists() {
        let Lookup::NoDag { available } = find_dag(&result(), "x") else {
            panic!()
        };
        assert_eq!(available, ["d"]);
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
        let dag = found(&result, "d");
        let mapped = dag.get("m").unwrap().mapped.clone().unwrap();
        assert!(mapped.op_kwargs);
        assert_eq!(mapped.expand_input["type"], "dict-of-lists");
        assert_eq!(dag.find_mapped_task_ids(), BTreeSet::from(["m".to_owned()]));
        assert!(!dag.get("m").unwrap().in_mapped_group);
        let grouped = dag.get("g.t").unwrap();
        assert!(grouped.mapped.is_none());
        assert!(grouped.in_mapped_group);
    }
}
