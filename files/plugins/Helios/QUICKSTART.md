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

# Helios Quick Start Guide

Get your Helios plugin up and running in Airflow in just a few minutes!

## Prerequisites

- Apache Airflow 3.1+
- pnpm installed (`npm install -g pnpm`)
- Node.js 22+

## Installation Steps

### 1. Build the Plugin

From the Helios directory:

```bash
cd Helios
pnpm install  # Install dependencies (already done)
pnpm build    # Build the production bundle
```

### 2. Copy to Airflow Plugins Directory

```bash
# Find your Airflow home directory
echo $AIRFLOW_HOME  # Default: ~/airflow

# Copy the Helios directory to plugins
cp -r Helios $AIRFLOW_HOME/plugins/
```

Or create a symbolic link (recommended for development):

```bash
ln -s /Users/ryan/projects/airflow/Helios $AIRFLOW_HOME/plugins/Helios
```

### 3. Verify Plugin Files

Ensure these files exist in your plugins directory:

```
$AIRFLOW_HOME/plugins/Helios/
├── dist/
│   └── main.umd.cjs          # Built JavaScript bundle
├── helios_plugin.py          # Airflow plugin definition
└── src/                      # Source code (for reference)
```

### 4. Restart Airflow Webserver

```bash
# Stop existing webserver
pkill -f "airflow webserver"

# Start webserver
airflow webserver --port 8080
```

Or if using airflow-ctl:

```bash
airflow-ctl webserver restart
```

### 5. Verify Installation

Check that the plugin is loaded:

```bash
airflow plugins
```

You should see "Helios" in the list of plugins.

### 6. Access Helios

1. Open your browser to `http://localhost:8080`
2. Look for "Helios" in the navigation menu
3. Click to view your new plugin!

## Development Workflow

### Making Changes

1. Edit files in `src/` directory
2. Rebuild: `pnpm build`
3. Restart Airflow webserver
4. Refresh browser

### Hot Reload Development

For faster development with hot reload:

```bash
# Terminal 1: Start dev server
cd Helios
pnpm dev
# Opens at http://localhost:5173

# Terminal 2: Keep Airflow running
airflow webserver
```

Develop on `localhost:5173`, then when ready:
1. `pnpm build`
2. Restart Airflow to see changes in production

## Customization

### Change the Plugin Name

Edit `helios_plugin.py`:

```python
class HeliosPlugin(AirflowPlugin):
    name = "My Custom Name"  # Change this

    react_apps = [
        {
            "name": "My Custom Name",  # And this
            # ... rest of config
        }
    ]
```

### Change the URL Route

Edit `helios_plugin.py`:

```python
react_apps = [
    {
        "url_route": "my-custom-route",  # Access at /my-custom-route
        # ... rest of config
    }
]
```

### Add Your Own Components

1. Create new components in `src/pages/`
2. Import them in `src/main.tsx`
3. Rebuild and restart

## Troubleshooting

### Plugin Not Showing

```bash
# Check Airflow logs
tail -f $AIRFLOW_HOME/logs/webserver.log

# Verify plugin loads
airflow plugins

# Check file permissions
ls -la $AIRFLOW_HOME/plugins/Helios/
```

### JavaScript Errors

- Open browser console (F12) to see errors
- Verify bundle path in `helios_plugin.py` matches actual file location
- Check that `dist/main.umd.cjs` exists

### Build Errors

```bash
# Clean and reinstall
cd Helios
rm -rf node_modules pnpm-lock.yaml
pnpm install
pnpm build
```

## Next Steps

- Read [INTEGRATION_GUIDE.md](./INTEGRATION_GUIDE.md) for detailed information
- Check [README.md](./README.md) for development best practices
- Explore example components in `src/pages/`
- Connect to Airflow REST API to display real data

## Support

For issues:
1. Check browser console for JavaScript errors
2. Check Airflow logs for Python errors
3. Verify all files are in the correct locations
4. Ensure Airflow version is 3.1 or later

Happy coding! 🚀
