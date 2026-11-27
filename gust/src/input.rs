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

//! The `--input` mapping: everything the task can see that gust does not learn from the bundle.
//!
//! The format is gust's own and is documented in `docs/input.md`. Each fact has one key; gust derives
//! everything else from it and copies values to wherever the supervisor messages need them.

use std::collections::BTreeMap;

use serde::{Deserialize, Deserializer};
use serde_json::{Map, Value};
use url::Url;

use crate::{models::DagRunType, timestamp::Timestamp};

/// The validated `--input`, with every default filled in.
#[derive(Clone, Debug)]
pub struct Input {
    pub dag_run: DagRunInput,
    pub try_number: i64,
    /// `ti` was given at all, which only makes sense for a single task.
    pub ti_given: bool,
    /// `None` takes the task's `retries` from its Dag, or 0.
    pub max_tries: Option<i64>,
    pub variables: Vec<(String, String)>,
    pub connections: Vec<ConnInput>,
    pub xcoms: Vec<XComInput>,
    pub task_state: BTreeMap<String, Value>,
    /// Keyed by asset name, or by the name or URI given when the asset is not otherwise known.
    pub asset_state: BTreeMap<String, Map<String, Value>>,
    pub assets: Vec<Asset>,
    pub asset_events: Vec<AssetEvent>,
}

#[derive(Clone, Debug)]
pub struct DagRunInput {
    pub run_id: String,
    pub run_type: DagRunType,
    pub logical_date: Option<Timestamp>,
    pub data_interval: Option<(Timestamp, Timestamp)>,
    pub run_after: Timestamp,
    pub start_date: Timestamp,
    pub conf: Option<Map<String, Value>>,
    pub partition_key: Option<String>,
    pub triggering_user: Option<String>,
    pub note: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Asset {
    pub name: String,
    pub uri: String,
    pub group: String,
    pub extra: Map<String, Value>,
}

#[derive(Clone, Debug)]
pub struct AssetEvent {
    pub id: i64,
    pub asset: Asset,
    pub extra: Map<String, Value>,
    pub timestamp: Timestamp,
    pub source_dag_id: Option<String>,
    pub source_task_id: Option<String>,
    pub source_run_id: Option<String>,
    pub source_map_index: Option<i64>,
    pub aliases: Vec<String>,
    pub partition_key: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct XComInput {
    pub dag_id: String,
    pub task_id: String,
    pub key: String,
    pub value: Value,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ConnInput {
    pub conn_id: String,
    pub conn_type: String,
    pub host: Option<String>,
    pub schema: Option<String>,
    pub login: Option<String>,
    pub password: Option<String>,
    pub port: Option<i64>,
    pub extra: Option<String>,
}

/// Look up an asset by name or URI.
pub fn find_asset<'a>(
    assets: &'a [Asset],
    name: Option<&str>,
    uri: Option<&str>,
) -> Option<&'a Asset> {
    if name.is_none() && uri.is_none() {
        return None;
    }
    assets
        .iter()
        .find(|a| name.is_none_or(|n| a.name == n) && uri.is_none_or(|u| a.uri == u))
}

/// The key an asset's state is stored under: its name when the asset is known, else what was given.
pub fn find_asset_state_key(assets: &[Asset], name: Option<&str>, uri: Option<&str>) -> String {
    match find_asset(assets, name, uri) {
        Some(asset) => asset.name.clone(),
        None => name.or(uri).unwrap_or_default().to_owned(),
    }
}

#[derive(Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields, expecting = "a JSON object")]
struct RawInput {
    dag_run: RawDagRun,
    ti: RawTi,
    variables: Map<String, Value>,
    connections: Map<String, Value>,
    xcoms: Map<String, Value>,
    task_state: Map<String, Value>,
    asset_state: Map<String, Value>,
}

#[derive(Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields, expecting = "a JSON object")]
struct RawDagRun {
    run_id: Option<String>,
    run_type: Option<DagRunType>,
    #[serde(deserialize_with = "nullable")]
    logical_date: Option<Option<Timestamp>>,
    #[serde(deserialize_with = "nullable")]
    data_interval: Option<Option<RawDataInterval>>,
    run_after: Option<Timestamp>,
    start_date: Option<Timestamp>,
    conf: Option<Map<String, Value>>,
    partition_key: Option<String>,
    triggering_user: Option<String>,
    note: Option<String>,
    consumed_asset_events: Vec<RawAssetEvent>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, expecting = "a JSON object")]
struct RawDataInterval {
    start: Timestamp,
    end: Timestamp,
}

#[derive(Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields, expecting = "a JSON object")]
struct RawTi {
    try_number: Option<i64>,
    max_tries: Option<i64>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, expecting = "a JSON object")]
struct RawAssetEvent {
    asset: RawAsset,
    #[serde(default)]
    extra: Map<String, Value>,
    timestamp: Option<Timestamp>,
    #[serde(default)]
    source: RawEventSource,
    #[serde(default)]
    aliases: Vec<String>,
    partition_key: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, expecting = "a JSON object")]
struct RawAsset {
    name: Option<String>,
    uri: Option<String>,
    group: Option<String>,
    #[serde(default)]
    extra: Map<String, Value>,
}

#[derive(Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields, expecting = "a JSON object")]
struct RawEventSource {
    dag_id: Option<String>,
    task_id: Option<String>,
    run_id: Option<String>,
    map_index: Option<i64>,
}

/// Tell an explicit `null` (`Some(None)`) apart from a missing key (`None`).
fn nullable<'de, D: Deserializer<'de>, T: Deserialize<'de>>(
    deserializer: D,
) -> Result<Option<Option<T>>, D::Error> {
    Option::<T>::deserialize(deserializer).map(Some)
}

/// Parse and validate `--input`.
pub fn parse_input(s: &str) -> Result<Input, String> {
    let mut deserializer = serde_json::Deserializer::from_str(s);
    let raw: RawInput =
        serde_path_to_error::deserialize(&mut deserializer).map_err(describe_error)?;
    deserializer.end().map_err(|e| e.to_string())?;
    resolve(raw, Timestamp::now())
}

/// Prefix a deserialization error with where it happened, such as `dag_run.run_type`.
fn describe_error(e: serde_path_to_error::Error<serde_json::Error>) -> String {
    use serde_path_to_error::Segment;
    let mut segments: Vec<&Segment> = e.path().iter().collect();
    let inner = e.inner().to_string();
    // The path of an unknown field ends with that field, which the message names already.
    if inner.starts_with("unknown field") {
        segments.pop();
    }
    let mut path = String::new();
    for segment in segments {
        match segment {
            Segment::Seq { index } => path.push_str(&format!("[{index}]")),
            Segment::Map { key } | Segment::Enum { variant: key } => {
                if !path.is_empty() {
                    path.push('.');
                }
                path.push_str(key);
            }
            Segment::Unknown => {}
        }
    }
    if path.is_empty() {
        inner
    } else {
        format!("{path}: {inner}")
    }
}

fn resolve(raw: RawInput, now: Timestamp) -> Result<Input, String> {
    let d = raw.dag_run;
    let run_type = d.run_type.unwrap_or(DagRunType::Manual);
    let logical_date = d.logical_date.unwrap_or(Some(now));
    let data_interval = match d.data_interval {
        Some(interval) => interval.map(|i| (i.start, i.end)),
        None => logical_date.map(|date| (date, date)),
    };
    let run_after = d.run_after.or(logical_date).unwrap_or(now);
    let dag_run = DagRunInput {
        run_id: d
            .run_id
            .unwrap_or_else(|| format!("{run_type}__{}", logical_date.unwrap_or(run_after))),
        run_type,
        logical_date,
        data_interval,
        run_after,
        start_date: d.start_date.unwrap_or(now),
        conf: d.conf,
        partition_key: d.partition_key,
        triggering_user: d.triggering_user,
        note: d.note,
    };

    let mut assets: Vec<Asset> = Vec::new();
    let mut asset_events = Vec::new();
    for (index, event) in d.consumed_asset_events.into_iter().enumerate() {
        let path = format!("dag_run.consumed_asset_events[{index}]");
        let asset = resolve_asset(event.asset).map_err(|e| format!("{path}.asset: {e}"))?;
        match assets
            .iter()
            .find(|a| a.name == asset.name || a.uri == asset.uri)
        {
            Some(known) if *known != asset => {
                return Err(format!(
                    "{path}.asset: differs from an earlier event's asset with the same name or URI"
                ));
            }
            Some(_) => {}
            None => assets.push(asset.clone()),
        }
        asset_events.push(AssetEvent {
            id: index as i64 + 1,
            asset,
            extra: event.extra,
            timestamp: event.timestamp.unwrap_or(now),
            source_dag_id: event.source.dag_id,
            source_task_id: event.source.task_id,
            source_run_id: event.source.run_id,
            source_map_index: event.source.map_index,
            aliases: event.aliases,
            partition_key: event.partition_key,
        });
    }

    let mut input = Input {
        dag_run,
        ti_given: raw.ti.try_number.is_some() || raw.ti.max_tries.is_some(),
        try_number: raw.ti.try_number.unwrap_or(1),
        max_tries: raw.ti.max_tries,
        variables: resolve_variables(raw.variables)?,
        connections: resolve_connections(raw.connections)?,
        xcoms: resolve_xcoms(raw.xcoms)?,
        task_state: raw.task_state.into_iter().collect(),
        asset_state: BTreeMap::new(),
        assets,
        asset_events,
    };
    for (asset, store) in raw.asset_state {
        let Value::Object(store) = store else {
            return Err(format!("asset_state.{asset}: expected a JSON object"));
        };
        let key = find_asset(&input.assets, Some(&asset), None)
            .or_else(|| find_asset(&input.assets, None, Some(&asset)))
            .map_or(asset, |known| known.name.clone());
        if input.asset_state.insert(key.clone(), store).is_some() {
            return Err(format!("asset_state: {key:?} is given more than once"));
        }
    }
    Ok(input)
}

/// Fill in an asset's name from its URI or the other way round, as `Asset(name=...)` does.
fn resolve_asset(raw: RawAsset) -> Result<Asset, String> {
    let (name, uri) = match (raw.name, raw.uri) {
        (None, None) => return Err("needs a name or a uri".into()),
        (Some(name), None) => (name.clone(), name),
        (None, Some(uri)) => (uri.clone(), uri),
        (Some(name), Some(uri)) => (name, uri),
    };
    Ok(Asset {
        name,
        uri,
        group: raw.group.unwrap_or_else(|| "asset".into()),
        extra: raw.extra,
    })
}

fn resolve_variables(map: Map<String, Value>) -> Result<Vec<(String, String)>, String> {
    map.into_iter()
        .map(|(key, value)| match value {
            _ if key.is_empty() => Err("variables: keys must not be empty".into()),
            Value::Null => Err(format!("variables.{key}: must not be null")),
            Value::String(v) => Ok((key, v)),
            v => Ok((key, v.to_string())),
        })
        .collect()
}

fn resolve_xcoms(map: Map<String, Value>) -> Result<Vec<XComInput>, String> {
    let mut xcoms = Vec::new();
    for (name, keys) in map {
        let (dag_id, task_id) = match name.split_once('/') {
            // A Dag id cannot contain a slash, but a Lang-SDK packer only warns about one in a task
            // id, so everything after the first slash is the task id.
            Some((d, t)) if !d.is_empty() && !t.is_empty() => (d, t),
            _ => {
                return Err(format!(
                    "xcoms: expected a \"dag_id/task_id\" key, got {name:?}"
                ));
            }
        };
        let Value::Object(keys) = keys else {
            return Err(format!("xcoms.{name}: expected a JSON object"));
        };
        if keys.contains_key("") && keys.contains_key("return_value") {
            return Err(format!(
                "xcoms.{name}: \"\" and \"return_value\" are the same key"
            ));
        }
        for (key, value) in keys {
            xcoms.push(XComInput {
                dag_id: dag_id.into(),
                task_id: task_id.into(),
                key: if key.is_empty() {
                    "return_value".into()
                } else {
                    key
                },
                value,
            });
        }
    }
    Ok(xcoms)
}

fn resolve_connections(map: Map<String, Value>) -> Result<Vec<ConnInput>, String> {
    map.into_iter()
        .map(|(conn_id, value)| {
            if conn_id.is_empty() {
                return Err("connections: ids must not be empty".into());
            }
            let path = format!("connections.{conn_id}");
            match value {
                Value::String(uri) => parse_conn_uri(conn_id, &uri),
                Value::Object(fields) => parse_conn_fields(conn_id, fields),
                _ => Err("expected a URI string or a JSON object".into()),
            }
            .map_err(|e| format!("{path}: {e}"))
        })
        .collect()
}

fn decode(s: &str) -> String {
    url::form_urlencoded::parse(format!("x={s}").as_bytes())
        .next()
        .map(|(_, v)| v.into_owned())
        .unwrap_or_default()
}

fn non_empty(s: &str) -> Option<String> {
    (!s.is_empty()).then(|| decode(s))
}

/// Parse a connection URI the way Airflow's `Connection(uri=...)` does.
fn parse_conn_uri(conn_id: String, uri: &str) -> Result<ConnInput, String> {
    let url = Url::parse(uri).map_err(|e| format!("invalid URI: {e}"))?;
    let query: Vec<(String, String)> = url.query_pairs().into_owned().collect();
    let extra = match query.as_slice() {
        [] => None,
        [(k, v)] if k == "__extra__" => Some(v.clone()),
        pairs => Some(
            Value::Object(
                pairs
                    .iter()
                    .map(|(k, v)| (k.clone(), Value::String(v.clone())))
                    .collect(),
            )
            .to_string(),
        ),
    };
    Ok(ConnInput {
        conn_id,
        conn_type: url.scheme().replace('-', "_"),
        host: url.host_str().and_then(non_empty),
        schema: non_empty(url.path().trim_start_matches('/')),
        login: non_empty(url.username()),
        password: url.password().and_then(non_empty),
        port: url.port().map(i64::from),
        extra,
    })
}

/// Parse a connection object the way Airflow's `Connection.from_json` does.
fn parse_conn_fields(conn_id: String, mut fields: Map<String, Value>) -> Result<ConnInput, String> {
    let mut take_string = |name: &str| match fields.remove(name) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(v)) => Ok(Some(v)),
        Some(_) => Err(format!("{name}: expected a string")),
    };
    let conn_type = take_string("conn_type")?.ok_or("missing field `conn_type`")?;
    let host = take_string("host")?;
    let schema = take_string("schema")?;
    let login = take_string("login")?;
    let password = take_string("password")?;
    let port = match fields.remove("port") {
        None | Some(Value::Null) => None,
        Some(Value::Number(n)) if n.is_i64() => n.as_i64(),
        Some(Value::String(p)) if p.parse::<i64>().is_ok() => p.parse().ok(),
        Some(_) => return Err("port: expected an integer".into()),
    };
    let extra = match fields.remove("extra") {
        None | Some(Value::Null) => None,
        Some(Value::String(v)) => Some(v),
        Some(v @ Value::Object(_)) => Some(v.to_string()),
        Some(_) => return Err("extra: expected a string or a JSON object".into()),
    };
    if let Some(name) = fields.keys().next() {
        return Err(format!("unknown field `{name}`"));
    }
    Ok(ConnInput {
        conn_id,
        conn_type,
        host,
        schema,
        login,
        password,
        port,
        extra,
    })
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn ts(s: &str) -> Timestamp {
        s.parse().unwrap()
    }

    fn parse_at(s: &str, now: &str) -> Result<Input, String> {
        let raw: RawInput = serde_json::from_str(s).map_err(|e| e.to_string())?;
        resolve(raw, ts(now))
    }

    const NOW: &str = "2026-11-21T00:00:00Z";

    #[test]
    fn empty_input_gets_defaults() {
        let input = parse_at("{}", NOW).unwrap();
        let run = &input.dag_run;
        assert_eq!(run.run_type, DagRunType::Manual);
        assert_eq!(run.logical_date, Some(ts(NOW)));
        assert_eq!(run.data_interval, Some((ts(NOW), ts(NOW))));
        assert_eq!(run.run_after, ts(NOW));
        assert_eq!(run.start_date, ts(NOW));
        assert_eq!(run.run_id, "manual__2026-11-21T00:00:00Z");
        assert_eq!(run.conf, None);
        assert_eq!(input.try_number, 1);
        assert_eq!(input.max_tries, None);
    }

    #[test]
    fn dag_run_defaults_follow_logical_date_and_run_type() {
        let input = parse_at(
            r#"{"dag_run": {"logical_date": "2026-01-01T00:00:00Z", "run_type": "scheduled"}}"#,
            NOW,
        )
        .unwrap();
        let run = &input.dag_run;
        let date = ts("2026-01-01T00:00:00Z");
        assert_eq!(run.data_interval, Some((date, date)));
        assert_eq!(run.run_after, date);
        assert_eq!(run.run_id, "scheduled__2026-01-01T00:00:00Z");
        assert_eq!(run.start_date, ts(NOW));
    }

    #[test]
    fn null_logical_date_means_none() {
        let input = parse_at(r#"{"dag_run": {"logical_date": null}}"#, NOW).unwrap();
        let run = &input.dag_run;
        assert_eq!(run.logical_date, None);
        assert_eq!(run.data_interval, None);
        assert_eq!(run.run_after, ts(NOW));
        assert_eq!(run.run_id, "manual__2026-11-21T00:00:00Z");
    }

    #[test]
    fn unknown_and_excluded_keys_are_rejected_with_their_path() {
        for (input, path) in [
            (r#"{"dag_runs": {}}"#, "unknown field `dag_runs`"),
            (r#"{"ti": {"task_id": "t"}}"#, "ti: unknown field `task_id`"),
            (
                r#"{"dag_run": {"dag_id": "d"}}"#,
                "dag_run: unknown field `dag_id`",
            ),
            (
                r#"{"dag_run": {"consumed_asset_events": [{"asset": {"name": "a"}, "extras": {}}]}}"#,
                "dag_run.consumed_asset_events[0]: unknown field `extras`",
            ),
            (
                r#"{"dag_run": {"run_type": "nope"}}"#,
                "dag_run.run_type: unknown variant `nope`",
            ),
        ] {
            let error = parse_input(input).unwrap_err();
            assert!(error.starts_with(path), "{input}: {error}");
        }
        assert!(
            parse_input("[1]")
                .unwrap_err()
                .contains("expected a JSON object")
        );
    }

    #[test]
    fn asset_events_fill_in_assets() {
        let input = parse_at(
            r#"{"dag_run": {"consumed_asset_events": [
                {"asset": {"uri": "s3://b/k"}, "aliases": ["al"]},
                {"asset": {"name": "orders", "uri": "s3://b/o"}, "extra": {"n": 1},
                 "timestamp": "2026-01-01T00:00:00Z", "source": {"dag_id": "up"}},
                {"asset": {"name": "orders", "uri": "s3://b/o"}}
            ]}}"#,
            NOW,
        )
        .unwrap();
        let names: Vec<_> = input
            .assets
            .iter()
            .map(|a| (a.name.as_str(), a.uri.as_str(), a.group.as_str()))
            .collect();
        assert_eq!(
            names,
            [
                ("s3://b/k", "s3://b/k", "asset"),
                ("orders", "s3://b/o", "asset")
            ]
        );
        let events = &input.asset_events;
        assert_eq!(events.len(), 3);
        assert_eq!((events[0].id, events[0].timestamp), (1, ts(NOW)));
        assert_eq!(events[0].aliases, ["al"]);
        assert_eq!(events[1].source_dag_id.as_deref(), Some("up"));
        assert_eq!(events[1].extra, *json!({"n": 1}).as_object().unwrap());

        let conflict = parse_at(
            r#"{"dag_run": {"consumed_asset_events": [
                {"asset": {"name": "orders", "uri": "s3://b/o"}},
                {"asset": {"name": "orders", "uri": "s3://b/other"}}
            ]}}"#,
            NOW,
        );
        assert!(
            conflict
                .unwrap_err()
                .contains("consumed_asset_events[1].asset")
        );
    }

    #[test]
    fn asset_state_is_keyed_by_asset_name() {
        let input = parse_at(
            r#"{"dag_run": {"consumed_asset_events": [{"asset": {"name": "orders", "uri": "s3://b/o"}}]},
                "asset_state": {"s3://b/o": {"k": 1}, "other": {"j": 2}}}"#,
            NOW,
        )
        .unwrap();
        assert_eq!(
            input.asset_state.keys().collect::<Vec<_>>(),
            ["orders", "other"]
        );
        assert_eq!(
            find_asset_state_key(&input.assets, None, Some("s3://b/o")),
            "orders"
        );
        let duplicate = parse_at(
            r#"{"dag_run": {"consumed_asset_events": [{"asset": {"name": "orders", "uri": "s3://b/o"}}]},
                "asset_state": {"s3://b/o": {}, "orders": {}}}"#,
            NOW,
        );
        assert!(duplicate.unwrap_err().contains("more than once"));
    }

    #[test]
    fn xcoms_by_dag_and_task() {
        let mut x = parse_at(
            r#"{"xcoms": {"d/t": {"": [1, 2], "k": "s"}, "d/u": {"return_value": 3}, "d/u/v": {"": 4}}}"#,
            NOW,
        )
        .unwrap()
        .xcoms;
        x.sort_by(|a, b| (&a.task_id, &a.key).cmp(&(&b.task_id, &b.key)));
        let got: Vec<_> = x
            .iter()
            .map(|x| {
                (
                    x.dag_id.as_str(),
                    x.task_id.as_str(),
                    x.key.as_str(),
                    &x.value,
                )
            })
            .collect();
        assert_eq!(
            got,
            [
                ("d", "t", "k", &json!("s")),
                ("d", "t", "return_value", &json!([1, 2])),
                ("d", "u", "return_value", &json!(3)),
                ("d", "u/v", "return_value", &json!(4)),
            ]
        );
        for bad in [
            r#"{"d": {"k": 1}}"#,
            r#"{"d/": {"k": 1}}"#,
            r#"{"/t": {"k": 1}}"#,
            r#"{"d/t": 1}"#,
            r#"{"d/t": {"": 1, "return_value": 2}}"#,
        ] {
            let input = format!(r#"{{"xcoms": {bad}}}"#);
            assert!(parse_at(&input, NOW).is_err(), "{bad}");
        }
    }

    #[test]
    fn variables_pass_non_strings_as_json_text() {
        let mut v = parse_at(
            r#"{"variables": {"s": "a b", "n": 3, "o": {"x": [true]}}}"#,
            NOW,
        )
        .unwrap()
        .variables;
        v.sort();
        assert_eq!(
            v,
            [
                ("n".into(), "3".into()),
                ("o".into(), r#"{"x":[true]}"#.into()),
                ("s".into(), "a b".into()),
            ]
        );
        assert!(parse_at(r#"{"variables": {"k": null}}"#, NOW).is_err());
        assert!(parse_at(r#"{"variables": {"": "v"}}"#, NOW).is_err());
    }

    #[test]
    fn connections_from_uri_or_fields() {
        let c = parse_at(
            r#"{"connections": {
                "a": "postgres://us%40er:p%2Fw@example.com:5432/my%20db?sslmode=require",
                "b": "google-cloud-platform://?__extra__=%7B%22a%22%3A1%7D",
                "c": {"conn_type": "aws", "port": "5432", "password": "p@ss/word",
                      "extra": {"region": "eu"}}
            }}"#,
            NOW,
        )
        .unwrap()
        .connections;
        assert_eq!(
            c,
            [
                ConnInput {
                    conn_id: "a".into(),
                    conn_type: "postgres".into(),
                    host: Some("example.com".into()),
                    schema: Some("my db".into()),
                    login: Some("us@er".into()),
                    password: Some("p/w".into()),
                    port: Some(5432),
                    extra: Some(r#"{"sslmode":"require"}"#.into()),
                },
                ConnInput {
                    conn_id: "b".into(),
                    conn_type: "google_cloud_platform".into(),
                    host: None,
                    schema: None,
                    login: None,
                    password: None,
                    port: None,
                    extra: Some(r#"{"a":1}"#.into()),
                },
                ConnInput {
                    conn_id: "c".into(),
                    conn_type: "aws".into(),
                    host: None,
                    schema: None,
                    login: None,
                    password: Some("p@ss/word".into()),
                    port: Some(5432),
                    extra: Some(r#"{"region":"eu"}"#.into()),
                },
            ]
        );
        for bad in [
            r#"1"#,
            r#""not a uri""#,
            r#"{"host": "h"}"#,
            r#"{"conn_type": "x", "port": "abc"}"#,
            r#"{"conn_type": "x", "extra": [1]}"#,
            r#"{"conn_type": "x", "hots": "h"}"#,
        ] {
            let input = format!(r#"{{"connections": {{"c": {bad}}}}}"#);
            let error = parse_at(&input, NOW).unwrap_err();
            assert!(error.starts_with("connections.c: "), "{bad}: {error}");
        }
    }
}
