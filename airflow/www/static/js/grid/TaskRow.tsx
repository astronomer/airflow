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

import React, { useCallback } from 'react';
import {
  Box,
  Flex,
  FlexProps,
} from '@chakra-ui/react';

import StatusBox, { boxSize, boxSizePx } from './components/StatusBox';
import TaskName from './components/TaskName';

import useSelection from './utils/useSelection';
import type { DagRun, BasicTask } from './types';

const boxPadding = 3;
const boxPaddingPx = `${boxPadding}px`;
const columnWidth = boxSize + 2 * boxPadding;

interface RowProps extends FlexProps {
  task: BasicTask;
  dagRunIds: DagRun['runId'][];
  openGroupIds?: string[];
  onToggleGroups?: (groupIds: string[]) => void;
  hoveredTaskState?: string | null;
}

const TaskRow = ({
  task,
  dagRunIds,
  openGroupIds = [],
  onToggleGroups = () => {},
  hoveredTaskState,
  ...rest
}: RowProps) => {
  const { selected, onSelect } = useSelection();

  const isOpen = openGroupIds.some((g) => g === task.label);

  // assure the function is the same across renders
  const memoizedToggle = useCallback(
    () => {
      if (task.isGroup && task.label) {
        let newGroupIds = [];
        if (!isOpen) {
          newGroupIds = [...openGroupIds, task.label];
        } else {
          newGroupIds = openGroupIds.filter((g) => g !== task.label);
        }
        onToggleGroups(newGroupIds);
      }
    },
    [task.isGroup, isOpen, task.label, openGroupIds, onToggleGroups],
  );

  return (
    <Flex
      role="group"
      justifyContent="space-between"
      {...rest}
    >
      <TaskName
        onToggle={memoizedToggle}
        isGroup={task.isGroup}
        isMapped={task.isMapped}
        label={task.label || task.id || ''}
        isOpen={isOpen}
        level={task.level}
        isSelected={selected.taskId === task.id}
      />
      <Flex
        p={0}
        width={`${dagRunIds.length * columnWidth}px`}
        borderBottom={0}
        justifyContent="flex-end"
      >
        {dagRunIds.map((runId: string) => {
          // Check if an instance exists for the run, or return an empty box
          const instance = task.instances.find((ti) => ti && ti.runId === runId);
          const isSelected = selected.runId === runId || selected.taskId === instance?.taskId;
          return (
            <Box
              key={`${runId}-${task.id}`}
              className={`js-${runId}`}
              py="4px"
              px={boxPaddingPx}
              data-selected={isSelected}
              transition="background-color 0.2s"
              bg={isSelected ? 'blue.100' : undefined}
              _groupHover={!isSelected ? { bg: 'blue.50' } : undefined}
              borderBottomColor={task.isGroup && isOpen ? 'gray.400' : 'gray.200'}
              borderBottomWidth={1}
            >
              {instance
                ? (
                  <StatusBox
                    instance={instance}
                    group={task}
                    onSelect={onSelect}
                    isActive={hoveredTaskState === undefined || hoveredTaskState === instance.state}
                  />
                )
                : <Box width={boxSizePx} data-testid="blank-task" />}
            </Box>
          );
        })}
      </Flex>
    </Flex>
  );
};

export default TaskRow;
