/*!
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
import babel from "@rolldown/plugin-babel";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import { createConnection } from "node:net";
import cssInjectedByJsPlugin from "vite-plugin-css-injected-by-js";
import { defineConfig } from "vitest/config";

const VITE_DEV_PORT_FLOOR = 5173;
const VITE_DEV_PORT_RANGE = 50;
const PORT_PROBE_TIMEOUT_MS = 500;

// The api-server the dev server proxies to. Breeze exports this so it matches whatever port it
// started the api-server on; the default is breeze's own.
const API_SERVER_ORIGIN = process.env.AIRFLOW_API_SERVER_ORIGIN ?? "http://localhost:28080";

// Probed by connecting rather than by binding. A trial bind is not a usable test here: Node sets
// SO_REUSEADDR, so on BSD/macOS binding the wildcard address succeeds even while another dev
// server holds `::1` on that port, and every port looks free. Connecting to `localhost` also
// matches how Vite and the browser reach the server — Node tries every address the name resolves
// to, so a server bound only to `::1` is still detected.
const isPortFree = (port: number): Promise<boolean> =>
  new Promise((resolve) => {
    const probe = createConnection({ host: "localhost", port });
    const finish = (free: boolean) => {
      probe.destroy();
      resolve(free);
    };

    probe.once("connect", () => finish(false));
    probe.once("error", () => finish(true));
    probe.setTimeout(PORT_PROBE_TIMEOUT_MS, () => finish(true));
  });

const findFreePort = async (port: number, remaining: number): Promise<number> => {
  if (remaining <= 0) {
    throw new Error(
      `No free Vite dev port between ${VITE_DEV_PORT_FLOOR} and ${VITE_DEV_PORT_FLOOR + VITE_DEV_PORT_RANGE - 1}.`,
    );
  }

  return (await isPortFree(port)) ? port : findFreePort(port + 1, remaining - 1);
};

// https://vitejs.dev/config/
export default defineConfig(async ({ command }) => {
  // Several worktrees can run a dev server against one breeze backend, so the port is not a
  // constant. It is resolved here, before Vite binds, rather than left to Vite's own
  // increment-on-conflict: `server.origin` below has to name the port that actually gets bound,
  // and Vite resolves the config *before* binding — an auto-incremented port would leave
  // `origin` pointing at whichever worktree happens to own the floor port, silently serving that
  // worktree's workers and assets into this one's page.
  const portFromEnv = Number(process.env.VITE_DEV_PORT);
  let devPort = VITE_DEV_PORT_FLOOR;

  if (Number.isInteger(portFromEnv) && portFromEnv > 0) {
    devPort = portFromEnv;
  } else if (command === "serve" && process.env.VITEST === undefined) {
    devPort = await findFreePort(VITE_DEV_PORT_FLOOR, VITE_DEV_PORT_RANGE);
  }

  return {
    base: "./",
    build: { chunkSizeWarningLimit: 1600, manifest: true },
    optimizeDeps: {
      exclude: ["@guanmingchiu/sqlparser-ts"], // WASM package needs to be excluded from pre-bundling
    },
    plugins: [
      react(),
      babel({
        presets: [reactCompilerPreset()],
      }),
      // Replace the directory to work with the flask plugin generation
      {
        name: "transform-url-src",
        transformIndexHtml: (html: string) =>
          html
            .replaceAll(`src="./assets/`, `src="./static/assets/`)
            .replaceAll(`href="./assets/`, `href="./static/assets/`)
            .replaceAll(`href="/`, `href="./`),
      },
      // Keep Monaco's codicon CSS as a real CSS file (rather than inlined into JS).
      // The codicon stylesheet references `codicon.ttf` with a CSS-relative URL — when
      // it gets inlined into a `<style>` tag the URL resolves against the page origin
      // (the api-server) instead of the asset directory and the font fails to load.
      // Keeping the CSS as an emitted file lets the browser resolve the URL relative
      // to the stylesheet's own location (`/static/assets/`). Vite still chunks it so
      // it only loads on the routes that pull Monaco in.
      cssInjectedByJsPlugin({
        cssAssetsFilterFunction: (asset: { fileName: string }) => !asset.fileName.includes("codicon"),
      }),
    ],
    resolve: { alias: { openapi: "/openapi-gen", src: "/src" } },
    server: {
      cors: true, // Only used by the dev server.
      // The dev SPA shell is served by the airflow api-server (a different origin), so
      // Vite must emit fully-qualified URLs — otherwise asset paths (notably worker
      // module URLs) resolve against the api-server origin and 404.
      origin: `http://localhost:${devPort}`,
      port: devPort,
      proxy: {
        "/hitl-review": {
          changeOrigin: true,
          target: API_SERVER_ORIGIN,
        },
      },
      // The api-server templates this exact port into the dev shell, so a silent shift to a
      // neighbouring port would serve another worktree's code. Fail loudly instead.
      strictPort: true,
    },
    test: {
      coverage: {
        include: ["src/**/*.ts", "src/**/*.tsx"],
      },
      css: true,
      environment: "happy-dom",
      exclude: ["**/node_modules/**", "**/dist/**", "tests/e2e/**"],
      globals: true,
      mockReset: true,
      restoreMocks: true,
      setupFiles: "./testsSetup.ts",
    },
  };
});
