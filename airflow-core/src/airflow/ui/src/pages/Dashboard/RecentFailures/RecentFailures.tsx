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
import { useMemo } from "react";
import { FiAlertCircle, FiCheckCircle } from "react-icons/fi";
import { Link as RouterLink } from "react-router-dom";

import {
  useDagRunServiceGetDagRuns,
  useDagServiceGetDagsUi,
  useTaskInstanceServiceGetTaskInstances,
} from "openapi/queries";
import type { DAGRunLightResponse, DAGRunResponse, TaskInstanceResponse } from "openapi/requests/types.gen";
import { useAutoRefresh } from "src/utils";

import { FailureRow } from "./FailureRow";

// Cap on total failed TIs we fetch across the window. 10 runs × ~5 failed
// tasks per run is a reasonable ceiling. Runs with more than this will show
// their first few tasks inline; users click through to the run detail for
// the full list.
const TI_FETCH_CAP = 50;
// Cap on failed runs pulled to build the grouped-by-DAG table. The table
// shows `limit` (default 10) *groups* — we fetch more raw runs so grouping
// has enough data to surface distinct DAGs even when one DAG dominates with
// repeat failures. 30 covers three repeats per DAG for 10 DAGs; deployments
// with more than this hit a ceiling.
const RUN_FETCH_CAP = 30;

const runKey = (dagId: string, dagRunId: string) => `${dagId}:${dagRunId}`;

type Props = {
  readonly compact?: boolean;
  readonly endDate: string;
  readonly limit?: number;
  readonly startDate: string;
  readonly windowLabel: string;
};

export const RecentFailures = ({ compact = false, endDate, limit = 10, startDate, windowLabel }: Props) => {
  const refetchInterval = useAutoRefresh({ checkPendingRuns: true });

  const { data: runsData, isLoading: runsLoading } = useDagRunServiceGetDagRuns(
    {
      dagId: "~",
      limit: RUN_FETCH_CAP,
      orderBy: ["-end_date", "-run_after"],
      runAfterGte: startDate,
      runAfterLte: endDate,
      state: ["failed"],
    },
    undefined,
    { refetchInterval },
  );

  const { data: tisData } = useTaskInstanceServiceGetTaskInstances(
    {
      dagId: "~",
      dagRunId: "~",
      limit: TI_FETCH_CAP,
      orderBy: ["start_date"],
      runAfterGte: startDate,
      runAfterLte: endDate,
      state: ["failed"],
    },
    undefined,
    { refetchInterval },
  );

  const hasNoFailures = runsData?.total_entries === 0;

  // Count of successful runs in the window — used only in the empty state
  // to distinguish "All clear" (runs succeeded) from "No activity" (nothing
  // ran). Uses limit: 1 so we only pay for total_entries. Gated on empty
  // state so we don't poll it when failures exist.
  const { data: successData } = useDagRunServiceGetDagRuns(
    {
      dagId: "~",
      limit: 1,
      runAfterGte: startDate,
      runAfterLte: endDate,
      state: ["success"],
    },
    undefined,
    { enabled: hasNoFailures, refetchInterval },
  );

  const successCount = successData?.total_entries ?? 0;

  const uniqueDagIds = useMemo(
    () => [...new Set((runsData?.dag_runs ?? []).map((run) => run.dag_id))],
    [runsData],
  );

  const { data: dagsData } = useDagServiceGetDagsUi(
    {
      // Only the single most recent run per DAG is read (RunStatusDot uses
      // runs[0]); owners come from the same payload.
      dagIds: uniqueDagIds,
      dagRunsLimit: 1,
      limit: Math.max(uniqueDagIds.length, 1),
    },
    undefined,
    { enabled: uniqueDagIds.length > 0, refetchInterval },
  );

  const ownersByDagId = useMemo(() => {
    const map = new Map<string, Array<string>>();

    for (const dag of dagsData?.dags ?? []) {
      map.set(dag.dag_id, dag.owners);
    }

    return map;
  }, [dagsData]);

  const recentRunsByDagId = useMemo(() => {
    const map = new Map<string, Array<DAGRunLightResponse>>();

    for (const dag of dagsData?.dags ?? []) {
      map.set(dag.dag_id, dag.latest_dag_runs);
    }

    return map;
  }, [dagsData]);

  const tisByRun = useMemo(() => {
    const map = new Map<string, Array<TaskInstanceResponse>>();

    for (const ti of tisData?.task_instances ?? []) {
      const key = runKey(ti.dag_id, ti.dag_run_id);
      const existing = map.get(key);

      if (existing === undefined) {
        map.set(key, [ti]);
      } else {
        existing.push(ti);
      }
    }

    return map;
  }, [tisData]);

  // Sort client-side by most-recent failure first. The API request already
  // asks for -end_date, but we enforce the order here too so a subtle API
  // ordering change can't silently flip the triage table.
  const allRuns = useMemo(() => {
    const unsorted = runsData?.dag_runs ?? [];
    const copy = [...unsorted];

    copy.sort((first, second) => {
      const firstEnd = first.end_date ?? first.run_after;
      const secondEnd = second.end_date ?? second.run_after;

      return secondEnd.localeCompare(firstEnd);
    });

    return copy;
  }, [runsData]);

  // Group runs by dag_id so repeated failures collapse into one row with a
  // ×N count, surfacing the "this DAG keeps failing" pattern that per-run
  // rows bury in visual duplication.
  const groupedRuns = useMemo(() => {
    const groups = new Map<string, Array<DAGRunResponse>>();

    for (const run of allRuns) {
      const existing = groups.get(run.dag_id);

      if (existing === undefined) {
        groups.set(run.dag_id, [run]);
      } else {
        existing.push(run);
      }
    }

    // Iteration order of Map preserves insertion order; first-seen run for a
    // dag_id is the most recent (allRuns is sorted desc). So groups are
    // already ordered by most-recent-failure per DAG.
    return [...groups.values()];
  }, [allRuns]);
  const visibleGroups = useMemo(() => groupedRuns.slice(0, limit), [groupedRuns, limit]);
  const totalFailures = runsData?.total_entries ?? allRuns.length;

  if (runsLoading && allRuns.length === 0) {
    return (
      <Box>
        <Flex align="center" color="fg.muted" my={2}>
          <FiAlertCircle />
          <Heading ml={1} size="xs">
            Failures · {windowLabel}
          </Heading>
        </Flex>
        <Skeleton height={compact ? "80px" : "140px"} />
      </Box>
    );
  }

  if (allRuns.length === 0) {
    const hasActivity = successCount > 0;

    return (
      <Box>
        <Flex align="center" justify="space-between" my={2}>
          <Flex align="center" color={hasActivity ? "green.fg" : "fg.muted"}>
            <FiCheckCircle />
            <Heading ml={1} size="xs">
              {hasActivity ? "All clear" : "No activity"} · {windowLabel}
            </Heading>
          </Flex>
          <Link asChild color="fg.info" fontSize="sm">
            <RouterLink to="/dag_runs">View all runs →</RouterLink>
          </Link>
        </Flex>
        <Box
          borderColor={hasActivity ? "green.solid" : "border"}
          borderLeftWidth={hasActivity ? 3 : 1}
          borderRadius="md"
          borderWidth={1}
          px={4}
          py={3}
        >
          <Text color="fg.muted" fontSize="sm">
            {hasActivity ? (
              <>
                No failures ·{" "}
                <Text as="span" color="fg" fontWeight="semibold">
                  {successCount.toLocaleString()}
                </Text>{" "}
                Dag run{successCount === 1 ? "" : "s"} completed successfully in this window.
              </>
            ) : (
              <>No Dag runs have executed in this window yet.</>
            )}
          </Text>
        </Box>
      </Box>
    );
  }

  return (
    <Box>
      <Flex align="center" justify="space-between" my={2}>
        <Flex align="center" gap={2}>
          <Box color="red.fg">
            <FiAlertCircle />
          </Box>
          <Heading size="md">
            {totalFailures.toLocaleString()} failure{totalFailures === 1 ? "" : "s"}
          </Heading>
        </Flex>
        <Link asChild color="fg.info" fontSize="sm">
          <RouterLink to="/dag_runs?state=failed">See all failed runs →</RouterLink>
        </Link>
      </Flex>
      <Box bg="bg.subtle" borderColor="border.emphasized" borderRadius="md" borderWidth={1} overflow="hidden">
        <Table.Root
          size={compact ? "sm" : "md"}
          style={{ tableLayout: "fixed" }}
          variant="outline"
          width="100%"
        >
          <Table.Header bg="bg.muted">
            <Table.Row>
              <Table.ColumnHeader width="40px" />
              <Table.ColumnHeader>Dag · Task · Error</Table.ColumnHeader>
              <Table.ColumnHeader width="180px">Last failed at</Table.ColumnHeader>
              <Table.ColumnHeader width="120px">Duration</Table.ColumnHeader>
              <Table.ColumnHeader textAlign="end" width="140px">
                Actions
              </Table.ColumnHeader>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {visibleGroups.map((dagRuns) => {
              const [mostRecent] = dagRuns;

              if (mostRecent === undefined) {
                return undefined;
              }

              return (
                <FailureRow
                  dagRuns={dagRuns}
                  endDate={endDate}
                  failedTis={tisByRun.get(runKey(mostRecent.dag_id, mostRecent.dag_run_id)) ?? []}
                  key={mostRecent.dag_id}
                  owners={ownersByDagId.get(mostRecent.dag_id) ?? []}
                  recentRuns={recentRunsByDagId.get(mostRecent.dag_id) ?? []}
                  startDate={startDate}
                />
              );
            })}
          </Table.Body>
        </Table.Root>
      </Box>
    </Box>
  );
};
