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
import { createInstance, type i18n as I18n } from "i18next";
import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";

import { i18nBaseOptions } from "src/i18n/config";

// DataTable renders its heading as `t(modelName, { count })`, so i18next derives the plural suffix.
// Nothing else validates these keys: the i18n lint rules only compare locale files against each
// other, and eslint-plugin-i18next only forbids literal strings. A key that lacks `_one`/`_other`
// silently renders a key path or the same word for every count.
const SRC_DIR = path.resolve(import.meta.dirname, "../..");
const LOCALES_DIR = path.resolve(SRC_DIR, "../public/i18n/locales/en");

const collectSourceFiles = (dir: string): Array<string> =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = path.join(dir, entry.name);

    if (entry.isDirectory()) {
      return collectSourceFiles(entryPath);
    }

    return entry.name.endsWith(".tsx") && !entry.name.endsWith(".test.tsx") ? [entryPath] : [];
  });

const findModelNames = (): Array<string> => {
  const found = new Set<string>();

  for (const file of collectSourceFiles(SRC_DIR)) {
    for (const match of fs.readFileSync(file, "utf8").matchAll(/modelName="(?<key>[^"]+)"/gu)) {
      const key = match.groups?.key;

      if (key !== undefined) {
        found.add(key);
      }
    }
  }

  return [...found].sort();
};

const modelNames = findModelNames();

let instance: I18n;

beforeAll(async () => {
  const resources = Object.fromEntries(
    fs
      .readdirSync(LOCALES_DIR)
      .filter((file) => file.endsWith(".json"))
      .map((file) => [
        path.basename(file, ".json"),
        JSON.parse(fs.readFileSync(path.join(LOCALES_DIR, file), "utf8")) as Record<string, unknown>,
      ]),
  );

  instance = createInstance();
  // Use the production options so the test guards the real defaultNS/fallback behaviour
  await instance.init({ ...i18nBaseOptions, lng: "en", resources: { en: resources } });
});

describe("DataTable modelName keys", () => {
  it("finds the modelName props to check", () => {
    expect(modelNames.length).toBeGreaterThan(15);
  });

  it.each(modelNames)("%s resolves to distinct singular and plural labels", (modelName) => {
    const singular = instance.t(modelName, { count: 1 });
    const plural = instance.t(modelName, { count: 2 });
    // DataTable reads this key directly for the count-free label, because no integer count selects
    // `_other` in every language
    const countFreePlural = instance.t(`${modelName}_other`);

    // A missing key comes back as the key itself, minus its namespace
    const keyPath = modelName.includes(":") ? modelName.split(":")[1] : modelName;

    expect(singular).not.toBe(keyPath);
    expect(plural).not.toBe(keyPath);
    expect(countFreePlural).not.toBe(`${keyPath}_other`);
    // Catches title keys used as model names, which have no plural form
    expect(singular).not.toBe(plural);
  });
});
