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
import { Flex, Box } from "@chakra-ui/react";

import DagRunInfo from "src/components/DagRunInfo";
// import { isEqual } from "lodash";
// import React from "react";
import { RunTypeIcon } from "src/components/RunTypeIcon";
import { Tooltip } from "src/components/ui";
// import Time from "src/components/Time";
// import { useContainerRef } from "src/context/containerRef";
// import type { SelectionProps } from "src/dag/useSelection";
// import { hoverDelay, getStatusBackgroundColor, getDagRunLabel } from "src/utils";
import { stateColor } from "src/utils/stateColor";

import type { RunWithDuration } from "./DagRunHeader";

const BAR_HEIGHT = 100;

type Props = {
  // readonly index: number;
  // readonly isSelected: boolean;
  readonly max: number;
  // readonly onSelect: (props: SelectionProps) => void;
  readonly run: RunWithDuration;
  // readonly totalRuns: number;
};

export const Bar = ({ max, run }: Props) => {
  // const { colors } = useTheme();
  // const hoverBlue = `${colors.blue[100]}50`;

  // // Fetch the corresponding column element and set its background color when hovering
  // const onMouseEnter = () => {
  //   if (!isSelected) {
  //     const els = [...containerRef?.current?.getElementsByClassName(
  //         `js-${runId}`
  //       ) as HTMLCollectionOf<HTMLElement>];

  //     els.forEach((e) => {
  //       e.style.backgroundColor = hoverBlue;
  //     });
  //   }
  // };
  // const onMouseLeave = () => {
  //   const els = [...containerRef?.current?.getElementsByClassName(
  //       `js-${runId}`
  //     ) as HTMLCollectionOf<HTMLElement>];

  //   els.forEach((e) => {
  //     e.style.backgroundColor = "";
  //   });
  // };

  // show the tick on the 4th DagRun and then every 10th tick afterwards
  // const inverseIndex = totalRuns - index;
  // const shouldShowTick = inverseIndex === 4 || (inverseIndex > 4 && (inverseIndex - 4) % 10 === 0);

  const color = stateColor[run.state];

  return (
    <Box
      // bg={isSelected ? "blue.100" : undefined}
      // className={`js-${runId}`}
      // data-selected={isSelected}
      pb="2px"
      position="relative"
      px="1px"
      transition="background-color 0.2s"
    >
      <Flex
        alignItems="flex-end"
        cursor="pointer"
        height={BAR_HEIGHT}
        justifyContent="center"
        // onClick={() => onSelect({ runId })}
        // onMouseEnter={onMouseEnter}
        // onMouseLeave={onMouseLeave}
        px="2px"
        width="14px"
        zIndex={1}
      >
        <Tooltip
          content={
            <DagRunInfo
              dataIntervalEnd={run.data_interval_end}
              dataIntervalStart={run.data_interval_start}
              endDate={run.end_date}
              startDate={run.start_date}
              state={run.state}
            />
          }
        >
          <Flex
            alignItems="center"
            background={color}
            borderRadius={2}
            cursor="pointer"
            data-testid="run"
            direction="column"
            height={`${(run.duration / max) * BAR_HEIGHT}px`}
            justifyContent="flex-end"
            minHeight="14px"
            pb="2px"
            px="1px"
            width="10px"
            zIndex={1}
          >
            {/* Scheduled is the default, hence no icon */}
            {run.run_type !== "scheduled" && <RunTypeIcon runType={run.run_type} size="8px" />}
          </Flex>
        </Tooltip>
      </Flex>
      {/* {shouldShowTick ? <VStack
          left="8px"
          position="absolute"
          spacing={0}
          top="0"
          width={0}
          zIndex={0}
        >
          <Text
            color="gray.400"
            fontSize="sm"
            mt="-23px !important"
            transform="rotate(-30deg) translateX(28px)"
            whiteSpace="nowrap"
          >
            <Time
              dateTime={getDagRunLabel({ dagRun, ordering })}
              format="MMM DD, HH:mm"
            />
          </Text>
          <Box borderLeftWidth={1} height="100px" opacity={0.7} zIndex={0} />
        </VStack> : null} */}
    </Box>
  );
};
