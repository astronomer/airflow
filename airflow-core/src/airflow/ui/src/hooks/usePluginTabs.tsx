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
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useMemo } from "react";
import { LuPlug } from "react-icons/lu";

import { usePluginServiceGetPlugins } from "openapi/queries";
import type { ExternalViewResponse, ReactAppResponse } from "openapi/requests/types.gen";
import { useColorMode } from "src/context/colorMode";

type TabPlugin = {
  icon: ReactNode;
  label: string;
  value: string;
};

export type PluginRouteContext = {
  dagId?: string;
  mapIndex?: string;
  runId?: string;
  taskId?: string;
};

const fetchVisibility = async (
  checks: Array<{ name: string; url: string }>,
  context: PluginRouteContext,
): Promise<Record<string, boolean>> => {
  const results: Record<string, boolean> = {};

  await Promise.all(
    checks.map(async ({ name, url }) => {
      try {
        const fullUrl = new URL(url, globalThis.location.origin);

        if (context.dagId !== undefined && context.dagId !== "") {
          fullUrl.searchParams.set("dag_id", context.dagId);
        }
        if (context.runId !== undefined && context.runId !== "") {
          fullUrl.searchParams.set("run_id", context.runId);
        }
        if (context.taskId !== undefined && context.taskId !== "") {
          fullUrl.searchParams.set("task_id", context.taskId);
        }
        if (context.mapIndex !== undefined && context.mapIndex !== "") {
          fullUrl.searchParams.set("map_index", context.mapIndex);
        }
        const resp = await fetch(fullUrl);
        const data = (await resp.json()) as { visible: boolean };

        results[name] = data.visible;
      } catch {
        results[name] = false;
      }
    }),
  );

  return results;
};

export const usePluginTabs = (destination: string, context?: PluginRouteContext): Array<TabPlugin> => {
  const { colorMode } = useColorMode();
  const { data: pluginData } = usePluginServiceGetPlugins();

  const externalViews = useMemo(
    () =>
      pluginData?.plugins
        .flatMap((plugin) => [...plugin.external_views, ...plugin.react_apps])
        .filter(
          (view: ExternalViewResponse | ReactAppResponse) =>
            view.destination === destination && Boolean(view.url_route),
        ) ?? [],
    [pluginData, destination],
  );

  const visibilityChecks = useMemo(
    () =>
      externalViews
        .filter(
          (view): view is ReactAppResponse =>
            "visibility_check_url" in view &&
            view.visibility_check_url !== undefined &&
            view.visibility_check_url !== null,
        )
        .map((view) => ({ name: view.name, url: view.visibility_check_url as string })),
    [externalViews],
  );

  const stableContextKey = context
    ? `${context.dagId ?? ""}-${context.runId ?? ""}-${context.taskId ?? ""}-${context.mapIndex ?? ""}`
    : "";

  const { data: visibilityMap } = useQuery({
    enabled: visibilityChecks.length > 0 && context !== undefined,
    queryFn: () => fetchVisibility(visibilityChecks, context as PluginRouteContext),
    queryKey: ["pluginTabVisibility", destination, stableContextKey, visibilityChecks],
  });

  return externalViews
    .filter((view) => {
      if (
        "visibility_check_url" in view &&
        view.visibility_check_url !== undefined &&
        view.visibility_check_url !== null
      ) {
        return visibilityMap?.[view.name] === true;
      }

      return true;
    })
    .map((view) => {
      let iconSrc = view.icon;

      if (colorMode === "dark" && view.icon_dark_mode !== undefined && view.icon_dark_mode !== null) {
        iconSrc = view.icon_dark_mode;
      }

      const icon =
        iconSrc !== undefined && iconSrc !== null ? (
          <img alt={view.name} src={iconSrc} style={{ height: "1rem", width: "1rem" }} />
        ) : (
          <LuPlug />
        );

      return {
        icon,
        label: view.name,
        value: `plugin/${view.url_route}`,
      };
    });
};
