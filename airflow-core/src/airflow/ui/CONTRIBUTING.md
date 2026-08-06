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

# Contributing to the UI

## System Requirements

Building the UI requires at least 8GB of system RAM (6GB available).

If you encounter out-of-memory errors during the build, you can increase Node.js heap size:

```bash
export NODE_OPTIONS="--max-old-space-size=8192"
```

## Quick Start

With Breeze:
`breeze start-airflow --dev-mode`

Manually:

- Have the `DEV_MODE` environment variable set to `true` when starting airflow api-server
- Run `pnpm install && pnpm dev`
- Note: Make sure to access the UI via the Airflow localhost port (8080 or 28080) and not the vite port (5173)

## Editing multiple UI worktrees against a single breeze instance

You only ever need **one** breeze instance. In dev mode the api-server serves a small shell page and
nothing else — every line of the SPA comes from a Vite dev server on your host — so a single backend
can serve the UI from any number of worktrees.

### The first worktree

Nothing new here, carry on as usual:

```bash
breeze start-airflow --dev-mode
```

Then open `http://localhost:28080`.

### The second and later worktrees

Do **not** start another breeze. Start only the UI dev server:

```bash
cd airflow-core/src/airflow/ui && pnpm install && pnpm dev
```

It claims the first free port from 5173 upwards and prints it:

```text
➜  Local:   http://localhost:5174/
```

Read the port off that line, but **do not open it**. Vite has no api-server behind it, so it serves
the page template unprocessed and you get 404s against a literal `{{ backend_server_base_url }}`
path. Open the api-server with that port in the query string instead:

```text
http://localhost:28080/?vite=5174
```

That tab now runs the second worktree's UI against the first worktree's backend. The port is
remembered in a cookie, so navigating and reloading stay put. Pass `?vite=<port>` again to switch,
and use a second browser profile to see two worktrees side by side.

### Two things always come from the breeze worktree

- **The login page.** The simple auth manager UI is a singleton on port 5172 — the first breeze to
  start it wins and later ones reuse it. Edit the login page in the worktree running breeze, or your
  change will not show up.
- **Translations.** These are served by the api-server, not by Vite. A branch that adds new
  translation keys renders the bare key names until that branch is the one running breeze.

### Tips

- Which worktree is this tab showing? Run `document.querySelector('script[src*="main.tsx"]').src` in
  the browser console.
- Want a fixed port instead of reading it off the console? `VITE_DEV_PORT=5273 pnpm dev`.

## More

See [node environment setup docs](/contributing-docs/15_node_environment_setup.rst)
