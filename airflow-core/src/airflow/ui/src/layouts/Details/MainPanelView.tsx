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
import { Box, Flex, HStack } from "@chakra-ui/react";
import type { ReactNode, RefObject } from "react";

import type { DagRunState, DagRunType } from "openapi/requests/types.gen";
import type { DagView } from "src/constants/dagView";
import type { VersionIndicatorOptions } from "src/constants/showVersionIndicatorOptions";

import { Gantt } from "./Gantt/Gantt";
import { Graph } from "./Graph";
import { Grid } from "./Grid";

// Shared scroll container for the grid + gantt in the combined view.
const SharedScrollBox = ({
  children,
  scrollRef,
}: {
  readonly children: ReactNode;
  readonly scrollRef: RefObject<HTMLDivElement | null>;
}) => (
  <Box
    height="100%"
    minH={0}
    minW={0}
    overflowX="hidden"
    overflowY="auto"
    ref={scrollRef}
    style={{ scrollbarGutter: "stable" }}
    w="100%"
  >
    {children}
  </Box>
);

type Props = {
  readonly dagRunState?: DagRunState;
  readonly dagView: DagView;
  readonly limit: number;
  readonly offset: number;
  readonly onJumpToLatest: () => void;
  readonly runAfterGte?: string;
  readonly runAfterLte?: string;
  readonly runId?: string;
  readonly runIdPattern?: string;
  readonly runType?: DagRunType;
  readonly setOffset: (value: number) => void;
  readonly sharedScrollContainerRef: RefObject<HTMLDivElement | null>;
  readonly showVersionIndicatorMode: VersionIndicatorOptions;
  readonly triggeringUser?: string;
};

/**
 * The body of the details layout's main panel: the graph, the grid, or the
 * grid and gantt side by side.
 */
export const MainPanelView = ({
  dagRunState,
  dagView,
  limit,
  offset,
  onJumpToLatest,
  runAfterGte,
  runAfterLte,
  runId,
  runIdPattern,
  runType,
  setOffset,
  sharedScrollContainerRef,
  showVersionIndicatorMode,
  triggeringUser,
}: Props) => {
  if (dagView === "graph") {
    return <Graph />;
  }

  if (dagView === "gantt" && Boolean(runId)) {
    return (
      <SharedScrollBox scrollRef={sharedScrollContainerRef}>
        <Flex alignItems="flex-start" gap={0} maxW="100%" minW={0} overflow="clip" w="100%">
          <Grid
            dagRunState={dagRunState}
            limit={limit}
            offset={offset}
            onJumpToLatest={onJumpToLatest}
            runAfterGte={runAfterGte}
            runAfterLte={runAfterLte}
            runIdPattern={runIdPattern}
            runType={runType}
            setOffset={setOffset}
            sharedScrollContainerRef={sharedScrollContainerRef}
            showGantt
            showVersionIndicatorMode={showVersionIndicatorMode}
            triggeringUser={triggeringUser}
          />
          <Gantt
            dagRunState={dagRunState}
            limit={limit}
            offset={offset}
            runAfterGte={runAfterGte}
            runAfterLte={runAfterLte}
            runIdPattern={runIdPattern}
            runType={runType}
            sharedScrollContainerRef={sharedScrollContainerRef}
            triggeringUser={triggeringUser}
          />
        </Flex>
      </SharedScrollBox>
    );
  }

  return (
    <HStack alignItems="flex-start" gap={0} height="100%" maxW="100%" minW={0} overflow="hidden" w="100%">
      <Grid
        dagRunState={dagRunState}
        limit={limit}
        offset={offset}
        onJumpToLatest={onJumpToLatest}
        runAfterGte={runAfterGte}
        runAfterLte={runAfterLte}
        runIdPattern={runIdPattern}
        runType={runType}
        setOffset={setOffset}
        showVersionIndicatorMode={showVersionIndicatorMode}
        triggeringUser={triggeringUser}
      />
    </HStack>
  );
};
