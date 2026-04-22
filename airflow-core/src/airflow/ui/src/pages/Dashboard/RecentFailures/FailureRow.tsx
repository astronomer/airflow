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
import { Badge, Button, Flex, HStack, IconButton, Link, Stack, Table, Text } from "@chakra-ui/react";
import { useState } from "react";
import { FiArrowRight, FiChevronDown, FiChevronRight } from "react-icons/fi";
import { Link as RouterLink } from "react-router-dom";

import type { DAGRunLightResponse, DAGRunResponse, TaskInstanceResponse } from "openapi/requests/types.gen";
import { ClearRunButton } from "src/components/Clear";
import { RunTypeIcon } from "src/components/RunTypeIcon";
import Time from "src/components/Time";
import { ClipboardIconButton, ClipboardRoot, Tooltip } from "src/components/ui";
import { DagOwners } from "src/pages/DagsList/DagOwners";
import { renderHumanizedDuration } from "src/utils";
import { DEFAULT_DATETIME_FORMAT_WITH_TZ, getRelativeTime } from "src/utils/datetimeUtils";

import { RunStatusDot } from "./RunStatusDot";
import { TaskFailureLine } from "./TaskFailureLine";

// POC: labels mirror the common:runTypes.* i18n namespace; swap to translate()
// when this file is localized.
const RUN_TYPE_LABELS: Record<DAGRunResponse["run_type"], string> = {
  asset_materialization: "Asset materialization",
  asset_triggered: "Asset triggered",
  backfill: "Backfill",
  manual: "Manual",
  operator_triggered: "Operator triggered",
  scheduled: "Scheduled",
};

const INLINE_TASK_LIMIT = 3;
// Floor matches a size="md" button (~40px) so the first row stays aligned
// with other 40px content elsewhere on the page even though this row's
// size="sm" action buttons are shorter. Trim row padding to compensate.
const FIRST_ROW_MIN_H = "10";
const ROW_PY = 2;

type Props = {
  // Every run for this DAG in the current window, most recent first. The row
  // renders the head run's details and shows a ×N badge when len > 1.
  readonly dagRuns: Array<DAGRunResponse>;
  readonly endDate: string;
  readonly failedTis: Array<TaskInstanceResponse>;
  readonly owners: Array<string>;
  // The DAG's most recent runs overall (any state), newest first. The
  // RunStatusDot reads runs[0] to decide the row's current-state signal.
  readonly recentRuns: Array<DAGRunLightResponse>;
  readonly startDate: string;
};

export const FailureRow = ({ dagRuns, endDate, failedTis, owners, recentRuns, startDate }: Props) => {
  const [expanded, setExpanded] = useState(false);

  const [mostRecent] = dagRuns;

  if (mostRecent === undefined) {
    return undefined;
  }

  const failureCount = dagRuns.length;
  const hasMoreThanLimit = failedTis.length > INLINE_TASK_LIMIT;
  const visibleTis = expanded ? failedTis : failedTis.slice(0, INLINE_TASK_LIMIT);
  const hiddenCount = Math.max(0, failedTis.length - INLINE_TASK_LIMIT);

  const expandable = failedTis.length > 0;

  const failedAt = mostRecent.end_date ?? mostRecent.run_after;

  return (
    <Table.Row _hover={{ bg: "bg.emphasized" }}>
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
      <Table.Cell py={ROW_PY} verticalAlign="top">
        <Stack gap={1}>
          <Flex align="center" columnGap={2} flexWrap="wrap" minH={FIRST_ROW_MIN_H} rowGap={0.5}>
            <Link asChild color="fg.info" fontFamily="mono" fontWeight="semibold">
              <RouterLink to={`/dags/${mostRecent.dag_id}`}>{mostRecent.dag_display_name}</RouterLink>
            </Link>
            {owners.length > 0 ? (
              <Flex align="center" color="fg.muted" fontSize="sm" gap={1}>
                <span>·</span>
                <DagOwners owners={owners} />
              </Flex>
            ) : undefined}
            {failureCount > 1 ? (
              <Tooltip
                content={`${failureCount} failed runs for this DAG in this window — click to see them all`}
              >
                <Link
                  aria-label={`See all ${failureCount} failed runs for ${mostRecent.dag_display_name}`}
                  asChild
                >
                  <RouterLink
                    to={`/dag_runs?state=failed&dag_id_pattern=${encodeURIComponent(mostRecent.dag_id)}&run_after_gte=${encodeURIComponent(startDate)}&run_after_lte=${encodeURIComponent(endDate)}`}
                  >
                    <Badge colorPalette="red" size="sm" variant="subtle">
                      ×{failureCount}
                    </Badge>
                  </RouterLink>
                </Link>
              </Tooltip>
            ) : undefined}
            {recentRuns.length > 0 ? (
              <RunStatusDot focusedRunId={mostRecent.dag_run_id} runs={recentRuns} />
            ) : undefined}
          </Flex>
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
          {expanded ? (
            <HStack color="fg.muted" fontSize="xs" gap={1} pl={2} pt={1}>
              <Text as="span" fontWeight="medium">
                Run ID
              </Text>
              <Text as="span" fontFamily="mono">
                {mostRecent.dag_run_id}
              </Text>
              <ClipboardRoot value={mostRecent.dag_run_id}>
                <ClipboardIconButton aria-label="Copy run ID" />
              </ClipboardRoot>
            </HStack>
          ) : undefined}
        </Stack>
      </Table.Cell>
      <Table.Cell py={ROW_PY} verticalAlign="top">
        <Stack gap={0.5} justify="center" minH={FIRST_ROW_MIN_H}>
          <Tooltip
            content={
              <Time datetime={failedAt} format={DEFAULT_DATETIME_FORMAT_WITH_TZ} showTooltip={false} />
            }
          >
            <Link asChild color="fg.info">
              <RouterLink to={`/dags/${mostRecent.dag_id}/runs/${mostRecent.dag_run_id}`}>
                <Text as="span">{getRelativeTime(failedAt)}</Text>
              </RouterLink>
            </Link>
          </Tooltip>
          <HStack color="fg.muted" fontSize="xs" gap={1}>
            <RunTypeIcon runType={mostRecent.run_type} />
            <Text as="span">{RUN_TYPE_LABELS[mostRecent.run_type]}</Text>
          </HStack>
        </Stack>
      </Table.Cell>
      <Table.Cell py={ROW_PY} verticalAlign="top">
        <Flex align="center" fontFamily="mono" fontVariantNumeric="tabular-nums" minH={FIRST_ROW_MIN_H}>
          {renderHumanizedDuration(mostRecent.duration)}
        </Flex>
      </Table.Cell>
      <Table.Cell py={ROW_PY} verticalAlign="top">
        <HStack align="center" gap={2} justify="flex-end" minH={FIRST_ROW_MIN_H}>
          <ClearRunButton dagRun={mostRecent} size="sm" variant="outline" />
          <Tooltip content="Open dag run">
            <IconButton aria-label="Open dag run" asChild colorPalette="blue" size="sm" variant="outline">
              <RouterLink to={`/dags/${mostRecent.dag_id}/runs/${mostRecent.dag_run_id}`}>
                <FiArrowRight />
              </RouterLink>
            </IconButton>
          </Tooltip>
        </HStack>
      </Table.Cell>
    </Table.Row>
  );
};
