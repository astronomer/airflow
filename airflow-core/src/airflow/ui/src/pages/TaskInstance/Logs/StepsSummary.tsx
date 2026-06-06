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
import { Box, Flex, Heading, HStack, Icon, Spacer, Text } from "@chakra-ui/react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertTriangle, FiChevronRight } from "react-icons/fi";

import type { StepProgress, StepsTimelineEntry } from "src/queries/useLogs";

import {
  STEP_STATUS_VISUALS,
  formatStepDuration,
  outputChipLabel,
  resolveStepVisualState,
} from "./stepVisuals";

type Props = {
  readonly onStepClick?: (groupId: number) => void;
  // True when the task instance itself has reached a terminal state -- an open step is then
  // "interrupted" (it never finished) rather than "running".
  readonly taskTerminal?: boolean;
  readonly timeline: Array<StepsTimelineEntry>;
};

// Live progress on a running step. With a total: "7/10 (70%)" plus a bar. A message (e.g. the file
// being copied) is appended: "3/10 (30%) · copying foo.csv", or shown alone when indeterminate.
const StepProgressIndicator = ({ progress }: { readonly progress: StepProgress }) => {
  const { done, message, total } = progress;
  const pct = total !== undefined && total > 0 ? Math.min(100, Math.round((done / total) * 100)) : undefined;
  const countPart =
    total === undefined
      ? message === undefined
        ? done.toLocaleString()
        : ""
      : `${done.toLocaleString()}/${total.toLocaleString()}${pct === undefined ? "" : ` (${pct}%)`}`;
  const label = [countPart, message].filter(Boolean).join(" · ");

  return (
    <Flex alignItems="center" data-testid="steps-summary-progress" gap={2}>
      {pct === undefined ? undefined : (
        <Box bg="bg.muted" borderRadius="full" h="6px" overflow="hidden" w="80px">
          <Box bg="fg.info" h="100%" transition="width 0.3s" w={`${pct}%`} />
        </Box>
      )}
      <Text color="fg.info" fontSize="sm">
        {label}
      </Text>
    </Flex>
  );
};

const OutputChip = ({ outputKey, value }: { readonly outputKey: string; readonly value: unknown }) => {
  const { full, label } = outputChipLabel(outputKey, value);

  return (
    <Box
      as="span"
      bg="bg.muted"
      borderRadius="sm"
      color="fg.muted"
      data-testid={`steps-summary-output-${outputKey}`}
      fontSize="xs"
      px={1.5}
      title={full}
    >
      {label}
    </Box>
  );
};

/**
 * AIP-103 Task Steps: a compact, CI-pipeline-style summary of the task's steps, rendered above the
 * raw log. Each step shows its status, metadata chips and duration; time spent between steps in code
 * that was not wrapped in a step() surfaces as an "untracked" row (it is not checkpointed, so it
 * re-runs on every retry).
 */
export const StepsSummary = ({ onStepClick, taskTerminal = false, timeline }: Props) => {
  const { t: translate } = useTranslation("dag");
  const [open, setOpen] = useState(true);

  if (timeline.length === 0) {
    return undefined;
  }

  const stepCount = timeline.filter((entry) => entry.kind === "step").length;

  return (
    <Box borderRadius="md" borderWidth="1px" data-testid="steps-summary" mb={2}>
      <HStack cursor="pointer" onClick={() => setOpen((value) => !value)} px={3} py={2} roundedTop="md">
        <Icon
          as={FiChevronRight}
          transform={open ? "rotate(90deg)" : "rotate(0deg)"}
          transition="transform 0.15s"
        />
        <Heading size="sm">{translate("logs.steps.title")}</Heading>
        <Spacer />
        <Text color="fg.muted" fontSize="xs">
          {translate("logs.steps.stepCount", { count: stepCount })}
        </Text>
      </HStack>
      {open ? (
        <Box overflowX="auto">
          {timeline.map((entry, index) => {
            if (entry.kind === "gap") {
              return (
                <Flex
                  alignItems="center"
                  bg="bg.warning"
                  borderTopWidth="1px"
                  // eslint-disable-next-line react/no-array-index-key -- timeline order is stable per render
                  key={`gap-${index}`}
                  px={3}
                  py={1.5}
                  title={translate("logs.steps.untrackedTooltip")}
                >
                  <Icon as={FiAlertTriangle} color="fg.warning" me={2} />
                  <Text color="fg.warning" fontSize="sm">
                    {translate("logs.steps.untracked")}
                  </Text>
                  <Spacer />
                  <Text color="fg.warning" fontSize="sm">
                    {formatStepDuration(entry.durationMs)}
                  </Text>
                </Flex>
              );
            }

            const state = resolveStepVisualState(entry.status, taskTerminal);
            const visual = STEP_STATUS_VISUALS[state];
            // Progress only while the step is genuinely running (not interrupted/finished).
            const showProgress = state === "running" && entry.progress !== undefined;

            return (
              <Flex
                _hover={onStepClick ? { bg: "bg.muted" } : undefined}
                alignItems="center"
                borderTopWidth="1px"
                cursor={onStepClick ? "pointer" : undefined}
                data-testid={`steps-summary-row-${entry.name}`}
                // eslint-disable-next-line react/no-array-index-key -- timeline order is stable per render
                key={`step-${entry.name}-${index}`}
                onClick={onStepClick ? () => onStepClick(entry.groupId) : undefined}
                px={3}
                py={1.5}
                title={onStepClick ? translate("logs.steps.viewLogs") : undefined}
              >
                <Icon
                  as={visual.icon}
                  color={visual.color}
                  data-testid={`steps-summary-status-${state}`}
                  me={2}
                />
                <Text color={state === "interrupted" ? "fg.warning" : undefined} fontSize="sm">
                  {entry.name}
                </Text>
                {entry.outputs
                  ? Object.entries(entry.outputs).map(([outputKey, value]) => (
                      <Box key={outputKey} ms={2}>
                        <OutputChip outputKey={outputKey} value={value} />
                      </Box>
                    ))
                  : undefined}
                <Spacer />
                {showProgress && entry.progress ? (
                  <StepProgressIndicator progress={entry.progress} />
                ) : state === "interrupted" ? (
                  <Text color="fg.warning" fontSize="sm">
                    {translate("logs.steps.interrupted")}
                  </Text>
                ) : entry.durationMs === undefined ? undefined : (
                  <Text color="fg.muted" fontSize="sm">
                    {formatStepDuration(entry.durationMs)}
                  </Text>
                )}
              </Flex>
            );
          })}
        </Box>
      ) : undefined}
    </Box>
  );
};
