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

import React, { useState, useEffect } from 'react';
import {
  Box,
  Flex,
  IconButton,
} from '@chakra-ui/react';
import useVirtual from 'react-cool-virtual';

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

const flattenTasks = (group: Task, openGroupIds: string[], level: number = 0) => {
  let list: BasicTask[] = [];
  if (group.id) {
    const { children, ...groupProps } = group;
    list.push({
      ...groupProps,
      isGroup: !!group.children,
      level,
    });
  }
  // Add children to the list if the group is expanded
  if (group.children && (!group.label || openGroupIds.includes(group.label))) {
    group.children.forEach((c) => {
      list = [...list, ...flattenTasks(c, openGroupIds, level + 1)];
    });
  }
  return list;
};

const Grid = ({ isPanelOpen = false, onPanelToggle, hoveredTaskState }: Props) => {
  const { data: { groups, dagRuns } } = useGridData();
  const dagRunIds = dagRuns.map((dr) => dr.runId);

  const openGroupsKey = `${dagId}/open-groups`;
  const storedGroups = JSON.parse(localStorage.getItem(openGroupsKey) || '[]');
  const [openGroupIds, setOpenGroupIds] = useState(storedGroups);
  const [rows, setRows] = useState(flattenTasks(groups, openGroupIds));

  const { outerRef, innerRef, items } = useVirtual<HTMLDivElement>({
    itemCount: rows.length,
    itemSize: 18,
  });

  const onToggleGroups = (groupIds: string[]) => {
    localStorage.setItem(openGroupsKey, JSON.stringify(groupIds));
    setOpenGroupIds(groupIds);
    if (!groupIds.length) {
      const filteredRows = rows.filter((row) => row.level === 1);
      setRows(filteredRows);
    } else {
      const filteredRows = flattenTasks(groups, groupIds);
      setRows(filteredRows);
    }
  };

  useEffect(() => {
    const scrollOnResize = new ResizeObserver(() => {
      const runsContainer = outerRef.current;
      // Set scroll to top right if it is scrollable
      if (
        innerRef?.current
        && runsContainer
        && runsContainer.scrollWidth > runsContainer.clientWidth
      ) {
        runsContainer.scrollBy(innerRef.current.offsetWidth, 0);
      }
    });

    if (innerRef && innerRef.current) {
      const table = innerRef.current;

      scrollOnResize.observe(table);
      return () => {
        scrollOnResize.unobserve(table);
      };
    }
    return () => {};
  }, [innerRef, isPanelOpen, outerRef]);

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
        ref={outerRef}
        height="600px"
        position="relative"
      >
        <DagRuns />
        <Box ref={innerRef}>
          {items.map(({ index, size }) => {
            const task = rows[index];
            if (!task || !rows[index]) return null;
            return (
              <TaskRow
                key={rows[index].id}
                task={rows[index]}
                dagRunIds={dagRunIds}
                hoveredTaskState={hoveredTaskState}
                height={`${size}px`}
                onToggleGroups={onToggleGroups}
                openGroupIds={openGroupIds}
              />
            );
          })}
        </Box>
      </Box>
    </Box>
  );
};

export default Grid;
