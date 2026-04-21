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

/* eslint-disable @typescript-eslint/no-use-before-define --
   POC: dashboard layout variants are defined after the parent component for readability. */
import { Box, Heading, VStack } from "@chakra-ui/react";
import { useTranslation } from "react-i18next";

import { usePluginServiceGetPlugins } from "openapi/queries";
import type { ReactAppResponse, UIAlert } from "openapi/requests/types.gen";
import ReactMarkdown from "src/components/ReactMarkdown";
import { Accordion, Alert } from "src/components/ui";
import { useConfig } from "src/queries/useConfig";

import { ReactPlugin } from "../ReactPlugin";
import { DashboardVariantSwitcher, useDashboardVariant } from "./DashboardVariantSwitcher";
import { FavoriteDags } from "./FavoriteDags";
import { Health } from "./Health";
import { HistoricalMetrics } from "./HistoricalMetrics";
import { PoolSummary } from "./PoolSummary";
import { RecentFailures } from "./RecentFailures";
import { Stats } from "./Stats";

export const Dashboard = () => {
  const alerts = useConfig("dashboard_alert") as Array<UIAlert>;
  const { t: translate } = useTranslation("dashboard");
  const instanceName = useConfig("instance_name");
  const variant = useDashboardVariant();

  const { data: pluginData } = usePluginServiceGetPlugins();

  const dashboardReactPlugins =
    pluginData?.plugins
      .flatMap((plugin) => plugin.react_apps)
      .filter((reactAppPlugin: ReactAppResponse) => reactAppPlugin.destination === "dashboard") ?? [];

  const heading = (
    <Heading size="2xl">
      {typeof instanceName === "string" && instanceName !== "" && instanceName !== "Airflow"
        ? instanceName
        : translate("welcome")}
    </Heading>
  );

  const alertsBlock =
    alerts.length > 0 ? (
      <Accordion.Root collapsible defaultValue={["ui_alerts"]}>
        <Accordion.Item key="ui_alerts" value="ui_alerts">
          {alerts.map((alert: UIAlert, index) =>
            index === 0 ? (
              <Accordion.ItemTrigger key={alert.text} mb={2}>
                <Alert status={alert.category}>
                  <ReactMarkdown>{alert.text}</ReactMarkdown>
                </Alert>
              </Accordion.ItemTrigger>
            ) : (
              <Accordion.ItemContent key={alert.text} pr={8}>
                <Alert status={alert.category}>
                  <ReactMarkdown>{alert.text}</ReactMarkdown>
                </Alert>
              </Accordion.ItemContent>
            ),
          )}
        </Accordion.Item>
      </Accordion.Root>
    ) : undefined;

  const plugins = dashboardReactPlugins.map((plugin) => <ReactPlugin key={plugin.name} reactApp={plugin} />);

  return (
    <Box overflow="auto" pb={24} px={{ base: 2, md: 4 }}>
      <VStack alignItems="stretch" gap={6}>
        {alertsBlock}
        {heading}
        {variant === "v1" ? <V1Minimal /> : undefined}
        {variant === "v2" ? <V2TriageHero /> : undefined}
        {variant === "v3" ? <V3Split /> : undefined}
        {plugins}
      </VStack>
      <DashboardVariantSwitcher />
    </Box>
  );
};

const V1Minimal = () => (
  <>
    <Box>
      <Stats />
    </Box>
    <Box>
      <RecentFailures />
    </Box>
    <Box>
      <FavoriteDags />
    </Box>
    <Box display="flex" flexDirection={{ base: "column", md: "row" }} gap={{ base: 4, md: 8 }}>
      <Health />
      <PoolSummary />
    </Box>
    <Box>
      <HistoricalMetrics />
    </Box>
  </>
);

const V2TriageHero = () => (
  <>
    <Box>
      <Stats />
    </Box>
    <Box>
      <RecentFailures limit={10} />
    </Box>
    <Box>
      <HistoricalMetrics />
    </Box>
    <Box>
      <FavoriteDags />
    </Box>
    <Box display="flex" flexDirection={{ base: "column", md: "row" }} gap={{ base: 4, md: 8 }}>
      <Health />
      <PoolSummary />
    </Box>
  </>
);

const V3Split = () => (
  <Box display="grid" gap={6} gridTemplateColumns={{ base: "1fr", xl: "minmax(0, 2fr) minmax(0, 1fr)" }}>
    <VStack alignItems="stretch" gap={6}>
      <Stats />
      <RecentFailures />
      <HistoricalMetrics />
    </VStack>
    <VStack alignItems="stretch" gap={6}>
      <FavoriteDags />
      <Health />
      <PoolSummary />
    </VStack>
  </Box>
);
