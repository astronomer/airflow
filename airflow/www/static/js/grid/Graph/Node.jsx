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

/* global stateColors */

import React from 'react';
import { Box, Text } from '@chakra-ui/react';
import { Group } from '@visx/group';

import useSelection from '../utils/useSelection';
import { useGridData } from '../api';
import getTask from '../utils/getTask';

const Node = ({
  node: {
    id, height, width, x, y,
  },
  task,
  children,
}) => {
  const { selected: { taskId, runId }, onSelect } = useSelection();
  const { data: { groups } } = useGridData();

  const isSelected = taskId === id;

  const group = getTask({ taskId: id, runId, task: groups });
  const instance = group && group.instances.find((ti) => ti.runId === runId);

  return (
    <Group top={y} left={x} height={height} width={width}>
      <foreignObject width={width} height={height}>
        <Box
          borderWidth={isSelected ? 4 : 2}
          borderRadius={5}
          p={1}
          pl={2}
          pt={0}
          height="100%"
          width="100%"
          borderColor={(instance && (stateColors[instance.state] || 'gray.400')) || 'gray.400'}
          fontWeight={isSelected ? 'bold' : 'normal'}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onSelect({ runId, taskId: id });
          }}
          cursor="pointer"
        >
          <Text fontSize={12}>{id}</Text>
          <Text fontSize={12}>{(!!task && task.taskType) || ''}</Text>
        </Box>
      </foreignObject>
      {children}
    </Group>
  );
};

export default Node;
