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
import { Box, Grid, HStack, Text, VStack } from "@chakra-ui/react";

import { AlertBanner } from "../components/AlertBanner";
import { DagDurationAlert } from "../components/DagDurationAlert";
import { DagFailureAlert } from "../components/DagFailureAlert";
import { DagSuccessAlert } from "../components/DagSuccessAlert";
import { DagTimelinessAlert } from "../components/DagTimelinessAlert";
import { MegaphoneIcon } from "../MegaphoneIcon";

type AlertsTabPageProps = {
  readonly dagId?: string;
  readonly taskId?: string;
};

// Mock data - in a real implementation, this would come from an API
const getMockDagData = (_dagId: string) => {
  return {
    cumulativeCount: 62,
    dagDuration: {
      alertCount: 3,
      durationThreshold: 30,
      recentRuns: [
        {
          duration: 25,
          runId: "scheduled__2025-11-04T12:00:00+00:00",
          startDate: "Nov 4, 2025 12:00 PM",
        },
        {
          duration: 35,
          runId: "scheduled__2025-11-04T11:00:00+00:00",
          startDate: "Nov 4, 2025 11:00 AM",
        },
        {
          duration: 28,
          runId: "scheduled__2025-11-04T10:00:00+00:00",
          startDate: "Nov 4, 2025 10:00 AM",
        },
        {
          duration: 42,
          runId: "scheduled__2025-11-04T09:00:00+00:00",
          startDate: "Nov 4, 2025 9:00 AM",
        },
        {
          duration: 22,
          runId: "scheduled__2025-11-04T08:00:00+00:00",
          startDate: "Nov 4, 2025 8:00 AM",
        },
      ],
    },
    dagFailure: {
      alertCount: 12,
      failedRuns: [
        {
          duration: "15m 32s",
          error: "Task 'extract_data' failed: Connection timeout",
          runId: "scheduled__2025-11-04T13:00:00+00:00",
          startDate: "Nov 4, 2025 1:00 PM",
        },
        {
          duration: "8m 12s",
          error: "Task 'transform_data' failed: Memory limit exceeded",
          runId: "scheduled__2025-11-04T07:00:00+00:00",
          startDate: "Nov 4, 2025 7:00 AM",
        },
      ],
    },
    dagSuccess: {
      alertCount: 45,
      successfulRuns: [
        {
          duration: "22m 15s",
          endDate: "Nov 4, 2025 2:45 PM",
          runId: "scheduled__2025-11-04T14:30:00+00:00",
          startDate: "Nov 4, 2025 2:23 PM",
        },
        {
          duration: "18m 42s",
          endDate: "Nov 4, 2025 1:42 PM",
          runId: "scheduled__2025-11-04T13:23:00+00:00",
          startDate: "Nov 4, 2025 1:23 PM",
        },
        {
          duration: "25m 08s",
          endDate: "Nov 4, 2025 12:48 PM",
          runId: "scheduled__2025-11-04T12:23:00+00:00",
          startDate: "Nov 4, 2025 12:23 PM",
        },
      ],
    },
    dagTimeliness: {
      alertCount: 2,
      missedDeadlines: [
        {
          dagRuns: [
            {
              completionTime: "Nov 4, 2025 11:35 AM",
              runId: "scheduled__2025-11-04T11:00:00+00:00",
              startDate: "Nov 4, 2025 11:00 AM",
            },
          ],
          deadline: "Nov 4, 2025 11:30 AM",
          missed: true,
        },
        {
          dagRuns: [
            {
              completionTime: "Nov 4, 2025 10:25 AM",
              runId: "scheduled__2025-11-04T10:00:00+00:00",
              startDate: "Nov 4, 2025 10:00 AM",
            },
          ],
          deadline: "Nov 4, 2025 10:30 AM",
          missed: false,
        },
        {
          dagRuns: [
            {
              completionTime: "Nov 4, 2025 9:42 AM",
              runId: "scheduled__2025-11-04T09:00:00+00:00",
              startDate: "Nov 4, 2025 9:00 AM",
            },
          ],
          deadline: "Nov 4, 2025 9:30 AM",
          missed: true,
        },
      ],
      upcomingDeadline: "Nov 4, 2025 3:30 PM",
    },
    totalAlerts: 4,
  };
};

export const AlertsTabPage = ({ dagId, taskId }: AlertsTabPageProps) => {
  // For DAG-level alerts
  if (dagId && !taskId) {
    const mockData = getMockDagData(dagId);

    return (
      <Box p={4}>
        <VStack alignItems="flex-start" gap={4}>
          <AlertBanner cumulativeCount={mockData.cumulativeCount} totalAlerts={mockData.totalAlerts} />

          <Grid columnGap={4} columns={{ base: 1, lg: 2 }} rowGap={4} width="full">
            <DagSuccessAlert
              alertCount={mockData.dagSuccess.alertCount}
              successfulRuns={mockData.dagSuccess.successfulRuns}
            />
            <DagFailureAlert alertCount={mockData.dagFailure.alertCount} failedRuns={mockData.dagFailure.failedRuns} />
            <DagDurationAlert
              alertCount={mockData.dagDuration.alertCount}
              durationThreshold={mockData.dagDuration.durationThreshold}
              recentRuns={mockData.dagDuration.recentRuns}
            />
            <DagTimelinessAlert
              alertCount={mockData.dagTimeliness.alertCount}
              missedDeadlines={mockData.dagTimeliness.missedDeadlines}
              upcomingDeadline={mockData.dagTimeliness.upcomingDeadline}
            />
          </Grid>
        </VStack>
      </Box>
    );
  }

  // For Task-level (placeholder for future implementation)
  if (taskId) {
    return (
      <Box p={4}>
        <VStack alignItems="flex-start" gap={4}>
          <HStack gap={2}>
            <MegaphoneIcon color="purple.500" />
            <Text fontSize="xl" fontWeight="bold">
              Task Alerts
            </Text>
          </HStack>

          <Box>
            <Text color="fg.muted" fontSize="sm" fontWeight="medium">
              Task ID
            </Text>
            <Text fontSize="md">{taskId}</Text>
          </Box>

          <Text color="fg.muted" fontSize="sm">
            Task-level alerts coming soon...
          </Text>
        </VStack>
      </Box>
    );
  }

  // Fallback
  return (
    <Box p={4}>
      <Text color="fg.muted" fontSize="sm">
        No DAG or Task ID available
      </Text>
    </Box>
  );
};
