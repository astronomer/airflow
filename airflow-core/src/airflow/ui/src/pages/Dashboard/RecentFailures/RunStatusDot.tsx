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
import { Box, Link } from "@chakra-ui/react";
import { Link as RouterLink } from "react-router-dom";

import type { DAGRunLightResponse, DagRunState } from "openapi/requests/types.gen";
import { Tooltip } from "src/components/ui";
import { useTimezone } from "src/context/timezone";
import { DEFAULT_DATETIME_FORMAT_WITH_TZ, formatDate, getRelativeTime } from "src/utils/datetimeUtils";

const DOT_SIZE = "10px";

type Props = {
  readonly focusedRunId: string;
  // DAG's most recent runs overall, newest first.
  readonly runs: Array<DAGRunLightResponse>;
};

type Status = {
  colorState: DagRunState;
  link?: string;
  tooltip: string;
};

const describe = (
  runs: Array<DAGRunLightResponse>,
  focusedRunId: string,
  timezone: string,
): Status | undefined => {
  const [latestRun] = runs;

  if (latestRun === undefined) {
    return undefined;
  }

  const hasLaterRun = latestRun.run_id !== focusedRunId;

  if (!hasLaterRun) {
    return {
      colorState: "failed",
      tooltip: "Still failed — no later dag runs",
    };
  }

  const laterLink = `/dags/${latestRun.dag_id}/runs/${latestRun.run_id}`;

  if (latestRun.state === "running" || latestRun.state === "queued") {
    const started = latestRun.start_date ?? latestRun.run_after;
    const verb = latestRun.state === "running" ? "is running" : "is queued";

    return {
      colorState: latestRun.state,
      link: laterLink,
      tooltip: `Another dag run ${verb} · started ${getRelativeTime(started)}`,
    };
  }

  if (latestRun.state === "success") {
    const when = latestRun.end_date ?? latestRun.run_after;

    return {
      colorState: "success",
      link: laterLink,
      tooltip: `Recovered — a later dag run succeeded ${getRelativeTime(when)} (${formatDate(
        when,
        timezone,
        DEFAULT_DATETIME_FORMAT_WITH_TZ,
      )})`,
    };
  }

  return {
    colorState: "failed",
    link: laterLink,
    tooltip: `Still failed — latest dag run state: ${latestRun.state}`,
  };
};

export const RunStatusDot = ({ focusedRunId, runs }: Props) => {
  const { selectedTimezone } = useTimezone();
  const status = describe(runs, focusedRunId, selectedTimezone);

  if (status === undefined) {
    return undefined;
  }

  const dot = (
    <Box
      aria-label={status.tooltip}
      bg={`${status.colorState}.solid`}
      borderRadius="full"
      boxSize={DOT_SIZE}
    />
  );

  if (status.link === undefined) {
    return <Tooltip content={status.tooltip}>{dot}</Tooltip>;
  }

  return (
    <Tooltip content={status.tooltip}>
      <Link
        _hover={{ transform: "scale(1.3)" }}
        aria-label={status.tooltip}
        asChild
        transition="transform 0.1s ease-out"
      >
        <RouterLink to={status.link}>{dot}</RouterLink>
      </Link>
    </Tooltip>
  );
};
