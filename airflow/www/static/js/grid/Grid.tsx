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

/* global localStorage, ResizeObserver */

import React, { useState, MutableRefObject } from 'react';
import {
  Box,
  Flex,
  IconButton,
} from '@chakra-ui/react';
import useVirtual from "react-cool-virtual";

import { MdReadMore } from 'react-icons/md';
import { useGridData } from './api';
import TaskRow from './TaskRow';
import ResetRoot from './ResetRoot';
import DagRuns from './dagRuns';
import ToggleGroups from './ToggleGroups';
import { getMetaValue } from '../utils';
import AutoRefresh from './AutoRefresh';
import type { Task, BasicTask } from './types';

const dagId = getMetaValue('dag_id');

interface Props {
  isPanelOpen?: boolean;
  onPanelToggle: () => void;
  hoveredTaskState?: string | null;
}

const flattenTasks = (group: Task, level: number = 0) => {
  let list: BasicTask[] = [];
  if (group.id) {
    const { children, ...groupProps } = group;
    list.push({
      ...groupProps,
      isGroup: !!group.children,
      level,
    });
  }
  if (group.children) {
    group.children.forEach((c) => {
      list = [...list, ...flattenTasks(c, level + 1)];
    })
  }
  return list;
}

const Grid = ({ isPanelOpen = false, onPanelToggle, hoveredTaskState }: Props) => {
  // const scrollRef = useRef<HTMLDivElement>(null);
  // const tableRef = useRef<HTMLTableSectionElement>(null);

  const { data: { groups, dagRuns } } = useGridData();
  const dagRunIds = dagRuns.map((dr) => dr.runId);

  const rows = flattenTasks(groups);

  const { outerRef, innerRef, items } = useVirtual({
    itemCount: rows.length,
    itemSize: 18,
  });

  const openGroupsKey = `${dagId}/open-groups`;
  const storedGroups = JSON.parse(localStorage.getItem(openGroupsKey) || '[]');
  const [openGroupIds, setOpenGroupIds] = useState(storedGroups);

  const onToggleGroups = (groupIds: string[]) => {
    localStorage.setItem(openGroupsKey, JSON.stringify(groupIds));
    setOpenGroupIds(groupIds);
  };

  // useEffect(() => {
  //   const scrollOnResize = new ResizeObserver(() => {
  //     const runsContainer = scrollRef.current;
  //     // Set scroll to top right if it is scrollable
  //     if (
  //       tableRef?.current
  //       && runsContainer
  //       && runsContainer.scrollWidth > runsContainer.clientWidth
  //     ) {
  //       runsContainer.scrollBy(tableRef.current.offsetWidth, 0);
  //     }
  //   });

  //   if (tableRef && tableRef.current) {
  //     const table = tableRef.current;

  //     scrollOnResize.observe(table);
  //     return () => {
  //       scrollOnResize.unobserve(table);
  //     };
  //   }
  //   return () => {};
  // }, [tableRef, isPanelOpen]);

  return (
    <Box
      minWidth={isPanelOpen ? '350px' : undefined}
      flexGrow={1}
      m={3}
      mt={0}
    >
      <Flex
        alignItems="center"
        justifyContent="space-between"
        mb={2}
        p={1}
        backgroundColor="white"
      >
        <Flex alignItems="center">
          <AutoRefresh />
          <ToggleGroups
            groups={groups}
            openGroupIds={openGroupIds}
            onToggleGroups={onToggleGroups}
          />
          <ResetRoot />
        </Flex>
        <IconButton
          fontSize="2xl"
          onClick={onPanelToggle}
          title={`${isPanelOpen ? 'Hide ' : 'Show '} Details Panel`}
          aria-label={isPanelOpen ? 'Show Details' : 'Hide Details'}
          icon={<MdReadMore />}
          transform={!isPanelOpen ? 'rotateZ(180deg)' : undefined}
          transitionProperty="none"
        />
      </Flex>
      <Box
        overflow="auto"
        ref={outerRef as MutableRefObject<HTMLDivElement>}
        height="600px"
        position="relative"
      >
        <DagRuns />
        <Box ref={innerRef as MutableRefObject<HTMLDivElement>}>
          {items.map(({ index, size }) => (
            <TaskRow
              key={rows[index].id}
              task={rows[index]}
              dagRunIds={dagRunIds}
              hoveredTaskState={hoveredTaskState}
              height={`${size}px`}
            />
          ))}
        </Box>
      </Box>
    </Box>
  );
};

export default Grid;
