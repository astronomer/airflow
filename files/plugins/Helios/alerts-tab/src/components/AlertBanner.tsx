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
import { Box, HStack, Text } from "@chakra-ui/react";

import { MegaphoneIcon } from "../MegaphoneIcon";

type AlertBannerProps = {
  readonly cumulativeCount: number;
  readonly totalAlerts: number;
};

export const AlertBanner = ({ cumulativeCount, totalAlerts }: AlertBannerProps) => (
  <Box bg="purple.800" borderRadius="md" borderWidth={1} color="white" p={4}>
    <HStack gap={4} justify="space-between">
      <HStack gap={2}>
        <MegaphoneIcon boxSize={5} />
        <Text fontSize="lg" fontWeight="bold">
          DAG Alerts Overview
        </Text>
      </HStack>
      <HStack divideX={1} gap={4}>
        <Box>
          <Text fontSize="sm" fontWeight="medium" opacity={0.9}>
            Configured Alerts
          </Text>
          <Text fontSize="2xl" fontWeight="bold">
            {totalAlerts}
          </Text>
        </Box>
        <Box pl={4}>
          <Text fontSize="sm" fontWeight="medium" opacity={0.9}>
            Sent (24h)
          </Text>
          <Text fontSize="2xl" fontWeight="bold">
            {cumulativeCount}
          </Text>
        </Box>
      </HStack>
    </HStack>
  </Box>
);

