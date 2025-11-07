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
import { Box, Flex, HStack, Icon, Text, VStack } from "@chakra-ui/react";
import { FiCheckCircle, FiXCircle } from "react-icons/fi";

import { AlertFilledIcon } from "../icons/AlertFilledIcon";

type DagRun = {
  duration: number; // in minutes
  runId: string;
  startDate: string;
  status: "success" | "failed";
};

type DagDurationAlertProps = {
  readonly alertCount: number;
  readonly durationThreshold: number; // in minutes
  readonly recentRuns: DagRun[];
};

const BAR_HEIGHT = 65;

export const DagDurationAlert = ({ alertCount, durationThreshold, recentRuns }: DagDurationAlertProps) => {
  const maxDuration = Math.max(...recentRuns.map((run) => run.duration), durationThreshold);

  return (
    <Box bg="bg.muted" borderColor="border" borderRadius="md" borderWidth={1} p={4}>
      <VStack alignItems="flex-start" gap={3}>
        <HStack gap={2} width="full">
          <Icon asChild boxSize={5} color="warning.solid">
            <AlertFilledIcon />
          </Icon>
          <Text flex={1} fontSize="md" fontWeight="semibold">
            DAG Duration
          </Text>
          <Box
            bg={alertCount > 0 ? "warning.solid" : "bg.subtle"}
            borderRadius="full"
            color={alertCount > 0 ? "warning.contrast" : "fg.muted"}
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
          <Box position="relative" width="full">
            {/* Bar chart similar to RecentRuns */}
            <Flex alignItems="flex-end" flexDirection="row-reverse" gap={1} height={`${BAR_HEIGHT}px`} pb={1}>
              {recentRuns.map((run) => {
                const state = run.duration > durationThreshold ? "warning" : run.status;
                const height = Math.max((run.duration / maxDuration) * BAR_HEIGHT, 12);

                return (
                  <Flex
                    key={run.runId}
                    alignItems="center"
                    bg={`${state}.solid`}
                    borderRadius="4px"
                    flexDir="column"
                    fontSize="12px"
                    height={`${height}px`}
                    justifyContent="flex-end"
                    minHeight="12px"
                    width="12px"
                  >
                    <Icon asChild color="white">
                      {run.status === "success" ? <FiCheckCircle /> : <FiXCircle />}
                    </Icon>
                  </Flex>
                );
              })}
            </Flex>

            {/* Threshold line */}
            <Box
              bg="danger.solid"
              bottom={`${(durationThreshold / maxDuration) * BAR_HEIGHT + 4}px`}
              height="2px"
              left={0}
              position="absolute"
              right={0}
            />
          </Box>

          {/* Legend */}
          <HStack fontSize="xs" gap={4} mt={3}>
            <HStack gap={1}>
              <Box bg="success.solid" borderRadius="sm" height="12px" width="12px" />
              <Text color="fg.muted">Within threshold</Text>
            </HStack>
            <HStack gap={1}>
              <Box bg="warning.solid" borderRadius="sm" height="12px" width="12px" />
              <Text color="fg.muted">Exceeded threshold</Text>
            </HStack>
            <HStack gap={1}>
              <Box bg="danger.solid" height="2px" width="12px" />
              <Text color="fg.muted">Threshold ({durationThreshold}m)</Text>
            </HStack>
          </HStack>
        </Box>
      </VStack>
    </Box>
  );
};
