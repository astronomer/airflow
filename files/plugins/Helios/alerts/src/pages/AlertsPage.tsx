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
import { Box, Text, HStack, Link, Icon, Table } from "@chakra-ui/react";
import { FiExternalLink } from "react-icons/fi";
import { MegaphoneIcon } from "../MegaphoneIcon";
import { AlertFilledIcon } from "src/AlertFilledIcon";
import { InfoIcon } from "src/InfoIcon";
import { AlertCircleFilledIcon } from "src/AlertCircleFilledIcon";


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
  }
];

const severityIconMap: Record<string, { color: string; icon: typeof AlertCircleFilledIcon }> = {
  CRITICAL: { color: "red.500", icon: AlertCircleFilledIcon },
  INFO: { color: "blue.500", icon: InfoIcon },
  WARNING: { color: "yellow.500", icon: AlertFilledIcon },
};

export const AlertsPage = () => (
  <Box w="100%" order={3} fontSize="sm">
    <HStack  p={2} borderTopRadius="md" color="white"  borderWidth={1} justify="space-between">
      <Text>
      <MegaphoneIcon mr={2} />
      100 Astro Alerts sent in the last 24 hours
      </Text>
      <Link color="white"href="https://cloud.astronomer-dev.io/alerts/notification-history?filter.period=86400&filter.endDate=2025-11-04T16%3A50%3A23.700Z" target="_blank" rel="noopener noreferrer">
         View all<Icon as={FiExternalLink} boxSize={4}/>
      </Link>
    </HStack>

    <Table.Root size="sm" variant="outline" boxShadow="none" borderLeftWidth={1} borderRightWidth={1}>
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
          return(
          <Table.Row key={`${alert.name}-${alert.type}-${index}`} _hover={{ bg: "bg.muted" }} cursor="pointer">
            <Table.Cell>{alert.count}</Table.Cell>
            <Table.Cell display="flex" alignItems="center" gap={2}>
                {config ? ( 
                  <Icon
                    as={config.icon}
                    boxSize={6}
                    color={config.color}
                    mr={2}
                  />) : undefined}
                <Text>{alert.severity}</Text>
            </Table.Cell>
            <Table.Cell>{alert.name}</Table.Cell>
            <Table.Cell>{alert.type}</Table.Cell>
            <Table.Cell>{alert.channel}</Table.Cell>

          </Table.Row>
        ) })}
      </Table.Body>
    </Table.Root>

    <HStack justify="space-between" color="fg.muted" p={2} borderBottomRadius="md" borderWidth={1}>
      <Text>6 Alerts configured on this deployment</Text>
      <Link href="https://cloud.astronomer-dev.io/clx9g3xak000w01ksr29jl6f2/deployments/clyz2mshy00e501p1vchz64yx/alerts" target="_blank" rel="noopener noreferrer">
        <Icon as={FiExternalLink} boxSize={4}/> View alert configuration
      </Link>
    </HStack>
  </Box>
);