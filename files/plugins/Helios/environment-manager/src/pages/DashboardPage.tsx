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

import { Box, Card, Grid, GridItem, Heading, HStack, Text, VStack } from "@chakra-ui/react";
import { LuActivity, LuCircleCheck, LuClock, LuCircleX } from "react-icons/lu";

interface MetricCardProps {
  title: string;
  value: string | number;
  icon: React.ComponentType;
  colorScheme: string;
}

const MetricCard = ({ colorScheme, icon: IconComponent, title, value }: MetricCardProps) => (
  <Card.Root bg="bg.subtle" borderRadius="lg" p={4}>
    <Card.Body>
      <HStack justify="space-between">
        <VStack align="start" gap={2}>
          <Text fontSize="sm" color="fg.muted">
            {title}
          </Text>
          <Heading size="2xl" color="fg">
            {value}
          </Heading>
        </VStack>
        <Box color={`${colorScheme}.solid`} fontSize="3xl" as={IconComponent} />
      </HStack>
    </Card.Body>
  </Card.Root>
);

export const DashboardPage = () => {
  // Example metrics - in a real plugin, these would come from Airflow APIs
  const metrics = [
    {
      colorScheme: "blue",
      icon: LuActivity,
      title: "Active DAGs",
      value: 42,
    },
    {
      colorScheme: "green",
      icon: LuCircleCheck,
      title: "Successful Runs",
      value: "1,234",
    },
    {
      colorScheme: "orange",
      icon: LuClock,
      title: "Pending Tasks",
      value: 17,
    },
    {
      colorScheme: "red",
      icon: LuCircleX,
      title: "Failed Tasks",
      value: 3,
    },
  ];

  return (
    <Box p={8} bg="bg" height="100%">
      <VStack align="stretch" gap={6}>
        <Heading size="xl" color="fg">
          Helios Dashboard
        </Heading>

        <Grid templateColumns="repeat(auto-fit, minmax(250px, 1fr))" gap={4}>
          {metrics.map((metric) => (
            <GridItem key={metric.title}>
              <MetricCard {...metric} />
            </GridItem>
          ))}
        </Grid>

        <Card.Root bg="bg.subtle" borderRadius="lg">
          <Card.Header>
            <Heading size="md" color="fg">
              Recent Activity
            </Heading>
          </Card.Header>
          <Card.Body>
            <Text color="fg.muted">
              This is where you can display recent DAG runs, task executions, or any other Airflow metrics you
              want to track.
            </Text>
            <Text color="fg.muted" mt={4}>
              Connect to Airflow's REST API to fetch real-time data and display it here.
            </Text>
          </Card.Body>
        </Card.Root>
      </VStack>
    </Box>
  );
};
