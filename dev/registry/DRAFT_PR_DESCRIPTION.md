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

- [Draft PR Description](#draft-pr-description)
  - [Summary](#summary)
  - [Motivation](#motivation)
  - [What's Included](#whats-included)
  - [What's NOT Changed](#whats-not-changed)
  - [Architecture](#architecture)
  - [Pages Overview](#pages-overview)
  - [Follow-up Work (not in this PR)](#follow-up-work-not-in-this-pr)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Draft PR Description

**Title:** Add Provider Registry — searchable catalog of all Airflow providers and modules

---

## Summary

Add an official, auto-generated **Provider Registry** to the Apache Airflow project,
deployed at `airflow.apache.org/registry/`.

- Built with Eleventy (11ty) — thanks to Ash Berlin-Taylor for suggesting and prototyping the approach
- Auto-generates from existing `provider.yaml` files; no manual curation
- Full-text search (Pagefind), category browsing, AIP-95 lifecycle badges, statistics
- JSON API endpoints for programmatic access (useful for AI agents and tooling)
- CI/CD workflow integrated with existing docs publish pipeline
- No changes to provider code, schemas, or core Airflow

## Motivation

With AIP-95 approved, Airflow now has a formal provider lifecycle (incubation,
production, mature, deprecated). That opens the door for accepting more community-built
providers and giving them an official home, while setting clear expectations about
maturity and support. But lifecycle stages only work if users can actually see them.
Right now there's no place on `airflow.apache.org` where someone can browse providers,
check their lifecycle stage, or discover what modules they ship.

This registry fills that gap:

1. **Surface governance visibly** — AIP-95 lifecycle stages are first-class citizens
   in the discovery experience (badges, filters, explore by stage)
2. **Stay in sync automatically** — generates directly from `provider.yaml` files in
   the repo, no separate data pipeline or manual curation
3. **Community-owned** — an official Apache project resource on `airflow.apache.org`

Many of you know the [Astronomer Registry](https://registry.astronomer.io), which has
been the go-to for discovering providers for years. Big thanks to Astronomer and Josh
Fell for building and maintaining it. This new registry is designed to be a
community-owned successor, with the eventual goal of redirecting
`registry.astronomer.io` traffic here once it's stable.

The registry is designed as a **discovery mechanism** — it acts as the front door for
finding providers and modules, then links out to API reference docs and user guides
rather than hosting everything in one place.

Airflow has 99 provider packages with 845 operators, 343 hooks, 161 triggers, 157 sensors,
90 transfers, and dozens of other module types across 7 categories.

## What's Included

### Registry Site (`registry/`)

| Component | Description |
|-----------|-------------|
| **Homepage** | Hero with search, featured providers, new providers, category browse, install widget |
| **Providers page** | Filterable/sortable list with lifecycle filter (stable/incubation/deprecated), category filter, search |
| **Provider detail** | Per-version pages with module tabs, connection types, parameters, dependencies, install commands |
| **Explore page** | Browse by category — Cloud, Databases, AI/ML, Data Processing, Messaging, Orchestration, Data Warehouses |
| **Statistics page** | Module type distribution, lifecycle breakdown, top providers by module count |
| **JSON API** | `/api/providers.json`, `/api/modules.json`, per-provider endpoints |
| **Search** | Cmd+K global search via Pagefind with custom index |

Tech stack: Eleventy 3, Nunjucks templates, Pagefind search, CSS custom properties
(tokens-based theming), progressive enhancement (works without JS).

### Metadata Extraction (`dev/registry/extract_metadata.py`)

Python script that:

1. Walks every `providers/*/provider.yaml`
2. Introspects Python modules via AST parsing — extracts class names, docstrings, and
   module types (all 11 types: operators, hooks, sensors, triggers, transfers, executors,
   notifiers, secrets, logging, bundles, decorators)
3. Fetches download stats from pypistats.org and release dates from PyPI JSON API
4. Resolves provider logos from `docs/integration-logos/` directories
5. Computes quality scores (weighted composite of module count, downloads, docs, breadth)
6. Determines AIP-95 lifecycle stages from `provider.yaml` state field
7. Extracts connection types, parameters, and version compatibility
8. Finds related providers via shared integrations
9. Writes `providers.json`, `modules.json`, `search-index.json`, and per-version data

Only dependency: `pyyaml` (standard in Airflow dev environment).

### CI/CD (`.github/workflows/registry-build.yml`)

- Reusable workflow: extracts metadata, builds site, syncs to S3
- Supports `staging` and `live` destinations
- Called automatically by `publish-docs-to-s3.yml` after docs publish
- Can be triggered manually via `workflow_dispatch`
- Deployment target: `s3://{staging|live}-docs-airflow-apache-org/registry/`

### Provider Logos

Added official logos for 87 of 99 providers sourced from:

- Provider `docs/integration-logos/` directories (existing convention)
- Official brand resources and project websites
- Simple Icons CDN

Logos are stored in `providers/*/docs/integration-logos/` (source) and copied to
`registry/public/logos/` during extraction. Providers without logos display a styled
initial letter.

### Other Changes

- `.gitignore` entries for generated JSON data files
- Updated `publish-docs-to-s3.yml` to include registry build step
- ASF-compliant footer with license and trademark notices

## What's NOT Changed

- No modifications to any provider package code
- No changes to `provider.yaml` schema
- No changes to core Airflow code
- No new Python dependencies for Airflow itself
- No changes to existing documentation build process

## Architecture

```
provider.yaml files ──► extract_metadata.py ──► JSON data files ──► Eleventy build ──► S3
                         (AST parsing,           (providers,         (static HTML,      (CloudFront)
                          PyPI stats,             modules,            Pagefind index)
                          logo resolution)        search-index)
```

### Key Design Decisions

1. **Static site, not a service** — no runtime dependencies, just HTML/CSS/JS served
   from S3 via CloudFront
2. **Auto-generated from `provider.yaml`** — no manual curation needed; adding a new
   provider automatically includes it in the next build
3. **Discovery-focused** — acts as a discovery mechanism and links out to API reference
   and user guides rather than hosting all documentation in one place
4. **Governance-first** — AIP-95 lifecycle stages are surfaced throughout (badges,
   filters, explore sections) to give the provider governance model immediate visibility
5. **Progressive enhancement** — the site works without JavaScript; search and filters
   are layered on top
6. **Integrated with existing CI/CD** — builds alongside docs, shares infrastructure
7. **JSON API for programmatic access** — enables AI agents and external tooling to
   query provider/module data

## Pages Overview

### Homepage

- Hero section with search bar and popular provider links
- Aggregate stats (total providers, modules, downloads, integrations)
- Featured providers (top 4 by quality score)
- New providers (sorted by first PyPI release date)
- Browse by category cards
- Install widget (pip/uv/requirements.txt)

### Providers List

- Searchable, filterable, sortable grid of provider cards
- Each card shows: logo, name, description, module count with type breakdown bar,
  download count, lifecycle badge
- Filters: lifecycle stage (All/Stable/Incubation/Deprecated), category
- Sort: downloads, name, last updated, quality score

### Provider Detail (per version)

- Header with logo, lifecycle badge, install command
- Stats grid: module count, downloads, Airflow compatibility, Python version
- Tabbed module listings by type (operators, hooks, sensors, etc.)
- Connection types with docs links
- Dependencies and optional extras
- Related providers

### Explore

- 7 category cards with descriptions and provider counts
- Top providers by module count
- Incubating providers section
- Links to search and statistics

### Statistics

- Total counts (providers, modules, stable vs incubating)
- Module type distribution with visual bars
- Lifecycle stage distribution
- Top 10 providers ranked by module count across types

## Follow-up Work (not in this PR)

- [ ] `apache/airflow-site` PR for `.htaccess` rewrite and nav link
- [ ] LLM-friendly exports (`llms.txt`) and "Copy for AI" buttons for MCP/AI tooling
- [ ] Redirect `registry.astronomer.io` traffic once the official registry is stable
- [ ] Dark mode CSS polish
- [ ] Explicit categories in `provider.yaml` (replacing keyword matching)
- [ ] Dynamic homepage stats (currently some are hardcoded)
- [ ] Version changelog/diff on provider detail pages

---

*This is a draft. Review and adjust statistics/counts before creating the actual PR,
as they may change as providers are added or updated.*
