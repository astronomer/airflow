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

import { Avatar, Box, Collapsible, CollapsibleRoot, Image, Link, Text } from "@chakra-ui/react";
import { LuChevronDown } from "react-icons/lu";

import { AstroALogo } from "../components/AstroALogo";

export const AstroBarPage = () => {
  const instanceName = "Alerting_E2E_Test_azure_DND";

  return (
    <CollapsibleRoot>
      <Box borderRadius="md" borderWidth="1px" mb={2}>
        <Box
          alignItems="stretch"
          borderBottomRadius="md"
          borderBottomWidth="1px"
          display="flex"
          fontFamily="Inter"
          fontSize="sm"
          justifyContent="space-between"
          overflow="hidden"
        >
          <Box alignItems="center" display="flex">
            <Box
              _hover={{ bg: "#7352ba" }}
              alignItems="center"
              as="button"
              borderLeftRadius="md"
              cursor="pointer"
              display="flex"
              fontWeight="bold"
              pr={4}
              transition="background-color 0.2s ease-in-out"
            >
              <AstroALogo boxSize="30px" m={2} />
              {instanceName}
            </Box>
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
                <datetime datetime="2025-11-03T10:00:00Z" title="last deployed">
                  18 minutes ago
                </datetime>
              </Text>
            </Box>
          </Box>
          <Collapsible.Trigger asChild>
            <Box px={2}>
              <Box
                alignItems="center"
                as="button"
                borderLeftWidth="1px"
                display="flex"
                fontWeight="bold"
                p={2}
              >
                Deployment Analytics <LuChevronDown />
              </Box>
            </Box>
          </Collapsible.Trigger>
        </Box>
        <Collapsible.Content>
          <Box p={2}>
            <Image
              alt="Deployment Analytics"
              src="https://p199.p4.n0.cdn.zight.com/items/OAuem5vA/129bb81d-7861-4e14-a650-d0f6264dbace.jpg?v=21d6d1deb8c9e83f3c6fafadfbc7b17c"
            />
          </Box>
        </Collapsible.Content>
      </Box>
    </CollapsibleRoot>
  );
};
