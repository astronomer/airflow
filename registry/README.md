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

# Airflow Registry

A next-generation registry for discovering Apache Airflow Providers, Operators, Hooks, Sensors, and more.

## Features

- **🔍 Instant Search**: Cmd+K command palette with symbol-level search
- **📊 Quality Scores**: Provider quality metrics and download statistics
- **🏷️ Tier Badges**: Core, Partner, and Community provider classification
- **📦 70+ Providers**: Official Apache Airflow providers
- **🔗 Visual Explorer**: Interactive D3.js provider ecosystem graph
- **📱 Responsive**: Mobile-first design with dark mode

## Tech Stack

- **Framework**: [Astro](https://astro.build/) with React islands
- **Styling**: Tailwind CSS
- **Search**: Client-side with Pagefind (WASM)
- **Visualizations**: D3.js
- **Hosting**: Static site (CDN-deployable)

## Development

### Prerequisites

- Node.js 20+
- npm or pnpm

### Setup

```bash
cd registry
npm install
```

### Development Server

```bash
npm run dev
```

Open [http://localhost:4321](http://localhost:4321) in your browser.

### Build

```bash
# Generate metadata from providers
cd .. && python dev/registry/extract_metadata.py && cd registry

# Build static site
npm run build

# Preview production build
npm run preview
```

## Project Structure

```
registry/
├── src/
│   ├── components/     # Astro and React components
│   ├── data/           # Generated JSON data files
│   ├── layouts/        # Page layouts
│   ├── pages/          # Route pages
│   ├── styles/         # Global CSS
│   └── types.ts        # TypeScript types
├── public/             # Static assets
├── astro.config.mjs    # Astro configuration
├── tailwind.config.mjs # Tailwind configuration
└── package.json
```

## Data Pipeline

The registry data is extracted from the Airflow source code:

1. **provider.yaml** - Provider metadata, integrations, logos
2. **provider_metadata.json** - Version history, Airflow compatibility
3. **objects.inv** - Sphinx documentation index

Run the extraction script:

```bash
python dev/registry/extract_metadata.py
```

This generates:
- `providers.json` - Provider metadata
- `modules.json` - Operator, Hook, Sensor details
- `search-index.json` - Search index data

## Adding Community Providers

Community providers can be added via PR:

1. Fork this repository
2. Add your provider to `registry/community-providers.yaml`
3. Submit a pull request

Requirements:
- Published on PyPI
- Follows Airflow provider conventions
- Has documentation
- Actively maintained

## CI/CD

The registry is automatically rebuilt:

- On provider release tags (`providers-*`)
- Weekly (for fresh PyPI download stats)
- On manual trigger

See `.github/workflows/registry-build.yml` for details.

## License

Apache License 2.0
