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

//! Reading Jar manifests as the Jar File Specification defines them.

use std::collections::BTreeMap;

pub const MANIFEST_NAME: &str = "META-INF/MANIFEST.MF";
pub const MAIN_CLASS: &str = "main-class";
pub const SUPERVISOR_SCHEMA_VERSION: &str = "airflow-supervisor-schema-version";

/// The main-section attributes of a manifest, keyed by lower-cased name.
///
/// Lines end with CRLF, LF or CR, a line starting with one space continues the previous value,
/// and the main section ends at the first blank line.
pub fn parse_main_attributes(data: &[u8]) -> BTreeMap<String, String> {
    let mut headers: Vec<Vec<u8>> = Vec::new();
    let mut rest = data;
    while !rest.is_empty() {
        let end = rest
            .iter()
            .position(|&b| b == b'\r' || b == b'\n')
            .unwrap_or(rest.len());
        let line = &rest[..end];
        rest = &rest[end..];
        rest = rest
            .strip_prefix(b"\r\n")
            .or_else(|| rest.strip_prefix(b"\r"))
            .or_else(|| rest.strip_prefix(b"\n"))
            .unwrap_or(rest);
        if line.is_empty() {
            break;
        }
        // Lines are folded by bytes, which can split a character, so unfold before decoding.
        match (line.strip_prefix(b" "), headers.last_mut()) {
            (Some(continued), Some(last)) => last.extend_from_slice(continued),
            (Some(_), None) => {}
            (None, _) => headers.push(line.to_vec()),
        }
    }
    headers
        .iter()
        .filter_map(|header| {
            let header = String::from_utf8_lossy(header);
            let (name, value) = header.split_once(':')?;
            Some((
                name.trim().to_lowercase(),
                value.strip_prefix(' ').unwrap_or(value).to_owned(),
            ))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_folded_main_attributes() {
        let attributes = parse_main_attributes(
            b"Manifest-Version: 1.0\r\nMain-Class: com.example.Ma\r\n in\r\nAirflow-Supervisor-Schema-Version: 2026-06-16\r\n\r\nName: other\r\nMain-Class: no\r\n",
        );
        assert_eq!(attributes[MAIN_CLASS], "com.example.Main");
        assert_eq!(attributes[SUPERVISOR_SCHEMA_VERSION], "2026-06-16");
        assert_eq!(attributes.len(), 3);
    }
}
