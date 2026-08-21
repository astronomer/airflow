<!--
 Licensed to the Apache Software Foundation (ASF) under one
 or more contributor license agreements.  See the NOTICE file
 distributed with this work for additional information
 regarding copyright ownership.  The ASF licenses this file
 to you under the Apache License, Version 2.0 (the
 "License"); you may not use this file except in compliance
 with the License.  You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing,
 software distributed under the License is distributed on an
 "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 KIND, either express or implied.  See the License for the
 specific language governing permissions and limitations
 under the License.
 -->

# Airflow UI

The React + TypeScript + Vite application served by the Airflow API server.

## Getting started

Setup, the `pnpm` commands, and the directory layout are documented in
[contributing-docs/15_node_environment_setup.rst](../../../../contributing-docs/15_node_environment_setup.rst).

```bash
pnpm install
pnpm dev
```

## Linting and formatting

- **[Oxlint](https://oxc.rs/docs/guide/usage/linter)** (`.oxlintrc.json`) runs most lint
  rules. `pnpm lint` runs it first.
- **ESLint** (`eslint.config.js`, `rules/`) covers only what Oxlint cannot express: the
  type-aware `typescript-eslint` rules, `perfectionist`, `@stylistic`, and the two in-repo
  plugins (`rules/rem.js`, `rules/i18n.js`).
- **[Oxfmt](https://oxc.rs/docs/guide/usage/formatter)** (`.oxfmtrc.json`) formats
  JS/TS/JSON. Run `pnpm format`, or `pnpm format:check` to check without writing.

Install the [`oxc.oxc-vscode`](https://marketplace.visualstudio.com/items?itemName=oxc.oxc-vscode)
extension to get both on save; the repo's `.vscode/settings.json` is already configured.
