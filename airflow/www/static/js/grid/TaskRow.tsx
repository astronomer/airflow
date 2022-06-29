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
  useTheme,
  TableRowProps,
} from '@chakra-ui/react';

import StatusBox, { boxSize, boxSizePx } from './components/StatusBox';
import TaskName from './components/TaskName';

import useSelection, { SelectionProps } from './utils/useSelection';
import type { Task, DagRun, BasicTask } from './types';

const boxPadding = 3;
const boxPaddingPx = `${boxPadding}px`;
const columnWidth = boxSize + 2 * boxPadding;

interface RowProps extends TableRowProps {
  task: BasicTask;
  dagRunIds: DagRun['runId'][];
  // openParentCount?: number;
  openGroupIds?: string[];
  onToggleGroups?: (groupIds: string[]) => void;
  hoveredTaskState?: string | null;
}

interface TaskInstancesProps {
  task: Task;
  dagRunIds: string[];
  selectedRunId?: string | null;
  onSelect: (selection: SelectionProps) => void;
  hoveredTaskState?: string | null;
}

const TaskInstances = ({
  task, dagRunIds, selectedRunId, onSelect, hoveredTaskState,
}: TaskInstancesProps) => (
  <Flex justifyContent="flex-end">
    {dagRunIds.map((runId: string) => {
      // Check if an instance exists for the run, or return an empty box
      const instance = task.instances.find((ti) => ti && ti.runId === runId);
      const isSelected = selectedRunId === runId;
      return (
        <Box
          py="4px"
          px={boxPaddingPx}
          className={`js-${runId}`}
          data-selected={isSelected}
          transition="background-color 0.2s"
          key={`${runId}-${task.id}`}
          bg={isSelected ? 'blue.100' : undefined}
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
);

const TaskRow = ({
  task,
  dagRunIds,
  // openParentCount = 0,
  openGroupIds = [],
  onToggleGroups = () => {},
  hoveredTaskState,
  ...rest
}: RowProps) => {
  const { colors } = useTheme();
  const { selected, onSelect } = useSelection();

  const hoverBlue = `${colors.blue[100]}50`;
  const isSelected = selected.taskId === task.id;

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

  // check if the group's parents are all open, if not, return null
  // if (task.level !== openParentCount) return null;

  return (
    <Flex
      bg={isSelected ? 'blue.100' : 'inherit'}
      borderBottomWidth={1}
      borderBottomColor={task.isGroup && isOpen ? 'gray.400' : 'gray.200'}
      role="group"
      _hover={!isSelected ? { bg: hoverBlue } : undefined}
      transition="background-color 0.2s"
      justifyContent="space-between"
      {...rest}
    >
      {/* <Td
        bg={isSelected ? 'blue.100' : 'white'}
        _groupHover={!isSelected ? { bg: 'blue.50' } : undefined}
        p={0}
        transition="background-color 0.2s"
        lineHeight="18px"
        position="sticky"
        left={0}
        borderBottom={0}
        width="100%"
        zIndex={1}
      > */}
      <TaskName
        onToggle={memoizedToggle}
        isGroup={task.isGroup}
        isMapped={task.isMapped}
        label={task.label || task.id || ''}
        isOpen={isOpen}
        level={task.level}
      />
      {/* </Td> */}
      <Flex
        p={0}
        align="right"
        width={`${dagRunIds.length * columnWidth}px`}
        borderBottom={0}
      >
        <TaskInstances
          dagRunIds={dagRunIds}
          task={task}
          selectedRunId={selected.runId}
          onSelect={onSelect}
          hoveredTaskState={hoveredTaskState}
        />
      </Flex>
    </Flex>
  );
};

export default TaskRow;
