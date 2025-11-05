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

import { InfoIcon } from "../icons/InfoIcon";

type DagRun = {
  duration: string;
  endDate: string;
  runId: string;
  startDate: string;
};

type DagSuccessAlertProps = {
  readonly alertCount: number;
  readonly successfulRuns: DagRun[];
};

export const DagSuccessAlert = ({ alertCount, successfulRuns }: DagSuccessAlertProps) => (
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
          <VStack alignItems="flex-start" gap={1} width="full">
            {successfulRuns.map((run) => (
              <Box
                key={run.runId}
                bg="bg.subtle"
                borderRadius="sm"
                fontSize="xs"
                p={2}
                width="full"
              >
                <HStack justify="space-between">
                  <Text color="fg" fontWeight="medium">
                    {run.runId}
                  </Text>
                  <Text color="fg.muted">{run.duration}</Text>
                </HStack>
                <Text color="fg.muted">{run.startDate}</Text>
              </Box>
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
