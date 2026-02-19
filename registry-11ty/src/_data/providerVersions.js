/*!
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

const fs = require("fs");
const path = require("path");
const providersData = require("./providers.json");
const modulesData = require("./modules.json");

function tryReadJson(filePath) {
  if (!fs.existsSync(filePath)) return null;
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (err) {
    console.warn(`Skipping invalid ${filePath}: ${err.message}`);
    return null;
  }
}

module.exports = function () {
  const result = [];

  // Index modules by provider_id for O(1) lookup
  const modulesByProvider = {};
  for (const m of modulesData.modules) {
    if (!modulesByProvider[m.provider_id]) modulesByProvider[m.provider_id] = [];
    modulesByProvider[m.provider_id].push(m);
  }

  for (const provider of providersData.providers) {
    const latestModules = modulesByProvider[provider.id] || [];
    const latestDir = path.join(__dirname, "versions", provider.id, provider.version);

    // Latest version entry -- data comes from providers.json + modules.json,
    // with optional parameters/connections from versions/{id}/{version}/
    result.push({
      provider,
      version: provider.version,
      isLatest: true,
      versionData: null,
      modules: latestModules,
      parameters: tryReadJson(path.join(latestDir, "parameters.json")),
      connections: tryReadJson(path.join(latestDir, "connections.json")),
      availableVersions: [],
    });

    // Older versions from _data/versions/{id}/{version}/metadata.json
    const allVersions = provider.versions || [provider.version];
    const olderVersions = allVersions.filter(v => v !== provider.version);
    for (const v of olderVersions) {
      const versionDir = path.join(__dirname, "versions", provider.id, v);
      const metadata = tryReadJson(path.join(versionDir, "metadata.json"));
      if (!metadata) continue;

      result.push({
        provider,
        version: v,
        isLatest: false,
        versionData: metadata,
        modules: metadata.modules || [],
        parameters: tryReadJson(path.join(versionDir, "parameters.json")),
        connections: tryReadJson(path.join(versionDir, "connections.json")),
        availableVersions: [],
      });
    }
  }

  // Build the set of versions that have pages, per provider
  const versionsByProvider = {};
  for (const entry of result) {
    const pid = entry.provider.id;
    if (!versionsByProvider[pid]) versionsByProvider[pid] = [];
    versionsByProvider[pid].push(entry.version);
  }
  for (const entry of result) {
    entry.availableVersions = versionsByProvider[entry.provider.id];
  }

  return result;
};
