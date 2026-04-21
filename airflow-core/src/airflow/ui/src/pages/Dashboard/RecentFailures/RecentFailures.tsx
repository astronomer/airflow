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

/* eslint-disable i18next/no-literal-string --
   POC: strings will be localized before any real PR. */
import { Box, Flex, Heading, Link, Skeleton, Table, Text } from "@chakra-ui/react";
import { FiAlertCircle, FiCheckCircle } from "react-icons/fi";
import { Link as RouterLink } from "react-router-dom";

import { useDagRunServiceGetDagRuns } from "openapi/queries";
import { useAutoRefresh } from "src/utils";

import { FailureRow } from "./FailureRow";

type Props = {
  readonly compact?: boolean;
  readonly limit?: number;
};

export const RecentFailures = ({ compact = false, limit = 10 }: Props) => {
  const refetchInterval = useAutoRefresh({ checkPendingRuns: true });

  const { data, isLoading } = useDagRunServiceGetDagRuns(
    {
      dagId: "~",
      limit,
      orderBy: ["-run_after"],
      state: ["failed"],
    },
    undefined,
    { refetchInterval },
  );

  const runs = data?.dag_runs ?? [];

  if (isLoading && runs.length === 0) {
    return (
      <Box>
        <Flex align="center" color="fg.muted" my={2}>
          <FiAlertCircle />
          <Heading ml={1} size="xs">
            Recent Failures
          </Heading>
        </Flex>
        <Skeleton height={compact ? "80px" : "140px"} />
      </Box>
    );
  }

  if (runs.length === 0) {
    return (
      <Box>
        <Flex align="center" color="fg.muted" my={2}>
          <FiCheckCircle color="var(--chakra-colors-green-fg)" />
          <Heading ml={1} size="xs">
            Recent Failures
          </Heading>
        </Flex>
        <Text color="fg.muted" fontSize="sm" ml={1}>
          No recent failures. All clear.
        </Text>
      </Box>
    );
  }

  return (
    <Box>
      <Flex align="center" justify="space-between" my={2}>
        <Flex align="center" color="fg.muted">
          <FiAlertCircle />
          <Heading ml={1} size="xs">
            Recent Failures
          </Heading>
        </Flex>
        <Link asChild color="fg.info" fontSize="sm">
          <RouterLink to="/dag_runs?state=failed">See all failed runs →</RouterLink>
        </Link>
      </Flex>
      <Box borderColor="border" borderRadius="md" borderWidth={1} overflow="hidden">
        <Table.Root size={compact ? "sm" : "md"} variant="outline">
          <Table.Header>
            <Table.Row>
              <Table.ColumnHeader width="1" />
              <Table.ColumnHeader>Dag</Table.ColumnHeader>
              <Table.ColumnHeader>Run After</Table.ColumnHeader>
              <Table.ColumnHeader>Duration</Table.ColumnHeader>
              <Table.ColumnHeader textAlign="end">Actions</Table.ColumnHeader>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {runs.map((run) => (
              <FailureRow dagRun={run} key={`${run.dag_id}:${run.dag_run_id}`} />
            ))}
          </Table.Body>
        </Table.Root>
      </Box>
    </Box>
  );
};
