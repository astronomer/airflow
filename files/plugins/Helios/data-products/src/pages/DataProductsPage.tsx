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
import { Badge, Box, HStack, Icon, Table, Text } from "@chakra-ui/react";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import { FiCheckCircle, FiXCircle } from "react-icons/fi";

dayjs.extend(relativeTime);

type DataProductsPageProps = {
  readonly dagId?: string;
  readonly taskId?: string;
};

type DataProduct = {
  description: string;
  lastRefreshed: string;
  name: string;
  slaName: string;
  slaStatus: "met" | "missed";
};

// Mock data - in a real implementation, this would come from an API
const mockDataProducts: DataProduct[] = [
  {
    description: "Daily aggregated customer behavior metrics and segmentation analysis",
    lastRefreshed: dayjs().subtract(2, "hour").toISOString(),
    name: "Customer Analytics",
    slaName: "30 day freshness",
    slaStatus: "met",
  },
  {
    description: "Real-time sales pipeline data with forecasting and conversion metrics",
    lastRefreshed: dayjs().subtract(30, "minute").toISOString(),
    name: "Sales Pipeline",
    slaName: "weekday landing",
    slaStatus: "met",
  },
  {
    description: "Current inventory levels across all warehouses with stock alerts",
    lastRefreshed: dayjs().subtract(5, "hour").toISOString(),
    name: "Inventory Snapshot",
    slaName: "hourly refresh",
    slaStatus: "missed",
  },
  {
    description: "Multi-touch attribution model for marketing campaign performance",
    lastRefreshed: dayjs().subtract(1, "hour").toISOString(),
    name: "Marketing Attribution",
    slaName: "daily by 9am",
    slaStatus: "met",
  },
  {
    description: "Consolidated financial metrics and KPIs for executive reporting",
    lastRefreshed: dayjs().subtract(8, "hour").toISOString(),
    name: "Financial Summary",
    slaName: "business hours",
    slaStatus: "missed",
  },
];

export const DataProductsPage = ({ dagId, taskId }: DataProductsPageProps) => {
  return (
    <Box p={4}>
      <HStack gap={2} mb={4}>
        <Text fontSize="lg" fontWeight="bold">
          Data Products
        </Text>
        {dagId && (
          <Text color="fg.muted" fontSize="sm">
            for DAG: {dagId}
          </Text>
        )}
        {taskId && (
          <Text color="fg.muted" fontSize="sm">
            / Task: {taskId}
          </Text>
        )}
      </HStack>

      <Table.Root size="sm" variant="outline">
        <Table.Header>
          <Table.Row bg="bg.emphasized">
            <Table.ColumnHeader>Name</Table.ColumnHeader>
            <Table.ColumnHeader>SLA</Table.ColumnHeader>
            <Table.ColumnHeader>Last Refreshed</Table.ColumnHeader>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {mockDataProducts.map((product) => (
            <Table.Row
              key={product.name}
              _hover={{ bg: "bg.muted", cursor: "pointer" }}
              cursor="pointer"
              transition="background-color 0.2s"
            >
              <Table.Cell>
                <Box>
                  <Text fontWeight="medium">{product.name}</Text>
                  <Text color="fg.muted" fontSize="sm">
                    {product.description}
                  </Text>
                </Box>
              </Table.Cell>
              <Table.Cell>
                <Badge colorPalette={product.slaStatus === "met" ? "success" : "danger"} variant="subtle">
                  <HStack gap={1}>
                    <Icon asChild boxSize={4}>
                      {product.slaStatus === "met" ? <FiCheckCircle /> : <FiXCircle />}
                    </Icon>
                    <Text>{product.slaName}</Text>
                  </HStack>
                </Badge>
              </Table.Cell>
              <Table.Cell>
                <Text fontSize="sm">{dayjs(product.lastRefreshed).fromNow()}</Text>
              </Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table.Root>
    </Box>
  );
};
