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

# Helios Plugin - React Monorepo

This directory contains a **pnpm workspace** with multiple React applications that are registered as Airflow plugins. It demonstrates how to build modular, reusable UI components shared across multiple apps.

## 📁 Project Structure

```
plugins/Helios/
├── pnpm-workspace.yaml          # Workspace configuration
├── package.json                 # Root workspace package
├── helios_plugin.py             # Python plugin registration
├── environment-manager/         # React app #1
│   ├── src/
│   ├── dist/                    # Build output
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig*.json
├── alerts/                      # React app #2
│   ├── src/
│   ├── dist/                    # Build output
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig*.json
└── shared/                      # Shared component library
    ├── src/
    │   ├── components/
    │   │   └── HeliosButton.tsx
    │   └── index.ts
    └── package.json
```

## 🚀 Getting Started

### Prerequisites

- **Node.js**: >=22
- **pnpm**: Install with `npm install -g pnpm` or `corepack enable`

### Installation

```bash
# Install all dependencies for all projects in the workspace
pnpm install
```

## 🛠️ Development

### Build All Apps

```bash
# Build all apps in the workspace
pnpm build

# Or build individually
pnpm build:env        # Build environment-manager
pnpm build:alerts     # Build alerts
```

### Development Server

```bash
# Run dev server for environment-manager (port 5173)
pnpm dev:env

# Run dev server for alerts (port 5174)
pnpm dev:alerts
```

### Linting and Formatting

```bash
# Lint all projects
pnpm lint

# Format all projects
pnpm format
```

## 📦 Workspace Packages

### `@helios/shared`

Shared component library used by both apps. Currently includes:

- **`HeliosButton`**: A customizable button with `primary`, `secondary`, `danger`, and `colorModeToggle` variants
- **`ColorModeProvider`**: Shared color mode context provider using next-themes
- **`useColorMode`**: Hook for accessing and controlling color mode across all apps

#### Using Shared Components

```tsx
import { ColorModeProvider, HeliosButton, useColorMode } from "@helios/shared";

// Wrap your app with ColorModeProvider
const App = () => (
  <ColorModeProvider>
    <MyComponent />
  </ColorModeProvider>
);

// Use the shared button and color mode
const MyComponent = () => {
  const { colorMode } = useColorMode();
  
  return (
    <>
      <p>Current mode: {colorMode}</p>
      {/* Color mode toggle button */}
      <HeliosButton variant="colorModeToggle" />
      {/* Other variants */}
      <HeliosButton variant="primary">Primary</HeliosButton>
      <HeliosButton variant="secondary">Secondary</HeliosButton>
      <HeliosButton variant="danger">Danger</HeliosButton>
    </>
  );
};
```

### `environment-manager`

The environment manager React application. Provides UI for managing Airflow connections, variables, and environment settings.

- **Route**: `/environment-manager`
- **Dev Port**: 5173

### `alerts`

The alerts React application. Provides UI for monitoring and managing Airflow alerts.

- **Route**: `/alerts`
- **Dev Port**: 5174

## 🔌 Airflow Plugin Registration

Both React apps are registered in `helios_plugin.py` as Airflow plugins:

```python
react_apps = [
    {
        "name": "Environment Manager",
        "url_route": "environment-manager",
        "bundle_url": "http://localhost:28080/helios-plugin/environment-manager/main.umd.cjs",
        "destination": "nav",
    },
    {
        "name": "Alerts",
        "url_route": "alerts",
        "bundle_url": "http://localhost:28080/helios-plugin/alerts/main.umd.cjs",
        "destination": "nav",
    },
]
```

## 🎨 Technology Stack

- **React 19**: Latest React with modern features
- **TypeScript**: Type-safe development
- **Chakra UI 3**: Component library with theming and dark mode
- **Vite**: Fast build tool and dev server
- **pnpm**: Fast, disk-efficient package manager
- **Vitest**: Fast unit testing framework
- **ESLint + Prettier**: Code quality and formatting

## 📝 Adding New Shared Components

1. Create your component in `shared/src/components/`:

```tsx
// shared/src/components/MyComponent.tsx
export const MyComponent = () => {
  return <div>Hello from shared!</div>;
};
```

2. Export it from `shared/src/index.ts`:

```typescript
export { MyComponent } from "./components/MyComponent";
```

3. Use it in any app:

```tsx
import { MyComponent } from "@helios/shared";
```

## 🔄 Workflow

1. **Make changes** to shared components or individual apps
2. **Build** the apps using `pnpm build`
3. **Restart Airflow webserver** to see changes
4. For development, use `pnpm dev:env` or `pnpm dev:alerts` for hot reloading

## 🧪 Testing

```bash
# Run tests (environment-manager includes Vitest)
cd environment-manager
pnpm test

# With coverage
pnpm coverage
```

## 🎨 Shared Features

### Color Mode

Both apps share the same color mode (light/dark theme) state:

- Color mode preference persists across page reloads (localStorage)
- Toggling in one app affects both apps (shared state via next-themes)
- Use `<HeliosButton variant="colorModeToggle" />` for an automatic toggle button
- Or use `useColorMode()` hook for programmatic control

See [`SHARED_COLORMODE.md`](./SHARED_COLORMODE.md) for detailed documentation.

## 🤝 Contributing

When adding new features:

1. Consider if the component should be shared
2. Follow the TypeScript and ESLint rules
3. Test your changes locally
4. Build and verify the UMD bundle loads correctly

## 📄 License

Licensed under the Apache License, Version 2.0. See the LICENSE file for details.
