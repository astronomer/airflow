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
import { Box, Heading, VStack, Text, HStack, Badge } from "@chakra-ui/react";
import { FiBell, FiAlertCircle, FiCheckCircle } from "react-icons/fi";
import { HeliosButton } from "@helios/shared";

type Alert = {
  id: string;
  level: "info" | "warning" | "critical";
  message: string;
  timestamp: string;
};

const mockAlerts: Array<Alert> = [
  {
    id: "1",
    level: "critical",
    message: "DAG run failed: data_pipeline_v2",
    timestamp: "2025-11-03 14:30:00",
  },
  {
    id: "2",
    level: "warning",
    message: "High memory usage detected on worker-01",
    timestamp: "2025-11-03 14:15:00",
  },
  {
    id: "3",
    level: "info",
    message: "Scheduled maintenance completed successfully",
    timestamp: "2025-11-03 13:00:00",
  },
];

const getLevelColor = (level: Alert["level"]) => {
  const colors = {
    critical: "red",
    info: "blue",
    warning: "yellow",
  };

  return colors[level];
};

export const AlertsPage = () => (
  <Box p={8}>
    <VStack align="start" gap={6}>
      <HStack>
        <FiBell size={32} />
        <Heading>Airflow Alerts</Heading>
      </HStack>

      <Text color="gray.600">
        Monitor and manage alerts from your Airflow environment
      </Text>

      <HStack gap={4}>
        <HeliosButton variant="colorModeToggle" />
        <HeliosButton variant="primary">Mark All as Read</HeliosButton>
        <HeliosButton variant="secondary">Filter Alerts</HeliosButton>
        <HeliosButton variant="danger">Clear All</HeliosButton>
      </HStack>

      <VStack align="stretch" gap={4} width="100%">
        {mockAlerts.map((alert) => (
          <Box
            key={alert.id}
            p={4}
            borderWidth="1px"
            borderRadius="md"
            _hover={{ bg: "gray.50" }}
          >
            <HStack justify="space-between">
              <HStack>
                {alert.level === "critical" ? (
                  <FiAlertCircle color="red" size={20} />
                ) : (
                  <FiCheckCircle color="green" size={20} />
                )}
                <Text fontWeight="medium">{alert.message}</Text>
              </HStack>
              <Badge colorPalette={getLevelColor(alert.level)}>
                {alert.level.toUpperCase()}
              </Badge>
            </HStack>
            <Text fontSize="sm" color="gray.500" mt={2}>
              {alert.timestamp}
            </Text>
          </Box>
        ))}
      </VStack>
    </VStack>
  </Box>
);

