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

//! A date-time that crosses the comm socket as a msgpack timestamp (extension type -1).
//!
//! The Python supervisor sends `datetime`s through msgspec, which writes msgpack timestamps, and
//! the SDK runtimes read and write the same: the TypeScript runtime decodes them to `Date` and
//! rejects a string. Human-readable formats (JSON, YAML) see an RFC 3339 string instead.

use std::{fmt, str::FromStr};

use chrono::{DateTime, SecondsFormat, TimeZone, Utc};
use serde::{
    Deserialize, Deserializer, Serialize, Serializer,
    de::{self, SeqAccess, Visitor},
};
use serde_bytes::ByteBuf;

const MSGPACK_EXT_STRUCT_NAME: &str = "_ExtStruct";
const TIMESTAMP_EXT_TYPE: i8 = -1;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Timestamp(pub DateTime<Utc>);

impl Timestamp {
    pub fn now() -> Self {
        Self(Utc::now())
    }

    fn to_ext_bytes(self) -> Vec<u8> {
        let secs = self.0.timestamp();
        let nanos = self.0.timestamp_subsec_nanos();
        if (0..1 << 34).contains(&secs) {
            let packed = (u64::from(nanos) << 34) | secs as u64;
            if packed >> 32 == 0 {
                (packed as u32).to_be_bytes().to_vec()
            } else {
                packed.to_be_bytes().to_vec()
            }
        } else {
            let mut buf = nanos.to_be_bytes().to_vec();
            buf.extend_from_slice(&secs.to_be_bytes());
            buf
        }
    }

    fn from_ext_bytes(bytes: &[u8]) -> Option<Self> {
        let (secs, nanos) = match bytes.len() {
            4 => (i64::from(u32::from_be_bytes(bytes.try_into().ok()?)), 0),
            8 => {
                let packed = u64::from_be_bytes(bytes.try_into().ok()?);
                ((packed & ((1 << 34) - 1)) as i64, (packed >> 34) as u32)
            }
            12 => (
                i64::from_be_bytes(bytes[4..].try_into().ok()?),
                u32::from_be_bytes(bytes[..4].try_into().ok()?),
            ),
            _ => return None,
        };
        Utc.timestamp_opt(secs, nanos).single().map(Self)
    }
}

impl From<DateTime<Utc>> for Timestamp {
    fn from(value: DateTime<Utc>) -> Self {
        Self(value)
    }
}

impl fmt::Display for Timestamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0.to_rfc3339_opts(SecondsFormat::AutoSi, true))
    }
}

impl FromStr for Timestamp {
    type Err = chrono::ParseError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        DateTime::parse_from_rfc3339(s).map(|dt| Self(dt.with_timezone(&Utc)))
    }
}

impl Serialize for Timestamp {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        if serializer.is_human_readable() {
            serializer.collect_str(self)
        } else {
            serializer.serialize_newtype_struct(
                MSGPACK_EXT_STRUCT_NAME,
                &(TIMESTAMP_EXT_TYPE, ByteBuf::from(self.to_ext_bytes())),
            )
        }
    }
}

struct TimestampVisitor;

impl<'de> Visitor<'de> for TimestampVisitor {
    type Value = Timestamp;

    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str("a msgpack timestamp or an RFC 3339 string")
    }

    fn visit_str<E: de::Error>(self, v: &str) -> Result<Timestamp, E> {
        v.parse().map_err(E::custom)
    }

    fn visit_newtype_struct<D: Deserializer<'de>>(self, d: D) -> Result<Timestamp, D::Error> {
        d.deserialize_any(self)
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Timestamp, A::Error> {
        let kind: i8 = seq
            .next_element()?
            .ok_or_else(|| de::Error::invalid_length(0, &self))?;
        let data: ByteBuf = seq
            .next_element()?
            .ok_or_else(|| de::Error::invalid_length(1, &self))?;
        if kind != TIMESTAMP_EXT_TYPE {
            return Err(de::Error::custom(format!(
                "msgpack extension {kind} is not a timestamp"
            )));
        }
        Timestamp::from_ext_bytes(&data)
            .ok_or_else(|| de::Error::custom("malformed msgpack timestamp"))
    }
}

impl<'de> Deserialize<'de> for Timestamp {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        if deserializer.is_human_readable() {
            deserializer.deserialize_str(TimestampVisitor)
        } else {
            deserializer.deserialize_newtype_struct(MSGPACK_EXT_STRUCT_NAME, TimestampVisitor)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_through_msgpack() {
        for value in [
            "2026-11-20T01:02:03Z",
            "2026-11-20T01:02:03.456789Z",
            "1960-01-01T00:00:00.5Z",
            "2600-01-01T00:00:00Z",
        ] {
            let ts: Timestamp = value.parse().unwrap();
            let bytes = rmp_serde::to_vec_named(&ts).unwrap();
            assert_eq!(
                rmp_serde::from_slice::<Timestamp>(&bytes).unwrap(),
                ts,
                "{value}"
            );
        }
    }

    #[test]
    fn encodes_as_msgpack_timestamp_extension() {
        let ts: Timestamp = "2026-11-20T01:02:03Z".parse().unwrap();
        let bytes = rmp_serde::to_vec_named(&ts).unwrap();
        // fixext4 (0xd6), type -1, then the 32-bit seconds.
        assert_eq!(bytes[..2], [0xd6, 0xff]);
        assert_eq!(bytes[2..], (ts.0.timestamp() as u32).to_be_bytes());
    }

    #[test]
    fn uses_rfc3339_in_json() {
        let ts: Timestamp = "2026-11-20T01:02:03Z".parse().unwrap();
        assert_eq!(
            serde_json::to_string(&ts).unwrap(),
            "\"2026-11-20T01:02:03Z\""
        );
    }
}
