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

//! Reader for TypeScript bundles built by `airflow-ts-pack`.
//!
//! This follows Airflow's reader (`airflow/sdk/coordinators/node/_bundle_reader.py`), which is
//! ahead of `task-sdk/docs/ts-bundle-spec.rst`: a bundle holds one source region per native Dag
//! file, each opened by `/*# airflowSource:<path>`.

use std::{
    fs::File,
    io::{BufRead, BufReader, Read, Seek, SeekFrom},
    path::Path,
};

use anyhow::{Context, Result, bail, ensure};
use serde_json::Value as Json;
use sha2::{Digest, Sha256};

use crate::artifact::Sdk;

pub const SUFFIX: &str = ".min.mjs";

const LAYOUT_PREFIX: &[u8] = b"//# airflowBundle=";
const MAX_LAYOUT_LINE: usize = 4096;
const METADATA_PREFIX: &[u8] = b"//# airflowMetadata=";
const MAX_METADATA_LINE: usize = 1024 * 1024;
const SOURCE_OPEN_PREFIX: &[u8] = b"/*# airflowSource:";
const SOURCE_CLOSE: &[u8] = b"\n#*/\n";
const MAX_SOURCE: u64 = 1024 * 1024;
const SUPPORTED_MAJOR_VERSION: &str = "1";

/// A byte range, end exclusive, and the SHA-256 its bytes must have.
#[derive(Debug, PartialEq)]
struct Section {
    start: u64,
    end: u64,
    sha256: [u8; 32],
}

struct Layout {
    metadata: Section,
    sources: Vec<(String, Section)>,
    code: Section,
}

/// Read and verify the bundle at `path`, returning the SDK it was built with.
pub fn read_sdk(path: &Path) -> Result<Sdk> {
    let file = File::open(path).with_context(|| format!("opening {}", path.display()))?;
    let size = file.metadata()?.len();
    let mut reader = BufReader::new(file);

    let layout_payload =
        read_prefixed_line(&mut reader, LAYOUT_PREFIX, MAX_LAYOUT_LINE, "bundle layout")?
            .context("it has no airflow bundle layout; build it with airflow-ts-pack")?;
    let layout = parse_layout(&layout_payload)?;
    let metadata = read_prefixed_line(&mut reader, METADATA_PREFIX, MAX_METADATA_LINE, "metadata")?
        .context("it has no embedded airflow metadata after its layout")?;

    let metadata_start =
        (LAYOUT_PREFIX.len() + layout_payload.len() + 1 + METADATA_PREFIX.len()) as u64;
    let metadata_end = metadata_start + metadata.len() as u64;
    ensure!(
        (layout.metadata.start, layout.metadata.end) == (metadata_start, metadata_end),
        "its layout's metadata offsets do not match the metadata section"
    );
    let code_start = check_sources(&mut reader, metadata_end + 1, &layout.sources)?;
    ensure!(
        (layout.code.start, layout.code.end) == (code_start, size),
        "its layout's code offsets do not match the executable section"
    );

    let mut file = reader.into_inner();
    let sections = std::iter::once(("metadata", &layout.metadata))
        .chain(layout.sources.iter().map(|(_, s)| ("source", s)))
        .chain(std::iter::once(("code", &layout.code)));
    for (name, section) in sections {
        file.seek(SeekFrom::Start(section.start))?;
        let mut hasher = Sha256::new();
        std::io::copy(
            &mut (&mut file).take(section.end - section.start),
            &mut hasher,
        )?;
        ensure!(
            hasher.finalize().as_slice() == section.sha256,
            "its {name} section does not match its SHA-256; was it modified after packing?"
        );
    }
    parse_metadata(&metadata)
}

/// One newline-terminated line starting with `prefix`, without the prefix and the newline.
/// `None` when the line does not start with `prefix`.
fn read_prefixed_line(
    reader: &mut impl BufRead,
    prefix: &[u8],
    max: usize,
    section: &str,
) -> Result<Option<Vec<u8>>> {
    let mut line = Vec::new();
    reader.take(max as u64 + 1).read_until(b'\n', &mut line)?;
    if !line.starts_with(prefix) {
        return Ok(None);
    }
    ensure!(
        line.len() <= max,
        "its embedded {section} exceeds {max} bytes"
    );
    ensure!(
        line.ends_with(b"\n"),
        "its embedded {section} is not newline-terminated"
    );
    let payload = line[prefix.len()..line.len() - 1].to_vec();
    // These end a JavaScript comment even inside a JSON string.
    let has_terminator = payload.contains(&b'\r')
        || payload
            .windows(3)
            .any(|w| w == "\u{2028}".as_bytes() || w == "\u{2029}".as_bytes());
    ensure!(
        !has_terminator,
        "its embedded {section} contains a JavaScript line terminator"
    );
    Ok(Some(payload))
}

/// Check each source region's comment markers, returning where the code starts.
fn check_sources(reader: &mut impl Read, start: u64, sources: &[(String, Section)]) -> Result<u64> {
    let mut cursor = start;
    for (path, section) in sources {
        let open = [SOURCE_OPEN_PREFIX, path.as_bytes(), b"\n"].concat();
        ensure!(
            section.start == cursor + open.len() as u64,
            "its layout's source offsets do not match the source section"
        );
        let length = section.end - section.start;
        ensure!(
            length <= MAX_SOURCE,
            "its embedded source exceeds {MAX_SOURCE} bytes"
        );
        let mut opener = vec![0; open.len()];
        let mut payload = vec![0; length as usize];
        let mut closer = [0; SOURCE_CLOSE.len()];
        reader.read_exact(&mut opener)?;
        reader.read_exact(&mut payload)?;
        reader.read_exact(&mut closer)?;
        ensure!(
            opener == open,
            "its embedded source marker does not match its declared path"
        );
        ensure!(
            closer == SOURCE_CLOSE,
            "its embedded source is not closed by its block comment"
        );
        // An unescaped `*/` would end the comment, so bytes called source would run.
        ensure!(
            !payload.windows(2).any(|w| w == b"*/"),
            "its embedded source contains an unescaped block comment terminator"
        );
        cursor = section.end + SOURCE_CLOSE.len() as u64;
    }
    Ok(cursor)
}

fn parse_layout(payload: &[u8]) -> Result<Layout> {
    let layout: Json = serde_json::from_slice(payload).context("cannot parse its bundle layout")?;
    let sources = layout
        .get("sources")
        .and_then(Json::as_array)
        .context("its bundle layout is missing the sources section")?
        .iter()
        .map(|entry| {
            let path = entry
                .get("path")
                .and_then(Json::as_str)
                .filter(|p| !p.is_empty())
                .context("a source path in its bundle layout is not a non-empty string")?;
            Ok((path.to_owned(), parse_section(entry, "source")?))
        })
        .collect::<Result<Vec<_>>>()?;
    let mut paths: Vec<&str> = sources.iter().map(|(p, _)| p.as_str()).collect();
    paths.sort_unstable();
    paths.dedup();
    ensure!(
        paths.len() == sources.len(),
        "its bundle layout declares duplicate source paths"
    );
    let section = |name| {
        parse_section(
            layout
                .get(name)
                .with_context(|| format!("its bundle layout is missing the {name} section"))?,
            name,
        )
    };
    Ok(Layout {
        metadata: section("metadata")?,
        sources,
        code: section("code")?,
    })
}

fn parse_section(section: &Json, name: &str) -> Result<Section> {
    let hex = |field: &str, len: usize| -> Result<&str> {
        section
            .get(field)
            .and_then(Json::as_str)
            .filter(|s| s.len() == len && s.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f')))
            .with_context(|| {
                format!(
                    "its bundle layout's {name}.{field} is not {len} lowercase hexadecimal digits"
                )
            })
    };
    let start = u64::from_str_radix(hex("start", 16)?, 16)?;
    let end = u64::from_str_radix(hex("end", 16)?, 16)?;
    ensure!(start < end, "its bundle layout's {name} section is empty");
    let digest = hex("sha256", 64)?;
    let mut sha256 = [0; 32];
    for (i, byte) in sha256.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&digest[i * 2..i * 2 + 2], 16)?;
    }
    Ok(Section { start, end, sha256 })
}

fn parse_metadata(payload: &[u8]) -> Result<Sdk> {
    let metadata: Json = serde_json::from_slice(payload).context("cannot parse its metadata")?;
    let version = metadata.get("airflow_bundle_metadata_version");
    let supported = version.and_then(Json::as_str).is_some_and(|v| {
        let parts: Vec<&str> = v.split('.').collect();
        (2..=3).contains(&parts.len())
            && parts
                .iter()
                .all(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()))
            && match parts[0].trim_start_matches('0') {
                "" => "0",
                major => major,
            } == SUPPORTED_MAJOR_VERSION
    });
    if !supported {
        bail!(
            "its metadata version {} is not supported; gust reads major version {SUPPORTED_MAJOR_VERSION}",
            version.map_or("(missing)".into(), Json::to_string)
        );
    }
    ensure!(
        metadata.get("task_handlers").is_some_and(Json::is_object),
        "its metadata has no task_handlers mapping"
    );
    let sdk = metadata
        .get("sdk")
        .context("its metadata has no sdk mapping")?;
    let field = |key: &str| {
        sdk.get(key)
            .and_then(Json::as_str)
            .filter(|s| !s.is_empty())
    };
    Ok(Sdk {
        language: field("language").unwrap_or("typescript").to_owned(),
        version: field("version").map(str::to_owned),
        supervisor_schema_version: field("supervisor_schema_version")
            .context("its metadata has no sdk.supervisor_schema_version")?
            .to_owned(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(bytes: &[u8]) -> String {
        Sha256::digest(bytes)
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect()
    }

    /// Lay a bundle out the way `airflow-ts-pack` does.
    fn pack(metadata: &str, sources: &[(&str, &str)], code: &str) -> Vec<u8> {
        let section = |start: usize, bytes: &[u8]| {
            format!(
                r#"{{"start":"{start:016x}","end":"{:016x}","sha256":"{}"}}"#,
                start + bytes.len(),
                hex(bytes)
            )
        };
        // The layout's length does not depend on the offsets, which are fixed width.
        let layout_len = |sources_json: &str| {
            format!(
                r#"{{"metadata":{},"sources":[{sources_json}],"code":{}}}"#,
                section(0, b""),
                section(0, b"")
            )
            .len()
        };
        let mut placeholder = Vec::new();
        for (path, text) in sources {
            placeholder.push(format!(
                r#"{{"path":"{path}",{}"#,
                &section(0, text.as_bytes())[1..]
            ));
        }
        let layout_size = LAYOUT_PREFIX.len() + layout_len(&placeholder.join(",")) + 1;
        let metadata_start = layout_size + METADATA_PREFIX.len();
        let mut cursor = metadata_start + metadata.len() + 1;
        let mut body = Vec::new();
        let mut entries = Vec::new();
        for (path, text) in sources {
            let open = format!("/*# airflowSource:{path}\n");
            cursor += open.len();
            entries.push(format!(
                r#"{{"path":"{path}",{}"#,
                &section(cursor, text.as_bytes())[1..]
            ));
            body.extend_from_slice(open.as_bytes());
            body.extend_from_slice(text.as_bytes());
            body.extend_from_slice(SOURCE_CLOSE);
            cursor += text.len() + SOURCE_CLOSE.len();
        }
        let layout = format!(
            r#"{{"metadata":{},"sources":[{}],"code":{}}}"#,
            section(metadata_start, metadata.as_bytes()),
            entries.join(","),
            section(cursor, code.as_bytes())
        );
        let mut out = [
            LAYOUT_PREFIX,
            layout.as_bytes(),
            b"\n",
            METADATA_PREFIX,
            metadata.as_bytes(),
            b"\n",
        ]
        .concat();
        out.extend(body);
        out.extend_from_slice(code.as_bytes());
        out
    }

    const METADATA: &str = r#"{"airflow_bundle_metadata_version":"1.0","sdk":{"language":"typescript","version":"1.0.0","supervisor_schema_version":"2026-06-16"},"task_handlers":{}}"#;

    fn write_temp(name: &str, bytes: &[u8]) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!("gust-node-{}-{name}", std::process::id()));
        std::fs::write(&path, bytes).unwrap();
        path
    }

    #[test]
    fn reads_a_packed_bundle() {
        let bytes = pack(
            METADATA,
            &[("main.ts", "export {};"), ("dags/a.ts", "x")],
            "console.log(1);\n",
        );
        let sdk = read_sdk(&write_temp("ok.min.mjs", &bytes)).unwrap();
        assert_eq!(sdk.supervisor_schema_version, "2026-06-16");
        assert_eq!(sdk.version.as_deref(), Some("1.0.0"));
    }

    #[test]
    fn rejects_an_unpacked_module() {
        let err = read_sdk(&write_temp("plain.min.mjs", b"export const x = 1;\n")).unwrap_err();
        assert!(err.to_string().contains("airflow-ts-pack"), "{err}");
    }

    #[test]
    fn rejects_modified_code() {
        let mut bytes = pack(METADATA, &[("main.ts", "export {};")], "console.log(1);\n");
        let last = bytes.len() - 3;
        bytes[last] = b'2';
        let err = read_sdk(&write_temp("tampered.min.mjs", &bytes)).unwrap_err();
        assert!(err.to_string().contains("code section"), "{err}");
    }

    #[test]
    fn rejects_an_unescaped_comment_end_in_source() {
        let bytes = pack(METADATA, &[("main.ts", "a */ b")], "1;\n");
        let err = read_sdk(&write_temp("escape.min.mjs", &bytes)).unwrap_err();
        assert!(err.to_string().contains("unescaped"), "{err}");
    }

    #[test]
    fn rejects_another_major_version() {
        let metadata = METADATA.replace(r#""1.0""#, r#""2.0""#);
        let bytes = pack(&metadata, &[], "1;\n");
        let err = read_sdk(&write_temp("v2.min.mjs", &bytes)).unwrap_err();
        assert!(err.to_string().contains("not supported"), "{err}");
    }
}
