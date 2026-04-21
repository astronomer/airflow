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
import { Box, Flex, HStack, IconButton, Link, Spinner, Table, Text } from "@chakra-ui/react";
import { useMemo, useState } from "react";
import { FiChevronDown, FiChevronRight } from "react-icons/fi";
import { Link as RouterLink } from "react-router-dom";

import { useTaskInstanceServiceGetTaskInstances } from "openapi/queries";
import type { DAGRunResponse } from "openapi/requests/types.gen";
import { ClearRunButton } from "src/components/Clear";
import Time from "src/components/Time";
import { useLogs } from "src/queries/useLogs";
import { renderDuration } from "src/utils";

import { extractException } from "./extractException";

type Props = {
  readonly dagRun: DAGRunResponse;
};

export const FailureRow = ({ dagRun }: Props) => {
  const [expanded, setExpanded] = useState(false);

  const { data: failedTis, isLoading: tiLoading } = useTaskInstanceServiceGetTaskInstances(
    {
      dagId: dagRun.dag_id,
      dagRunId: dagRun.dag_run_id,
      limit: 1,
      orderBy: ["-start_date"],
      state: ["failed"],
    },
    undefined,
    { enabled: expanded },
  );

  const lastFailedTi = failedTis?.task_instances[0];

  const { isLoading: logLoading, parsedData } = useLogs(
    {
      dagId: dagRun.dag_id,
      limit: 200,
      logLevelFilters: ["error", "critical"],
      taskInstance: lastFailedTi,
      tryNumber: lastFailedTi?.try_number,
    },
    { enabled: expanded && Boolean(lastFailedTi), refetchInterval: false, retry: false },
  );

  const extracted = useMemo(() => {
    const text = parsedData.searchableText.join("\n");

    return text.length > 0 ? extractException(text) : undefined;
  }, [parsedData.searchableText]);

  const extractionInFlight = expanded && (tiLoading || logLoading);
  const noExceptionDetected = expanded && !extractionInFlight && extracted === undefined;

  return (
    <>
      <Table.Row _hover={{ bg: "bg.subtle" }}>
        <Table.Cell width="1">
          <IconButton
            aria-label={expanded ? "Collapse error details" : "Expand error details"}
            onClick={() => setExpanded((prev) => !prev)}
            size="xs"
            variant="ghost"
          >
            {expanded ? <FiChevronDown /> : <FiChevronRight />}
          </IconButton>
        </Table.Cell>
        <Table.Cell>
          <Link asChild color="fg.info" fontWeight="medium">
            <RouterLink to={`/dags/${dagRun.dag_id}`}>{dagRun.dag_display_name}</RouterLink>
          </Link>
        </Table.Cell>
        <Table.Cell>
          <Link asChild color="fg.info">
            <RouterLink to={`/dags/${dagRun.dag_id}/runs/${dagRun.dag_run_id}`}>
              <Time datetime={dagRun.run_after} />
            </RouterLink>
          </Link>
        </Table.Cell>
        <Table.Cell>{renderDuration(dagRun.duration)}</Table.Cell>
        <Table.Cell>
          <HStack gap={1} justify="flex-end">
            <ClearRunButton dagRun={dagRun} />
            <Link asChild color="fg.info" fontSize="sm">
              <RouterLink to={`/dags/${dagRun.dag_id}/runs/${dagRun.dag_run_id}`}>View</RouterLink>
            </Link>
          </HStack>
        </Table.Cell>
      </Table.Row>
      {expanded ? (
        <Table.Row>
          <Table.Cell colSpan={5} p={0}>
            <Box bg="bg.subtle" borderLeftColor="red.500" borderLeftWidth={3} p={3}>
              {extractionInFlight ? (
                <Flex align="center" gap={2}>
                  <Spinner size="xs" />
                  <Text color="fg.muted" fontSize="sm">
                    Extracting error…
                  </Text>
                </Flex>
              ) : undefined}
              {extracted ? (
                <Box fontFamily="mono" fontSize="sm">
                  <Text as="span" color="red.fg" fontWeight="bold">
                    {extracted.exceptionClass}:
                  </Text>{" "}
                  <Text as="span">{extracted.message}</Text>
                </Box>
              ) : undefined}
              {noExceptionDetected ? (
                <Text color="fg.muted" fontSize="sm">
                  No exception pattern detected in recent ERROR-level logs.{" "}
                  {lastFailedTi ? (
                    <Link asChild color="fg.info">
                      <RouterLink
                        to={`/dags/${lastFailedTi.dag_id}/runs/${lastFailedTi.dag_run_id}/tasks/${lastFailedTi.task_id}/logs`}
                      >
                        Open full logs
                      </RouterLink>
                    </Link>
                  ) : undefined}
                </Text>
              ) : undefined}
            </Box>
          </Table.Cell>
        </Table.Row>
      ) : undefined}
    </>
  );
};
