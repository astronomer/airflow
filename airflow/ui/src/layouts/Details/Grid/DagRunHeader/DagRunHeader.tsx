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
import { Table, Flex } from "@chakra-ui/react";
import dayjs from "dayjs";
import dayjsDuration from "dayjs/plugin/duration";

import type { GridDAGRunwithTIs } from "openapi/requests/types.gen";

import { Bar } from "./Bar";
import { DurationAxis } from "./DurationAxis";
import { DurationTick } from "./DurationTick";

dayjs.extend(dayjsDuration);

export type RunWithDuration = {
  duration: number;
} & GridDAGRunwithTIs;

type Props = {
  readonly dagRuns: Array<GridDAGRunwithTIs>;
};

export const DagRunHeader = ({ dagRuns }: Props) => {
  const durations: Array<number> = [];
  const runs: Array<RunWithDuration> = dagRuns.map((run) => {
    const duration = dayjs.duration(dayjs(run.end_date).diff(run.start_date)).asSeconds();

    durations.push(duration);

    return {
      ...run,
      duration,
    };
  });

  // calculate dag run bar heights relative to max
  const max = Math.max.apply(undefined, durations);

  return (
    <Table.Row>
      <Table.ColumnHeader align="left" pr={0}>
        <Flex flexDirection="column-reverse" height="100px" position="relative" width="100%">
          {Boolean(runs.length) && (
            <>
              <DurationTick bottom="90px">{Math.floor(max)}s</DurationTick>
              <DurationTick bottom="44px">{Math.floor(max / 2)}s</DurationTick>
              <DurationTick bottom={0}>0s</DurationTick>
            </>
          )}
        </Flex>
      </Table.ColumnHeader>
      <Table.ColumnHeader align="right" verticalAlign="bottom">
        <Flex justifyContent="flex-end" position="relative">
          {runs.map((run: RunWithDuration) => (
            <Bar key={run.dag_run_id} max={max} run={run} />
          ))}
          <DurationAxis bottom="100px" />
          <DurationAxis bottom="50px" />
          <DurationAxis bottom="4px" />
        </Flex>
      </Table.ColumnHeader>
    </Table.Row>
  );
};
