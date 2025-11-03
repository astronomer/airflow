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

import { Box, Button, Card, Heading, HStack, Icon, Link, Tabs, Text, VStack } from "@chakra-ui/react";
import { LuMoon, LuSun } from "react-icons/lu";

import { useColorMode } from "src/context/colorMode";

export const HomePage = () => {
  const { colorMode, setColorMode } = useColorMode();

  return (
    <>
    <Heading size="2xl" color="fg"  mt={4}>Astro Environment Manager</Heading>
    <Tabs.Root variant="enclosed" mt={4}>
      <Tabs.List>
        <Tabs.Trigger value="environments">Connections</Tabs.Trigger>
        <Tabs.Trigger value="resources">Airflow Variables</Tabs.Trigger>
        <Tabs.Trigger value="users">Environment Variables</Tabs.Trigger>
      </Tabs.List>
    </Tabs.Root>
    <Box p={8} bg="bg" height="100%" overflow="auto">
      <VStack gap={8} maxW="1200px" mx="auto">
        {/* Hero Section */}
        <VStack gap={4} py={12} align="center" textAlign="center">
          <Heading size="4xl" color="fg" fontWeight="bold">
            Welcome to Helios
          </Heading>
          <Text fontSize="xl" color="fg.muted" maxW="2xl">
            A modern React plugin for Apache Airflow v3.1+ that demonstrates how to create
            custom UI integrations with beautiful components and seamless integration.
          </Text>
          <HStack gap={4} mt={4}>
            <Button
              colorPalette="blue"
              size="lg"
              onClick={() => setColorMode(colorMode === "dark" ? "light" : "dark")}
            >
              <Icon>{colorMode === "dark" ? <LuSun /> : <LuMoon />}</Icon>
              Toggle {colorMode === "dark" ? "Light" : "Dark"} Mode
            </Button>
          </HStack>
        </VStack>

        {/* Features Grid */}
        <VStack gap={6} align="stretch" w="100%">
          <Heading size="xl" color="fg">
            Features
          </Heading>
          <Box display="grid" gridTemplateColumns="repeat(auto-fit, minmax(300px, 1fr))" gap={6}>
            <Card.Root bg="bg.subtle" borderRadius="lg">
              <Card.Header>
                <Heading size="md" color="fg">
                  🚀 Modern React
                </Heading>
              </Card.Header>
              <Card.Body>
                <Text color="fg.muted">
                  Built with React 19, TypeScript, and the latest web technologies for a fast and
                  reliable experience.
                </Text>
              </Card.Body>
            </Card.Root>

            <Card.Root bg="bg.subtle" borderRadius="lg">
              <Card.Header>
                <Heading size="md" color="fg">
                  🎨 Chakra UI 3
                </Heading>
              </Card.Header>
              <Card.Body>
                <Text color="fg.muted">
                  Beautiful, accessible components out of the box with full theming support and
                  dark mode.
                </Text>
              </Card.Body>
            </Card.Root>

            <Card.Root bg="bg.subtle" borderRadius="lg">
              <Card.Header>
                <Heading size="md" color="fg">
                  ⚡ Lightning Fast
                </Heading>
              </Card.Header>
              <Card.Body>
                <Text color="fg.muted">
                  Powered by Vite for instant hot module replacement and optimized production
                  builds.
                </Text>
              </Card.Body>
            </Card.Root>

            <Card.Root bg="bg.subtle" borderRadius="lg">
              <Card.Header>
                <Heading size="md" color="fg">
                  🔌 Airflow Integration
                </Heading>
              </Card.Header>
              <Card.Body>
                <Text color="fg.muted">
                  Seamlessly integrates with Airflow v3.1+ using the React plugin system and
                  FastAPI.
                </Text>
              </Card.Body>
            </Card.Root>

            <Card.Root bg="bg.subtle" borderRadius="lg">
              <Card.Header>
                <Heading size="md" color="fg">
                  📦 UMD Bundle
                </Heading>
              </Card.Header>
              <Card.Body>
                <Text color="fg.muted">
                  Builds as a UMD module that shares React with the host application to minimize
                  bundle size.
                </Text>
              </Card.Body>
            </Card.Root>

            <Card.Root bg="bg.subtle" borderRadius="lg">
              <Card.Header>
                <Heading size="md" color="fg">
                  🛠️ Developer Friendly
                </Heading>
              </Card.Header>
              <Card.Body>
                <Text color="fg.muted">
                  Includes ESLint, Prettier, TypeScript, and testing setup for a great developer
                  experience.
                </Text>
              </Card.Body>
            </Card.Root>
          </Box>
        </VStack>

        {/* Getting Started */}
        <Card.Root bg="bg.subtle" borderRadius="lg" w="100%">
          <Card.Header>
            <Heading size="lg" color="fg">
              Getting Started
            </Heading>
          </Card.Header>
          <Card.Body>
            <VStack align="stretch" gap={4}>
              <Text color="fg">
                To customize this plugin, edit the components in <code>src/pages/</code> and rebuild:
              </Text>
              <Box
                as="pre"
                bg="bg.emphasized"
                p={4}
                borderRadius="md"
                overflowX="auto"
                fontSize="sm"
                fontFamily="mono"
              >
                <code>
                  pnpm build{"\n"}
                  # Then restart Airflow webserver
                </code>
              </Box>
              <Text color="fg.muted">
                For detailed integration instructions, see <code>INTEGRATION_GUIDE.md</code>
              </Text>
            </VStack>
          </Card.Body>
        </Card.Root>

        {/* Footer */}
        <Box py={8} textAlign="center">
          <Text color="fg.muted">
            Built with ❤️ for Apache Airflow • See{" "}
            <Link href="https://airflow.apache.org" color="blue.solid" target="_blank">
              airflow.apache.org
            </Link>
          </Text>
        </Box>
      </VStack>
    </Box>
    </>
  );
};
