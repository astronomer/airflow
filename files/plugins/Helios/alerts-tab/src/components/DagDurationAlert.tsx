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
  duration: number; // in minutes
  runId: string;
  startDate: string;
};

type DagDurationAlertProps = {
  readonly alertCount: number;
  readonly durationThreshold: number; // in minutes
  readonly recentRuns: DagRun[];
};

export const DagDurationAlert = ({ alertCount, durationThreshold, recentRuns }: DagDurationAlertProps) => {
  const maxDuration = Math.max(...recentRuns.map((run) => run.duration), durationThreshold);

  return (
    <Box bg="bg.muted" borderColor="border" borderRadius="md" borderWidth={1} p={4}>
      <VStack alignItems="flex-start" gap={3}>
        <HStack gap={2} width="full">
          <Icon asChild boxSize={5} color="yellow.500">
            <AlertFilledIcon />
          </Icon>
          <Text flex={1} fontSize="md" fontWeight="semibold">
            DAG Duration
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
          Sends notifications when a DAG run exceeds {durationThreshold} minutes
        </Text>

        <Box width="full">
          <Text color="fg" fontSize="sm" fontWeight="medium" mb={2}>
            Recent DAG run durations:
          </Text>
          <VStack alignItems="flex-start" gap={2} width="full">
            {recentRuns.map((run) => {
              const widthPercent = (run.duration / maxDuration) * 100;
              const thresholdPercent = (durationThreshold / maxDuration) * 100;
              const exceededThreshold = run.duration > durationThreshold;

              return (
                <Box key={run.runId} width="full">
                  <HStack fontSize="xs" justify="space-between" mb={1}>
                    <Text color="fg.muted">{run.runId}</Text>
                    <Text color={exceededThreshold ? "yellow.400" : "fg"} fontWeight="medium">
                      {run.duration}m
                    </Text>
                  </HStack>
                  <Box height="24px" position="relative" width="full">
                    <Box
                      bg={exceededThreshold ? "yellow.600" : "blue.600"}
                      borderRadius="sm"
                      height="full"
                      width={`${widthPercent}%`}
                    />
                    <Box
                      bg="red.500"
                      height="full"
                      left={`${thresholdPercent}%`}
                      position="absolute"
                      top={0}
                      width="2px"
                    />
                  </Box>
                </Box>
              );
            })}
            <HStack fontSize="xs" gap={4} mt={1}>
              <HStack gap={1}>
                <Box bg="blue.600" borderRadius="sm" height="12px" width="12px" />
                <Text color="fg.muted">Within threshold</Text>
              </HStack>
              <HStack gap={1}>
                <Box bg="yellow.600" borderRadius="sm" height="12px" width="12px" />
                <Text color="fg.muted">Exceeded threshold</Text>
              </HStack>
              <HStack gap={1}>
                <Box bg="red.500" height="12px" width="2px" />
                <Text color="fg.muted">Threshold line ({durationThreshold}m)</Text>
              </HStack>
            </HStack>
          </VStack>
        </Box>
      </VStack>
    </Box>
  );
};
