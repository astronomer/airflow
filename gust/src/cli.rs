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

/// Run an Airflow Dag, or one task of it, against a mock supervisor.
///
/// gust starts the Dag file the way an Airflow worker does (with `--comm` and `--logs`), answers
/// its requests from `--input`, and prints what the tasks did.
#[derive(Debug, Parser)]
#[command(version, max_term_width = 100)]
pub struct Cli {
    /// The Dag file: an executable bundle, a `.min.mjs` built by airflow-ts-pack, a fat Jar, a
    /// `.py` or `.pyc` file, or a directory or zip file with `__main__.py`.
    pub dag_file: PathBuf,

    /// The program that runs the Dag file, such as `node`, `java -jar` or `python3`. The Dag file
    /// and the `--comm`/`--logs` arguments are added after it. Split like a shell command line.
    /// An executable bundle needs none.
    #[arg(long, value_name = "COMMAND", value_parser = parse_runtime)]
    pub runtime: Option<RuntimeCommand>,

    /// The Dag to run.
    #[arg(
        long = "dag",
        value_name = "DAG_ID",
        required_unless_present = "task_handler",
        conflicts_with = "task_handler"
    )]
    dag: Option<String>,

    /// The Dag id, from `--dag` or `--task-handler`.
    #[arg(skip)]
    pub dag_id: String,

    /// The task to run alone. Without it, the whole Dag runs.
    #[arg(long = "task", value_name = "TASK_ID", conflicts_with = "task_handler")]
    pub task_id: Option<String>,

    /// Run the task handler the Dag file declares for a stub task of a Python Dag, instead of a
    /// Dag of its own. The Dag and task ids are split at the first `/`, which a Dag id cannot
    /// contain. The task gets the arguments given as `args` in `--input`.
    #[arg(
        long = "task-handler",
        value_name = "DAG_ID/TASK_ID",
        value_parser = parse_task_handler,
        conflicts_with = "no_parse"
    )]
    pub task_handler: Option<TaskHandlerId>,

    /// Everything the tasks can see beyond the Dag file itself, as one JSON object: the Dag run,
    /// the task instance's try, Variables, Connections, XComs, asset events and state stores.
    /// Run `gust --help:input` for the format.
    #[arg(long, value_name = "JSON", value_parser = parse_input)]
    pub input: Option<Input>,

    /// Print the format of `--input`.
    // `main` answers this before parsing, since it takes no Dag file or `--dag`; declaring it here
    // lists it in `--help` and rejects it alongside other arguments.
    #[arg(long = "help:input", exclusive = true)]
    pub help_input: bool,

    /// Do not ask the Dag file for its Dags before running the task. The task then gets no
    /// TaskFlow argument bindings, retries, or execution timeout from its Dag.
    #[arg(long)]
    pub no_parse: bool,

    /// Seconds to wait for the Dag file's runtime to connect back.
    #[arg(long, default_value = "10", value_name = "SECONDS", value_parser = parse_seconds)]
    pub startup_timeout: Duration,

    /// Do not echo the task's log lines while it runs.
    #[arg(long, short)]
    pub quiet: bool,

    /// Print the summary as JSON on stdout.
    #[arg(long)]
    pub json: bool,
}

impl Cli {
    /// Parse the command line, and take the Dag and task ids from `--task-handler` if given.
    pub fn parse_args() -> Self {
        Self::parse().resolve()
    }

    fn resolve(mut self) -> Self {
        match &self.task_handler {
            Some(handler) => {
                self.dag_id.clone_from(&handler.dag_id);
                self.task_id = Some(handler.task_id.clone());
            }
            None => self.dag_id = self.dag.take().unwrap_or_default(),
        }
        self
    }
}

#[derive(Clone, Debug)]
pub struct TaskHandlerId {
    pub dag_id: String,
    pub task_id: String,
}

fn parse_task_handler(s: &str) -> Result<TaskHandlerId, String> {
    match s.split_once('/') {
        Some((dag_id, task_id)) if !dag_id.is_empty() && !task_id.is_empty() => Ok(TaskHandlerId {
            dag_id: dag_id.into(),
            task_id: task_id.into(),
        }),
        _ => Err(format!("expected DAG_ID/TASK_ID, got {s:?}")),
    }
}

/// The `--input` reference: the part of `docs/input.md` between the `input-help` markers.
pub fn find_input_help() -> &'static str {
    const INPUT_DOC: &str = include_str!("../docs/input.md");
    const START: &str = "<!-- input-help:start -->";
    let start = INPUT_DOC.find(START).map_or(0, |i| i + START.len());
    let end = INPUT_DOC[start..]
        .find("<!-- input-help:end -->")
        .map_or(INPUT_DOC.len(), |i| start + i);
    INPUT_DOC[start..end].trim()
}

/// Whether the command line is exactly `gust --help:input`.
pub fn is_input_help_request(args: impl IntoIterator<Item = std::ffi::OsString>) -> bool {
    let args: Vec<_> = args.into_iter().skip(1).collect();
    args.len() == 1 && args[0] == "--help:input"
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
    fn finds_the_input_help_section() {
        let help = find_input_help();
        assert!(
            help.starts_with("`--input` takes one JSON object"),
            "{help}"
        );
        assert!(help.ends_with("```"), "{help}");
        assert!(!help.contains("<!--"));
        assert!(help.lines().all(|l| l.chars().count() <= 80));
    }

    #[test]
    fn task_handler_names_the_dag_and_task() {
        let parse = |args: &[&str]| {
            Cli::try_parse_from(std::iter::once("gust").chain(args.iter().copied()))
                .map(Cli::resolve)
        };
        let cli = parse(&["b", "--task-handler", "d/g.t/odd"]).unwrap();
        assert_eq!(
            (cli.dag_id.as_str(), cli.task_id.as_deref()),
            ("d", Some("g.t/odd"))
        );
        let cli = parse(&["b", "--dag", "d"]).unwrap();
        assert_eq!((cli.dag_id.as_str(), cli.task_id), ("d", None));

        for args in [
            &["b", "--task-handler", "d/t", "--dag", "d"][..],
            &["b", "--task-handler", "d/t", "--task", "t"],
            &["b", "--task-handler", "d/t", "--no-parse"],
        ] {
            let err = parse(args).unwrap_err();
            assert_eq!(
                err.kind(),
                clap::error::ErrorKind::ArgumentConflict,
                "{args:?}"
            );
        }
        let err = parse(&["b"]).unwrap_err();
        assert_eq!(err.kind(), clap::error::ErrorKind::MissingRequiredArgument);
        for bad in ["d", "d/", "/t"] {
            let err = parse(&["b", "--task-handler", bad]).unwrap_err();
            assert_eq!(err.kind(), clap::error::ErrorKind::ValueValidation, "{bad}");
        }
    }

    #[test]
    fn answers_only_a_lone_input_help_flag() {
        let args = |a: &[&str]| a.iter().map(std::ffi::OsString::from).collect::<Vec<_>>();
        assert!(is_input_help_request(args(&["gust", "--help:input"])));
        assert!(!is_input_help_request(args(&["gust", "--help:input", "b"])));
        assert!(!is_input_help_request(args(&["gust", "b", "--dag", "d"])));
        let err = Cli::try_parse_from(["gust", "b", "--dag", "d", "--help:input"]).unwrap_err();
        assert_eq!(err.kind(), clap::error::ErrorKind::ArgumentConflict);
    }

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
