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

# Helios - Airflow React Plugin Integration Guide

This guide explains how to integrate the Helios React plugin with Apache Airflow v3.1+.

## Overview

Helios is a React-based plugin for Apache Airflow that demonstrates how to create custom UI components that integrate seamlessly with the Airflow web interface.

## Prerequisites

- Apache Airflow 3.1 or later
- Node.js 22 or later
- pnpm package manager

## Project Structure

```
Helios/
├── src/                      # React source code
│   ├── main.tsx             # Main plugin component
│   ├── pages/               # Page components
│   └── context/             # React context providers
├── dist/                     # Built plugin files (generated)
│   ├── main.umd.cjs         # UMD bundle for Airflow
│   └── main.d.ts            # TypeScript definitions
├── helios_plugin.py          # Airflow plugin integration
├── package.json              # Node.js dependencies
├── vite.config.ts            # Vite build configuration
└── README.md                 # Development documentation
```

## Installation

### Step 1: Build the React Application

```bash
cd Helios
pnpm install
pnpm build
```

This will create the `dist/` directory with the compiled JavaScript bundle.

### Step 2: Copy to Airflow Plugins Directory

Copy the entire Helios directory to your Airflow plugins directory:

```bash
# Default location
cp -r Helios $AIRFLOW_HOME/plugins/

# Or specify custom plugins folder
cp -r Helios /path/to/your/plugins/
```

Alternatively, you can create a symbolic link:

```bash
ln -s /path/to/Helios $AIRFLOW_HOME/plugins/Helios
```

### Step 3: Restart Airflow

Restart your Airflow webserver to load the plugin:

```bash
# If using airflow-ctl
airflow-ctl webserver restart

# Or if using traditional commands
airflow webserver
```

## Accessing the Plugin

Once installed and Airflow is restarted, you can access the Helios plugin:

1. Open the Airflow web interface in your browser
2. Look for "Helios" in the navigation menu
3. Click to open the Helios interface

The plugin will be available at: `http://localhost:8080/helios`

## Configuration

### Plugin Settings

The plugin configuration is in `helios_plugin.py`:

```python
class HeliosPlugin(AirflowPlugin):
    name = "Helios"

    react_apps = [
        {
            "name": "Helios",  # Display name in UI
            "url_route": "helios",  # URL path (/helios)
            "bundle_url": "/helios-plugin/helios/main.umd.cjs",  # JS bundle
            "destination": "nav",  # Where to show: "nav" or "page"
        }
    ]
```

### Customization Options

You can customize the plugin by modifying:

- **`name`**: The display name in the navigation menu
- **`url_route`**: The URL path where the plugin is accessible
- **`destination`**: Where to render the plugin:
  - `"nav"`: Adds to main navigation menu
  - `"page"`: Available as a separate page
- **`icon`**: (optional) Custom icon for the menu item

## Development Workflow

### Running in Development Mode

For active development with hot reload:

```bash
cd Helios
pnpm dev
```

This starts a development server at `http://localhost:5173` where you can develop and test changes in real-time.

### Building for Production

When ready to deploy changes:

```bash
pnpm build
```

Then restart the Airflow webserver to load the updated plugin.

### Linting and Formatting

```bash
# Check code quality
pnpm lint

# Fix linting issues
pnpm lint:fix

# Format code
pnpm format
```

## Troubleshooting

### Plugin Not Appearing

1. **Check plugin loading**:
   ```bash
   airflow plugins
   ```
   This should list "Helios" in the output.

2. **Check Airflow logs** for any errors:
   ```bash
   tail -f $AIRFLOW_HOME/logs/webserver.log
   ```

3. **Verify file permissions**: Ensure Airflow can read all files in the Helios directory.

### JavaScript Errors

1. **Check browser console** for errors
2. **Verify MIME types**: Ensure `.cjs` files are served with correct content type
3. **Check bundle path**: Verify `bundle_url` in `helios_plugin.py` matches the actual file location

### Build Errors

1. **Clear node_modules and reinstall**:
   ```bash
   rm -rf node_modules pnpm-lock.yaml
   pnpm install
   ```

2. **Check Node.js version**: Ensure you're using Node.js 22+
   ```bash
   node --version
   ```

## Architecture

### React Application

The Helios React app is built with:

- **React 19**: Modern React with hooks
- **Chakra UI 3**: Component library for UI elements
- **Vite**: Fast build tool and dev server
- **TypeScript**: Type safety

### Integration with Airflow

The plugin uses two Airflow plugin mechanisms:

1. **FastAPI Apps**: Serves the static React bundle files
2. **React Apps**: Registers the application with Airflow's UI

The UMD bundle format allows Airflow to dynamically load the React component while sharing React instances with the host application, avoiding conflicts and reducing bundle size.

## Extending the Plugin

### Adding New Pages

1. Create a new component in `src/pages/`:
   ```tsx
   export const MyNewPage = () => {
     return <div>My New Page</div>;
   };
   ```

2. Import and use in `src/main.tsx`:
   ```tsx
   import { MyNewPage } from "src/pages/MyNewPage";
   ```

3. Rebuild:
   ```bash
   pnpm build
   ```

### Adding API Endpoints

You can extend the FastAPI app in `helios_plugin.py`:

```python
@app.get("/api/data")
def get_data():
    return {"message": "Hello from Helios!"}
```

### Styling

The plugin uses Chakra UI's theming system. Modify `src/theme.ts` to customize:

- Colors
- Fonts
- Component styles
- Dark/light mode settings

## Support

For issues, questions, or contributions:

1. Check the main README.md for development documentation
2. Review Airflow's plugin documentation
3. Check browser console and Airflow logs for error messages

## License

This plugin follows Apache Airflow's licensing (Apache License 2.0).
