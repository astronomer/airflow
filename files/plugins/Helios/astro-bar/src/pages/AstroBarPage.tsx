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

import { Avatar, Badge, Box, Button, Heading, IconButton, Link, Menu, Text, VStack } from "@chakra-ui/react";
import { LuChevronDown } from "react-icons/lu";

import { AstroALogo } from "../components/AstroALogo";
import { FiMoreHorizontal } from "react-icons/fi";
import { LogSummaries } from "src/components/LogSummaries";

export const AstroBarPage = () => {
  const instanceName = "Alerting_E2E_Test_azure_DND";

  return (
    <VStack alignItems="stretch" gap={2} mb={2}>
      <Box
        alignItems="stretch"
        borderRadius="md"
        bg="#3f2971"
        color="white"
        display="flex"
        fontFamily="Inter"
        fontSize="sm"
        justifyContent="space-between"
      >
        <Box alignItems="center" display="flex">
          <Menu.Root size="md">
            <Menu.Trigger asChild>
              <Button px={2} variant="plain" color="white" w="280px">
                <AstroALogo boxSize={6} contextBg="dark" />
                {instanceName}
                <LuChevronDown color="fg.muted" />
              </Button>
            </Menu.Trigger>
            <Menu.Positioner>
              <Menu.Content w="280px">
                <Heading fontSize="2xs" mx={2} color="white" fontWeight="normal" textTransform="uppercase">Workspace Deployments</Heading>
                <Menu.Item value="deploy-history">DQ_MUTATOR_E2E_DND</Menu.Item>
                <Menu.Item value="analytics">Alerting_E2E_Test_azure_DND</Menu.Item>
                <Menu.Item value="logs">e2e_cost_DND</Menu.Item>
                <Menu.Item value="access">Alert_E2E_CRUD_DND</Menu.Item>
              </Menu.Content>
            </Menu.Positioner>
          </Menu.Root>
          <Box alignItems="center" borderLeftWidth="1px" borderColor="rgba(255, 255, 255, 0.16)" display="flex" gap={2} px={4}>
            <Avatar.Root size="2xs">
              <Avatar.Fallback name="Ryan Hamilton" />
              <Avatar.Image src="https://avatars.githubusercontent.com/u/3267?v=4" />
            </Avatar.Root>
            <Text color="#c2aef0">
              <Link
                href="http://localhost:5000/clx9g3xak000w01ksr29jl6f2/deployments/cmbh39k15000j01mk2092ez9f"
                title="View deploy history"
                color="white"
              >
                <Box as="span" color="white" fontWeight="bold">
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
          <Badge colorPalette="info" bg="#1a0d36" color="white">Scheduled to hibernate in 1 hour <Link href="https://localhost:8000/instance/1/manage" color="#c2aef0" textDecoration="underline">manage</Link></Badge>
          <Box borderLeftWidth="1px" borderColor="rgba(255, 255, 255, 0.16)">
            <Menu.Root size="md">
              <Menu.Trigger asChild>
                <IconButton variant="plain">
                  <FiMoreHorizontal color="#c2aef0" />
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

      <LogSummaries />

      {/* <Image
        alt="Deployment Analytics"
        src="https://p199.p4.n0.cdn.zight.com/items/OAuem5vA/129bb81d-7861-4e14-a650-d0f6264dbace.jpg?v=21d6d1deb8c9e83f3c6fafadfbc7b17c"
      /> */}
    </VStack>
  );
};
