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
import { Box, HStack, Icon, Link, Text } from "@chakra-ui/react";
import { FiExternalLink } from "react-icons/fi";

import { MegaphoneIcon } from "./MegaphoneIcon";

type AlertBannerProps = {
  readonly cumulativeCount: number;
  readonly title?: string;
  readonly totalAlerts: number;
  readonly viewAllUrl: string;
};

export const AlertBanner = ({
  cumulativeCount,
  totalAlerts,
  viewAllUrl,
}: AlertBannerProps) => (
  <Box bg="brand.subtle" borderRadius="md" borderTopRadius="md" borderWidth={1} color="brand.contrast" p={2}>
    <HStack gap={4} justify="space-between">
      <HStack gap={2}>
        <MegaphoneIcon boxSize={5} />
        <Text fontSize="md" fontWeight="bold">
          {cumulativeCount} Astro Alerts sent in the last 24 hours
        </Text>
          <Link color="white" href={viewAllUrl} rel="noopener noreferrer" target="_blank">
            <Text fontSize="sm" fontWeight="medium">
              View All
            </Text>
            <Icon asChild boxSize={4}>
              <FiExternalLink />
            </Icon>
        </Link>
      </HStack>
      <HStack divideColor="whiteAlpha/40" divideX="1px" gap={3}>
        <Text fontSize="sm" fontWeight="medium" opacity={0.9}>
          {totalAlerts} Alerts Configured
        </Text>
      </HStack>
    </HStack>
  </Box>
);
