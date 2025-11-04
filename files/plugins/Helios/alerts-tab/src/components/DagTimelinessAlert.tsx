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
import { Box, HStack, Icon, Text, VStack } from "@chakra-ui/react";

import { AlertFilledIcon } from "../icons/AlertFilledIcon";

type DagRun = {
  completionTime: string;
  runId: string;
  startDate: string;
};

type MissedDeadline = {
  dagRuns: DagRun[];
  deadline: string;
  missed: boolean;
};

type DagTimelinessAlertProps = {
  readonly alertCount: number;
  readonly missedDeadlines: MissedDeadline[];
  readonly upcomingDeadline: string;
};

export const DagTimelinessAlert = ({ alertCount, missedDeadlines, upcomingDeadline }: DagTimelinessAlertProps) => (
  <Box bg="bg.muted" borderColor="border" borderRadius="md" borderWidth={1} p={4}>
    <VStack alignItems="flex-start" gap={3}>
      <HStack gap={2} width="full">
        <Icon asChild boxSize={5} color="yellow.500">
          <AlertFilledIcon />
        </Icon>
        <Text flex={1} fontSize="md" fontWeight="semibold">
          DAG Timeliness
        </Text>
        <Box
          bg={alertCount > 0 ? "yellow.500" : "bg.subtle"}
          borderRadius="full"
          color={alertCount > 0 ? "black" : "fg.muted"}
          fontSize="sm"
          fontWeight="bold"
          minW={8}
          px={2}
          py={1}
          textAlign="center"
        >
          {alertCount}
        </Box>
      </HStack>
      
      <Text color="fg.muted" fontSize="sm">
        Sends notifications when a DAG run doesn't complete by a specified deadline
      </Text>

      <Box width="full">
        <Text color="fg" fontSize="sm" fontWeight="medium" mb={2}>
          Upcoming deadline:
        </Text>
        <Box bg="blue.950" borderColor="blue.800" borderRadius="sm" borderWidth={1} fontSize="sm" p={2}>
          <Text color="blue.200" fontWeight="medium">
            {upcomingDeadline}
          </Text>
        </Box>
      </Box>

      {missedDeadlines.length > 0 ? (
        <Box width="full">
          <Text color="fg" fontSize="sm" fontWeight="medium" mb={2}>
            Recent deadline periods:
          </Text>
          <VStack alignItems="flex-start" gap={2} width="full">
            {missedDeadlines.map((deadline, index) => (
              <Box
                key={index}
                bg={deadline.missed ? "yellow.950" : "green.950"}
                borderColor={deadline.missed ? "yellow.800" : "green.800"}
                borderRadius="sm"
                borderWidth={1}
                fontSize="xs"
                p={2}
                width="full"
              >
                <HStack justify="space-between" mb={1}>
                  <Text color={deadline.missed ? "yellow.200" : "green.200"} fontWeight="medium">
                    {deadline.missed ? "⚠️ Missed" : "✓ Met"}
                  </Text>
                  <Text color={deadline.missed ? "yellow.300" : "green.300"}>
                    Deadline: {deadline.deadline}
                  </Text>
                </HStack>
                {deadline.dagRuns.length > 0 ? (
                  <VStack alignItems="flex-start" gap={1} mt={1}>
                    {deadline.dagRuns.map((run) => (
                      <Box
                        key={run.runId}
                        bg="bg.subtle"
                        borderRadius="sm"
                        p={1}
                        width="full"
                      >
                        <Text color="fg" fontWeight="medium">
                          {run.runId}
                        </Text>
                        <Text color="fg.muted">
                          Completed: {run.completionTime}
                        </Text>
                      </Box>
                    ))}
                  </VStack>
                ) : (
                  <Text color="fg.muted" fontSize="xs" mt={1}>
                    No runs in this period
                  </Text>
                )}
              </Box>
            ))}
          </VStack>
        </Box>
      ) : (
        <Text color="fg.muted" fontSize="xs">
          No deadline data available
        </Text>
      )}
    </VStack>
  </Box>
);
