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
import type { HITLDetailCollection } from "openapi-gen/requests";
import React, { useMemo } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { MdOutlineTask } from "react-icons/md";

import { usePluginTabs } from "src/hooks/usePluginTabs";

/**
 * Base tab configuration
 */
export type TabConfig = {
  icon: ReactNode;
  label: string;
  value: string;
};

/**
 * Plugin destination types supported by usePluginTabs
 */
export type PluginDestination = "dag_run" | "dag" | "task_instance" | "task";

/**
 * Data types for different contexts
 */
type TabData = {
  dag?: { timetable_summary?: string | null };
  groupId?: string;
  hitlDetails?: HITLDetailCollection;
  mappedInstance?: {
    isMapped?: boolean;
    taskCount?: number;
  };
};

/**
 * Simple function to filter tabs based on page and data
 */
export const filterTabs = ({
  data = {},
  page,
  tabs,
  translate,
}: {
  data?: TabData;
  page: PluginDestination;
  tabs: Array<TabConfig>;
  translate: (key: string, options?: { count: number }) => string;
}): Array<TabConfig> => {
  // Check if we have any pending HITL actions (standardized approach)
  const hasPendingHitl = (data.hitlDetails?.hitl_details.length ?? 0) > 0;
  const pendingHitlCount =
    data.hitlDetails?.hitl_details.filter((hitl) => hitl.response_received !== true).length ?? 0;

  console.log("hasPendingHitl", hasPendingHitl);

  return tabs
    .filter((tab) => {
      switch (page) {
        case "dag": {
          if (tab.value === "backfills") {
            return data.dag?.timetable_summary !== null;
          }

          if (tab.value === "required_actions") {
            return hasPendingHitl;
          }

          break;
        }

        case "dag_run": {
          if (tab.value === "required_actions") {
            return hasPendingHitl;
          }

          break;
        }

        case "task": {
          if (tab.value === "events") {
            return data.groupId === undefined;
          }

          if (tab.value === "required_actions") {
            return hasPendingHitl;
          }

          break;
        }

        case "task_instance": {
          if (tab.value === "required_actions") {
            return hasPendingHitl;
          }

          break;
        }

        default: {
          break;
        }
      }

      return true; // Show all other tabs
    })
    .map((tab) => {
      // Modify labels for required_actions tabs that need review counts
      if (tab.value === "required_actions") {
        // Show "Review (count)" when there are pending items, otherwise just "Review"
        return pendingHitlCount > 0
          ? {
              ...tab,
              label: translate("hitl:needsReviewCount", { count: pendingHitlCount }),
            }
          : {
              ...tab,
              label: translate("hitl:reviewHistory"),
            };
      }

      return tab;
    });
};

/**
 * Hook for filtering and managing DAG-related tabs with plugin integration
 */
export const useDagTabs = (baseTabs: Array<TabConfig>, page: PluginDestination, data: TabData = {}) => {
  const { t: translate } = useTranslation(["dag", "hitl"]);

  // Get external tabs from plugins
  const externalTabs = usePluginTabs(page);

  // Combine base tabs with external tabs
  const allTabs = useMemo(() => [...baseTabs, ...externalTabs], [baseTabs, externalTabs]);

  // Handle special case for mapped task instances - insert additional tab
  const tabsWithMappedInstances = useMemo(() => {
    if (page === "task_instance" && data.mappedInstance?.isMapped) {
      return [
        ...allTabs.slice(0, 1),
        {
          icon: React.createElement(MdOutlineTask),
          label: translate("tabs.mappedTaskInstances_other", {
            count: data.mappedInstance.taskCount ?? 0,
          }),
          value: "task_instances",
        },
        ...allTabs.slice(1),
      ];
    }

    return allTabs;
  }, [allTabs, page, data.mappedInstance, translate]);

  // Apply filtering and modification
  const displayTabs = useMemo(
    () => filterTabs({ data, page, tabs: tabsWithMappedInstances, translate }),
    [tabsWithMappedInstances, page, data, translate],
  );

  return {
    displayTabs,
    originalTabs: allTabs,
  };
};
