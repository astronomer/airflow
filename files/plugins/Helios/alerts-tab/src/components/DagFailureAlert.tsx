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

import { AlertCircleFilledIcon } from "../icons/AlertCircleFilledIcon";

type DagRun = {
  duration: string;
  error: string;
  runId: string;
  startDate: string;
};

type DagFailureAlertProps = {
  readonly alertCount: number;
  readonly failedRuns: DagRun[];
};

export const DagFailureAlert = ({ alertCount, failedRuns }: DagFailureAlertProps) => (
  <Box bg="bg.muted" borderColor="border" borderRadius="md" borderWidth={1} p={4}>
    <VStack alignItems="flex-start" gap={3}>
      <HStack gap={2} width="full">
        <Icon asChild boxSize={5} color="red.500">
          <AlertCircleFilledIcon />
        </Icon>
        <Text flex={1} fontSize="md" fontWeight="semibold">
          DAG Failure
        </Text>
        <Box
          bg={alertCount > 0 ? "red.500" : "bg.subtle"}
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
        Sends notifications when a DAG run fails or encounters an error
      </Text>

      {failedRuns.length > 0 ? (
        <Box width="full">
          <Text color="fg" fontSize="sm" fontWeight="medium" mb={2}>
            Failed runs in last 24 hours:
          </Text>
          <VStack alignItems="flex-start" gap={1} width="full">
            {failedRuns.map((run) => (
              <Box
                key={run.runId}
                bg="red.950"
                borderColor="red.800"
                borderRadius="sm"
                borderWidth={1}
                fontSize="xs"
                p={2}
                width="full"
              >
                <HStack justify="space-between">
                  <Text color="red.200" fontWeight="medium">
                    {run.runId}
                  </Text>
                  <Text color="red.300">{run.duration}</Text>
                </HStack>
                <Text color="red.300">{run.startDate}</Text>
                <Text color="red.400" fontSize="xs" mt={1}>
                  {run.error}
                </Text>
              </Box>
            ))}
          </VStack>
        </Box>
      ) : (
        <Text color="fg.muted" fontSize="xs">
          No failed runs in the last 24 hours
        </Text>
      )}
    </VStack>
  </Box>
);
