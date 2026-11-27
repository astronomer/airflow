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

//! The mock supervisor services: answers the runtime's requests from the command-line inputs and
//! records everything the runtime sends.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use anyhow::{Result, bail};
use rmpv::Value;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value as Json, json};

use crate::{
    frame::{self, Reply},
    input::{self, Asset, AssetEvent, ConnInput, Input},
    models,
    timestamp::Timestamp,
};

const TERMINAL_MESSAGES: &[&str] = &[
    "SucceedTask",
    "TaskState",
    "RetryTask",
    "DeferTask",
    "RescheduleTask",
    "AwaitInputTask",
];

#[derive(Debug, Serialize)]
pub struct RequestLog {
    pub phase: &'static str,
    #[serde(rename = "type")]
    pub type_: String,
    pub target: String,
    pub outcome: Outcome,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Outcome {
    Ok,
    NotFound,
    Unsupported,
    Invalid,
}

#[derive(Debug, Serialize)]
pub struct PushedXCom {
    pub dag_id: String,
    pub task_id: String,
    pub key: String,
    pub map_index: i64,
    pub value: Json,
}

#[derive(Debug, Serialize)]
pub struct TerminalMessage {
    #[serde(rename = "type")]
    pub type_: String,
    pub state: String,
    pub body: Json,
}

/// Everything the runtime sent, for the summary.
#[derive(Debug, Default, Serialize)]
pub struct Record {
    pub requests: Vec<RequestLog>,
    pub xcoms_pushed: Vec<PushedXCom>,
    /// Variables written (`Some`) or deleted (`None`), in order.
    pub variables_written: Vec<(String, Option<String>)>,
    pub rendered_fields: Option<Json>,
    pub rendered_map_index: Option<String>,
    pub execution_timeout: Option<f64>,
    /// Tasks a branching task asked to skip, as task ids or `[task_id, map_index]`.
    pub skipped_downstream: Vec<Json>,
    pub secrets_masked: usize,
    pub state_written: Vec<StateWrite>,
    pub terminal: Option<TerminalMessage>,
}

/// A write to a state store: `key` is `None` when the whole store was cleared, and `value` is
/// `None` when the key was deleted.
#[derive(Debug, Serialize)]
pub struct StateWrite {
    /// `None` for the task's own store, else the asset's name.
    pub asset: Option<String>,
    pub key: Option<String>,
    pub value: Option<Json>,
}

/// The fields of the state store requests, which differ only in which of them they carry.
#[derive(Deserialize)]
struct StoreRequest {
    name: Option<String>,
    uri: Option<String>,
    key: Option<String>,
    value: Option<Json>,
}

/// The fields of the XCom sequence requests, which differ only in which of them they carry.
#[derive(Deserialize)]
struct SequenceRequest {
    dag_id: String,
    task_id: String,
    run_id: Option<String>,
    key: String,
    offset: Option<i64>,
    start: Option<i64>,
    stop: Option<i64>,
    step: Option<i64>,
}

/// The indexes `items[start:stop:step]` takes in Python, for a sequence of `len` items. A step of
/// 0 counts as 1, as the Execution API does.
fn slice_indexes(
    len: usize,
    start: Option<i64>,
    stop: Option<i64>,
    step: Option<i64>,
) -> Vec<usize> {
    let len = len as i64;
    let step = step.filter(|s| *s != 0).unwrap_or(1);
    let (lower, upper) = if step > 0 { (0, len) } else { (-1, len - 1) };
    let clamp = |bound: Option<i64>, default: i64| match bound {
        None => default,
        Some(b) if b < 0 => (b + len).max(lower),
        Some(b) => b.min(upper),
    };
    let start = clamp(start, if step > 0 { lower } else { upper });
    let stop = clamp(stop, if step > 0 { upper } else { lower });
    let mut indexes = Vec::new();
    let mut i = start;
    while (step > 0 && i < stop) || (step < 0 && i > stop) {
        indexes.push(i as usize);
        i += step;
    }
    indexes
}

/// The filters shared by the asset event requests.
struct EventFilter {
    after: Option<Timestamp>,
    before: Option<Timestamp>,
    partition_key: Option<String>,
    partition_key_regexp_pattern: Option<String>,
    extra: Option<HashMap<String, String>>,
    ascending: bool,
    limit: Option<i64>,
}

/// An XCom row: Dag, task, key and map index. Values from `--input` are at map index -1.
type XComKey = (String, String, String, i64);

pub struct Services {
    variables: BTreeMap<String, String>,
    connections: BTreeMap<String, ConnInput>,
    xcoms: BTreeMap<XComKey, Json>,
    /// `(dag_id, task_id)` of the tasks the parsed Dag maps.
    mapped_tasks: BTreeSet<(String, String)>,
    /// How many instances each mapped task of this run expanded to, by `(dag_id, task_id)`.
    map_lengths: BTreeMap<(String, String), usize>,
    /// The task instance being run: task id and map index.
    current: (String, i64),
    map_index: i64,
    /// The try each task instance last ran, to clear its XComs when it runs again.
    tries: BTreeMap<(String, i64), i64>,
    /// The store every task instance starts with.
    initial_task_state: BTreeMap<String, Json>,
    /// The current task instance's store; the others' are in `task_states`.
    task_state: BTreeMap<String, Json>,
    task_states: BTreeMap<(String, i64), BTreeMap<String, Json>>,
    asset_state: BTreeMap<String, BTreeMap<String, Json>>,
    assets: Vec<Asset>,
    asset_events: Vec<AssetEvent>,
    pub phase: &'static str,
    pub record: Record,
}

fn typed(name: &str) -> String {
    name.to_owned()
}

fn optional_values(map: &Map<String, Json>) -> HashMap<String, Option<Json>> {
    map.iter()
        .map(|(k, v)| (k.clone(), Some(v.clone())))
        .collect()
}

/// The Python supervisor answers state store writes with `OKResponse` rather than an empty ack.
fn ok_response() -> Result<Reply> {
    Reply::body(&models::OkResponse {
        ok: true,
        type_: typed("OKResponse"),
    })
}

fn asset_result(asset: &Asset) -> models::AssetResult {
    models::AssetResult {
        extra: Some(optional_values(&asset.extra)),
        group: asset.group.clone(),
        name: asset.name.clone(),
        uri: asset.uri.clone(),
        type_: typed("AssetResult"),
    }
}

fn not_found(error: models::ErrorType, detail: Json) -> Result<Reply> {
    let detail = match detail {
        Json::Object(map) => Some(map),
        _ => None,
    };
    Reply::error(&models::ErrorResponse {
        detail,
        error,
        type_: typed("ErrorResponse"),
    })
}

impl Services {
    pub fn new(input: &Input) -> Self {
        Self {
            variables: input.variables.iter().cloned().collect(),
            connections: input
                .connections
                .iter()
                .map(|c| (c.conn_id.clone(), c.clone()))
                .collect(),
            mapped_tasks: BTreeSet::new(),
            map_lengths: BTreeMap::new(),
            current: (String::new(), -1),
            map_index: -1,
            tries: BTreeMap::new(),
            initial_task_state: input.task_state.clone(),
            task_state: input.task_state.clone(),
            task_states: BTreeMap::new(),
            asset_state: input
                .asset_state
                .iter()
                .map(|(asset, store)| (asset.clone(), store.clone().into_iter().collect()))
                .collect(),
            assets: input.assets.clone(),
            asset_events: input.asset_events.clone(),
            xcoms: input
                .xcoms
                .iter()
                .map(|x| {
                    (
                        (x.dag_id.clone(), x.task_id.clone(), x.key.clone(), -1),
                        x.value.clone(),
                    )
                })
                .collect(),
            phase: "run",
            record: Record::default(),
        }
    }

    pub fn set_mapped_tasks(&mut self, dag_id: &str, task_ids: &BTreeSet<String>) {
        self.mapped_tasks = task_ids
            .iter()
            .map(|t| (dag_id.to_owned(), t.clone()))
            .collect();
    }

    pub fn set_map_length(&mut self, dag_id: &str, task_id: &str, length: usize) {
        self.map_lengths
            .insert((dag_id.to_owned(), task_id.to_owned()), length);
    }

    /// Start serving a try of a task instance of `dag_id`, with a fresh record. Each task
    /// instance keeps its own task state store across tries, starting from `--input`'s; a try
    /// after the first starts without the XComs the earlier one pushed.
    pub fn begin_instance(&mut self, dag_id: &str, task_id: &str, map_index: i64, try_number: i64) {
        let key = (task_id.to_owned(), map_index);
        let store = std::mem::take(&mut self.task_state);
        self.task_states
            .insert(std::mem::replace(&mut self.current, key.clone()), store);
        self.task_state = self
            .task_states
            .remove(&key)
            .unwrap_or_else(|| self.initial_task_state.clone());
        if self
            .tries
            .insert(key, try_number)
            .is_some_and(|previous| previous != try_number)
        {
            self.xcoms
                .retain(|(d, t, _, i), _| !(d == dag_id && t == task_id && *i == map_index));
        }
        self.map_index = map_index;
        self.record = Record::default();
    }

    /// A task's whole output for `key`: the value at map index -1, or for a mapped task that ran
    /// in this run, every instance's value in map index order (`null` for one that pushed none).
    fn find_whole(&self, dag_id: &str, task_id: &str, key: &str) -> Option<Json> {
        let row = |index: i64| {
            self.xcoms
                .get(&(dag_id.to_owned(), task_id.to_owned(), key.to_owned(), index))
        };
        if let Some(value) = row(-1) {
            return Some(value.clone());
        }
        let length = *self
            .map_lengths
            .get(&(dag_id.to_owned(), task_id.to_owned()))?;
        let values: Vec<Option<&Json>> = (0..length as i64).map(row).collect();
        values.iter().any(Option::is_some).then(|| {
            Json::Array(
                values
                    .into_iter()
                    .map(|v| v.cloned().unwrap_or(Json::Null))
                    .collect(),
            )
        })
    }

    /// Every XCom of `dag_id`, whole, by `(task_id, key)`.
    pub fn find_xcom_values(&self, dag_id: &str) -> crate::expand::XComValues {
        let keys: BTreeSet<(String, String)> = self
            .xcoms
            .keys()
            .filter(|(d, ..)| d == dag_id)
            .map(|(_, t, k, _)| (t.clone(), k.clone()))
            .collect();
        keys.into_iter()
            .filter_map(|(t, k)| {
                let value = self.find_whole(dag_id, &t, &k)?;
                Some(((t, k), value))
            })
            .collect()
    }

    /// Read an XCom row. A mapped task's value from `--input` is an array of its instances'
    /// values, so a map index picks an element of it. Inputs are not tied to a run or a map
    /// index otherwise, so an unmapped task's value answers any map index.
    fn find_xcom(&self, dag_id: &str, task_id: &str, key: &str, map_index: i64) -> Option<Json> {
        let row = |index: i64| {
            self.xcoms
                .get(&(dag_id.to_owned(), task_id.to_owned(), key.to_owned(), index))
        };
        if let Some(value) = row(map_index) {
            return Some(value.clone());
        }
        if map_index < 0 {
            return self.find_whole(dag_id, task_id, key);
        }
        let whole = row(-1)?;
        if !self
            .mapped_tasks
            .contains(&(dag_id.to_owned(), task_id.to_owned()))
        {
            return Some(whole.clone());
        }
        whole.as_array()?.get(map_index as usize).cloned()
    }

    fn log(&mut self, type_: &str, target: impl Into<String>, outcome: Outcome) {
        self.record.requests.push(RequestLog {
            phase: self.phase,
            type_: type_.to_owned(),
            target: target.into(),
            outcome,
        });
    }

    /// Serve a task (`asset` is `None`) or asset state store request.
    fn handle_store(
        &mut self,
        type_: &str,
        asset: Option<String>,
        msg: StoreRequest,
    ) -> Result<Reply> {
        use models::ErrorType::*;
        let op = ["Get", "Set", "Delete", "Clear"]
            .into_iter()
            .find(|op| type_.starts_with(op))
            .unwrap_or_default();
        let target = match (&asset, &msg.key) {
            (Some(a), Some(k)) => format!("{a}/{k}"),
            (Some(a), None) => format!("{a}/*"),
            (None, Some(k)) => k.clone(),
            (None, None) => "*".into(),
        };
        let store = match &asset {
            None => &mut self.task_state,
            Some(name) => self.asset_state.entry(name.clone()).or_default(),
        };
        let (outcome, reply, write) = match (op, msg.key) {
            ("Get", Some(key)) => match (store.get(&key).cloned(), &asset) {
                (Some(value), Some(_)) => (
                    Outcome::Ok,
                    Reply::body(&models::AssetStateStoreResult {
                        value: Some(value),
                        type_: typed("AssetStateStoreResult"),
                    }),
                    None,
                ),
                (Some(value), None) => (
                    Outcome::Ok,
                    Reply::body(&models::TaskStateStoreResult {
                        value: Some(value),
                        type_: typed("TaskStateStoreResult"),
                    }),
                    None,
                ),
                (None, Some(name)) => (
                    Outcome::NotFound,
                    not_found(AssetStoreNotFound, json!({"name": name, "key": key})),
                    None,
                ),
                (None, None) => (
                    Outcome::NotFound,
                    not_found(TaskStoreNotFound, json!({"key": key})),
                    None,
                ),
            },
            ("Set", Some(key)) => {
                let value = msg.value.unwrap_or(Json::Null);
                store.insert(key.clone(), value.clone());
                (Outcome::Ok, ok_response(), Some((Some(key), Some(value))))
            }
            ("Delete", Some(key)) => {
                store.remove(&key);
                (Outcome::Ok, ok_response(), Some((Some(key), None)))
            }
            ("Clear", None) => {
                store.clear();
                (Outcome::Ok, ok_response(), Some((None, None)))
            }
            _ => bail!("{type_} has no key"),
        };
        self.log(type_, target, outcome);
        if let Some((key, value)) = write {
            self.record
                .state_written
                .push(StateWrite { asset, key, value });
        }
        reply
    }

    /// Return the stored asset events that `matches` accepts and `filter` lets through.
    fn find_events(
        &self,
        filter: &EventFilter,
        matches: impl Fn(&AssetEvent) -> bool,
    ) -> Result<models::AssetEventsResult> {
        let pattern = filter
            .partition_key_regexp_pattern
            .as_deref()
            .map(regress::Regex::new)
            .transpose()
            .map_err(|e| anyhow::anyhow!("invalid partition_key_regexp_pattern: {e}"))?;
        let mut events: Vec<&AssetEvent> = self
            .asset_events
            .iter()
            .filter(|e| matches(e))
            .filter(|e| filter.after.is_none_or(|t| e.timestamp >= t))
            .filter(|e| filter.before.is_none_or(|t| e.timestamp <= t))
            .filter(|e| {
                filter
                    .partition_key
                    .as_ref()
                    .is_none_or(|k| e.partition_key.as_ref() == Some(k))
            })
            .filter(|e| {
                pattern.as_ref().is_none_or(|p| {
                    e.partition_key
                        .as_deref()
                        .is_some_and(|k| p.find(k).is_some())
                })
            })
            .filter(|e| {
                filter
                    .extra
                    .iter()
                    .flatten()
                    .all(|(k, v)| match e.extra.get(k) {
                        Some(Json::String(s)) => s == v,
                        Some(other) => serde_json::to_string(other).is_ok_and(|text| text == *v),
                        None => false,
                    })
            })
            .collect();
        events.sort_by_key(|e| (e.timestamp, e.id));
        if !filter.ascending {
            events.reverse();
        }
        if let Some(limit) = filter.limit {
            events.truncate(limit.max(0) as usize);
        }
        Ok(models::AssetEventsResult {
            asset_events: events
                .into_iter()
                .map(|e| models::AssetEventResponse {
                    asset: models::AssetResponse {
                        extra: Some(optional_values(&e.asset.extra)),
                        group: e.asset.group.clone(),
                        name: e.asset.name.clone(),
                        uri: e.asset.uri.clone(),
                    },
                    created_dagruns: vec![],
                    extra: Some(optional_values(&e.extra)),
                    id: e.id,
                    partition_key: e.partition_key.clone(),
                    source_dag_id: e.source_dag_id.clone(),
                    source_map_index: e.source_map_index,
                    source_run_id: e.source_run_id.clone(),
                    source_task_id: e.source_task_id.clone(),
                    timestamp: e.timestamp,
                })
                .collect(),
            type_: typed("AssetEventsResult"),
        })
    }

    /// Answer one request from the runtime.
    pub fn handle(&mut self, body: &Value) -> Result<Reply> {
        let type_ = frame::type_of(body).unwrap_or("<untyped>").to_owned();
        match self.dispatch(&type_, body) {
            Ok(reply) => Ok(reply),
            Err(e) => {
                self.log(&type_, format!("{e:#}"), Outcome::Invalid);
                Reply::error(&models::ErrorResponse {
                    detail: json!({"status_code": null, "message": format!("Unable to decode message: {e:#}")})
                        .as_object()
                        .cloned(),
                    error: models::ErrorType::GenericError,
                    type_: typed("ErrorResponse"),
                })
            }
        }
    }

    fn dispatch(&mut self, type_: &str, body: &Value) -> Result<Reply> {
        use models::ErrorType::*;
        match type_ {
            "GetVariable" => {
                let msg: models::GetVariable = frame::decode(body)?;
                match self.variables.get(&msg.key).cloned() {
                    Some(value) => {
                        self.log(type_, &msg.key, Outcome::Ok);
                        Reply::body(&models::VariableResult {
                            key: msg.key,
                            value,
                            type_: typed("VariableResult"),
                        })
                    }
                    None => {
                        self.log(type_, &msg.key, Outcome::NotFound);
                        not_found(VariableNotFound, json!({"key": msg.key}))
                    }
                }
            }
            "GetVariableKeys" => {
                let msg: models::GetVariableKeys = frame::decode(body)?;
                let prefix = msg.prefix.unwrap_or_default();
                let matching: Vec<String> = self
                    .variables
                    .keys()
                    .filter(|k| k.starts_with(&prefix))
                    .cloned()
                    .collect();
                self.log(type_, format!("{prefix}*"), Outcome::Ok);
                Reply::body(&models::VariableKeysResult {
                    total_entries: matching.len() as i64,
                    keys: matching
                        .into_iter()
                        .skip(msg.offset.max(0) as usize)
                        .take(msg.limit.max(0) as usize)
                        .collect(),
                    type_: typed("VariableKeysResult"),
                })
            }
            "PutVariable" => {
                let msg: models::PutVariable = frame::decode(body)?;
                self.log(type_, &msg.key, Outcome::Ok);
                self.variables.insert(msg.key.clone(), msg.value.clone());
                self.record
                    .variables_written
                    .push((msg.key, Some(msg.value)));
                Ok(Reply::Ack)
            }
            "DeleteVariable" => {
                let msg: models::DeleteVariable = frame::decode(body)?;
                self.log(type_, &msg.key, Outcome::Ok);
                self.variables.remove(&msg.key);
                self.record.variables_written.push((msg.key, None));
                Ok(Reply::Ack)
            }
            "GetConnection" => {
                let msg: models::GetConnection = frame::decode(body)?;
                match self.connections.get(&msg.conn_id).cloned() {
                    Some(c) => {
                        self.log(type_, &msg.conn_id, Outcome::Ok);
                        Reply::body(&models::ConnectionResult {
                            conn_id: c.conn_id.clone(),
                            conn_type: c.conn_type.clone(),
                            host: c.host.clone(),
                            schema: c.schema.clone(),
                            login: c.login.clone(),
                            password: c.password.clone(),
                            port: c.port,
                            extra: c.extra.clone(),
                            type_: typed("ConnectionResult"),
                        })
                    }
                    None => {
                        self.log(type_, &msg.conn_id, Outcome::NotFound);
                        not_found(ConnectionNotFound, json!({"conn_id": msg.conn_id}))
                    }
                }
            }
            "GetXCom" => {
                let msg: models::GetXCom = frame::decode(body)?;
                let map_index = msg.map_index.unwrap_or(-1);
                let mut target = format!("{}/{}/{}", msg.dag_id, msg.task_id, msg.key);
                if map_index >= 0 {
                    target.push_str(&format!("[{map_index}]"));
                }
                match self.find_xcom(&msg.dag_id, &msg.task_id, &msg.key, map_index) {
                    Some(value) => {
                        self.log(type_, target, Outcome::Ok);
                        Reply::body(&models::XComResult {
                            key: msg.key,
                            value: Some(value),
                            type_: typed("XComResult"),
                        })
                    }
                    None => {
                        self.log(type_, target, Outcome::NotFound);
                        not_found(
                            XcomNotFound,
                            json!({"dag_id": msg.dag_id, "task_id": msg.task_id, "key": msg.key, "map_index": map_index}),
                        )
                    }
                }
            }
            "GetXComCount" | "GetXComSequenceItem" | "GetXComSequenceSlice" => {
                let msg: SequenceRequest = frame::decode(body)?;
                let target = format!("{}/{}/{}", msg.dag_id, msg.task_id, msg.key);
                let items = match self.find_whole(&msg.dag_id, &msg.task_id, &msg.key) {
                    None => None,
                    Some(Json::Array(items)) => Some(items),
                    Some(_) => {
                        self.log(type_, target.clone(), Outcome::Invalid);
                        return Reply::error(&models::ErrorResponse {
                            detail: json!({"message": format!(
                                "{target} is not a JSON array; gust reads a mapped task's XComs as an array of its map indexes' values"
                            )})
                            .as_object()
                            .cloned(),
                            error: GenericError,
                            type_: typed("ErrorResponse"),
                        });
                    }
                };
                let outcome = if items.is_some() {
                    Outcome::Ok
                } else {
                    Outcome::NotFound
                };
                let items = items.unwrap_or_default();
                match type_ {
                    "GetXComCount" => {
                        self.log(type_, target, outcome);
                        Reply::body(&models::XComCountResponse {
                            len: items.len() as i64,
                            type_: typed("XComCountResponse"),
                        })
                    }
                    "GetXComSequenceItem" => {
                        let offset = msg.offset.unwrap_or_default();
                        let target = format!("{target}[{offset}]");
                        let index = if offset < 0 {
                            items.len() as i64 + offset
                        } else {
                            offset
                        };
                        match usize::try_from(index).ok().filter(|&i| i < items.len()) {
                            Some(index) => {
                                self.log(type_, target, Outcome::Ok);
                                Reply::body(&models::XComSequenceIndexResult {
                                    root: items[index].clone(),
                                    type_: typed("XComSequenceIndexResult"),
                                })
                            }
                            _ => {
                                self.log(type_, target, Outcome::NotFound);
                                // Airflow answers with the error as the body, and the Python
                                // Task SDK stops iterating a mapped task's results on it.
                                Reply::body(&models::ErrorResponse {
                                    detail: json!({"dag_id": msg.dag_id, "run_id": msg.run_id, "task_id": msg.task_id, "key": msg.key, "offset": offset})
                                        .as_object()
                                        .cloned(),
                                    error: XcomNotFound,
                                    type_: typed("ErrorResponse"),
                                })
                            }
                        }
                    }
                    _ => {
                        self.log(type_, target, outcome);
                        Reply::body(&models::XComSequenceSliceResult {
                            root: slice_indexes(items.len(), msg.start, msg.stop, msg.step)
                                .into_iter()
                                .map(|i| items[i].clone())
                                .collect(),
                            type_: typed("XComSequenceSliceResult"),
                        })
                    }
                }
            }
            "SetXCom" => {
                let msg: models::SetXCom = frame::decode(body)?;
                let map_index = msg.map_index.unwrap_or(self.map_index);
                self.log(
                    type_,
                    format!("{}/{}/{}", msg.dag_id, msg.task_id, msg.key),
                    Outcome::Ok,
                );
                self.xcoms.insert(
                    (
                        msg.dag_id.clone(),
                        msg.task_id.clone(),
                        msg.key.clone(),
                        map_index,
                    ),
                    msg.value.clone(),
                );
                self.record.xcoms_pushed.push(PushedXCom {
                    dag_id: msg.dag_id,
                    task_id: msg.task_id,
                    key: msg.key,
                    map_index,
                    value: msg.value,
                });
                Ok(Reply::Ack)
            }
            "DeleteXCom" => {
                let msg: models::DeleteXCom = frame::decode(body)?;
                self.log(
                    type_,
                    format!("{}/{}/{}", msg.dag_id, msg.task_id, msg.key),
                    Outcome::Ok,
                );
                let map_index = msg.map_index.unwrap_or(self.map_index);
                self.xcoms
                    .remove(&(msg.dag_id, msg.task_id, msg.key, map_index));
                Ok(Reply::Ack)
            }
            "GetTaskStateStore"
            | "SetTaskStateStore"
            | "DeleteTaskStateStore"
            | "ClearTaskStateStore" => {
                let msg: StoreRequest = frame::decode(body)?;
                self.handle_store(type_, None, msg)
            }
            "GetAssetStateStoreByName"
            | "GetAssetStateStoreByUri"
            | "SetAssetStateStoreByName"
            | "SetAssetStateStoreByUri"
            | "DeleteAssetStateStoreByName"
            | "DeleteAssetStateStoreByUri"
            | "ClearAssetStateStoreByName"
            | "ClearAssetStateStoreByUri" => {
                let msg: StoreRequest = frame::decode(body)?;
                let asset = input::find_asset_state_key(
                    &self.assets,
                    msg.name.as_deref(),
                    msg.uri.as_deref(),
                );
                self.handle_store(type_, Some(asset), msg)
            }
            "GetAssetByName" | "GetAssetByUri" => {
                let msg: StoreRequest = frame::decode(body)?;
                let target = msg.name.clone().or(msg.uri.clone()).unwrap_or_default();
                match input::find_asset(&self.assets, msg.name.as_deref(), msg.uri.as_deref()) {
                    Some(asset) => {
                        let result = asset_result(asset);
                        self.log(type_, target, Outcome::Ok);
                        Reply::body(&result)
                    }
                    None => {
                        self.log(type_, target, Outcome::NotFound);
                        let detail = match msg.name {
                            Some(name) => json!({"name": name}),
                            None => json!({"uri": msg.uri}),
                        };
                        not_found(AssetNotFound, detail)
                    }
                }
            }
            "GetAssetsByAlias" => {
                let msg: models::GetAssetsByAlias = frame::decode(body)?;
                let mut assets: Vec<models::AssetResult> = Vec::new();
                for event in &self.asset_events {
                    if event.aliases.contains(&msg.alias_name)
                        && !assets.iter().any(|a| a.name == event.asset.name)
                    {
                        assets.push(asset_result(&event.asset));
                    }
                }
                self.log(type_, &msg.alias_name, Outcome::Ok);
                Reply::body(&models::AssetsByAliasResult {
                    assets,
                    type_: typed("AssetsByAliasResult"),
                })
            }
            "GetAssetEventByAsset" => {
                let msg: models::GetAssetEventByAsset = frame::decode(body)?;
                let (name, uri) = (msg.name.clone(), msg.uri.clone());
                let target = name.clone().or(uri.clone()).unwrap_or_default();
                let filter = EventFilter {
                    after: msg.after,
                    before: msg.before,
                    partition_key: msg.partition_key,
                    partition_key_regexp_pattern: msg.partition_key_regexp_pattern,
                    extra: msg.extra,
                    ascending: msg.ascending,
                    limit: msg.limit,
                };
                let events = self.find_events(&filter, |e| {
                    (name.is_some() || uri.is_some())
                        && name.as_ref().is_none_or(|n| *n == e.asset.name)
                        && uri.as_ref().is_none_or(|u| *u == e.asset.uri)
                })?;
                self.log(type_, target, Outcome::Ok);
                Reply::body(&events)
            }
            "GetAssetEventByAssetAlias" => {
                let msg: models::GetAssetEventByAssetAlias = frame::decode(body)?;
                let alias = msg.alias_name.clone();
                let filter = EventFilter {
                    after: msg.after,
                    before: msg.before,
                    partition_key: msg.partition_key,
                    partition_key_regexp_pattern: msg.partition_key_regexp_pattern,
                    extra: msg.extra,
                    ascending: msg.ascending,
                    limit: msg.limit,
                };
                let events = self.find_events(&filter, |e| e.aliases.contains(&alias))?;
                self.log(type_, msg.alias_name, Outcome::Ok);
                Reply::body(&events)
            }
            "MaskSecret" => {
                let msg: models::MaskSecret = frame::decode(body)?;
                self.log(type_, msg.name.unwrap_or_default(), Outcome::Ok);
                self.record.secrets_masked += 1;
                Ok(Reply::Ack)
            }
            "SetRenderedFields" => {
                let msg: models::SetRenderedFields = frame::decode(body)?;
                self.log(type_, "", Outcome::Ok);
                self.record.rendered_fields =
                    Some(Json::Object(msg.rendered_fields.into_iter().collect::<Map<
                        String,
                        Json,
                    >>(
                    )));
                Ok(Reply::Ack)
            }
            "SetRenderedMapIndex" => {
                let msg: models::SetRenderedMapIndex = frame::decode(body)?;
                self.log(type_, &msg.rendered_map_index, Outcome::Ok);
                self.record.rendered_map_index = Some(msg.rendered_map_index);
                Ok(Reply::Ack)
            }
            "SetExecutionTimeout" => {
                let msg: models::SetExecutionTimeout = frame::decode(body)?;
                self.log(type_, format!("{}s", msg.timeout_seconds), Outcome::Ok);
                self.record.execution_timeout = Some(msg.timeout_seconds);
                Ok(Reply::Ack)
            }
            "SkipDownstreamTasks" => {
                let msg: models::SkipDownstreamTasks = frame::decode(body)?;
                let tasks: Vec<Json> = msg
                    .tasks
                    .into_iter()
                    .map(|t| match t {
                        models::TasksItem::String(id) => Json::String(id),
                        models::TasksItem::Array(pair) => Json::Array(pair.to_vec()),
                    })
                    .collect();
                self.log(type_, Json::Array(tasks.clone()).to_string(), Outcome::Ok);
                self.record.skipped_downstream.extend(tasks);
                Ok(Reply::Ack)
            }
            t if TERMINAL_MESSAGES.contains(&t) => {
                let body = frame::to_json(body);
                let state = body
                    .get("state")
                    .and_then(Json::as_str)
                    .unwrap_or(match t {
                        "SucceedTask" => "success",
                        "RetryTask" => "up_for_retry",
                        "DeferTask" => "deferred",
                        "RescheduleTask" => "up_for_reschedule",
                        _ => "unknown",
                    })
                    .to_owned();
                self.log(type_, &state, Outcome::Ok);
                if let Some(Json::String(index)) = body.get("rendered_map_index") {
                    self.record.rendered_map_index = Some(index.clone());
                }
                self.record.terminal = Some(TerminalMessage {
                    type_: t.to_owned(),
                    state,
                    body,
                });
                Ok(Reply::Ack)
            }
            _ => {
                self.log(type_, "", Outcome::Unsupported);
                Reply::error(&models::ErrorResponse {
                    detail: json!({"status_code": 400, "message": format!("gust does not support {type_}")})
                        .as_object()
                        .cloned(),
                    error: ApiServerError,
                    type_: typed("ErrorResponse"),
                })
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(json: Json) -> Value {
        let bytes = rmp_serde::to_vec_named(&json).unwrap();
        rmpv::decode::read_value(&mut bytes.as_slice()).unwrap()
    }

    fn reply_json(reply: Reply) -> (&'static str, Option<Json>) {
        let (kind, bytes) = match reply {
            Reply::Body(b) => ("body", b),
            Reply::Error(e) => ("error", e),
            Reply::Ack => return ("ack", None),
        };
        let value = rmpv::decode::read_value(&mut bytes.as_slice()).unwrap();
        (kind, Some(frame::to_json(&value)))
    }

    fn services() -> Services {
        Services::new(
            &input::parse_input(
                r#"{
                    "variables": {"greeting": "hi"},
                    "xcoms": {"d/up": {"": 42}},
                    "task_state": {"cursor": 7},
                    "asset_state": {"s3://b/o": {"last": 1}},
                    "dag_run": {"consumed_asset_events": [
                        {"asset": {"name": "orders", "uri": "s3://b/o"}, "extra": {"n": 1},
                         "timestamp": "2026-01-02T00:00:00Z", "partition_key": "eu-1",
                         "aliases": ["al"]},
                        {"asset": {"name": "orders", "uri": "s3://b/o"}, "extra": {"n": 2},
                         "timestamp": "2026-01-01T00:00:00Z"},
                        {"asset": {"name": "users"}, "timestamp": "2026-01-03T00:00:00Z",
                         "aliases": ["al"]}
                    ]}
                }"#,
            )
            .unwrap(),
        )
    }

    fn ask(s: &mut Services, req: Json) -> (&'static str, Option<Json>) {
        reply_json(s.handle(&request(req)).unwrap())
    }

    #[test]
    fn slices_like_python() {
        type Case = (Option<i64>, Option<i64>, Option<i64>, &'static [usize]);
        let cases: &[Case] = &[
            (None, None, None, &[0, 1, 2, 3, 4]),
            (Some(1), Some(3), None, &[1, 2]),
            (Some(-2), None, None, &[3, 4]),
            (None, Some(-1), None, &[0, 1, 2, 3]),
            (None, None, Some(2), &[0, 2, 4]),
            (None, None, Some(-1), &[4, 3, 2, 1, 0]),
            (Some(3), Some(0), Some(-2), &[3, 1]),
            (Some(-1), Some(-4), Some(-1), &[4, 3, 2]),
            (Some(10), None, None, &[]),
            (Some(-10), Some(2), None, &[0, 1]),
            (None, None, Some(0), &[0, 1, 2, 3, 4]),
        ];
        for &(start, stop, step, want) in cases {
            assert_eq!(
                slice_indexes(5, start, stop, step),
                want,
                "{start:?}:{stop:?}:{step:?}"
            );
        }
    }

    #[test]
    fn reads_a_mapped_upstream_from_an_array() {
        let mut s = Services::new(
            &input::parse_input(r#"{"xcoms": {"d/m": {"": [10, 20, 30]}, "d/scalar": {"": 1}}}"#)
                .unwrap(),
        );
        let req = |type_: &str, extra: Json| {
            let mut r = json!({"type": type_, "dag_id": "d", "task_id": "m", "run_id": "r", "key": "return_value", "previous_iteration": false, "include_prior_dates": false});
            r.as_object_mut()
                .unwrap()
                .extend(extra.as_object().unwrap().clone());
            r
        };
        let (_, body) = ask(&mut s, req("GetXComCount", json!({})));
        assert_eq!(body.unwrap()["len"], 3);
        let (_, body) = ask(&mut s, req("GetXComSequenceItem", json!({"offset": -1})));
        assert_eq!(body.unwrap()["root"], 30);
        // Airflow answers with the error as the body, not in the error slot.
        let (slot, body) = ask(&mut s, req("GetXComSequenceItem", json!({"offset": 3})));
        assert_eq!(
            (slot, &body.unwrap()["error"]),
            ("body", &json!("XCOM_NOT_FOUND"))
        );
        let (_, body) = ask(&mut s, req("GetXComSequenceItem", json!({"offset": -4})));
        assert_eq!(body.unwrap()["error"], "XCOM_NOT_FOUND");
        let (_, body) = ask(
            &mut s,
            req(
                "GetXComSequenceSlice",
                json!({"start": 1, "stop": null, "step": null}),
            ),
        );
        assert_eq!(body.unwrap()["root"], json!([20, 30]));

        let (_, body) = ask(
            &mut s,
            json!({"type": "GetXComCount", "dag_id": "d", "task_id": "nope", "run_id": "r", "key": "return_value", "previous_iteration": false}),
        );
        assert_eq!(body.unwrap()["len"], 0);
        let (kind, body) = ask(
            &mut s,
            json!({"type": "GetXComCount", "dag_id": "d", "task_id": "scalar", "run_id": "r", "key": "return_value", "previous_iteration": false}),
        );
        assert_eq!(kind, "error");
        assert!(
            body.unwrap()["detail"]["message"]
                .as_str()
                .unwrap()
                .contains("not a JSON array")
        );
    }

    #[test]
    fn serves_task_state_and_records_writes() {
        let mut s = services();
        let (kind, body) = ask(
            &mut s,
            json!({"type": "GetTaskStateStore", "ti_id": "00000000-0000-0000-0000-000000000000", "key": "cursor"}),
        );
        assert_eq!((kind, body.unwrap()["value"].clone()), ("body", json!(7)));
        let (kind, body) = ask(
            &mut s,
            json!({"type": "GetTaskStateStore", "ti_id": "00000000-0000-0000-0000-000000000000", "key": "nope"}),
        );
        assert_eq!(
            (kind, body.unwrap()["error"].clone()),
            ("error", json!("TASK_STORE_NOT_FOUND"))
        );
        ask(
            &mut s,
            json!({"type": "SetTaskStateStore", "ti_id": "00000000-0000-0000-0000-000000000000", "key": "cursor", "value": [8]}),
        );
        ask(
            &mut s,
            json!({"type": "ClearTaskStateStore", "ti_id": "00000000-0000-0000-0000-000000000000"}),
        );
        let (kind, _) = ask(
            &mut s,
            json!({"type": "GetTaskStateStore", "ti_id": "00000000-0000-0000-0000-000000000000", "key": "cursor"}),
        );
        assert_eq!(kind, "error");
        let writes: Vec<_> = s
            .record
            .state_written
            .iter()
            .map(|w| (w.asset.clone(), w.key.clone(), w.value.clone()))
            .collect();
        assert_eq!(
            writes,
            [
                (None, Some("cursor".into()), Some(json!([8]))),
                (None, None, None)
            ]
        );
    }

    #[test]
    fn asset_state_answers_by_name_or_uri() {
        let mut s = services();
        let (_, body) = ask(
            &mut s,
            json!({"type": "GetAssetStateStoreByName", "name": "orders", "key": "last"}),
        );
        assert_eq!(body.unwrap()["value"], json!(1));
        ask(
            &mut s,
            json!({"type": "SetAssetStateStoreByUri", "uri": "s3://b/o", "key": "last", "value": 2}),
        );
        let (_, body) = ask(
            &mut s,
            json!({"type": "GetAssetStateStoreByName", "name": "orders", "key": "last"}),
        );
        assert_eq!(body.unwrap()["value"], json!(2));
        let (_, body) = ask(
            &mut s,
            json!({"type": "GetAssetStateStoreByName", "name": "users", "key": "last"}),
        );
        assert_eq!(body.unwrap()["error"], "ASSET_STORE_NOT_FOUND");
        assert_eq!(s.record.state_written[0].asset.as_deref(), Some("orders"));
    }

    #[test]
    fn serves_assets_and_their_events() {
        let mut s = services();
        let (_, body) = ask(&mut s, json!({"type": "GetAssetByUri", "uri": "s3://b/o"}));
        assert_eq!(body.unwrap()["name"], "orders");
        let (_, body) = ask(&mut s, json!({"type": "GetAssetByName", "name": "nope"}));
        assert_eq!(body.unwrap()["error"], "ASSET_NOT_FOUND");

        let ids = |body: Option<Json>| -> Vec<i64> {
            body.unwrap()["asset_events"]
                .as_array()
                .unwrap()
                .iter()
                .map(|e| e["id"].as_i64().unwrap())
                .collect()
        };
        let (_, body) = ask(
            &mut s,
            json!({"type": "GetAssetEventByAsset", "name": "orders", "uri": null, "ascending": true}),
        );
        assert_eq!(ids(body), [2, 1]);
        let (_, body) = ask(
            &mut s,
            json!({"type": "GetAssetEventByAsset", "name": null, "uri": "s3://b/o", "ascending": false, "limit": 1}),
        );
        assert_eq!(ids(body), [1]);
        let (_, body) = ask(
            &mut s,
            json!({"type": "GetAssetEventByAsset", "name": "orders", "uri": null, "ascending": true, "extra": {"n": "2"}}),
        );
        assert_eq!(ids(body), [2]);
        let (_, body) = ask(
            &mut s,
            json!({"type": "GetAssetEventByAsset", "name": "orders", "uri": null, "ascending": true, "partition_key_regexp_pattern": "^eu-"}),
        );
        assert_eq!(ids(body), [1]);
        let (_, body) = ask(
            &mut s,
            json!({"type": "GetAssetEventByAssetAlias", "alias_name": "al", "ascending": true}),
        );
        assert_eq!(ids(body), [1, 3]);

        let (_, body) = ask(
            &mut s,
            json!({"type": "GetAssetsByAlias", "alias_name": "al"}),
        );
        let names: Vec<_> = body.unwrap()["assets"]
            .as_array()
            .unwrap()
            .iter()
            .map(|a| a["name"].clone())
            .collect();
        assert_eq!(names, [json!("orders"), json!("users")]);
    }

    #[test]
    fn serves_variables_and_reports_missing() {
        let mut s = services();
        let (kind, body) = reply_json(
            s.handle(&request(json!({"type": "GetVariable", "key": "greeting"})))
                .unwrap(),
        );
        assert_eq!(kind, "body");
        assert_eq!(body.unwrap()["value"], "hi");
        let (kind, body) = reply_json(
            s.handle(&request(json!({"type": "GetVariable", "key": "nope"})))
                .unwrap(),
        );
        assert_eq!(kind, "error");
        assert_eq!(body.unwrap()["error"], "VARIABLE_NOT_FOUND");
    }

    #[test]
    fn xcom_matches_any_run_and_keeps_integers() {
        let mut s = services();
        let req = json!({"type": "GetXCom", "dag_id": "d", "task_id": "up", "key": "return_value", "run_id": "whatever", "map_index": -1});
        let (kind, body) = reply_json(s.handle(&request(req)).unwrap());
        assert_eq!(kind, "body");
        assert_eq!(body.unwrap()["value"], json!(42));
    }

    #[test]
    fn reads_one_instance_of_a_mapped_upstream() {
        let mut s = Services::new(
            &input::parse_input(r#"{"xcoms": {"d/m": {"": [10, 20]}, "d/u": {"": [1, 2]}}}"#)
                .unwrap(),
        );
        s.set_mapped_tasks("d", &BTreeSet::from(["m".to_owned()]));
        let mut get = |task: &str, map_index: i64| {
            let req = json!({"type": "GetXCom", "dag_id": "d", "task_id": task, "key": "return_value", "run_id": "r", "map_index": map_index});
            reply_json(s.handle(&request(req)).unwrap()).1.unwrap()
        };
        assert_eq!(get("m", 1)["value"], 20);
        assert_eq!(get("m", -1)["value"], json!([10, 20]));
        assert_eq!(get("m", 2)["error"], "XCOM_NOT_FOUND");
        assert_eq!(get("u", 1)["value"], json!([1, 2]));
    }

    #[test]
    fn keeps_each_instance_s_pushes_apart() {
        let mut s = services();
        for map_index in [0, 1] {
            s.begin_instance("d", "t", map_index, 1);
            let push = json!({"type": "SetXCom", "dag_id": "d", "task_id": "t", "run_id": "r", "key": "k", "value": map_index});
            s.handle(&request(push)).unwrap();
            assert_eq!(s.record.xcoms_pushed.len(), 1);
            assert_eq!(s.record.xcoms_pushed[0].map_index, map_index);
        }
        let get = |s: &mut Services, map_index: i64| {
            let req = json!({"type": "GetXCom", "dag_id": "d", "task_id": "t", "key": "k", "run_id": "r", "map_index": map_index});
            reply_json(s.handle(&request(req)).unwrap()).1.unwrap()
        };
        assert_eq!(get(&mut s, 0)["value"], 0);
        assert_eq!(get(&mut s, -1)["error"], "XCOM_NOT_FOUND");
        s.set_map_length("d", "t", 3);
        assert_eq!(get(&mut s, -1)["value"], json!([0, 1, null]));
        assert_eq!(
            s.find_xcom_values("d")[&("t".to_owned(), "k".to_owned())],
            json!([0, 1, null])
        );

        // A second try of instance 1 starts without its earlier push, and keeps its state store.
        let set = json!({"type": "SetTaskStateStore", "key": "c", "value": 5});
        s.handle(&request(set)).unwrap();
        s.begin_instance("d", "t", 0, 1);
        s.begin_instance("d", "t", 1, 2);
        assert_eq!(get(&mut s, 1)["error"], "XCOM_NOT_FOUND");
        assert_eq!(get(&mut s, 0)["value"], 0);
        let read = json!({"type": "GetTaskStateStore", "key": "c"});
        assert_eq!(
            reply_json(s.handle(&request(read)).unwrap()).1.unwrap()["value"],
            5
        );
    }

    #[test]
    fn records_pushed_xcom_and_terminal_state() {
        let mut s = services();
        let push = json!({"type": "SetXCom", "dag_id": "d", "task_id": "t", "run_id": "r", "key": "return_value", "value": {"a": 1}});
        assert_eq!(reply_json(s.handle(&request(push)).unwrap()).0, "ack");
        let done = json!({"type": "TaskState", "state": "failed"});
        assert_eq!(reply_json(s.handle(&request(done)).unwrap()).0, "ack");
        assert_eq!(s.record.xcoms_pushed[0].value, json!({"a": 1}));
        assert_eq!(s.record.terminal.as_ref().unwrap().state, "failed");
    }

    #[test]
    fn records_skipped_downstream_tasks() {
        let mut s = services();
        let skip = json!({"type": "SkipDownstreamTasks", "tasks": ["a", ["b", 2]]});
        assert_eq!(reply_json(s.handle(&request(skip)).unwrap()).0, "ack");
        assert_eq!(s.record.skipped_downstream, [json!("a"), json!(["b", 2])]);
    }

    #[test]
    fn rejects_unsupported_requests() {
        let mut s = services();
        let (kind, body) = reply_json(
            s.handle(&request(json!({"type": "GetTaskStates", "dag_id": "d"})))
                .unwrap(),
        );
        assert_eq!(kind, "error");
        assert_eq!(body.unwrap()["error"], "API_SERVER_ERROR");
        assert_eq!(s.record.requests[0].outcome, Outcome::Unsupported);
    }
}
