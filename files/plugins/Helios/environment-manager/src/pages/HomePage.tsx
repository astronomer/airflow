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
import { Heading, Table, Tabs, Text } from "@chakra-ui/react";

import { connectionsData } from "./connectionsData";

export const HomePage = () => (
  <>
    <Heading size="2xl" color="fg" mt={4}>
      Astro Environment Manager
    </Heading>
    <Text color="fg.muted" mt={2}>
      Astro Environment Manager enables shared access to connections, airflow variables, and environment
      variables for your deployment.
    </Text>
    <Tabs.Root variant="enclosed" defaultValue="connections" mt={4}>
      <Tabs.List>
        <Tabs.Trigger value="connections">Connections</Tabs.Trigger>
        <Tabs.Trigger value="resources">Airflow Variables</Tabs.Trigger>
        <Tabs.Trigger value="users">Environment Variables</Tabs.Trigger>
        {/* <Tabs.Trigger value="migration" asChild>
            <Button variant="ghost">Migration Tool</Button>
          </Tabs.Trigger> */}
      </Tabs.List>
      <Tabs.Content value="connections">
        <Table.Root size="sm" variant="outline" boxShadow="none" borderLeftWidth={1} borderRightWidth={1}>
          <Table.Header>
            <Table.Row>
              <Table.ColumnHeader bg="bg.emphasized">Connection ID</Table.ColumnHeader>
              <Table.ColumnHeader bg="bg.emphasized">Type</Table.ColumnHeader>
              <Table.ColumnHeader bg="bg.emphasized">Scope</Table.ColumnHeader>
              <Table.ColumnHeader bg="bg.emphasized" />
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {connectionsData.environmentObjects.map((object) => (
              <Table.Row key={object.id}>
                <Table.Cell>{object.connection.connectionAuthType.name}</Table.Cell>
                <Table.Cell>{object.connection.type}</Table.Cell>
                <Table.Cell>{object.scope === "WORKSPACE" ? "Workspace" : "This Deployment"}</Table.Cell>
                <Table.Cell textAlign="right">Manage connection</Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table.Root>
      </Tabs.Content>
      <Tabs.Content value="resources"></Tabs.Content>
      <Tabs.Content value="users"></Tabs.Content>
    </Tabs.Root>
  </>
);
