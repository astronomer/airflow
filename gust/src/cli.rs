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
    #[arg(long = "dag", value_name = "DAG_ID")]
    pub dag_id: String,

    /// The task to run alone. Without it, the whole Dag runs.
    #[arg(long = "task", value_name = "TASK_ID")]
    pub task_id: Option<String>,

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
