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
import { Badge, Box, HStack, Icon, Text, VStack } from "@chakra-ui/react";
import dayjs from "dayjs";

import { InfoIcon } from "../icons/InfoIcon";

type DagRun = {
  duration: number; // in seconds
  endDate: string;
  runId: string;
  startDate: string;
  status: "success";
};

type DagSuccessAlertProps = {
  readonly alertCount: number;
  readonly successfulRuns: DagRun[];
};

const formatDuration = (seconds: number): string => {
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return remainingSeconds > 0 ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
};

export const DagSuccessAlert = ({ alertCount, successfulRuns }: DagSuccessAlertProps) => {
  return (
    <Box bg="bg.muted" borderColor="border" borderRadius="md" borderWidth={1} p={4}>
      <VStack alignItems="flex-start" gap={3}>
        <HStack gap={2} width="full">
          <Icon asChild boxSize={5} color="info.solid">
            <InfoIcon />
          </Icon>
          <Text flex={1} fontSize="md" fontWeight="semibold">
            DAG Success
          </Text>
          <Box
            bg={alertCount > 0 ? "info.solid" : "bg.subtle"}
            borderRadius="full"
            color={alertCount > 0 ? "white" : "fg.muted"}
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
          Sends notifications when a DAG run completes successfully
        </Text>

        {successfulRuns.length > 0 ? (
          <Box width="full">
            <Text color="fg" fontSize="sm" fontWeight="medium" mb={2}>
              Successful runs in last 24 hours:
            </Text>
            <VStack alignItems="flex-start" gap={2} width="full">
              {successfulRuns.map((run) => (
                <HStack key={run.runId} gap={3} width="full">
                  {/* Circular state badge */}
                  <Badge
                    borderRadius="full"
                    colorPalette="success"
                    fontSize="sm"
                    px={1}
                    py={1}
                    variant="solid"
                  >
                    <Icon asChild>
                      <svg fill="currentColor" height="12" viewBox="0 0 16 16" width="12">
                        <circle cx="8" cy="8" r="8" />
                      </svg>
                    </Icon>
                  </Badge>

                  {/* Run info */}
                  <VStack alignItems="flex-start" flex={1} gap={0}>
                    <Text color="fg" fontSize="sm" fontWeight="medium">
                      {dayjs(run.startDate).format("MMM D, h:mm A")}
                    </Text>
                    <HStack fontSize="xs" gap={2}>
                      <Text color="fg.muted">ID: {run.runId}</Text>
                      <Text color="fg.muted">•</Text>
                      <Text color="fg.muted">Duration: {formatDuration(run.duration)}</Text>
                    </HStack>
                  </VStack>
                </HStack>
              ))}
            </VStack>
          </Box>
        ) : (
          <Text color="fg.muted" fontSize="xs">
            No successful runs in the last 24 hours
          </Text>
        )}
      </VStack>
    </Box>
  );
};
