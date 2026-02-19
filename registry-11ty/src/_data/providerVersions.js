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

    // Latest version entry -- data comes from providers.json + modules.json
    result.push({
      provider,
      version: provider.version,
      isLatest: true,
      versionData: null,
      modules: latestModules,
      availableVersions: [],
    });

    // Older versions from _data/versions/{id}/{version}.json
    const allVersions = provider.versions || [provider.version];
    for (const v of allVersions.slice(1)) {
      const dataPath = path.join(__dirname, "versions", provider.id, `${v}.json`);
      if (fs.existsSync(dataPath)) {
        let data;
        try {
          data = JSON.parse(fs.readFileSync(dataPath, "utf8"));
        } catch (err) {
          console.warn(`Skipping invalid ${dataPath}: ${err.message}`);
          continue;
        }
        result.push({
          provider,
          version: v,
          isLatest: false,
          versionData: data,
          modules: data.modules || [],
          availableVersions: [],
        });
      }
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
