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

//! Launching a Dag file's runtime the way a coordinator does, and talking to it.

use std::{
    ffi::OsString,
    io::{BufRead, BufReader, ErrorKind, Read},
    net::{TcpListener, TcpStream},
    process::{Child, Command, ExitStatus, Stdio},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

use anyhow::{Context, Result, bail};
use serde::Serialize;
use serde_json::Value as Json;

use crate::frame::{self, Frame, Reply};

/// Config the runtime cannot read from Airflow, passed the way the coordinator passes it.
const RUNTIME_ENV_DEFAULTS: &[(&str, &str)] = &[
    ("AIRFLOW__LOGGING__LOGGING_LEVEL", "INFO"),
    ("AIRFLOW__LOGGING__NAMESPACE_LEVELS", ""),
    ("AIRFLOW__API__BASE_URL", "/"),
    ("AIRFLOW__OPERATORS__DEFAULT_DEFERRABLE", "False"),
    ("AIRFLOW__TRIGGERER__QUEUES_ENABLED", "False"),
    ("AIRFLOW__STATE_STORE__DEFAULT_RETENTION_DAYS", "30"),
];

/// Grace period after the execution timeout before the runtime is killed, as Airflow gives.
const KILL_GRACE: Duration = Duration::from_secs(5);
/// How long to wait for the runtime to exit once it closed the comm socket.
const EXIT_WAIT: Duration = Duration::from_secs(10);

#[derive(Clone, Debug, Serialize)]
pub struct LogLine {
    pub source: &'static str,
    pub level: String,
    pub event: String,
    #[serde(skip_serializing_if = "Json::is_null")]
    pub fields: Json,
}

#[derive(Clone)]
pub struct LogSink {
    lines: Arc<Mutex<Vec<LogLine>>>,
    echo: bool,
    phase: Arc<Mutex<String>>,
}

impl LogSink {
    pub fn new(echo: bool) -> Self {
        Self {
            lines: Arc::default(),
            echo,
            phase: Arc::new(Mutex::new("run".into())),
        }
    }

    pub fn set_phase(&self, phase: impl Into<String>) {
        *self.phase.lock().unwrap() = phase.into();
    }

    pub fn take(&self) -> Vec<LogLine> {
        std::mem::take(&mut self.lines.lock().unwrap())
    }

    fn push(&self, source: &'static str, raw: &str) {
        let line = match (source, serde_json::from_str::<Json>(raw)) {
            ("logs", Ok(Json::Object(mut map))) => {
                let level = map
                    .remove("level")
                    .and_then(|v| v.as_str().map(str::to_lowercase))
                    .unwrap_or_else(|| "info".into());
                let event = map
                    .remove("event")
                    .map(|v| v.as_str().map_or_else(|| v.to_string(), str::to_owned))
                    .unwrap_or_default();
                map.remove("timestamp");
                LogLine {
                    source,
                    level,
                    event,
                    fields: Json::Object(map),
                }
            }
            _ => LogLine {
                source,
                level: if source == "stderr" {
                    "stderr".into()
                } else {
                    "stdout".into()
                },
                event: raw.to_owned(),
                fields: Json::Null,
            },
        };
        if self.echo {
            let phase = self.phase.lock().unwrap().clone();
            eprintln!("{}", format_line(&phase, &line));
        }
        self.lines.lock().unwrap().push(line);
    }

    fn spawn_reader(
        &self,
        source: &'static str,
        reader: impl Read + Send + 'static,
    ) -> JoinHandle<()> {
        let sink = self.clone();
        thread::spawn(move || {
            for line in BufReader::new(reader).lines() {
                match line {
                    Ok(line) if line.trim().is_empty() => {}
                    Ok(line) => sink.push(source, &line),
                    Err(_) => break,
                }
            }
        })
    }
}

fn format_line(phase: &str, line: &LogLine) -> String {
    format!(
        "  {phase:>5} | {:<7} {}",
        line.level.to_uppercase(),
        line.describe()
    )
}

impl LogLine {
    /// The event followed by its fields, `logger` last.
    pub fn describe(&self) -> String {
        let mut out = self.event.clone();
        if let Json::Object(map) = &self.fields {
            for (k, v) in map {
                if k == "logger" {
                    continue;
                }
                let v = v.as_str().map_or_else(|| v.to_string(), str::to_owned);
                out.push_str(&format!(" {k}={v}"));
            }
            if let Some(Json::String(logger)) = map.get("logger") {
                out.push_str(&format!(" [{logger}]"));
            }
        }
        out
    }
}

/// A running Dag file process connected to this supervisor.
pub struct Runtime {
    child: Arc<Mutex<Child>>,
    comm: TcpStream,
    readers: Vec<JoinHandle<()>>,
    timed_out: Arc<AtomicBool>,
    deadline: Arc<Mutex<Option<Instant>>>,
    watchdog: Option<JoinHandle<()>>,
}

pub struct Exit {
    pub status: ExitStatus,
    pub timed_out: bool,
}

impl Runtime {
    /// Start `command` (the program, then its arguments) with `--comm` and `--logs` appended.
    pub fn launch(command: &[OsString], startup_timeout: Duration, sink: &LogSink) -> Result<Self> {
        let (program, args) = command
            .split_first()
            .context("the command to start the Dag file is empty")?;
        let comm_listener = TcpListener::bind("127.0.0.1:0")?;
        let logs_listener = TcpListener::bind("127.0.0.1:0")?;
        comm_listener.set_nonblocking(true)?;
        logs_listener.set_nonblocking(true)?;

        let mut command = Command::new(program);
        command
            .args(args)
            .arg(format!("--comm={}", comm_listener.local_addr()?))
            .arg(format!("--logs={}", logs_listener.local_addr()?))
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        for (key, value) in RUNTIME_ENV_DEFAULTS {
            if std::env::var_os(key).is_none() {
                command.env(key, value);
            }
        }
        let mut child = command
            .spawn()
            .with_context(|| format!("starting {}", program.to_string_lossy()))?;
        let mut readers = vec![
            sink.spawn_reader("stdout", child.stdout.take().unwrap()),
            sink.spawn_reader("stderr", child.stderr.take().unwrap()),
        ];

        let deadline = Instant::now() + startup_timeout;
        let (mut comm, mut logs) = (None, None);
        while comm.is_none() || logs.is_none() {
            for (listener, slot) in [(&comm_listener, &mut comm), (&logs_listener, &mut logs)] {
                if slot.is_some() {
                    continue;
                }
                match listener.accept() {
                    Ok((stream, _)) => *slot = Some(stream),
                    Err(e) if e.kind() == ErrorKind::WouldBlock => {}
                    Err(e) => return Err(e).context("accepting runtime connection"),
                }
            }
            if comm.is_some() && logs.is_some() {
                break;
            }
            if let Some(status) = child.try_wait()? {
                readers.drain(..).for_each(|r| drop(r.join()));
                bail!("the runtime exited ({status}) before connecting to the supervisor");
            }
            if Instant::now() > deadline {
                let _ = child.kill();
                let _ = child.wait();
                bail!("the runtime did not connect within {startup_timeout:?}");
            }
            thread::sleep(Duration::from_millis(20));
        }
        let (comm, logs) = (comm.unwrap(), logs.unwrap());
        comm.set_nonblocking(false)?;
        logs.set_nonblocking(false)?;
        readers.push(sink.spawn_reader("logs", logs));

        Ok(Self {
            child: Arc::new(Mutex::new(child)),
            comm,
            readers,
            timed_out: Arc::default(),
            deadline: Arc::default(),
            watchdog: None,
        })
    }

    pub fn send(&mut self, id: i64, reply: &Reply) -> Result<()> {
        frame::write_frame(&mut self.comm, id, reply)
    }

    pub fn read(&mut self) -> Result<Option<Frame>> {
        frame::read_frame(&mut self.comm)
    }

    /// Kill the runtime if it is still running `seconds` (plus a grace period) from now.
    /// Zero means no timeout; a later call replaces the deadline.
    pub fn arm_timeout(&mut self, seconds: f64) {
        *self.deadline.lock().unwrap() = (seconds != 0.0)
            .then(|| Instant::now() + Duration::from_secs_f64(seconds.max(0.0)) + KILL_GRACE);
        if self.watchdog.is_some() {
            return;
        }
        let (child, deadline, timed_out) = (
            self.child.clone(),
            self.deadline.clone(),
            self.timed_out.clone(),
        );
        self.watchdog = Some(thread::spawn(move || {
            loop {
                thread::sleep(Duration::from_millis(100));
                let mut child = child.lock().unwrap();
                if !matches!(child.try_wait(), Ok(None)) {
                    return;
                }
                if deadline.lock().unwrap().is_some_and(|d| Instant::now() > d) {
                    timed_out.store(true, Ordering::SeqCst);
                    let _ = child.kill();
                    return;
                }
            }
        }));
    }

    /// Wait for the runtime to exit and its output to drain.
    pub fn finish(mut self) -> Result<Exit> {
        let started = Instant::now();
        let status = loop {
            if let Some(status) = self.child.lock().unwrap().try_wait()? {
                break status;
            }
            if started.elapsed() > EXIT_WAIT {
                let mut child = self.child.lock().unwrap();
                let _ = child.kill();
                break child.wait()?;
            }
            thread::sleep(Duration::from_millis(20));
        };
        drop(self.comm);
        for reader in self.readers.drain(..) {
            let _ = reader.join();
        }
        if let Some(watchdog) = self.watchdog.take() {
            let _ = watchdog.join();
        }
        Ok(Exit {
            status,
            timed_out: self.timed_out.load(Ordering::SeqCst),
        })
    }
}
