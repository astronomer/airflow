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

## Install Dependencies

```bash
cd /Users/brent/dev/airflow/files/plugins/Helios
pnpm install
```

## Build All Apps

```bash
# Build both environment-manager and alerts
pnpm build --watch
```

This will create and update:
- `environment-manager/dist/main.umd.cjs`
- `alerts/dist/main.umd.cjs`

## Access Your Apps

Once Airflow is running, you'll see two new navigation items:

1. **Environment Manager** - http://localhost:8080/environment-manager
2. **Alerts** - http://localhost:8080/alerts

Both apps use the shared `HeliosButton` component from `@helios/shared`!

## Verify Everything Works

1. **Check workspace**: `pnpm list --depth 0`
2. **Check shared package is linked**: Both apps should show `@helios/shared: link:../shared`
3. **Check builds**: `ls -la environment-manager/dist alerts/dist`
4. **Check plugin registration**: Airflow should show both apps in the navigation
