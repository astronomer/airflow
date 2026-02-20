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

# Apache Airflow Provider Registry

A searchable catalog of all Apache Airflow providers and their modules (operators,
hooks, sensors, triggers, transfers, and more). Built with [Eleventy](https://www.11ty.dev/)
and deployed to `airflow.apache.org/registry/`.

## Quick Start

### Prerequisites

- Python 3.10+ (for metadata extraction)
- Node.js 20+ and pnpm 9+
- `pyyaml` Python package (`pip install pyyaml`)

### Local Development

```bash
# 1. Extract metadata from provider.yaml files into JSON
python dev/registry/extract_metadata.py

# 2. Install Node.js dependencies
cd registry
pnpm install

# 3. Start dev server (http://localhost:8080)
pnpm dev
```

The `dev` script sets `REGISTRY_PATH_PREFIX=/` so links work at the root during local
development. In production the prefix defaults to `/registry/`.

## Architecture

### Data Pipeline

```
provider.yaml files (providers/*/provider.yaml)
        │
        ▼
extract_metadata.py          ← Parses YAML, introspects Python modules,
        │                       fetches PyPI stats, resolves logos
        ▼
registry/src/_data/
  ├── providers.json         ← Provider metadata (name, versions, downloads, lifecycle, ...)
  ├── modules.json           ← Individual modules (operators, hooks, sensors, ...)
  ├── search-index.json      ← Flat records consumed by Pagefind indexer
  └── versions/{id}/{ver}/   ← Per-version metadata, parameters, connections
        │
        ▼
Eleventy build (pnpm build)  ← Generates static HTML + Pagefind search index
        │
        ▼
registry/_site/              ← Deployable static site
```

The three root-level JSON files (`providers.json`, `modules.json`, `search-index.json`)
are generated artifacts and are listed in `.gitignore`. The `versions/` directory is also
gitignored. Only `exploreCategories.js`, `statsData.js`, `latestVersionData.js`, and
`providerVersions.js` are checked in because they contain hand-authored or computed logic.

### Extraction Script (`dev/registry/extract_metadata.py`)

The script walks every `providers/*/provider.yaml` and:

1. **Parses provider metadata** — name, description, versions, dependencies
2. **Introspects Python modules** — walks the `operators/`, `hooks/`, `sensors/`,
   `triggers/`, `transfers/`, `notifications/`, `secrets/`, `log/`, `executors/`, and
   `decorators/` sections of `provider.yaml`, locates the corresponding `.py` files, and
   extracts class names and docstrings via AST parsing
3. **Fetches PyPI download stats** — calls `pypistats.org/api/packages/{name}/recent`
4. **Resolves logos** — checks `public/logos/` for matching images
5. **Computes a quality score** — weighted composite of module count, download volume,
   documentation completeness, and integration breadth
6. **Determines AIP-95 lifecycle stage** — reads `state` from `provider.yaml`
   (`suspended → deprecated`, otherwise maps to `incubation`/`production`/`mature`)
7. **Writes JSON** — `providers.json`, `modules.json`, `search-index.json`, and
   per-version files under `versions/`

### Eleventy Data Files (`src/_data/`)

| File | Type | Purpose |
|---|---|---|
| `providers.json` | Generated | All providers with metadata, sorted by quality score |
| `modules.json` | Generated | All extracted modules (operators, hooks, etc.) |
| `search-index.json` | Generated | Flat records for Pagefind custom indexing |
| `versions/` | Generated | Per-provider, per-version metadata/parameters/connections |
| `exploreCategories.js` | Checked-in | Category definitions with keyword lists for the Explore page |
| `statsData.js` | Checked-in | Computed statistics (lifecycle counts, top providers, etc.) |
| `providerVersions.js` | Checked-in | Builds the provider × version page collection |
| `latestVersionData.js` | Checked-in | Latest version parameters/connections lookup |

### Pages

| Page | Template | URL |
|---|---|---|
| Home | `src/index.njk` | `/` |
| All Providers | `src/providers.njk` | `/providers/` |
| Explore by Category | `src/explore.njk` | `/explore/` |
| Statistics | `src/stats.njk` | `/stats/` |
| Provider Detail | `src/provider-detail.njk` | `/providers/{id}/` (redirects to latest) |
| Provider Version | `src/provider-version.njk` | `/providers/{id}/{version}/` |

### Client-Side JavaScript

| Script | Purpose |
|---|---|
| `js/provider-filters.js` | Search, lifecycle filter, category filter, sort on `/providers/` |
| `js/search.js` | Global search modal (Cmd+K) powered by Pagefind |
| `js/provider-detail.js` | Module tabs, copy-to-clipboard on provider version pages |
| `js/install-widget.js` | pip/uv/requirements toggle on homepage |
| `js/copy-button.js` | Generic copy button utility |
| `js/theme.js` | Dark/light mode toggle |
| `js/mobile-menu.js` | Responsive navigation |

### Path Prefix / Deployment

The site is deployed under `/registry/` on `airflow.apache.org`. Eleventy's `pathPrefix`
is configured via the `REGISTRY_PATH_PREFIX` environment variable:

- **Production**: `REGISTRY_PATH_PREFIX=/registry/` (the default)
- **Local dev**: `REGISTRY_PATH_PREFIX=/` (set automatically by `pnpm dev`)

All internal links in templates use the `| url` Nunjucks filter, which prepends the
prefix. Client-side JavaScript accesses the base path via `window.__REGISTRY_BASE__`
(injected in `base.njk`).

### Search

Full-text search is powered by [Pagefind](https://pagefind.app/). During `postbuild`:

1. `scripts/build-pagefind-index.mjs` creates a Pagefind index with custom records from
   `search-index.json` (providers and modules)
2. URLs in the index are prefixed with `REGISTRY_PATH_PREFIX`
3. The client loads Pagefind lazily on first search interaction (`js/search.js`)

## Key Concepts

### Provider Lifecycle (AIP-95)

Providers follow the AIP-95 lifecycle stages:

| Stage | Meaning |
|---|---|
| `incubation` | New provider, API may change |
| `production` / `stable` | Stable, recommended for use |
| `mature` | Well-established, widely adopted |
| `deprecated` | No longer maintained, consider alternatives |

The UI displays `stable` for both `production` and `mature` stages.

### Categories

The Explore page and provider filtering use categories defined in
`src/_data/exploreCategories.js`. Each category has:

- `id` — URL-safe identifier (e.g., `cloud`, `databases`, `ai-ml`)
- `name` — Display name
- `keywords` — List of substrings matched against `provider.id`
- `icon`, `color`, `description` — Visual properties

Providers are assigned to categories at build time by checking if any keyword in a
category matches (substring) the provider's ID. A provider can belong to multiple
categories.

### Homepage "New Providers" Section

The homepage has a "New Providers" section powered by dates fetched from the PyPI JSON
API during extraction. It shows providers sorted by `first_released` (the upload date
of their earliest PyPI release) descending, highlighting providers that are new to the
ecosystem.

### API Endpoints

The `src/api/` directory contains Eleventy templates that generate JSON API endpoints,
providing programmatic access to provider and module data:

- `/api/providers.json` — All providers
- `/api/modules.json` — All modules
- `/api/providers/{id}/modules.json` — Modules for a specific provider
- `/api/providers/{id}/parameters.json` — Parameters for a provider
- `/api/providers/{id}/connections.json` — Connection types
- `/api/providers/{id}/{version}/modules.json` — Version-specific modules
- `/api/providers/{id}/{version}/parameters.json` — Version-specific parameters
- `/api/providers/{id}/{version}/connections.json` — Version-specific connections

## CI/CD

### Workflows

- **`.github/workflows/registry-build.yml`** — Reusable workflow that extracts metadata,
  builds the site, and syncs to S3. Supports `staging` and `live` destinations.
- **`.github/workflows/publish-docs-to-s3.yml`** — Main docs workflow that calls
  `registry-build.yml` as a post-publish job.

### Manual Trigger

The registry can be rebuilt independently via `workflow_dispatch` on `registry-build.yml`.
Only designated committers can trigger manual builds.

### Deployment Target

The built site is synced to:

- **Staging**: `s3://staging-docs-airflow-apache-org/registry/`
- **Live**: `s3://live-docs-airflow-apache-org/registry/`

## Adding a New Provider

No registry-specific changes are needed. When `extract_metadata.py` runs during CI, it
automatically discovers all providers under `providers/*/provider.yaml`. To ensure your
provider appears well in the registry:

1. **Complete `provider.yaml`** — include description, integrations with `how-to-guide`
   links, and logo references
2. **Add a logo** — place a PNG/SVG in `registry/public/logos/{provider-id}-{Name}.png`
3. **Write docstrings** — the extraction script uses AST parsing to pull class-level
   docstrings for module descriptions
4. **Publish to PyPI** — download stats are fetched automatically

## Development Tips

- Run `python dev/registry/extract_metadata.py` whenever provider metadata changes
- The `pnpm dev` command runs both the Eleventy build and starts a live-reload dev server
- CSS uses custom properties defined in `src/css/tokens.css` for theming
- The site works without JavaScript (progressive enhancement); filters and search are
  layered on top via `js/` scripts

## Future Enhancements / TODO

### Data & Metadata

- [ ] **Define categories in `provider.yaml`** — Categories are currently assigned via
  keyword substring matching in `exploreCategories.js`, which is fragile and leaves ~45%
  of providers uncategorized. Adding an explicit `categories` field to `provider.yaml`
  would be more accurate, maintainable, and let provider authors self-classify.

- [ ] **Compute homepage stats dynamically** — The "293M+ Monthly Downloads" and "229+
  Integrations" counters on the homepage are hardcoded. These should be computed from
  `providers.json` / `modules.json` during the Eleventy build, similar to how the
  provider and module counts already work.

### Infrastructure & Deployment

- [ ] **`apache/airflow-site` PR** — A separate PR is needed in the
  [airflow-site](https://github.com/apache/airflow-site) repo to:
  1. Add an `.htaccess` rewrite rule to proxy `/registry/*` through CloudFront
  2. Add a "Registry" navigation link in the Hugo site header
  (Details documented in `AGENTS.md` under "Deployment Architecture")

### UI / UX

- [ ] **Wire up Explore page search button** — The "Search Modules" button on the
  Explore page (`src/explore.njk`) has a `TODO: Implement search` — it should open the
  global Cmd+K search modal.

- [ ] **Dark mode** — `js/theme.js` exists but dark mode CSS variables/overrides may
  not be fully implemented across all pages and components.

- [ ] **Provider logo coverage** — Some providers display only an initial letter because
  no logo file exists in `public/logos/`. Could add a contributing guide or automated
  process to source missing logos.

- [ ] **Version changelog / diff** — Provider version pages show module lists but no
  changelog or diff between versions. Could pull release notes from PyPI or GitHub.
