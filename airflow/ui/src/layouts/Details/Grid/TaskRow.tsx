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
import { Box, Flex, IconButton, Table } from "@chakra-ui/react";
import { FiChevronUp } from "react-icons/fi";

import type { GridDAGRunwithTIs, NodeResponse } from "openapi/requests/types.gen";
import TaskInstanceTooltip from "src/components/TaskInstanceTooltip";
import { useOpenGroups } from "src/context/openGroups";
import { stateColor } from "src/utils/stateColor";

import { TaskName } from "../Graph/TaskName";

type Props = {
  readonly dagRuns: Array<GridDAGRunwithTIs>;
  readonly depth: number;
  readonly isOpen?: boolean;
  readonly task: NodeResponse;
};

export const TaskRow = ({ dagRuns, depth, isOpen, task }: Props) => {
  const instances = dagRuns.map((run) => ({
    runId: run.dag_run_id,
    taskInstance: run.task_instances.find((ti) => ti.task_id === task.id),
  }));

  const { toggleGroupId } = useOpenGroups();

  return (
    <Table.Row bg={depth % 2 === 0 ? "bg.muted" : "bg"}>
      <Table.Cell align="left" paddingLeft={depth * 3}>
        <Flex alignItems="center">
          <TaskName
            id={task.id}
            isGroup={Boolean(task.children?.length)}
            isMapped={Boolean(task.is_mapped)}
            label={task.label}
            setupTeardownType={task.setup_teardown_type}
          />
          {Boolean(task.children?.length) && (
            <IconButton
              aria-label="Toggle group"
              height="20px"
              onClick={() => toggleGroupId(task.id)}
              variant="ghost"
            >
              <FiChevronUp
                style={{
                  transform: `rotate(${isOpen ? 0 : 180}deg)`,
                  transition: "transform 0.5s",
                }}
              />
            </IconButton>
          )}
        </Flex>
      </Table.Cell>
      <Table.Cell align="right">
        <Flex justifyContent="flex-end">
          {instances.map(({ runId, taskInstance }) => (
            <Box key={runId} pb="2px" position="relative" px="1px" transition="background-color 0.2s">
              <Flex
                alignItems="flex-end"
                cursor="pointer"
                justifyContent="center"
                px="2px"
                width="14px"
                zIndex={1}
              >
                <TaskInstanceTooltip taskInstance={taskInstance}>
                  <Box
                    background={stateColor[taskInstance?.state ?? "null"]}
                    borderRadius={2}
                    height="10px"
                    pb="2px"
                    px="1px"
                    width="10px"
                  />
                </TaskInstanceTooltip>
              </Flex>
            </Box>
          ))}
        </Flex>
      </Table.Cell>
    </Table.Row>
  );
};
