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

import React from 'react';
import { Box, Text } from '@chakra-ui/react';
import { Group } from '@visx/group';

const Node = ({
  node: {
    id, height, width, x, y,
  },
  task,
  children,
}) => (
  <Group top={y} left={x} height={height} width={width}>
    <foreignObject width={width} height={height}>
      <Box borderWidth={1} borderRadius={5} p={2} height="100%" width="100%" borderColor="gray.400">
        <Text fontSize={12}>{id}</Text>
        <Text fontSize={12}>{(!!task && task.taskType) || ''}</Text>
      </Box>
    </foreignObject>
    {children}
  </Group>
);

export default Node;
