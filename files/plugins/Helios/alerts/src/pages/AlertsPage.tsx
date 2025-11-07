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
import { Box, Icon, Table, Text } from "@chakra-ui/react";
import { AlertBanner } from "@helios/shared";

import { AlertCircleFilledIcon } from "src/AlertCircleFilledIcon";
import { AlertFilledIcon } from "src/AlertFilledIcon";
import { InfoIcon } from "src/InfoIcon";

const alerts = [
  {
    channel: "email",
    count: 57,
    name: "DAG Failure",
    severity: "CRITICAL",
    type: "Dag Failure",
  },
  {
    channel: "email",
    count: 9,
    name: "DAG Successes",
    severity: "INFO",
    type: "Dag Success",
  },
  {
    channel: "slack",
    count: 14,
    name: "Proactive SLA Alerts",
    severity: "INFO",
    type: "Data Product Proactive SLA",
  },
  {
    channel: "slack",
    count: 8,
    name: "Proactive SLA Alerts",
    severity: "INFO",
    type: "Data Product Proactive SLA",
  },
  {
    channel: "slack",
    count: 12,
    name: "Dag Duration Alert",
    severity: "WARNING",
    type: "Dag Duration",
  },
];

const severityIconMap: Record<string, { color: string; icon: typeof AlertCircleFilledIcon }> = {
  CRITICAL: { color: "danger.solid", icon: AlertCircleFilledIcon },
  INFO: { color: "info.solid", icon: InfoIcon },
  WARNING: { color: "warning.solid", icon: AlertFilledIcon },
};

export const AlertsPage = () => (
  <Box w="100%" order={3} fontSize="sm">
    <AlertBanner
      cumulativeCount={100}
      totalAlerts={6}
      viewAllUrl="https://cloud.astronomer-dev.io/alerts/notification-history?filter.period=86400&filter.endDate=2025-11-04T16%3A50%3A23.700Z"
    />

    <Table.Root boxShadow="none" borderLeftWidth={1} borderRightWidth={1} size="sm" variant="outline">
      <Table.Header>
        <Table.Row>
          <Table.ColumnHeader bg="bg.emphasized">Sent</Table.ColumnHeader>
          <Table.ColumnHeader bg="bg.emphasized">Severity</Table.ColumnHeader>
          <Table.ColumnHeader bg="bg.emphasized">Name</Table.ColumnHeader>
          <Table.ColumnHeader bg="bg.emphasized">Type</Table.ColumnHeader>
          <Table.ColumnHeader bg="bg.emphasized">Channel</Table.ColumnHeader>
        </Table.Row>
      </Table.Header>
      <Table.Body>
        {alerts.map((alert, index) => {
          const config = severityIconMap[alert.severity];
          return (
            <Table.Row key={`${alert.name}-${alert.type}-${index}`} _hover={{ bg: "bg.muted" }} cursor="pointer">
              <Table.Cell>{alert.count}</Table.Cell>
              <Table.Cell alignItems="center" display="flex" gap={2}>
                {config ? <Icon as={config.icon} boxSize={6} color={config.color} mr={2} /> : undefined}
                <Text>{alert.severity}</Text>
              </Table.Cell>
              <Table.Cell>{alert.name}</Table.Cell>
              <Table.Cell>{alert.type}</Table.Cell>
              <Table.Cell>{alert.channel}</Table.Cell>
            </Table.Row>
          );
        })}
      </Table.Body>
    </Table.Root>
  </Box>
);
