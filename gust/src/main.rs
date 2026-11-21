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

//! gust: test-run one task of an Airflow executable Dag bundle.

mod bundle;
mod cli;
mod dag;
mod frame;
mod input;
#[rustfmt::skip]
mod models;
mod runtime;
mod services;
mod summary;
mod timestamp;

use std::{ffi::OsString, path::Path, process::ExitCode, time::Instant};

use anyhow::{Context, Result, bail};
use clap::Parser;
use serde_json::Value as Json;
use uuid::Uuid;

use crate::{
    cli::Cli,
    dag::{Lookup, TaskSpec},
    frame::Reply,
    input::Input,
    runtime::{LogSink, Runtime},
    services::Services,
    summary::{ParseReport, Summary},
};

const BUNDLE_NAME: &str = "gust";

fn main() -> ExitCode {
    let cli = Cli::parse();
    match run(&cli) {
        Ok(summary) => {
            if cli.json {
                println!("{}", serde_json::to_string_pretty(&summary).unwrap());
            } else {
                summary.print();
            }
            if summary.state == "success" {
                ExitCode::SUCCESS
            } else {
                ExitCode::from(1)
            }
        }
        Err(e) => {
            eprintln!("gust: error: {e:#}");
            ExitCode::from(2)
        }
    }
}

fn run(cli: &Cli) -> Result<Summary> {
    let bundle_path = cli
        .bundle
        .canonicalize()
        .with_context(|| format!("cannot find bundle {}", cli.bundle.display()))?;
    let manifest = bundle::read_manifest(&bundle_path)?;
    let runtime_command = cli.runtime.as_ref().map(|r| r.0.clone());
    let mut command: Vec<OsString> = runtime_command
        .iter()
        .flatten()
        .map(OsString::from)
        .collect();
    command.push(bundle_path.clone().into());
    let mut notes = Vec::new();
    match &manifest {
        None if runtime_command.is_some() => {}
        None => notes.push("The file has no executable bundle trailer; it was run as a plain executable.".into()),
        Some(m) if m.sdk.supervisor_schema_version != models::SCHEMA_API_VERSION => notes.push(format!(
            "The bundle was built against supervisor schema {}, but gust speaks {} and does not migrate messages.",
            m.sdk.supervisor_schema_version,
            models::SCHEMA_API_VERSION,
        )),
        Some(_) => {}
    }

    let sink = LogSink::new(!cli.quiet);
    let input = match &cli.input {
        Some(input) => input.clone(),
        None => input::parse_input("{}").map_err(anyhow::Error::msg)?,
    };
    let mut services = Services::new(&input);

    let mut parse = ParseReport::default();
    let mut spec = TaskSpec::default();
    if !cli.no_parse {
        parse.performed = true;
        sink.set_phase("parse");
        services.phase = "parse";
        eprintln!("gust: asking {} for its Dags", bundle_path.display());
        match parse_dags(&bundle_path, &command, cli, &mut services, &sink)? {
            None => notes.push(
                "The bundle did not answer the Dag parse request; the task gets no argument bindings.".into(),
            ),
            Some(result) => {
                if let Some(Json::Object(errors)) = result.get("import_errors") {
                    for (file, error) in errors {
                        notes.push(format!("Import error in {file}: {}", error.as_str().unwrap_or_default()));
                    }
                }
                match dag::find_task(&result, &cli.dag_id, &cli.task_id) {
                    Lookup::Found(found) => {
                        parse.native_dag = true;
                        spec = found;
                    }
                    Lookup::NoTask { available } => bail!(
                        "Dag {:?} has no task {:?}; its tasks are: {}",
                        cli.dag_id,
                        cli.task_id,
                        available.join(", "),
                    ),
                    Lookup::NoDag { available } => {
                        let handler = manifest.as_ref().and_then(|m| m.dags.get(&cli.dag_id));
                        match handler {
                            Some(entry) if !entry.tasks.contains(&cli.task_id) => bail!(
                                "the bundle has no task handler for {}.{}; it handles: {}",
                                cli.dag_id,
                                cli.task_id,
                                entry.tasks.join(", "),
                            ),
                            Some(_) => notes.push(format!(
                                "{:?} is a Python Dag this bundle has task handlers for; its argument bindings live in the Python Dag file, so the task gets none.",
                                cli.dag_id,
                            )),
                            None if manifest.is_some() => {
                                let mut known = available;
                                known.extend(manifest.iter().flat_map(|m| m.dags.keys().cloned()));
                                bail!(
                                    "the bundle has no Dag {:?}; it knows: {}",
                                    cli.dag_id,
                                    if known.is_empty() { "nothing".into() } else { known.join(", ") },
                                )
                            }
                            None => notes.push(format!("The bundle's parse result has no Dag {:?}.", cli.dag_id)),
                        }
                    }
                }
            }
        }
    }
    parse.spec = (parse.native_dag).then(|| serde_json::to_value(&spec).unwrap());

    sink.set_phase("run");
    services.phase = "run";
    let started = Instant::now();
    let startup = build_startup(cli, &input, &bundle_path, &spec)?;
    let (run_id, logical_date) = (
        startup.ti.run_id.clone(),
        startup.ti_context.dag_run.logical_date,
    );
    eprintln!(
        "gust: running {}.{} (run {run_id})",
        cli.dag_id, cli.task_id
    );

    let mut runtime = Runtime::launch(&command, cli.startup_timeout, &sink)?;
    if let Some(timeout) = spec.execution_timeout {
        runtime.arm_timeout(timeout);
    }
    runtime.send(0, &Reply::body(&startup)?)?;
    loop {
        let frame = match runtime.read() {
            Ok(Some(frame)) => frame,
            Ok(None) => break,
            Err(e) => {
                notes.push(format!("The comm socket broke: {e:#}"));
                break;
            }
        };
        let Some(body) = frame.body.as_ref() else {
            continue;
        };
        let reply = services.handle(body)?;
        if frame.body_type() == Some("SetExecutionTimeout")
            && let Some(timeout) = services.record.execution_timeout
        {
            runtime.arm_timeout(timeout);
        }
        if let Err(e) = runtime.send(frame.id, &reply) {
            // A runtime may exit right after reporting its final state, without reading the ack.
            if services.record.terminal.is_none() {
                notes.push(format!("Could not answer the runtime: {e:#}"));
            }
            break;
        }
    }
    let exit = runtime.finish()?;
    let duration = started.elapsed();

    let state = if exit.timed_out {
        notes.push("The task ran past its execution timeout and was killed.".into());
        "failed".to_owned()
    } else if let Some(terminal) = &services.record.terminal {
        if matches!(
            terminal.type_.as_str(),
            "DeferTask" | "RescheduleTask" | "AwaitInputTask"
        ) {
            notes.push(format!(
                "The task sent {}; gust does not resume suspended tasks.",
                terminal.type_
            ));
        }
        terminal.state.clone()
    } else if exit.status.success() {
        "success".to_owned()
    } else {
        notes.push("The task reported no final state; it was derived from the exit code.".into());
        "failed".to_owned()
    };

    Ok(Summary {
        bundle: bundle_path,
        runtime: runtime_command,
        sdk: manifest.map(|m| m.sdk),
        dag_id: cli.dag_id.clone(),
        task_id: cli.task_id.clone(),
        run_id,
        logical_date,
        try_number: input.try_number,
        parse,
        state,
        exit_code: exit.status.code(),
        duration_secs: duration.as_secs_f64(),
        record: services.record,
        logs: sink.take(),
        notes,
    })
}

/// Ask the bundle for its Dags, as the Dag processor does, serving any requests it makes meanwhile.
fn parse_dags(
    bundle: &Path,
    command: &[OsString],
    cli: &Cli,
    services: &mut Services,
    sink: &LogSink,
) -> Result<Option<Json>> {
    let mut runtime = Runtime::launch(command, cli.startup_timeout, sink)?;
    let request = models::DagFileParseRequest {
        bundle_name: BUNDLE_NAME.into(),
        bundle_path: bundle
            .parent()
            .unwrap_or(Path::new("/"))
            .display()
            .to_string(),
        callback_requests: vec![],
        file: bundle.display().to_string(),
        type_: "DagFileParseRequest".into(),
    };
    runtime.send(0, &Reply::body(&request)?)?;
    let mut result = None;
    while let Ok(Some(frame)) = runtime.read() {
        let Some(body) = frame.body.as_ref() else {
            continue;
        };
        if frame.body_type() == Some("DagFileParsingResult") {
            result = Some(frame::to_json(body));
            break;
        }
        let reply = services.handle(body)?;
        if runtime.send(frame.id, &reply).is_err() {
            break;
        }
    }
    runtime.finish()?;
    Ok(result)
}

fn build_startup(
    cli: &Cli,
    input: &Input,
    bundle: &Path,
    spec: &TaskSpec,
) -> Result<models::StartupDetails> {
    let run = &input.dag_run;
    let arg_bindings = spec
        .arg_bindings
        .as_ref()
        .map(|b| serde_json::from_value(Json::Array(b.clone())))
        .transpose()
        .context("the bundle's argument bindings do not match the supervisor schema")?;
    let consumed_asset_events = input
        .asset_events
        .iter()
        .map(|e| models::AssetEventDagRunReference {
            asset: models::AssetReferenceAssetEventDagRun {
                extra: e.asset.extra.clone().into_iter().collect(),
                name: e.asset.name.clone(),
                uri: e.asset.uri.clone(),
            },
            extra: e.extra.clone().into_iter().collect(),
            partition_key: e.partition_key.clone(),
            source_aliases: e
                .aliases
                .iter()
                .map(|name| models::AssetAliasReferenceAssetEventDagRun { name: name.clone() })
                .collect(),
            source_dag_id: e.source_dag_id.clone(),
            source_map_index: e.source_map_index,
            source_run_id: e.source_run_id.clone(),
            source_task_id: e.source_task_id.clone(),
            timestamp: e.timestamp,
        })
        .collect();
    Ok(models::StartupDetails {
        bundle_info: models::BundleInfo {
            name: BUNDLE_NAME.into(),
            version: None,
            version_data: None,
        },
        dag_rel_path: bundle
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned(),
        sentry_integration: String::new(),
        start_date: run.start_date,
        ti: models::TaskInstance {
            context_carrier: None,
            dag_id: cli.dag_id.clone(),
            dag_version_id: Uuid::new_v4(),
            hostname: None,
            id: Uuid::new_v4(),
            map_index: -1,
            queue: spec.queue.clone().unwrap_or_else(|| "default".into()),
            region_id: None,
            region_index: None,
            run_id: run.run_id.clone(),
            task_id: cli.task_id.clone(),
            try_number: input.try_number,
        },
        ti_context: models::TiRunContext {
            arg_bindings,
            connections: vec![],
            dag_run: models::DagRun {
                clear_number: 0,
                conf: run.conf.clone(),
                consumed_asset_events,
                dag_id: cli.dag_id.clone(),
                data_interval_end: run.data_interval.map(|(_, end)| end),
                data_interval_start: run.data_interval.map(|(start, _)| start),
                end_date: None,
                logical_date: run.logical_date,
                note: run.note.clone(),
                partition_date: None,
                partition_key: run.partition_key.clone(),
                run_after: run.run_after,
                run_id: run.run_id.clone(),
                run_type: run.run_type,
                start_date: Some(run.start_date),
                state: models::DagRunState::Running,
                team_name: None,
                triggering_user_name: run.triggering_user.clone(),
            },
            execution_timeout: spec.execution_timeout,
            expanded_ti_count: None,
            first_task_reschedule_start_date: None,
            loop_: None,
            max_tries: input.max_tries.or(spec.retries).unwrap_or(0),
            multi_team: false,
            next_kwargs: models::NextKwargs::Null,
            next_method: None,
            should_retry: false,
            start_date: Some(run.start_date),
            task_reschedule_count: 0,
            variables: vec![],
            xcom_keys_to_clear: vec![],
        },
        type_: "StartupDetails".into(),
    })
}
