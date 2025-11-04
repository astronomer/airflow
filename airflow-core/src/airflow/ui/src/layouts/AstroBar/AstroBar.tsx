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

/* eslint-disable i18next/no-literal-string */
import { Avatar, Badge, Box, Button, IconButton, Image, Link, Menu, Text, VStack } from "@chakra-ui/react";
import { FiMoreHorizontal } from "react-icons/fi";
import { LuChevronDown } from "react-icons/lu";

import { AstroALogo } from "./AstroALogo";

export const AstroBar = () => {
  const instanceName = "Alerting_E2E_Test_azure_DND";

  return (
    <VStack alignItems="stretch" gap={2} mb={2}>
      <Box
        alignItems="stretch"
        borderRadius="md"
        borderWidth="1px"
        display="flex"
        fontFamily="Inter"
        fontSize="sm"
        justifyContent="space-between"
      >
        <Box alignItems="center" display="flex">
          <Menu.Root size="sm">
            <Menu.Trigger asChild>
              <Button px={2} variant="plain">
                <AstroALogo boxSize={6} />
                {instanceName}
                <LuChevronDown color="fg.muted" />
              </Button>
            </Menu.Trigger>
            <Menu.Positioner>
              <Menu.Content>
                <Menu.Item value="deploy-history">Deploy History</Menu.Item>
                <Menu.Item value="analytics">Analytics</Menu.Item>
                <Menu.Item value="logs">Logs</Menu.Item>
                <Menu.Item value="access">Access</Menu.Item>
                <Menu.Item value="alerts">Alerts</Menu.Item>
                <Menu.Item value="incident-history">Incident History</Menu.Item>
                <Menu.Item value="deployment-details">Deployment Details</Menu.Item>
              </Menu.Content>
            </Menu.Positioner>
          </Menu.Root>
          <Box alignItems="center" borderLeftWidth="1px" display="flex" gap={2} px={4}>
            <Avatar.Root size="2xs">
              <Avatar.Fallback name="Ryan Hamilton" />
              <Avatar.Image src="https://avatars.githubusercontent.com/u/3267?v=4" />
            </Avatar.Root>
            <Text color="fg.muted">
              <Link
                href="http://localhost:5000/clx9g3xak000w01ksr29jl6f2/deployments/cmbh39k15000j01mk2092ez9f"
                title="View deploy history"
              >
                <Box as="span" color="fg" fontWeight="bold">
                  Ryan Hamilton
                </Box>{" "}
                Refactor task dependency
              </Link>
              {" · "}
              <time dateTime="2025-11-03T10:00:00Z" title="last deployed">
                18 minutes ago
              </time>
            </Text>
          </Box>
        </Box>
        <Box alignItems="center" display="flex" gap={2}>
          <Badge colorPalette="info">Scheduled to hibernate in 1 hour</Badge>
          <Box borderLeftWidth="1px">
            <Menu.Root size="sm">
              <Menu.Trigger asChild>
                <IconButton variant="plain">
                  <FiMoreHorizontal color="fg.muted" />
                </IconButton>
              </Menu.Trigger>
              <Menu.Positioner>
                <Menu.Content>
                  <Menu.Item value="deploy-history">Deploy History</Menu.Item>
                  <Menu.Item value="analytics">Analytics</Menu.Item>
                  <Menu.Item value="logs">Logs</Menu.Item>
                  <Menu.Item value="access">Access</Menu.Item>
                  <Menu.Item value="alerts">Alerts</Menu.Item>
                  <Menu.Item value="incident-history">Incident History</Menu.Item>
                  <Menu.Item value="deployment-details">Deployment Details</Menu.Item>
                </Menu.Content>
              </Menu.Positioner>
            </Menu.Root>
          </Box>
        </Box>
      </Box>

      <Image
        alt="Deployment Analytics"
        src="https://p199.p4.n0.cdn.zight.com/items/OAuem5vA/129bb81d-7861-4e14-a650-d0f6264dbace.jpg?v=21d6d1deb8c9e83f3c6fafadfbc7b17c"
      />
    </VStack>
  );
};
