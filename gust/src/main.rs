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
mod expand;
mod frame;
mod input;
#[rustfmt::skip]
mod models;
mod runtime;
mod scheduler;
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
    dag::{DagSpec, Lookup, TaskSpec},
    expand::XComValues,
    frame::Reply,
    input::Input,
    runtime::{LogSink, Runtime},
    scheduler::{Executor, Settings, TiRun},
    services::Services,
    summary::{Instance, ParseReport, Summary},
    timestamp::Timestamp,
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
            if summary.dag_run.state == models::DagRunState::Success {
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
    let mut dag_spec: Option<DagSpec> = None;
    let mut known_dags: Vec<String> = Vec::new();
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
                match dag::find_dag(&result, &cli.dag_id) {
                    Lookup::Found(found) => {
                        parse.native_dag = true;
                        dag_spec = Some(found);
                    }
                    Lookup::NoDag { available } => {
                        known_dags.clone_from(&available);
                        let handler = manifest.as_ref().and_then(|m| m.dags.get(&cli.dag_id));
                        match (handler, &cli.task_id) {
                            (Some(entry), Some(task_id)) if !entry.tasks.contains(task_id) => bail!(
                                "the bundle has no task handler for {}.{task_id}; it handles: {}",
                                cli.dag_id,
                                entry.tasks.join(", "),
                            ),
                            (Some(_), Some(_)) => notes.push(format!(
                                "{:?} is a Python Dag this bundle has task handlers for; its argument bindings live in the Python Dag file, so the task gets none.",
                                cli.dag_id,
                            )),
                            (Some(_), None) => bail!(
                                "{:?} is a Python Dag this bundle has task handlers for; its tasks and edges live in the Python Dag file, so gust can only run one task of it at a time (give --task)",
                                cli.dag_id,
                            ),
                            (None, _) if manifest.is_some() => {
                                let mut known = available;
                                known.extend(manifest.iter().flat_map(|m| m.dags.keys().cloned()));
                                bail!(
                                    "the bundle has no Dag {:?}; it knows: {}",
                                    cli.dag_id,
                                    if known.is_empty() { "nothing".into() } else { known.join(", ") },
                                )
                            }
                            (None, _) => notes.push(format!("The bundle's parse result has no Dag {:?}.", cli.dag_id)),
                        }
                    }
                }
            }
        }
    }
    parse.requests = std::mem::take(&mut services.record.requests);
    let parse_logs = sink.take();

    let scope = match &cli.task_id {
        Some(task_id) => {
            let spec = match &dag_spec {
                Some(dag) => dag.get(task_id).cloned().with_context(|| {
                    format!(
                        "Dag {:?} has no task {task_id:?}; its tasks are: {}",
                        cli.dag_id,
                        dag.tasks
                            .iter()
                            .map(|t| t.task_id.as_str())
                            .collect::<Vec<_>>()
                            .join(", "),
                    )
                })?,
                None => TaskSpec::bare(task_id),
            };
            parse.spec = dag_spec
                .is_some()
                .then(|| serde_json::to_value(&spec).unwrap());
            spec.isolate()
        }
        None => {
            let Some(dag) = dag_spec.clone() else {
                if cli.no_parse {
                    bail!("--no-parse needs --task: gust learns a Dag's tasks by parsing it");
                }
                bail!(
                    "the bundle's parse result has no Dag {:?}, so gust does not know its tasks; it has: {}",
                    cli.dag_id,
                    if known_dags.is_empty() {
                        "nothing".into()
                    } else {
                        known_dags.join(", ")
                    },
                );
            };
            check_whole_dag_input(&input, &cli.dag_id)?;
            dag
        }
    };
    if let Some(task) = scope.tasks.iter().find(|t| t.in_mapped_group) {
        bail!(
            "{}.{} is in a mapped task group, which gust does not expand yet",
            cli.dag_id,
            task.task_id
        );
    }
    let mapped_task_ids = dag_spec
        .as_ref()
        .map(DagSpec::find_mapped_task_ids)
        .unwrap_or_default();
    services.set_mapped_tasks(&cli.dag_id, &mapped_task_ids);

    let dag_run = build_dag_run(cli, &input);
    match &cli.task_id {
        Some(task_id) => eprintln!(
            "gust: running {}.{task_id} (run {})",
            cli.dag_id, dag_run.run_id
        ),
        None => eprintln!(
            "gust: running Dag {} with {} task{} (run {})",
            cli.dag_id,
            scope.tasks.len(),
            if scope.tasks.len() == 1 { "" } else { "s" },
            dag_run.run_id,
        ),
    }
    let settings = Settings {
        whole_dag: cli.task_id.is_none(),
        first_try: input.try_number,
        max_tries: input.max_tries,
        mapped_task_ids: &mapped_task_ids,
    };
    let mut worker = Worker {
        cli,
        command: &command,
        bundle: &bundle_path,
        dag_run: &dag_run,
        services,
        sink: &sink,
    };
    let (instances, state) = scheduler::run_dag(&scope, &settings, &mut worker)?;
    let finished = matches!(
        state,
        models::DagRunState::Success | models::DagRunState::Failed
    );
    let dag_run = models::DagRun {
        state,
        end_date: finished.then(Timestamp::now),
        ..dag_run
    };

    Ok(Summary {
        bundle: bundle_path,
        runtime: runtime_command,
        sdk: manifest.map(|m| m.sdk),
        dag_id: cli.dag_id.clone(),
        task_id: cli.task_id.clone(),
        parse,
        dag_run,
        instances,
        logs: parse_logs,
        notes,
    })
}

/// In whole-Dag mode, the tries come from each task's retries, every task instance starts with
/// an empty state store, and the Dag's own XComs come from the run.
fn check_whole_dag_input(input: &Input, dag_id: &str) -> Result<()> {
    if input.ti_given {
        bail!(
            "\"ti\" sets one task instance's try, so it needs --task; a whole Dag run starts every task at try 1 with max_tries from its retries"
        );
    }
    if !input.task_state.is_empty() {
        bail!(
            "\"task_state\" is one task instance's store, so it needs --task; in a whole Dag run every task instance starts with an empty store"
        );
    }
    if let Some(x) = input.xcoms.iter().find(|x| x.dag_id == dag_id) {
        bail!(
            "\"xcoms\" has {dag_id}/{}, but a whole run of Dag {dag_id} gets its own tasks' XComs from the run; give only other Dags' XComs",
            x.task_id
        );
    }
    Ok(())
}

/// Runs task instances for the scheduler, each in its own runtime process.
struct Worker<'a> {
    cli: &'a Cli,
    command: &'a [OsString],
    bundle: &'a Path,
    dag_run: &'a models::DagRun,
    services: Services,
    sink: &'a LogSink,
}

impl Executor for Worker<'_> {
    fn run(&mut self, task: &TaskSpec, ti: TiRun) -> Result<Instance> {
        let mut phase = match &self.cli.task_id {
            Some(_) if ti.map_index < 0 => "run".to_owned(),
            Some(_) => String::new(),
            None => task.task_id.clone(),
        };
        if ti.map_index >= 0 {
            phase.push_str(&format!("[{}]", ti.map_index));
        }
        self.sink.set_phase(phase);
        self.services.phase = "run";
        self.services
            .begin_instance(&self.cli.dag_id, &task.task_id, ti.map_index, ti.try_number);
        let startup = build_startup(self.cli, self.bundle, self.dag_run, task, &ti)?;
        run_instance(
            self.cli,
            self.command,
            task,
            startup,
            ti,
            &mut self.services,
            self.sink,
        )
    }

    fn find_xcom_values(&self) -> XComValues {
        self.services.find_xcom_values(&self.cli.dag_id)
    }

    fn set_map_length(&mut self, task_id: &str, length: usize) {
        self.services
            .set_map_length(&self.cli.dag_id, task_id, length);
    }
}

/// Run one task instance try to the end, serving its requests.
fn run_instance(
    cli: &Cli,
    command: &[OsString],
    spec: &TaskSpec,
    startup: models::StartupDetails,
    ti: TiRun,
    services: &mut Services,
    sink: &LogSink,
) -> Result<Instance> {
    let mut notes = Vec::new();
    let started = Instant::now();
    let mut runtime = Runtime::launch(command, cli.startup_timeout, sink)?;
    if let Some(timeout) = spec.execution_timeout {
        runtime.arm_timeout(timeout);
    }
    let startup = match (&ti.bindings, ti.resolved) {
        (Some(bindings), true) => frame::encode_with_bindings(&startup, bindings)?,
        _ => Reply::body(&startup)?,
    };
    runtime.send(0, &startup)?;
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

    Ok(Instance {
        task_id: spec.task_id.clone(),
        map_index: ti.map_index,
        try_number: Some(ti.try_number),
        state,
        exit_code: exit.status.code(),
        duration_secs: Some(duration.as_secs_f64()),
        arg_bindings: ti.bindings,
        record: Some(std::mem::take(&mut services.record)),
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

fn build_dag_run(cli: &Cli, input: &Input) -> models::DagRun {
    let run = &input.dag_run;
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
    models::DagRun {
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
    }
}

fn build_startup(
    cli: &Cli,
    bundle: &Path,
    dag_run: &models::DagRun,
    spec: &TaskSpec,
    ti: &TiRun,
) -> Result<models::StartupDetails> {
    // Resolved bindings use ADR-0016 fields the supervisor schema does not have yet, so they are
    // written into the encoded message instead.
    let arg_bindings = match (&ti.bindings, ti.resolved) {
        (Some(b), false) => Some(
            serde_json::from_value(Json::Array(b.clone()))
                .context("the bundle's argument bindings do not match the supervisor schema")?,
        ),
        _ => None,
    };
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
        start_date: dag_run.start_date.unwrap_or_else(Timestamp::now),
        ti: models::TaskInstance {
            context_carrier: None,
            dag_id: cli.dag_id.clone(),
            dag_version_id: Uuid::new_v4(),
            hostname: None,
            id: Uuid::new_v4(),
            map_index: ti.map_index,
            queue: spec.queue.clone().unwrap_or_else(|| "default".into()),
            region_id: None,
            region_index: None,
            run_id: dag_run.run_id.clone(),
            task_id: spec.task_id.clone(),
            try_number: ti.try_number,
        },
        ti_context: models::TiRunContext {
            arg_bindings,
            connections: vec![],
            dag_run: dag_run.clone(),
            execution_timeout: spec.execution_timeout,
            expanded_ti_count: ti.expanded_ti_count,
            first_task_reschedule_start_date: None,
            loop_: None,
            max_tries: ti.max_tries,
            multi_team: false,
            next_kwargs: models::NextKwargs::Null,
            next_method: None,
            // As TaskInstance.is_eligible_to_retry decides it.
            should_retry: ti.max_tries > 0 && ti.try_number <= ti.max_tries,
            start_date: dag_run.start_date,
            task_reschedule_count: 0,
            variables: vec![],
            xcom_keys_to_clear: vec![],
        },
        type_: "StartupDetails".into(),
    })
}
