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

//! The report printed after the task finishes.

use std::{collections::BTreeMap, path::PathBuf};

use serde::Serialize;
use serde_json::Value as Json;

use crate::{
    artifact::{Kind, Sdk},
    models::DagRun,
    runtime::LogLine,
    services::{Outcome, Record, RequestLog},
};

#[derive(Debug, Default, Serialize)]
pub struct ParseReport {
    pub performed: bool,
    pub spec: Option<Json>,
    pub requests: Vec<RequestLog>,
}

#[derive(Serialize)]
pub struct Summary {
    pub dag_file: PathBuf,
    pub kind: Kind,
    pub runtime: Option<Vec<String>>,
    pub sdk: Option<Sdk>,
    pub dag_id: String,
    /// The task run alone, or `None` when the whole Dag ran.
    pub task_id: Option<String>,
    pub parse: ParseReport,
    /// The Dag run as the tasks saw it, with its final state. When one task runs alone, the
    /// state is the one a Dag of only that task would end in.
    pub dag_run: DagRun,
    /// Every task instance of the run, in the order gust ran or decided it.
    pub instances: Vec<Instance>,
    /// Log lines from parsing the Dag file.
    pub logs: Vec<LogLine>,
    pub notes: Vec<String>,
}

/// One task instance try, or a task instance its trigger rule or a branch decided without
/// running it.
#[derive(Debug, Serialize)]
pub struct Instance {
    pub task_id: String,
    pub map_index: i64,
    /// `None` when the instance did not run.
    pub try_number: Option<i64>,
    pub state: String,
    pub exit_code: Option<i32>,
    /// `None` when the instance did not run.
    pub duration_secs: Option<f64>,
    /// The bindings sent to the runtime.
    pub arg_bindings: Option<Vec<Json>>,
    /// `None` when the instance did not run.
    pub record: Option<Record>,
    pub logs: Vec<LogLine>,
    pub notes: Vec<String>,
}

impl Instance {
    /// An instance decided without running.
    pub fn decided(task_id: &str, map_index: i64, state: &str, note: String) -> Self {
        Self {
            task_id: task_id.to_owned(),
            map_index,
            try_number: None,
            state: state.to_owned(),
            exit_code: None,
            duration_secs: None,
            arg_bindings: None,
            record: None,
            logs: vec![],
            notes: vec![note],
        }
    }
}

fn compact(value: &Json) -> String {
    let s = match value {
        Json::String(s) => format!("{s:?}"),
        other => other.to_string(),
    };
    if s.chars().count() > 120 {
        format!("{}…", s.chars().take(119).collect::<String>())
    } else {
        s
    }
}

fn heading(title: &str) {
    println!("\n{title}");
}

fn print_requests(requests: &[RequestLog]) {
    for r in requests {
        let outcome = match r.outcome {
            Outcome::Ok => "ok",
            Outcome::NotFound => "NOT FOUND",
            Outcome::Unsupported => "UNSUPPORTED",
            Outcome::Invalid => "INVALID",
        };
        println!("  {:<22} {:<40} {outcome}", r.type_, r.target);
    }
}

fn print_logs(logs: &[LogLine]) {
    let mut levels: BTreeMap<&str, usize> = BTreeMap::new();
    for line in logs {
        *levels.entry(line.level.as_str()).or_default() += 1;
    }
    if levels.is_empty() {
        return;
    }
    heading("Log lines");
    let counts: Vec<String> = levels.iter().map(|(l, n)| format!("{l}: {n}")).collect();
    println!("  {}", counts.join(", "));
    for line in logs
        .iter()
        .filter(|l| matches!(l.level.as_str(), "error" | "critical"))
    {
        println!("  ERROR {}", line.describe());
    }
}

fn print_notes(notes: &[String]) {
    if !notes.is_empty() {
        heading("Notes");
        for note in notes {
            println!("  - {note}");
        }
    }
}

fn print_binding(b: &Json) {
    let name = b.get("name").and_then(Json::as_str).unwrap_or("?");
    let flags: String = [
        ("apply_map", " (map() callables applied by the runtime)"),
        ("spread", " (spread into the arguments)"),
    ]
    .iter()
    .filter(|(key, _)| b.get(*key).and_then(Json::as_bool) == Some(true))
    .map(|(_, text)| *text)
    .collect();
    let task = || b.get("task_id").and_then(Json::as_str).unwrap_or("?");
    match b.get("kind").and_then(Json::as_str) {
        Some("xcom") => println!("  {name} <- XCom of task {}{flags}", task()),
        Some("sequence") => println!("  {name} <- every XCom of mapped task {}{flags}", task()),
        _ if b.get("spread").and_then(Json::as_bool) == Some(true) => println!(
            "  ** = {}{flags}",
            compact(b.get("value").unwrap_or(&Json::Null))
        ),
        _ => println!(
            "  {name} = {}{flags}",
            compact(b.get("value").unwrap_or(&Json::Null))
        ),
    }
}

impl Instance {
    fn print(&self) {
        let mut title = self.task_id.clone();
        if self.map_index >= 0 {
            title.push_str(&format!("[{}]", self.map_index));
        }
        if let Some(try_number) = self.try_number {
            title.push_str(&format!(", try {try_number}"));
        }
        println!(
            "\n── {title} {}",
            "─".repeat(50usize.saturating_sub(title.chars().count()))
        );
        println!("  state       {}", self.state.to_uppercase());
        let (Some(duration), Some(record)) = (self.duration_secs, &self.record) else {
            print_notes(&self.notes);
            return;
        };
        match self.exit_code {
            Some(code) => println!("  exit code   {code}"),
            None => println!("  exit code   (killed by signal)"),
        }
        println!("  duration    {duration:.2}s");

        if let Some(terminal) = &record.terminal {
            heading("Final message from the task");
            println!("  {} {}", terminal.type_, compact(&terminal.body));
        }

        if let Some(bindings) = &self.arg_bindings {
            heading("Arguments");
            bindings.iter().for_each(print_binding);
        }

        if !record.xcoms_pushed.is_empty() {
            heading("XComs pushed");
            for x in &record.xcoms_pushed {
                let index = if x.map_index >= 0 {
                    format!("[{}]", x.map_index)
                } else {
                    String::new()
                };
                println!(
                    "  {}/{}/{}{index} = {}",
                    x.dag_id,
                    x.task_id,
                    x.key,
                    compact(&x.value)
                );
            }
        }

        if !record.skipped_downstream.is_empty() {
            heading("Downstream tasks to skip");
            for task in &record.skipped_downstream {
                println!(
                    "  {}",
                    task.as_str()
                        .map_or_else(|| task.to_string(), str::to_owned)
                );
            }
        }

        if !record.variables_written.is_empty() {
            heading("Variables written");
            for (key, value) in &record.variables_written {
                match value {
                    Some(v) => println!("  {key} = {v:?}"),
                    None => println!("  {key} (deleted)"),
                }
            }
        }

        if !record.state_written.is_empty() {
            heading("State stores written");
            for write in &record.state_written {
                let store = match &write.asset {
                    Some(asset) => format!("asset {asset:?}"),
                    None => "task".into(),
                };
                match (&write.key, &write.value) {
                    (Some(key), Some(value)) => println!("  {store}: {key} = {}", compact(value)),
                    (Some(key), None) => println!("  {store}: {key} (deleted)"),
                    (None, _) => println!("  {store}: (cleared)"),
                }
            }
        }

        if let Some(fields) = record.rendered_fields.as_ref().and_then(Json::as_object)
            && !fields.is_empty()
        {
            heading("Rendered fields");
            for (k, v) in fields {
                println!("  {k} = {}", compact(v));
            }
        }
        if let Some(index) = &record.rendered_map_index {
            println!("\nRendered map index: {index}");
        }
        if record.secrets_masked > 0 {
            println!(
                "\nSecrets registered for masking: {}",
                record.secrets_masked
            );
        }

        if !record.requests.is_empty() {
            heading("Requests from the task");
            print_requests(&record.requests);
        }
        print_logs(&self.logs);
        print_notes(&self.notes);
    }
}

impl Summary {
    pub fn print(&self) {
        let rule = "─".repeat(60);
        println!("\n{rule}");
        match &self.task_id {
            Some(task_id) => println!("gust summary: {}.{task_id}", self.dag_id),
            None => println!("gust summary: Dag {}", self.dag_id),
        }
        println!("{rule}");
        println!(
            "  Dag run     {}",
            self.dag_run.state.to_string().to_uppercase()
        );
        let mut states: BTreeMap<&str, usize> = BTreeMap::new();
        for instance in &self.instances {
            *states.entry(instance.state.as_str()).or_default() += 1;
        }
        let counts: Vec<String> = states.iter().map(|(s, n)| format!("{n} {s}")).collect();
        println!(
            "  instances   {}",
            if counts.is_empty() {
                "none".into()
            } else {
                counts.join(", ")
            }
        );
        println!("  run id      {}", self.dag_run.run_id);
        if let Some(date) = &self.dag_run.logical_date {
            println!("  logical     {date}");
        }
        print!("  dag file    {}", self.dag_file.display());
        match &self.sdk {
            Some(sdk) => {
                let version = sdk
                    .version
                    .as_deref()
                    .map(|v| format!(" {v}"))
                    .unwrap_or_default();
                println!(
                    " ({} SDK{version}, schema {})",
                    sdk.language, sdk.supervisor_schema_version
                );
            }
            None => println!(
                " ({})",
                serde_json::to_value(self.kind).unwrap().as_str().unwrap()
            ),
        }
        if let Some(runtime) = &self.runtime {
            println!("  runtime     {}", runtime.join(" "));
        }

        if !self.parse.requests.is_empty() {
            heading("Requests while parsing");
            print_requests(&self.parse.requests);
        }
        print_logs(&self.logs);

        for instance in &self.instances {
            instance.print();
        }

        print_notes(&self.notes);
        println!();
    }
}
