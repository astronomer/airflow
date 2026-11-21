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

//! Command-line interface.

use std::{path::PathBuf, time::Duration};

use clap::Parser;

use crate::input::{Input, parse_input};

/// Run one task from an Airflow executable Dag bundle against a mock supervisor.
///
/// gust starts the bundle the way an Airflow worker does (with `--comm` and `--logs`), answers its
/// requests from `--input`, and prints what the task did.
#[derive(Debug, Parser)]
#[command(version, max_term_width = 100)]
pub struct Cli {
    /// Path to the bundle executable.
    pub bundle: PathBuf,

    /// The program that runs the bundle, such as `node` or `java -jar`. The bundle path and the
    /// `--comm`/`--logs` arguments are added after it. Split like a shell command line. Without
    /// it, the bundle is run directly.
    #[arg(long, value_name = "COMMAND", value_parser = parse_runtime)]
    pub runtime: Option<RuntimeCommand>,

    /// The Dag the task belongs to.
    #[arg(long = "dag", value_name = "DAG_ID")]
    pub dag_id: String,

    /// The task to run.
    #[arg(long = "task", value_name = "TASK_ID")]
    pub task_id: String,

    /// Everything the task can see beyond the bundle itself, as one JSON object: the Dag run,
    /// the task instance's try, Variables, Connections, XComs, asset events and state stores.
    /// The format is described in the README.
    #[arg(long, value_name = "JSON", value_parser = parse_input)]
    pub input: Option<Input>,

    /// Do not ask the bundle for its Dags before running the task. The task then gets no
    /// TaskFlow argument bindings, retries, or execution timeout from its Dag.
    #[arg(long)]
    pub no_parse: bool,

    /// Seconds to wait for the bundle to connect back.
    #[arg(long, default_value = "10", value_name = "SECONDS", value_parser = parse_seconds)]
    pub startup_timeout: Duration,

    /// Do not echo the task's log lines while it runs.
    #[arg(long, short)]
    pub quiet: bool,

    /// Print the summary as JSON on stdout.
    #[arg(long)]
    pub json: bool,
}

#[derive(Clone, Debug)]
pub struct RuntimeCommand(pub Vec<String>);

fn parse_runtime(s: &str) -> Result<RuntimeCommand, String> {
    match shlex::split(s) {
        Some(words) if !words.is_empty() => Ok(RuntimeCommand(words)),
        Some(_) => Err("the runtime command is empty".into()),
        None => Err("the runtime command has an unclosed quote".into()),
    }
}

fn parse_seconds(s: &str) -> Result<Duration, String> {
    s.parse::<f64>()
        .ok()
        .and_then(|secs| Duration::try_from_secs_f64(secs).ok())
        .ok_or_else(|| format!("invalid number of seconds: {s:?}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_splits_like_a_shell() {
        assert_eq!(
            parse_runtime(r#"java -Dx="a b" -jar"#).unwrap().0,
            ["java", "-Dx=a b", "-jar"]
        );
        assert!(parse_runtime("  ").is_err());
        assert!(parse_runtime("node 'x").is_err());
    }
}
