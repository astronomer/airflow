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

/* eslint-disable i18next/no-literal-string --
   POC: strings will be localized before any real PR. */
import { Flex, Link, Text } from "@chakra-ui/react";
import { FiActivity, FiAlertTriangle, FiClipboard, FiStar } from "react-icons/fi";
import { LuGauge } from "react-icons/lu";
import { Link as RouterLink } from "react-router-dom";

import {
  useAuthLinksServiceGetAuthMenus,
  useDagServiceGetDagsUi,
  useDashboardServiceDagStats,
  useMonitorServiceGetHealth,
  usePoolServiceGetPools,
} from "openapi/queries";
import type { HealthInfoResponse, PoolCollectionResponse } from "openapi/requests/types.gen";
import { UNLIMITED_SLOTS } from "src/components/PoolBar";
import { Tooltip } from "src/components/ui";
import { useAutoRefresh } from "src/utils";

// Warn when any pool exceeds this utilization; matches the "ambient telemetry"
// principle — quiet when fine, loud when approaching saturation.
const POOL_WARNING_THRESHOLD = 0.75;
// Once the unhealthy list passes this many components, collapse to "N down"
// with the full list in a tooltip — keeps the strip from blowing out its
// horizontal budget on a catastrophic-state deployment.
const UNHEALTHY_SUMMARY_THRESHOLD = 3;
// Pool names can be arbitrary; cap the visible width so the saturated-pool
// chip stays within the strip. Full name still surfaces on hover.
const POOL_NAME_MAX_CHARS = 20;

type HealthSummary = {
  downComponents: Array<string>;
  isHealthy: boolean;
};

const summarizeHealth = (data: HealthInfoResponse | undefined): HealthSummary => {
  const downComponents: Array<string> = [];

  if (data === undefined) {
    return { downComponents, isHealthy: true };
  }
  if (data.metadatabase.status !== "healthy") {
    downComponents.push("MetaDatabase");
  }
  if (data.scheduler.status !== "healthy") {
    downComponents.push("Scheduler");
  }
  if (data.triggerer.status !== "healthy") {
    downComponents.push("Triggerer");
  }
  if (
    data.dag_processor !== undefined &&
    data.dag_processor !== null &&
    data.dag_processor.status !== "healthy"
  ) {
    downComponents.push("Dag Processor");
  }

  return { downComponents, isHealthy: downComponents.length === 0 };
};

type SlotsSummary = {
  mostSaturatedPool?: string;
  saturationPct: number;
  totalOpenSlots: number;
  unlimited: boolean;
};

const summarizeSlots = (data: PoolCollectionResponse | undefined): SlotsSummary | undefined => {
  const pools = data?.pools;

  if (pools === undefined || pools.length === 0) {
    return undefined;
  }

  let totalOpenSlots = 0;
  let saturationPct = 0;
  let mostSaturatedPool: string | undefined;
  const unlimited = pools.some((pool) => pool.slots === UNLIMITED_SLOTS);

  for (const pool of pools) {
    if (pool.slots !== UNLIMITED_SLOTS && pool.slots > 0) {
      totalOpenSlots += pool.open_slots;
      const used = (pool.slots - pool.open_slots) / pool.slots;

      if (used > saturationPct) {
        saturationPct = used;
        mostSaturatedPool = pool.name;
      }
    }
  }

  return { mostSaturatedPool, saturationPct, totalOpenSlots, unlimited };
};

const SlotsChipContent = ({ slots }: { readonly slots: SlotsSummary }) => {
  const saturated = slots.saturationPct >= POOL_WARNING_THRESHOLD;
  const pct = Math.round(slots.saturationPct * 100);

  if (saturated && slots.mostSaturatedPool !== undefined) {
    const truncated = slots.mostSaturatedPool.length > POOL_NAME_MAX_CHARS;
    const displayName = truncated
      ? `${slots.mostSaturatedPool.slice(0, POOL_NAME_MAX_CHARS - 1)}…`
      : slots.mostSaturatedPool;

    const chip = (
      <Flex align="center" color="red.fg" gap={1}>
        <FiAlertTriangle />
        <Text as="span" fontWeight="semibold">
          {displayName}
        </Text>
        <Text as="span">pool {pct}% full</Text>
      </Flex>
    );

    return truncated ? <Tooltip content={slots.mostSaturatedPool}>{chip}</Tooltip> : chip;
  }

  return (
    <Flex align="center" gap={1}>
      <LuGauge />
      <Text as="span" fontWeight="semibold">
        {slots.unlimited ? "∞" : slots.totalOpenSlots.toLocaleString()}
      </Text>
      <Text as="span">slots free</Text>
    </Flex>
  );
};

const HealthChipContent = ({ health }: { readonly health: HealthSummary }) => {
  if (health.isHealthy) {
    return (
      <Flex align="center" color="green.fg" gap={1}>
        <FiActivity />
        <Text as="span">Healthy</Text>
      </Flex>
    );
  }

  const count = health.downComponents.length;
  const collapsed = count >= UNHEALTHY_SUMMARY_THRESHOLD;
  const label = collapsed ? `${count} components down` : `${health.downComponents.join(" · ")} down`;

  const chip = (
    <Flex align="center" color="red.fg" gap={1}>
      <FiAlertTriangle />
      <Text as="span" fontWeight="semibold">
        {label}
      </Text>
    </Flex>
  );

  return collapsed ? <Tooltip content={health.downComponents.join(", ")}>{chip}</Tooltip> : chip;
};

export const DagsSummary = () => {
  const refetchInterval = useAutoRefresh({ checkPendingRuns: true });
  const { data: statsData } = useDashboardServiceDagStats(undefined, { refetchInterval });
  const { data: pausedData } = useDagServiceGetDagsUi({ limit: 1, paused: true }, undefined, {
    refetchInterval,
  });
  const { data: favoritesData } = useDagServiceGetDagsUi({ isFavorite: true, limit: 1 }, undefined, {
    refetchInterval,
  });
  const { data: healthData } = useMonitorServiceGetHealth(undefined, { refetchInterval });
  const { data: authLinks } = useAuthLinksServiceGetAuthMenus();
  const hasPoolsAccess = authLinks?.authorized_menu_items.includes("Pools") ?? false;
  const { data: poolsData, error: poolsError } = usePoolServiceGetPools(undefined, undefined, {
    enabled: hasPoolsAccess,
    refetchInterval: (query) => (query.state.error === null ? refetchInterval : false),
  });

  const activeDagsCount = statsData?.active_dag_count ?? 0;
  const pausedDagsCount = pausedData?.total_entries ?? 0;
  const favoritesCount = favoritesData?.total_entries ?? 0;
  const totalDagsCount = activeDagsCount + pausedDagsCount;

  const health = summarizeHealth(healthData);
  const slots = poolsError === undefined || poolsError === null ? summarizeSlots(poolsData) : undefined;

  return (
    <Flex align="center" color="fg.muted" columnGap={2} flexWrap="wrap" fontSize="md" rowGap={1}>
      <FiClipboard />
      <Link _hover={{ textDecoration: "underline" }} asChild color="fg">
        <RouterLink to="/dags">
          <Text as="span" fontWeight="semibold">
            {totalDagsCount.toLocaleString()}
          </Text>{" "}
          Dags
        </RouterLink>
      </Link>
      <Text color="fg.muted">·</Text>
      <Link _hover={{ textDecoration: "underline" }} asChild color="fg">
        <RouterLink to="/dags?paused=false">
          <Text as="span" fontWeight="semibold">
            {activeDagsCount.toLocaleString()}
          </Text>{" "}
          active
        </RouterLink>
      </Link>
      <Text color="fg.muted">·</Text>
      <Link _hover={{ textDecoration: "underline" }} asChild color="fg">
        <RouterLink to="/dags?paused=true">
          <Text as="span" fontWeight="semibold">
            {pausedDagsCount.toLocaleString()}
          </Text>{" "}
          paused
        </RouterLink>
      </Link>
      <Text color="fg.muted">·</Text>
      <Link _hover={{ textDecoration: "underline" }} asChild color="fg">
        <RouterLink to="/dags?favorite=true">
          <Flex align="center" gap={1}>
            <FiStar />
            <Text as="span" fontWeight="semibold">
              {favoritesCount.toLocaleString()}
            </Text>
            <Text as="span">favorite{favoritesCount === 1 ? "" : "s"}</Text>
          </Flex>
        </RouterLink>
      </Link>
      <Text color="fg.muted">·</Text>
      <HealthChipContent health={health} />
      {slots === undefined ? undefined : (
        <>
          <Text color="fg.muted">·</Text>
          {hasPoolsAccess ? (
            <Link _hover={{ textDecoration: "underline" }} asChild color="fg">
              <RouterLink to="/pools">
                <SlotsChipContent slots={slots} />
              </RouterLink>
            </Link>
          ) : (
            <SlotsChipContent slots={slots} />
          )}
        </>
      )}
    </Flex>
  );
};
