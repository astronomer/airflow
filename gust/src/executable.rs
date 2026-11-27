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

//! Reader for the executable bundle footer (`task-sdk/docs/executable-bundle-spec.rst`).

use std::{
    fs::File,
    io::{Read, Seek, SeekFrom},
    path::Path,
};

use anyhow::{Context, Result, bail, ensure};
use serde::Deserialize;
use sha2::{Digest, Sha256};

use crate::artifact::Sdk;

const TRAILER_LEN: u64 = 64;
const MAGIC: &[u8; 8] = b"AFBNDL01";
const FOOTER_VERSION: u32 = 1;

#[derive(Debug, Deserialize)]
pub struct Manifest {
    pub sdk: Sdk,
}

/// Read and verify the manifest of a bundle. `Ok(None)` means the file has no bundle trailer.
pub fn read_manifest(path: &Path) -> Result<Option<Manifest>> {
    let mut file = File::open(path).with_context(|| format!("opening {}", path.display()))?;
    let size = file.metadata()?.len();
    if size < TRAILER_LEN {
        return Ok(None);
    }
    let mut trailer = [0u8; TRAILER_LEN as usize];
    file.seek(SeekFrom::End(-(TRAILER_LEN as i64)))?;
    file.read_exact(&mut trailer)?;
    if &trailer[56..64] != MAGIC {
        return Ok(None);
    }
    let u32_at = |i: usize| u32::from_le_bytes(trailer[i..i + 4].try_into().unwrap());
    let (source_len, metadata_len, footer_ver) = (u32_at(0), u32_at(4), u32_at(8));
    ensure!(
        footer_ver == FOOTER_VERSION,
        "unsupported bundle footer version {footer_ver}"
    );

    let metadata_start = (size - TRAILER_LEN)
        .checked_sub(u64::from(metadata_len))
        .context("bundle metadata length runs past the start of the file")?;
    let source_start = metadata_start
        .checked_sub(u64::from(source_len))
        .context("bundle source length runs past the start of the file")?;
    ensure!(source_start > 0, "bundle has an empty binary region");

    file.seek(SeekFrom::Start(0))?;
    let mut hasher = Sha256::new();
    std::io::copy(&mut (&mut file).take(source_start), &mut hasher)?;
    if hasher.finalize().as_slice() != &trailer[12..44] {
        bail!(
            "bundle binary does not match the SHA-256 in its trailer; was it modified after packing?"
        );
    }

    let mut metadata = vec![0u8; metadata_len as usize];
    file.seek(SeekFrom::Start(metadata_start))?;
    file.read_exact(&mut metadata)?;
    let manifest = serde_yaml::from_slice(&metadata).context("parsing bundle manifest")?;
    Ok(Some(manifest))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pack(binary: &[u8], source: &[u8], metadata: &[u8]) -> Vec<u8> {
        let mut out = binary.to_vec();
        out.extend_from_slice(source);
        out.extend_from_slice(metadata);
        out.extend_from_slice(&(source.len() as u32).to_le_bytes());
        out.extend_from_slice(&(metadata.len() as u32).to_le_bytes());
        out.extend_from_slice(&FOOTER_VERSION.to_le_bytes());
        out.extend_from_slice(&Sha256::digest(binary));
        out.extend_from_slice(&[0; 12]);
        out.extend_from_slice(MAGIC);
        out
    }

    fn write_temp(name: &str, bytes: &[u8]) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!("gust-test-{}-{name}", std::process::id()));
        std::fs::write(&path, bytes).unwrap();
        path
    }

    const METADATA: &[u8] = b"airflow_bundle_metadata_version: '1.0'\nsdk:\n  language: go\n  version: 0.1.0\n  supervisor_schema_version: '2026-06-16'\ndags:\n  d:\n    tasks: [t]\n";

    #[test]
    fn reads_manifest() {
        let path = write_temp("ok", &pack(b"\x7fELF...", b"package main", METADATA));
        let manifest = read_manifest(&path).unwrap().unwrap();
        assert_eq!(manifest.sdk.language, "go");
        assert_eq!(manifest.sdk.supervisor_schema_version, "2026-06-16");
    }

    #[test]
    fn plain_file_is_not_a_bundle() {
        let path = write_temp("plain", b"#!/bin/sh\necho hi\n");
        assert!(read_manifest(&path).unwrap().is_none());
    }

    #[test]
    fn rejects_modified_binary() {
        let mut bytes = pack(b"\x7fELF...", b"", METADATA);
        bytes[0] = 0;
        let path = write_temp("tampered", &bytes);
        assert!(read_manifest(&path).is_err());
    }
}
