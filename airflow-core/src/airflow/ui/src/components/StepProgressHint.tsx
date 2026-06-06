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
import { Box, Flex, Text } from "@chakra-ui/react";
import { useTranslation } from "react-i18next";

import { useTaskStoreServiceGetTaskStore } from "openapi/queries";

/**
 * Single reserved task-store key the SDK's ``step()`` overwrites with the latest step
 * lifecycle/progress. Kept in sync with ``STEP_STATE_KEY`` in
 * ``task-sdk/.../execution_time/step.py``.
 */
const STEP_STATE_KEY = "__step__.state";

type StepState = {
  readonly done?: number;
  readonly message?: string;
  readonly name: string;
  readonly status: string;
  readonly total?: number;
};

/** Narrow the untyped task-store ``JsonValue`` to the step-state shape, or undefined if it isn't one. */
const parseStepState = (value: unknown): StepState | undefined => {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const record = value as Record<string, unknown>;

  if (typeof record.name !== "string" || typeof record.status !== "string") {
    return undefined;
  }

  return {
    done: typeof record.done === "number" ? record.done : undefined,
    message: typeof record.message === "string" ? record.message : undefined,
    name: record.name,
    status: record.status,
    total: typeof record.total === "number" ? record.total : undefined,
  };
};

type Props = {
  readonly dagId: string;
  readonly mapIndex?: number;
  readonly runId: string;
  readonly taskId: string;
};

/**
 * Live "which step is this running task on" hint for the grid hover.
 *
 * Reads the single reserved step-state task-store key written by the SDK over the structured
 * worker->server channel, so it never parses logs. The parent only mounts this while the tooltip is
 * open over a running cell, so an unhovered grid cell fetches nothing; while a tooltip is held open
 * it polls every 2s and stops on close (the component unmounts). Bounded to the one cell in focus.
 */
const StepProgressHint = ({ dagId, mapIndex = -1, runId, taskId }: Props) => {
  const { t: translate } = useTranslation("common");
  const { data } = useTaskStoreServiceGetTaskStore(
    { dagId, dagRunId: runId, key: STEP_STATE_KEY, mapIndex, taskId },
    undefined,
    { refetchInterval: 2000 },
  );

  const step = parseStepState(data?.value);

  // Only surface a step that is currently running -- a finished step's outcome is already conveyed
  // by the cell colour.
  if (step?.status !== "running") {
    return undefined;
  }

  const { done, message, name, total } = step;
  const pct =
    total !== undefined && total > 0 && done !== undefined
      ? Math.min(100, Math.round((done / total) * 100))
      : undefined;
  const countPart =
    done === undefined
      ? ""
      : total === undefined
        ? done.toLocaleString()
        : `${done.toLocaleString()}/${total.toLocaleString()}${pct === undefined ? "" : ` (${pct}%)`}`;
  const detail = [countPart, message].filter(Boolean).join(" · ");

  return (
    <Box
      borderTopColor="border.muted"
      borderTopWidth="1px"
      data-testid="step-progress-hint"
      mt={1}
      pt={1}
      w="100%"
    >
      <Text fontWeight="bold">
        {translate("taskInstance.step")}: {name}
      </Text>
      {detail === "" ? undefined : (
        <Flex alignItems="center" gap={2} mt={1}>
          {pct === undefined ? undefined : (
            <Box bg="bg.muted" borderRadius="full" h="6px" overflow="hidden" w="80px">
              <Box bg="fg.info" h="100%" transition="width 0.3s" w={`${pct}%`} />
            </Box>
          )}
          <Text color="fg.info" fontSize="xs">
            {detail}
          </Text>
        </Flex>
      )}
    </Box>
  );
};

export default StepProgressHint;
