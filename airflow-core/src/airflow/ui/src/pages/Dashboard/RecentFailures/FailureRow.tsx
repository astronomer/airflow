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
import { Button, HStack, IconButton, Link, Stack, Table } from "@chakra-ui/react";
import { useState } from "react";
import { FiChevronDown, FiChevronRight } from "react-icons/fi";
import { Link as RouterLink } from "react-router-dom";

import type { DAGRunResponse, TaskInstanceResponse } from "openapi/requests/types.gen";
import { ClearRunButton } from "src/components/Clear";
import Time from "src/components/Time";
import { renderDuration } from "src/utils";

import { TaskFailureLine } from "./TaskFailureLine";

const INLINE_TASK_LIMIT = 3;

type Props = {
  readonly dagRun: DAGRunResponse;
  readonly failedTis: Array<TaskInstanceResponse>;
};

export const FailureRow = ({ dagRun, failedTis }: Props) => {
  const [expanded, setExpanded] = useState(false);

  const hasMoreThanLimit = failedTis.length > INLINE_TASK_LIMIT;
  const visibleTis = expanded ? failedTis : failedTis.slice(0, INLINE_TASK_LIMIT);
  const hiddenCount = Math.max(0, failedTis.length - INLINE_TASK_LIMIT);

  const expandable = failedTis.length > 0;

  return (
    <Table.Row _hover={{ bg: "bg.subtle" }}>
      <Table.Cell verticalAlign="top" width="1">
        {expandable ? (
          <IconButton
            aria-label={expanded ? "Collapse failed tasks" : "Show full messages and all failed tasks"}
            onClick={() => setExpanded((prev) => !prev)}
            size="xs"
            variant="ghost"
          >
            {expanded ? <FiChevronDown /> : <FiChevronRight />}
          </IconButton>
        ) : undefined}
      </Table.Cell>
      <Table.Cell verticalAlign="top">
        <Stack gap={1}>
          <Link asChild color="fg.info" fontWeight="medium">
            <RouterLink to={`/dags/${dagRun.dag_id}`}>{dagRun.dag_display_name}</RouterLink>
          </Link>
          {failedTis.length === 0 ? undefined : (
            <Stack gap={0.5} pl={2}>
              {visibleTis.map((ti) => (
                <TaskFailureLine key={ti.id} taskInstance={ti} truncated={!expanded} />
              ))}
              {!expanded && hasMoreThanLimit ? (
                <Button
                  alignSelf="flex-start"
                  color="fg.info"
                  fontSize="xs"
                  height="auto"
                  onClick={() => setExpanded(true)}
                  p={0}
                  textDecoration="underline"
                  variant="plain"
                >
                  + {hiddenCount} more failed task{hiddenCount === 1 ? "" : "s"}
                </Button>
              ) : undefined}
            </Stack>
          )}
        </Stack>
      </Table.Cell>
      <Table.Cell verticalAlign="top">
        <Link asChild color="fg.info">
          <RouterLink to={`/dags/${dagRun.dag_id}/runs/${dagRun.dag_run_id}`}>
            <Time datetime={dagRun.run_after} />
          </RouterLink>
        </Link>
      </Table.Cell>
      <Table.Cell verticalAlign="top">{renderDuration(dagRun.duration)}</Table.Cell>
      <Table.Cell verticalAlign="top">
        <HStack gap={1} justify="flex-end">
          <ClearRunButton dagRun={dagRun} />
          <Link asChild color="fg.info" fontSize="sm">
            <RouterLink to={`/dags/${dagRun.dag_id}/runs/${dagRun.dag_run_id}`}>View</RouterLink>
          </Link>
        </HStack>
      </Table.Cell>
    </Table.Row>
  );
};
