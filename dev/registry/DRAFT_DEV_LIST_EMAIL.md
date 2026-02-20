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

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Draft Email: [DISCUSS] Apache Airflow Provider Registry](#draft-email-discuss-apache-airflow-provider-registry)
  - [Background](#background)
  - [The Problem](#the-problem)
  - [The Solution](#the-solution)
  - [Remaining Work](#remaining-work)
  - [Try It Locally](#try-it-locally)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Draft Email: [DISCUSS] Apache Airflow Provider Registry

**To:** dev@airflow.apache.org
**Subject:** [DISCUSS] Apache Airflow Provider Registry — a searchable catalog of all providers and modules

---

Hi everyone,

I'd like to propose adding an official **Provider Registry** to the Apache Airflow
project — a searchable, static catalog of all Airflow providers and their modules,
deployed at `airflow.apache.org/registry/`.

## Background

Many of you are familiar with the [Astronomer Registry](https://registry.astronomer.io),
which has served as the primary discovery hub for Airflow providers for several years.
As we roll out the new **provider governance model** (AIP-95 lifecycle stages —
incubation, production, mature, deprecated), we need proper tooling under the Apache
project to surface these stages and give the governance work immediate visibility.

This new registry is designed to **replace the Astronomer Registry** with an
official, community-owned alternative hosted on `airflow.apache.org`. The key
differences from the Astronomer Registry:

- **Owned by the Apache Airflow project** — not a third-party dependency
- **Auto-generated from `provider.yaml`** — always in sync with the repo, no manual
  curation or separate data pipeline
- **Built to surface AIP-95 governance** — lifecycle stages are first-class citizens
  in the UI (filter, badge, explore by stage)
- **Discovery-focused** — acts as a discovery mechanism and links out to API reference
  and user guides, rather than trying to host everything in one place
- **Mobile-friendly** and progressively enhanced (works without JavaScript)

## The Problem

Airflow has **99 provider packages** containing **1,648 modules** (operators, hooks,
sensors, triggers, transfers, executors, notifiers, and more). Today, discovering what's
available requires reading individual provider docs, searching PyPI, or browsing the
source tree. There's no official Apache-hosted place to:

- Search across all providers and modules in one place
- Compare providers by module count, download popularity, or lifecycle stage
- Explore providers by category (Cloud, Databases, AI/ML, etc.)
- See at a glance which providers are stable, incubating, or deprecated (AIP-95)

## The Solution

The Provider Registry is a **static site** built with [Eleventy](https://www.11ty.dev/)
that auto-generates from the existing `provider.yaml` files in the repo. No manual
curation required — when a provider is added or updated, the registry picks it up
automatically.

### Key Features

| Feature | Description |
|---------|-------------|
| **Full-text search** | Cmd+K search across all providers and modules (powered by Pagefind) |
| **Provider cards** | Each provider shows module counts, download stats, lifecycle stage, and a visual breakdown of module types |
| **Category browsing** | Explore by use case: Cloud Platforms, Databases, AI & ML, Data Processing, Messaging, Orchestration, Data Warehouses |
| **Statistics page** | Aggregate stats — module type distribution, lifecycle breakdown, top providers by module count |
| **Provider detail pages** | Per-version pages with module listings, connection types, dependencies, install commands, and parameters |
| **AIP-95 lifecycle badges** | Visual indicators for incubation/stable/deprecated status |
| **JSON API endpoints** | Programmatic access at `/api/providers.json`, `/api/modules.json`, etc. — useful for AI agents and tooling |
| **Dark/light mode** | Theme toggle with CSS custom properties |
| **Zero JS requirement** | Works without JavaScript; search and filters are progressive enhancement |

### Module Types Tracked

The registry extracts and displays all 11 module types from providers:

- Operators (845), Hooks (343), Triggers (161), Sensors (157), Transfers (90)
- Decorators (17), Notifiers (12), Logging handlers (9), Secret backends (6),
  Executors (5), DAG Bundles (3)

### How It Works

```
provider.yaml files (providers/*/provider.yaml)
        │
        ▼
extract_metadata.py     ← Parses YAML, introspects Python modules via AST,
        │                  fetches PyPI stats/dates, resolves logos, computes
        │                  quality scores, determines AIP-95 lifecycle
        ▼
registry/src/_data/     ← Generated JSON files
        │
        ▼
Eleventy build          ← Generates static HTML + Pagefind search index
        │
        ▼
S3 / CloudFront         ← Deployed to airflow.apache.org/registry/
```

The extraction script:

1. Walks every `providers/*/provider.yaml`
2. Introspects Python modules via AST parsing to extract class names and docstrings
3. Fetches download stats from pypistats.org and release dates from PyPI
4. Resolves provider logos from `docs/integration-logos/` directories
5. Computes a quality score (weighted composite of module count, downloads, docs, breadth)
6. Writes `providers.json`, `modules.json`, and `search-index.json`

### CI/CD Integration

- **Automated builds**: A reusable GitHub Actions workflow (`registry-build.yml`)
  extracts metadata, builds the site, and syncs to S3
- **Integrated with docs pipeline**: The existing `publish-docs-to-s3.yml` workflow
  calls the registry build as a post-publish step
- **Manual trigger**: Can be rebuilt independently via `workflow_dispatch`

### What's in the PR

The PR adds:

- `registry/` — Eleventy site (templates, CSS, JS, config)
- `dev/registry/extract_metadata.py` — Metadata extraction script
- `.github/workflows/registry-build.yml` — CI/CD workflow
- Provider logos in `providers/*/docs/integration-logos/`
- Updates to `.github/workflows/publish-docs-to-s3.yml` for integration
- Updates to `.gitignore` for generated data files

### What's NOT Changed

- No changes to any provider code, `provider.yaml` schemas, or core Airflow
- No new Python dependencies for Airflow itself (extraction uses only `pyyaml`)
- No changes to existing documentation build

## Remaining Work

A few items are tracked as future enhancements:

- **`apache/airflow-site` PR** needed to add `.htaccess` rewrite for `/registry/*`
  and a navigation link in the site header
- **LLM-friendly exports** — `llms.txt` and "Copy for AI" buttons for use with MCP
  servers, AI CLI tools, and IDEs
- **Dark mode** CSS may need polish across all components
- **Category definitions** in `provider.yaml` (currently keyword-based matching)
- **Dynamic homepage stats** (some counters are currently hardcoded)
- **Deprecate Astronomer Registry** — once the official registry is live, the
  Astronomer Registry at `registry.astronomer.io` can be sunset

## Try It Locally

```bash
# Extract metadata
python dev/registry/extract_metadata.py

# Install and run
cd registry && pnpm install && pnpm dev
# Open http://localhost:8080
```

I'd love to hear your thoughts on the approach, feature set, and any concerns before
we merge this. Happy to set up a staging deployment for review.

Thanks,
Kaxil

---

*This is a draft. Please review and adjust before sending.*
