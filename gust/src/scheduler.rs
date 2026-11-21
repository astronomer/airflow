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

//! Scheduling a Dag run: one task at a time, in the Dag's order, each once all its upstream tasks
//! are done. Trigger rules and the Dag run state follow the scheduler's own rules
//! (`TriggerRuleDep` and `DagRun.update_state`).

use std::collections::{BTreeMap, BTreeSet};

use anyhow::{Result, bail};
use serde_json::Value as Json;

use crate::{
    dag::{DagSpec, TaskSpec},
    expand::{Expansion, XComValues},
    models::DagRunState,
    summary::Instance,
};

/// One try of one task instance to run.
pub struct TiRun {
    pub map_index: i64,
    pub try_number: i64,
    pub max_tries: i64,
    pub expanded_ti_count: Option<i64>,
    pub bindings: Option<Vec<Json>>,
    /// The bindings are worked out by gust, in the wire form the supervisor sends, rather than
    /// taken from the Dag as they are.
    pub resolved: bool,
}

/// What actually runs task instances.
pub trait Executor {
    fn run(&mut self, task: &TaskSpec, ti: TiRun) -> Result<Instance>;
    /// Every XCom of the Dag so far, whole, for expanding a mapped task.
    fn find_xcom_values(&self) -> XComValues;
    fn set_map_length(&mut self, task_id: &str, length: usize);
}

pub struct Settings<'a> {
    /// The whole Dag runs, rather than one task in isolation. A whole run retries tasks,
    /// counts a task it cannot resume as failed, and fails a task whose expansion fails instead
    /// of stopping.
    pub whole_dag: bool,
    pub first_try: i64,
    /// Overrides every task's `retries` as its `max_tries`.
    pub max_tries: Option<i64>,
    /// Every mapped task of the Dag, including any outside the tasks being run.
    pub mapped_task_ids: &'a BTreeSet<String>,
}

const FINISHED: &[&str] = &["success", "failed", "skipped", "upstream_failed", "removed"];

/// Run `dag` to the end. Returns every instance in the order it ran or was decided, and the
/// Dag run's state.
pub fn run_dag(
    dag: &DagSpec,
    settings: &Settings,
    exec: &mut impl Executor,
) -> Result<(Vec<Instance>, DagRunState)> {
    let mut instances: Vec<Instance> = Vec::new();
    // The final state of each task instance, by task, in map index order.
    let mut states: BTreeMap<String, Vec<String>> = BTreeMap::new();
    // Branches ask for tasks, or single map indexes of them, to be skipped.
    let mut skip_tasks: BTreeMap<String, String> = BTreeMap::new();
    let mut skip_indexes: BTreeMap<(String, i64), String> = BTreeMap::new();

    loop {
        for (task_id, by) in std::mem::take(&mut skip_tasks) {
            if dag.get(&task_id).is_some() && !states.contains_key(&task_id) {
                instances.push(Instance::decided(
                    &task_id,
                    -1,
                    "skipped",
                    format!("Skipped by {by}."),
                ));
                states.insert(task_id, vec!["skipped".into()]);
            }
        }
        let Some(task) = dag.tasks.iter().find(|t| {
            !states.contains_key(&t.task_id) && t.upstream.iter().all(|u| states.contains_key(u))
        }) else {
            break;
        };

        let upstream: Vec<(&str, bool)> = task
            .upstream
            .iter()
            .flat_map(|u| {
                let is_setup = dag.get(u).is_some_and(|t| t.is_setup);
                states[u].iter().map(move |s| (s.as_str(), is_setup))
            })
            .collect();
        if let Some(state) = evaluate_trigger_rule(&task.trigger_rule, &upstream)? {
            instances.push(Instance::decided(
                &task.task_id,
                -1,
                state,
                format!(
                    "Trigger rule {} with upstream states {}.",
                    task.trigger_rule,
                    describe_states(&upstream)
                ),
            ));
            states.insert(task.task_id.clone(), vec![state.into()]);
            continue;
        }

        let max_tries = settings.max_tries.or(task.retries).unwrap_or(0);
        let mut runs: Vec<TiRun> = Vec::new();
        let mut task_states: Vec<String> = Vec::new();
        match &task.mapped {
            None => runs.push(TiRun {
                map_index: -1,
                try_number: settings.first_try,
                max_tries,
                expanded_ti_count: None,
                bindings: task.arg_bindings.clone(),
                resolved: false,
            }),
            Some(mapped) => {
                let xcoms = exec.find_xcom_values();
                let expanded =
                    Expansion::new(mapped, &xcoms, settings.mapped_task_ids).and_then(|e| {
                        (0..e.length)
                            .map(|index| {
                                task.arg_bindings
                                    .as_deref()
                                    .map(|entries| e.build_bindings(entries, index))
                                    .transpose()
                                    .map_err(|err| {
                                        err.context(format!(
                                            "cannot bind the arguments of map index {index}"
                                        ))
                                    })
                            })
                            .collect::<Result<Vec<_>>>()
                    });
                match expanded {
                    Ok(per_index) => {
                        let count = per_index.len();
                        exec.set_map_length(&task.task_id, count);
                        if count == 0 {
                            instances.push(Instance::decided(
                                &task.task_id,
                                -1,
                                "skipped",
                                "The task expanded to no instances.".into(),
                            ));
                            task_states.push("skipped".into());
                        }
                        for (index, bindings) in per_index.into_iter().enumerate() {
                            runs.push(TiRun {
                                map_index: index as i64,
                                try_number: settings.first_try,
                                max_tries,
                                expanded_ti_count: Some(count as i64),
                                bindings,
                                resolved: true,
                            });
                        }
                    }
                    Err(e) if settings.whole_dag => {
                        instances.push(Instance::decided(
                            &task.task_id,
                            -1,
                            "failed",
                            format!("Cannot expand the task: {e:#}"),
                        ));
                        task_states.push("failed".into());
                    }
                    Err(e) => return Err(e.context(format!("cannot expand {}", task.task_id))),
                }
            }
        }

        for mut ti in runs {
            if let Some(by) = skip_indexes.remove(&(task.task_id.clone(), ti.map_index)) {
                instances.push(Instance::decided(
                    &task.task_id,
                    ti.map_index,
                    "skipped",
                    format!("Skipped by {by}."),
                ));
                task_states.push("skipped".into());
                continue;
            }
            loop {
                let try_number = ti.try_number;
                let mut instance = exec.run(
                    task,
                    TiRun {
                        bindings: ti.bindings.clone(),
                        ..ti
                    },
                )?;
                let retry = settings.whole_dag
                    && instance.state == "up_for_retry"
                    && try_number <= ti.max_tries;
                if settings.whole_dag && !retry && !FINISHED.contains(&instance.state.as_str()) {
                    instance.notes.push(format!(
                        "The task ended {}, which gust cannot continue from, so it counts as failed.",
                        instance.state
                    ));
                    instance.state = "failed".into();
                }
                for target in instance.record.iter().flat_map(|r| &r.skipped_downstream) {
                    let by = format!("branch task {}", task.task_id);
                    match target {
                        Json::String(id) => {
                            skip_tasks.insert(id.clone(), by);
                        }
                        Json::Array(pair) => {
                            if let (Some(id), Some(index)) = (
                                pair.first().and_then(Json::as_str),
                                pair.get(1).and_then(Json::as_i64),
                            ) {
                                if index < 0 {
                                    skip_tasks.insert(id.to_owned(), by);
                                } else {
                                    skip_indexes.insert((id.to_owned(), index), by);
                                }
                            }
                        }
                        _ => {}
                    }
                }
                let state = instance.state.clone();
                instances.push(instance);
                if !retry {
                    task_states.push(state);
                    break;
                }
                ti.try_number = try_number + 1;
            }
        }
        states.insert(task.task_id.clone(), task_states);
    }

    if let Some(stuck) = dag.tasks.iter().find(|t| !states.contains_key(&t.task_id)) {
        bail!(
            "task {} can never run: its upstream tasks form a cycle",
            stuck.task_id
        );
    }
    Ok((instances, find_dag_run_state(dag, &states)))
}

fn describe_states(upstream: &[(&str, bool)]) -> String {
    let mut counts: BTreeMap<&str, usize> = BTreeMap::new();
    for (state, _) in upstream {
        *counts.entry(state).or_default() += 1;
    }
    counts
        .iter()
        .map(|(s, n)| format!("{n} {s}"))
        .collect::<Vec<_>>()
        .join(", ")
}

/// The state a task's trigger rule gives it once every upstream task instance is done, or `None`
/// when it should run. `upstream` holds each upstream task instance's state, and whether its task
/// is a setup task.
pub fn evaluate_trigger_rule(
    rule: &str,
    upstream: &[(&str, bool)],
) -> Result<Option<&'static str>> {
    if upstream.is_empty() {
        return Ok(None);
    }
    let count = |state: &str| upstream.iter().filter(|(s, _)| *s == state).count();
    let (success, skipped, failed, upstream_failed) = (
        count("success"),
        count("skipped"),
        count("failed"),
        count("upstream_failed"),
    );
    let total = upstream.len();
    let setups: Vec<&str> = upstream
        .iter()
        .filter(|(_, setup)| *setup)
        .map(|(s, _)| *s)
        .collect();
    let failures = failed + upstream_failed;
    const SKIP: Option<&str> = Some("skipped");
    const UPSTREAM_FAILED: Option<&str> = Some("upstream_failed");
    Ok(match rule {
        "all_success" if failures > 0 => UPSTREAM_FAILED,
        "all_success" if skipped > 0 => SKIP,
        "all_failed" if success + skipped > 0 => SKIP,
        "one_success" if skipped == total => SKIP,
        "one_success" if success == 0 => UPSTREAM_FAILED,
        "one_failed" if failures == 0 => SKIP,
        "one_done" if failed + success == 0 => SKIP,
        "none_failed" if failures > 0 => UPSTREAM_FAILED,
        "none_failed_min_one_success" if failures > 0 => UPSTREAM_FAILED,
        "none_failed_min_one_success" if skipped == total => SKIP,
        "none_failed_min_one_success" if success == 0 => UPSTREAM_FAILED,
        "none_skipped" if skipped > 0 => SKIP,
        "all_skipped" if success + failures > 0 => SKIP,
        "all_done_min_one_success" if skipped > 0 => SKIP,
        "all_done_min_one_success" if success == 0 => UPSTREAM_FAILED,
        "all_done_setup_success"
            if !setups.is_empty() && setups.iter().all(|s| *s == "skipped") =>
        {
            SKIP
        }
        "all_done_setup_success" if !setups.is_empty() && !setups.contains(&"success") => {
            UPSTREAM_FAILED
        }
        "all_success"
        | "all_failed"
        | "all_done"
        | "one_success"
        | "one_failed"
        | "one_done"
        | "none_failed"
        | "none_failed_min_one_success"
        | "none_skipped"
        | "all_skipped"
        | "all_done_min_one_success"
        | "all_done_setup_success"
        | "always" => None,
        other => bail!("unknown trigger rule {other:?}"),
    })
}

/// The Dag run's state, as `DagRun.update_state` decides it from the leaf tasks. A teardown is
/// not a leaf unless it sets `on_failure_fail_dagrun`.
pub fn find_dag_run_state(dag: &DagSpec, states: &BTreeMap<String, Vec<String>>) -> DagRunState {
    let all = || states.values().flatten();
    if dag.tasks.iter().any(|t| !states.contains_key(&t.task_id))
        || all().any(|s| !FINISHED.contains(&s.as_str()))
    {
        return DagRunState::Running;
    }
    let counts = |t: &TaskSpec| !t.is_teardown || t.on_failure_fail_dagrun;
    let mut leaves: Vec<&TaskSpec> = dag
        .tasks
        .iter()
        .filter(|t| {
            counts(t)
                && t.downstream
                    .iter()
                    .all(|d| dag.get(d).is_none_or(|d| !counts(d)))
        })
        .collect();
    if leaves.is_empty() {
        leaves = dag
            .tasks
            .iter()
            .filter(|t| t.downstream.is_empty())
            .collect();
    }
    let failed = leaves
        .iter()
        .flat_map(|t| &states[&t.task_id])
        .any(|s| s == "failed" || s == "upstream_failed");
    if failed {
        DagRunState::Failed
    } else {
        DagRunState::Success
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    use crate::{dag::MappedSpec, services::Record};

    /// Runs tasks by looking their states up, and records what ran.
    #[derive(Default)]
    struct FakeExec {
        /// Each try's state by task id, last one repeating; `success` by default.
        states: BTreeMap<String, Vec<&'static str>>,
        /// Branch skips a task sends.
        skips: BTreeMap<String, Vec<Json>>,
        xcoms: XComValues,
        ran: Vec<(String, i64, i64, Option<Vec<Json>>)>,
        lengths: BTreeMap<String, usize>,
    }

    impl Executor for FakeExec {
        fn run(&mut self, task: &TaskSpec, ti: TiRun) -> Result<Instance> {
            let tries = self
                .states
                .get(&task.task_id)
                .cloned()
                .unwrap_or(vec!["success"]);
            let state = tries[((ti.try_number - 1) as usize).min(tries.len() - 1)];
            self.ran.push((
                task.task_id.clone(),
                ti.map_index,
                ti.try_number,
                ti.bindings.clone(),
            ));
            let record = Record {
                skipped_downstream: self.skips.get(&task.task_id).cloned().unwrap_or_default(),
                ..Record::default()
            };
            Ok(Instance {
                try_number: Some(ti.try_number),
                exit_code: Some(0),
                duration_secs: Some(0.0),
                record: Some(record),
                ..Instance::decided(&task.task_id, ti.map_index, state, String::new())
            })
        }

        fn find_xcom_values(&self) -> XComValues {
            self.xcoms.clone()
        }

        fn set_map_length(&mut self, task_id: &str, length: usize) {
            self.lengths.insert(task_id.to_owned(), length);
        }
    }

    fn task(id: &str, upstream: &[&str]) -> TaskSpec {
        TaskSpec {
            upstream: upstream.iter().map(|s| s.to_string()).collect(),
            ..TaskSpec::bare(id)
        }
    }

    fn dag(mut tasks: Vec<TaskSpec>) -> DagSpec {
        let edges: Vec<(String, String)> = tasks
            .iter()
            .flat_map(|t| t.upstream.iter().map(|u| (u.clone(), t.task_id.clone())))
            .collect();
        for (up, down) in edges {
            tasks
                .iter_mut()
                .find(|t| t.task_id == up)
                .unwrap()
                .downstream
                .push(down);
        }
        DagSpec { tasks }
    }

    fn whole<'a>(mapped: &'a BTreeSet<String>) -> Settings<'a> {
        Settings {
            whole_dag: true,
            first_try: 1,
            max_tries: None,
            mapped_task_ids: mapped,
        }
    }

    fn summarize(instances: &[Instance]) -> Vec<String> {
        instances
            .iter()
            .map(|i| match (i.map_index, i.try_number) {
                (-1, None) => format!("{} {}", i.task_id, i.state),
                (-1, Some(t)) => format!("{}#{t} {}", i.task_id, i.state),
                (m, _) => format!("{}[{m}] {}", i.task_id, i.state),
            })
            .collect()
    }

    #[test]
    fn evaluates_trigger_rules() {
        let s = |states: &[&'static str]| states.iter().map(|s| (*s, false)).collect::<Vec<_>>();
        let cases: &[(&str, &[&'static str], Option<&str>)] = &[
            ("all_success", &["success", "success"], None),
            ("all_success", &["success", "skipped"], Some("skipped")),
            (
                "all_success",
                &["skipped", "failed"],
                Some("upstream_failed"),
            ),
            ("all_failed", &["failed", "upstream_failed"], None),
            ("all_failed", &["failed", "success"], Some("skipped")),
            ("all_done", &["failed", "skipped"], None),
            ("one_success", &["skipped", "skipped"], Some("skipped")),
            (
                "one_success",
                &["failed", "skipped"],
                Some("upstream_failed"),
            ),
            ("one_success", &["failed", "success"], None),
            ("one_failed", &["success"], Some("skipped")),
            ("one_failed", &["upstream_failed"], None),
            ("one_done", &["skipped"], Some("skipped")),
            ("none_failed", &["skipped", "success"], None),
            ("none_failed", &["upstream_failed"], Some("upstream_failed")),
            ("none_failed_min_one_success", &["skipped"], Some("skipped")),
            ("none_failed_min_one_success", &["skipped", "success"], None),
            ("none_skipped", &["skipped", "success"], Some("skipped")),
            ("all_skipped", &["skipped"], None),
            ("all_skipped", &["skipped", "success"], Some("skipped")),
            ("all_done_min_one_success", &["failed", "success"], None),
            (
                "all_done_min_one_success",
                &["failed"],
                Some("upstream_failed"),
            ),
            ("always", &["failed"], None),
        ];
        for (rule, states, want) in cases {
            assert_eq!(
                evaluate_trigger_rule(rule, &s(states)).unwrap(),
                *want,
                "{rule} {states:?}"
            );
        }
        let setup = [("failed", true), ("success", false)];
        assert_eq!(
            evaluate_trigger_rule("all_done_setup_success", &setup).unwrap(),
            Some("upstream_failed")
        );
        let setup = [("success", true), ("failed", false)];
        assert_eq!(
            evaluate_trigger_rule("all_done_setup_success", &setup).unwrap(),
            None
        );
        assert!(evaluate_trigger_rule("sometimes", &s(&["success"])).is_err());
        assert_eq!(evaluate_trigger_rule("all_failed", &[]).unwrap(), None);
    }

    #[test]
    fn runs_in_dag_order_once_upstreams_are_done() {
        let dag = dag(vec![
            task("c", &["a", "b"]),
            task("a", &[]),
            task("b", &["a"]),
        ]);
        let mapped = BTreeSet::new();
        let mut exec = FakeExec::default();
        exec.states.insert("b".into(), vec!["failed"]);
        let (instances, state) = run_dag(&dag, &whole(&mapped), &mut exec).unwrap();
        assert_eq!(
            summarize(&instances),
            ["a#1 success", "b#1 failed", "c upstream_failed"]
        );
        assert_eq!(state, DagRunState::Failed);
    }

    #[test]
    fn retries_until_max_tries() {
        let dag = dag(vec![TaskSpec {
            retries: Some(1),
            ..task("a", &[])
        }]);
        let mapped = BTreeSet::new();
        let mut exec = FakeExec::default();
        exec.states.insert("a".into(), vec!["up_for_retry"]);
        let (instances, state) = run_dag(&dag, &whole(&mapped), &mut exec).unwrap();
        assert_eq!(summarize(&instances), ["a#1 up_for_retry", "a#2 failed"]);
        assert_eq!(state, DagRunState::Failed);

        exec.states
            .insert("a".into(), vec!["up_for_retry", "success"]);
        let (instances, state) = run_dag(&dag, &whole(&mapped), &mut exec).unwrap();
        assert_eq!(summarize(&instances), ["a#1 up_for_retry", "a#2 success"]);
        assert_eq!(state, DagRunState::Success);
    }

    #[test]
    fn single_task_keeps_unfinished_states() {
        let dag = dag(vec![task("a", &[])]);
        let mapped = BTreeSet::new();
        let mut exec = FakeExec::default();
        exec.states.insert("a".into(), vec!["deferred"]);
        let settings = Settings {
            whole_dag: false,
            ..whole(&mapped)
        };
        let (instances, state) = run_dag(&dag, &settings, &mut exec).unwrap();
        assert_eq!(summarize(&instances), ["a#1 deferred"]);
        assert_eq!(state, DagRunState::Running);

        let (instances, state) = run_dag(&dag, &whole(&mapped), &mut exec).unwrap();
        assert_eq!(summarize(&instances), ["a#1 failed"]);
        assert_eq!(state, DagRunState::Failed);
    }

    #[test]
    fn follows_branch_skips() {
        let dag = dag(vec![
            task("branch", &[]),
            task("left", &["branch"]),
            task("right", &["branch"]),
            TaskSpec {
                trigger_rule: "none_failed_min_one_success".into(),
                ..task("join", &["left", "right"])
            },
        ]);
        let mapped = BTreeSet::new();
        let mut exec = FakeExec::default();
        exec.skips.insert("branch".into(), vec![json!("right")]);
        let (instances, state) = run_dag(&dag, &whole(&mapped), &mut exec).unwrap();
        assert_eq!(
            summarize(&instances),
            [
                "branch#1 success",
                "right skipped",
                "left#1 success",
                "join#1 success"
            ]
        );
        assert_eq!(state, DagRunState::Success);
    }

    #[test]
    fn expands_mapped_tasks_from_run_xcoms() {
        let mapped_spec = MappedSpec {
            expand_input: json!({"type": "dict-of-lists", "value": {"__type": "dict", "__var": {
                "x": {"__type": "xcomref", "__var": {"task_id": "up", "key": "return_value"}}}}}),
            partial_kwargs: json!({}),
            op_kwargs: false,
        };
        let dag = dag(vec![
            task("up", &[]),
            TaskSpec {
                mapped: Some(mapped_spec),
                arg_bindings: Some(vec![json!({"kind": "param", "name": "x"})]),
                ..task("m", &["up"])
            },
            task("after", &["m"]),
        ]);
        let mapped = dag.find_mapped_task_ids();
        let mut exec = FakeExec::default();
        exec.xcoms
            .insert(("up".into(), "return_value".into()), json!([5, 6]));
        exec.skips.insert("up".into(), vec![json!(["m", 1])]);
        let (instances, state) = run_dag(&dag, &whole(&mapped), &mut exec).unwrap();
        assert_eq!(
            summarize(&instances),
            [
                "up#1 success",
                "m[0] success",
                "m[1] skipped",
                "after skipped"
            ]
        );
        assert_eq!(
            exec.ran[1].3,
            Some(vec![json!({"kind": "literal", "name": "x", "value": 5})])
        );
        assert_eq!(exec.lengths["m"], 2);
        assert_eq!(state, DagRunState::Success);

        exec.xcoms.clear();
        exec.skips.clear();
        let (instances, _) = run_dag(&dag, &whole(&mapped), &mut exec).unwrap();
        assert_eq!(
            summarize(&instances),
            ["up#1 success", "m failed", "after upstream_failed"]
        );
        let settings = Settings {
            whole_dag: false,
            ..whole(&mapped)
        };
        assert!(run_dag(&dag, &settings, &mut exec).is_err());

        exec.xcoms
            .insert(("up".into(), "return_value".into()), json!([]));
        let (instances, _) = run_dag(&dag, &whole(&mapped), &mut exec).unwrap();
        assert_eq!(
            summarize(&instances),
            ["up#1 success", "m skipped", "after skipped"]
        );
    }

    #[test]
    fn ignores_teardowns_for_the_run_state() {
        let dag = dag(vec![
            TaskSpec {
                is_setup: true,
                ..task("setup", &[])
            },
            task("work", &["setup"]),
            TaskSpec {
                is_teardown: true,
                trigger_rule: "all_done_setup_success".into(),
                ..task("teardown", &["setup", "work"])
            },
        ]);
        let mapped = BTreeSet::new();
        let mut exec = FakeExec::default();
        exec.states.insert("teardown".into(), vec!["failed"]);
        let (_, state) = run_dag(&dag, &whole(&mapped), &mut exec).unwrap();
        assert_eq!(state, DagRunState::Success);

        exec.states.insert("work".into(), vec!["failed"]);
        exec.states.remove("teardown");
        let (instances, state) = run_dag(&dag, &whole(&mapped), &mut exec).unwrap();
        assert_eq!(
            summarize(&instances),
            ["setup#1 success", "work#1 failed", "teardown#1 success"]
        );
        assert_eq!(state, DagRunState::Failed);
    }
}
