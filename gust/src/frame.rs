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

//! Length-prefixed msgpack frames on the comm socket.
//!
//! Every frame is a 4-byte big-endian length followed by a msgpack array. The runtime sends
//! requests as `[id, body, context_carrier?, ti_id?]`; the supervisor sends `[id, body, error]`,
//! with exactly one of `body` and `error` set, or neither for a bare acknowledgement.

use std::io::{self, Read, Write};

use anyhow::{Context, Result, bail};
use rmpv::Value;
use serde::{Serialize, de::DeserializeOwned};

/// A frame the runtime sent.
#[derive(Debug)]
pub struct Frame {
    pub id: i64,
    pub body: Option<Value>,
    /// Only the supervisor sends errors; tests read replies back through it.
    #[allow(dead_code)]
    pub error: Option<Value>,
}

impl Frame {
    /// The `type` discriminator of the body, if any.
    pub fn body_type(&self) -> Option<&str> {
        type_of(self.body.as_ref()?)
    }
}

pub fn type_of(body: &Value) -> Option<&str> {
    body.as_map()?
        .iter()
        .find(|(k, _)| k.as_str() == Some("type"))
        .and_then(|(_, v)| v.as_str())
}

/// Read one frame. Returns `None` on a clean EOF between frames.
pub fn read_frame(reader: &mut impl Read) -> Result<Option<Frame>> {
    let mut len = [0u8; 4];
    match reader.read_exact(&mut len) {
        Ok(()) => {}
        Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => return Ok(None),
        Err(e) if e.kind() == io::ErrorKind::ConnectionReset => return Ok(None),
        Err(e) => return Err(e).context("reading frame length"),
    }
    let mut payload = vec![0u8; u32::from_be_bytes(len) as usize];
    reader
        .read_exact(&mut payload)
        .context("reading frame payload")?;
    let value = rmpv::decode::read_value(&mut payload.as_slice()).context("decoding frame")?;
    let Value::Array(mut items) = value else {
        bail!("frame is not a msgpack array: {value}");
    };
    if items.is_empty() {
        bail!("frame is an empty array");
    }
    let mut rest = items.split_off(1).into_iter();
    let id = items[0].as_i64().context("frame id is not an integer")?;
    let some = |v: Option<Value>| v.filter(|v| !v.is_nil());
    Ok(Some(Frame {
        id,
        body: some(rest.next()),
        error: some(rest.next()),
    }))
}

/// Deserialize a frame body into one of the generated models.
pub fn decode<T: DeserializeOwned>(body: &Value) -> Result<T> {
    let mut buf = Vec::new();
    rmpv::encode::write_value(&mut buf, body)?;
    Ok(rmp_serde::from_slice(&buf)?)
}

/// What the supervisor puts in a response frame.
pub enum Reply {
    Body(Vec<u8>),
    Error(Vec<u8>),
    Ack,
}

impl Reply {
    pub fn body(msg: &impl Serialize) -> Result<Self> {
        Ok(Self::Body(rmp_serde::to_vec_named(msg)?))
    }

    pub fn error(msg: &impl Serialize) -> Result<Self> {
        Ok(Self::Error(rmp_serde::to_vec_named(msg)?))
    }
}

/// Encode `msg` with `ti_context.arg_bindings` set to `bindings`, for fields the generated models
/// do not have.
pub fn encode_with_bindings(msg: &impl Serialize, bindings: &[serde_json::Value]) -> Result<Reply> {
    let encoded = rmp_serde::to_vec_named(msg)?;
    let mut value = rmpv::decode::read_value(&mut encoded.as_slice())?;
    let context = match &mut value {
        Value::Map(entries) => entries
            .iter_mut()
            .find(|(k, _)| k.as_str() == Some("ti_context"))
            .map(|(_, v)| v),
        _ => None,
    };
    let Some(Value::Map(context)) = context else {
        bail!("the message has no ti_context");
    };
    context.retain(|(k, _)| k.as_str() != Some("arg_bindings"));
    context.push((
        Value::from("arg_bindings"),
        from_json(&serde_json::Value::Array(bindings.to_vec())),
    ));
    let mut buf = Vec::new();
    rmpv::encode::write_value(&mut buf, &value)?;
    Ok(Reply::Body(buf))
}

fn from_json(value: &serde_json::Value) -> Value {
    use serde_json::Value as J;
    match value {
        J::Null => Value::Nil,
        J::Bool(b) => Value::Boolean(*b),
        J::Number(n) => match (n.as_i64(), n.as_u64()) {
            (Some(i), _) => Value::from(i),
            (_, Some(u)) => Value::from(u),
            _ => Value::F64(n.as_f64().unwrap_or_default()),
        },
        J::String(s) => Value::from(s.as_str()),
        J::Array(items) => Value::Array(items.iter().map(from_json).collect()),
        J::Object(map) => Value::Map(
            map.iter()
                .map(|(k, v)| (Value::from(k.as_str()), from_json(v)))
                .collect(),
        ),
    }
}

pub fn write_frame(writer: &mut impl Write, id: i64, reply: &Reply) -> Result<()> {
    let mut payload = Vec::new();
    rmp::encode::write_array_len(&mut payload, 3)?;
    rmp::encode::write_sint(&mut payload, id)?;
    let nil = [0xc0u8];
    let (body, error): (&[u8], &[u8]) = match reply {
        Reply::Body(b) => (b, &nil),
        Reply::Error(e) => (&nil, e),
        Reply::Ack => (&nil, &nil),
    };
    payload.extend_from_slice(body);
    payload.extend_from_slice(error);
    let len = u32::try_from(payload.len()).context("frame larger than 4 GiB")?;
    writer.write_all(&len.to_be_bytes())?;
    writer.write_all(&payload)?;
    writer.flush()?;
    Ok(())
}

/// Render a msgpack value as JSON for display, with timestamps as RFC 3339 strings.
pub fn to_json(value: &Value) -> serde_json::Value {
    use serde_json::Value as J;
    match value {
        Value::Nil => J::Null,
        Value::Boolean(b) => J::Bool(*b),
        Value::Integer(i) => i
            .as_i64()
            .map(J::from)
            .or_else(|| i.as_u64().map(J::from))
            .unwrap_or(J::Null),
        Value::F32(f) => J::from(f64::from(*f)),
        Value::F64(f) => J::from(*f),
        Value::String(s) => J::String(s.as_str().map_or_else(|| format!("{s}"), str::to_owned)),
        Value::Binary(b) => J::String(format!("<{} bytes>", b.len())),
        Value::Array(items) => J::Array(items.iter().map(to_json).collect()),
        Value::Map(entries) => J::Object(
            entries
                .iter()
                .map(|(k, v)| {
                    (
                        k.as_str().map_or_else(|| k.to_string(), str::to_owned),
                        to_json(v),
                    )
                })
                .collect(),
        ),
        Value::Ext(-1, _) => match decode::<crate::timestamp::Timestamp>(value) {
            Ok(ts) => J::String(ts.to_string()),
            Err(_) => J::String("<bad timestamp>".into()),
        },
        Value::Ext(kind, data) => J::String(format!("<ext {kind}: {} bytes>", data.len())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writes_body_and_error_slots() {
        let mut buf = Vec::new();
        write_frame(&mut buf, 7, &Reply::Ack).unwrap();
        let frame = read_frame(&mut buf.as_slice()).unwrap().unwrap();
        assert_eq!((frame.id, frame.body, frame.error), (7, None, None));

        let mut buf = Vec::new();
        let err = serde_json::json!({"type": "ErrorResponse", "error": "XCOM_NOT_FOUND"});
        write_frame(&mut buf, 3, &Reply::error(&err).unwrap()).unwrap();
        let frame = read_frame(&mut buf.as_slice()).unwrap().unwrap();
        assert!(frame.body.is_none());
        assert_eq!(
            frame.error.as_ref().and_then(type_of),
            Some("ErrorResponse")
        );
    }

    #[test]
    fn reads_request_frame_with_trailing_fields() {
        let value = Value::Array(vec![
            Value::from(1),
            Value::Map(vec![(Value::from("type"), Value::from("GetVariable"))]),
            Value::Nil,
        ]);
        let mut payload = Vec::new();
        rmpv::encode::write_value(&mut payload, &value).unwrap();
        let mut buf = (payload.len() as u32).to_be_bytes().to_vec();
        buf.extend(payload);
        let frame = read_frame(&mut buf.as_slice()).unwrap().unwrap();
        assert_eq!(frame.body_type(), Some("GetVariable"));
    }

    #[test]
    fn replaces_arg_bindings() {
        let msg = serde_json::json!({"type": "StartupDetails", "ti_context": {"arg_bindings": null, "x": 1}});
        let binding = serde_json::json!({"kind": "literal", "name": "n", "value": [1, 2.5], "apply_map": true});
        let Reply::Body(bytes) =
            encode_with_bindings(&msg, std::slice::from_ref(&binding)).unwrap()
        else {
            panic!()
        };
        let value = rmpv::decode::read_value(&mut bytes.as_slice()).unwrap();
        assert_eq!(
            to_json(&value)["ti_context"],
            serde_json::json!({"x": 1, "arg_bindings": [binding]})
        );
    }

    #[test]
    fn eof_between_frames_is_none() {
        assert!(read_frame(&mut [].as_slice()).unwrap().is_none());
    }
}
