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

# Astro Bar Plugin

A toolbar React plugin for Apache Airflow that displays deployment information and analytics.

## Features

- **Deployment Information**: Shows the current deployment instance name, user, and last deployment time
- **Astro Logo**: Displays the Astronomer logo with color mode support
- **Deployment Analytics**: Expandable section with deployment analytics visualization
- **Responsive Design**: Built with Chakra UI for a modern, responsive interface

## Development

### Install Dependencies

From the Helios root directory:

```bash
pnpm install
```

### Development Server

Run the development server:

```bash
cd astro-bar
pnpm dev
```

The dev server will run on http://localhost:5173

### Build

Build the production bundle:

```bash
pnpm build
```

This will generate the `dist/main.umd.cjs` file that Airflow uses to load the plugin.

### Lint

```bash
pnpm lint
```

Fix linting issues:

```bash
pnpm lint:fix
```

## Integration

The plugin is configured in the main `helios_plugin.py` file:

```python
react_apps = [
    {
        "name": "Astro Bar",
        "url_route": "astro-bar",
        "bundle_url": "http://localhost:28080/helios-plugin/astro-bar/main.umd.cjs",
        "destination": "dashboard",
    },
]
```

The plugin renders as a toolbar at the top of the Airflow dashboard.

## Structure

```
astro-bar/
├── src/
│   ├── components/
│   │   └── AstroALogo.tsx      # Astronomer logo component
│   ├── pages/
│   │   └── AstroBarPage.tsx    # Main toolbar component
│   └── main.tsx                # Plugin entry point
├── dist/                       # Build output
├── package.json
├── vite.config.ts
└── tsconfig.json
```

## Dependencies

- **@chakra-ui/react**: UI component library
- **@helios/shared**: Shared utilities and components
- **react**: UI framework
- **react-icons**: Icon library

## License

Licensed under the Apache License, Version 2.0
