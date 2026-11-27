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

//! Recognising the Dag file gust was given, and how to start it.
//!
//! Each kind is recognised by one test, tried in a fixed order. Once a test matches, gust commits
//! to that kind: a file that then fails the kind's checks is an error, never tried as the next
//! kind.

use std::{
    ffi::OsString,
    fs::{self, File},
    io::Read,
    path::{Path, PathBuf},
};

use anyhow::{Context, Result, bail, ensure};
use serde::{Deserialize, Serialize};

use crate::{executable, jar, node};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Sdk {
    pub language: String,
    pub version: Option<String>,
    pub supervisor_schema_version: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Executable,
    Node,
    Java,
}

#[derive(Debug)]
pub struct Artifact {
    pub kind: Kind,
    /// The path as given, which is what the runtime receives.
    pub path: PathBuf,
    /// The SDK the artifact declares.
    pub sdk: Option<Sdk>,
}

impl Artifact {
    /// Recognise and check the Dag file at `path`.
    pub fn inspect(path: &Path) -> Result<Self> {
        let metadata =
            fs::metadata(path).with_context(|| format!("cannot find {}", path.display()))?;
        let found = |kind, sdk| {
            Ok(Self {
                kind,
                path: path.to_owned(),
                sdk,
            })
        };
        ensure!(
            !metadata.is_dir(),
            "{} is a directory; gust takes one Dag file",
            path.display()
        );

        let describe =
            |e: anyhow::Error| e.context(format!("{} is not a usable bundle", path.display()));
        if let Some(manifest) = executable::read_manifest(path).map_err(describe)? {
            ensure!(
                is_executable(&metadata),
                "{} has an executable bundle trailer but is not executable; run `chmod +x` on it",
                path.display()
            );
            return found(Kind::Executable, Some(manifest.sdk));
        }
        let name = path.file_name().unwrap_or_default().to_string_lossy();
        if name.ends_with(node::SUFFIX) {
            let sdk = node::read_sdk(path)
                .with_context(|| format!("{} is not a usable TypeScript bundle", path.display()))?;
            return found(Kind::Node, Some(sdk));
        }
        if let Ok(mut archive) = zip::ZipArchive::new(File::open(path)?) {
            let attributes = match archive.by_name(jar::MANIFEST_NAME) {
                Ok(mut entry) => {
                    let mut data = Vec::new();
                    entry.read_to_end(&mut data)?;
                    Some(jar::parse_main_attributes(&data))
                }
                Err(_) => None,
            };
            if let Some(attributes) = &attributes
                && attributes.contains_key(jar::MAIN_CLASS)
            {
                let version = attributes.get(jar::SUPERVISOR_SCHEMA_VERSION).with_context(|| {
                    format!(
                        "{} sets no Airflow-Supervisor-Schema-Version; gust runs only fat Jars, \
                         which the Gradle plugin builds by default",
                        path.display()
                    )
                })?;
                return found(
                    Kind::Java,
                    Some(Sdk {
                        language: "java".into(),
                        version: None,
                        supervisor_schema_version: version.clone(),
                    }),
                );
            }
            if attributes.is_some() {
                bail!(
                    "{} is a Jar whose manifest sets no Main-Class",
                    path.display()
                );
            }
        }
        bail!(
            "gust cannot run {}. It takes an executable with an Airflow bundle trailer, a {} \
             built by airflow-ts-pack, or a fat Jar",
            path.display(),
            node::SUFFIX,
        )
    }

    /// Check that `runtime` can start this artifact.
    pub fn check_runtime(&self, runtime: Option<&[String]>) -> Result<()> {
        let example = match self.kind {
            Kind::Executable => return Ok(()),
            Kind::Node => "node",
            Kind::Java => "java -jar",
        };
        let Some(runtime) = runtime else {
            bail!(
                "{} needs a runtime to start it, such as `--runtime \"{example}\"`",
                self.path.display()
            );
        };
        if self.kind == Kind::Java && runtime.last().map(String::as_str) != Some("-jar") {
            bail!(
                "java does not take a Jar as its main class; end the runtime with -jar, such as \
                 `--runtime \"{example}\"`"
            );
        }
        Ok(())
    }

    /// The program and arguments that start this artifact, before `--comm` and `--logs`.
    pub fn build_command(&self, runtime: Option<&[String]>) -> Vec<OsString> {
        let mut command: Vec<OsString> =
            runtime.into_iter().flatten().map(OsString::from).collect();
        command.push(self.path.clone().into());
        command
    }
}

#[cfg(unix)]
fn is_executable(metadata: &fs::Metadata) -> bool {
    use std::os::unix::fs::PermissionsExt;
    metadata.permissions().mode() & 0o111 != 0
}

#[cfg(not(unix))]
fn is_executable(_: &fs::Metadata) -> bool {
    true
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use zip::write::SimpleFileOptions;

    use super::*;

    fn temp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("gust-artifact-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        dir.join(name)
    }

    fn write_zip(name: &str, entries: &[(&str, &str)]) -> PathBuf {
        let path = temp(name);
        let mut zip = zip::ZipWriter::new(File::create(&path).unwrap());
        for (entry, content) in entries {
            zip.start_file(*entry, SimpleFileOptions::default())
                .unwrap();
            zip.write_all(content.as_bytes()).unwrap();
        }
        zip.finish().unwrap();
        path
    }

    fn inspect_err(path: &Path) -> String {
        format!("{:#}", Artifact::inspect(path).unwrap_err())
    }

    #[test]
    fn fat_jars_only() {
        let fat = write_zip(
            "fat.bin",
            &[(
                jar::MANIFEST_NAME,
                "Main-Class: a.Main\nAirflow-Supervisor-Schema-Version: 2026-06-16\n",
            )],
        );
        let artifact = Artifact::inspect(&fat).unwrap();
        assert_eq!(artifact.kind, Kind::Java);
        assert_eq!(
            artifact.sdk.unwrap().supervisor_schema_version,
            "2026-06-16"
        );

        let thin = write_zip("thin.jar", &[(jar::MANIFEST_NAME, "Main-Class: a.Main\n")]);
        assert!(inspect_err(&thin).contains("fat Jars"));
        let library = write_zip(
            "lib.jar",
            &[(jar::MANIFEST_NAME, "Manifest-Version: 1.0\n")],
        );
        assert!(inspect_err(&library).contains("sets no Main-Class"));
    }

    #[test]
    fn unknown_files_are_rejected() {
        let script = temp("dag.mjs");
        fs::write(&script, "export {};").unwrap();
        assert!(inspect_err(&script).contains("gust cannot run"));
        let unpacked = temp("dag.min.mjs");
        fs::write(&unpacked, "export {};").unwrap();
        assert!(inspect_err(&unpacked).contains("airflow-ts-pack"));
        let plain = write_zip("plain.zip", &[("dag.py", "")]);
        assert!(inspect_err(&plain).contains("gust cannot run"));
        let dir = temp("dags");
        fs::create_dir_all(&dir).unwrap();
        assert!(inspect_err(&dir).contains("is a directory"));
        assert!(inspect_err(&temp("missing")).contains("cannot find"));
    }

    #[test]
    fn runtimes_are_checked_per_kind() {
        let artifact = |kind| Artifact {
            kind,
            path: "x".into(),
            sdk: None,
        };
        let words = |s: &[&str]| s.iter().map(|w| (*w).to_owned()).collect::<Vec<_>>();
        assert!(artifact(Kind::Executable).check_runtime(None).is_ok());
        assert!(artifact(Kind::Node).check_runtime(None).is_err());
        let java = artifact(Kind::Java);
        assert!(
            java.check_runtime(Some(&words(&["java", "-Xmx1g", "-jar"])))
                .is_ok()
        );
        assert!(
            java.check_runtime(Some(&words(&["java"])))
                .unwrap_err()
                .to_string()
                .contains("-jar")
        );
    }
}
