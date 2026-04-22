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
import { Box, Flex, Heading, VStack } from "@chakra-ui/react";
import dayjs from "dayjs";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { usePluginServiceGetPlugins } from "openapi/queries";
import type { ReactAppResponse, UIAlert } from "openapi/requests/types.gen";
import ReactMarkdown from "src/components/ReactMarkdown";
import TimeRangeSelector from "src/components/TimeRangeSelector";
import { Accordion, Alert } from "src/components/ui";
import { useConfig } from "src/queries/useConfig";

import { ReactPlugin } from "../ReactPlugin";
import { RecentFailures } from "./RecentFailures";
import { DagsSummary, Stats } from "./Stats";

const defaultHour = "24";

// Keep in sync with TimeRangeSelector's default options.
const windowLabelByHour: Record<string, string> = {
  "1": "Last hour",
  "12": "Last 12 hours",
  "24": "Last 24 hours",
  "168": "Past week",
};

export const Dashboard = () => {
  const alerts = useConfig("dashboard_alert") as Array<UIAlert>;
  const { t: translate } = useTranslation("dashboard");
  const instanceName = useConfig("instance_name");

  const now = dayjs();
  const [startDate, setStartDate] = useState(now.subtract(Number(defaultHour), "hour").toISOString());
  const [endDate, setEndDate] = useState(now.toISOString());
  const [windowHours, setWindowHours] = useState(defaultHour);

  const windowLabel = windowLabelByHour[windowHours] ?? `${windowHours}h`;

  const handleSetStartDate = (next: string) => {
    setStartDate(next);
    const hours = String(Math.round(dayjs(endDate).diff(dayjs(next), "hour")));

    setWindowHours(hours);
  };

  const { data: pluginData } = usePluginServiceGetPlugins();

  const dashboardReactPlugins =
    pluginData?.plugins
      .flatMap((plugin) => plugin.react_apps)
      .filter((reactAppPlugin: ReactAppResponse) => reactAppPlugin.destination === "dashboard") ?? [];

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
        <Flex align="baseline" flexWrap="wrap" gap={4} justify="space-between">
          <Heading size="2xl">
            {typeof instanceName === "string" && instanceName !== "" && instanceName !== "Airflow"
              ? instanceName
              : translate("welcome")}
          </Heading>
          <DagsSummary />
        </Flex>
        <Stats />
        <Box>
          <TimeRangeSelector
            defaultValue={defaultHour}
            endDate={endDate}
            setEndDate={setEndDate}
            setStartDate={handleSetStartDate}
            startDate={startDate}
          />
        </Box>
        <Box>
          <RecentFailures endDate={endDate} limit={10} startDate={startDate} windowLabel={windowLabel} />
        </Box>
        {plugins}
      </VStack>
    </Box>
  );
};
