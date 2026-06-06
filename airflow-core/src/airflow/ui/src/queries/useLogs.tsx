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
import type { UseQueryOptions } from "@tanstack/react-query";
import dayjs from "dayjs";
import type { TFunction } from "i18next";
import type { JSX } from "react";
import { useTranslation } from "react-i18next";
import innerText from "react-innertext";

import { useTaskInstanceServiceGetLog } from "openapi/queries";
import type { TaskInstanceResponse, TaskInstancesLogResponse } from "openapi/requests/types.gen";
import {
  extractTIContext,
  renderStructuredLog,
  renderTIContextPreamble,
} from "src/components/renderStructuredLog";
import { isStatePending, useAutoRefresh } from "src/utils";
import { getTaskInstanceLink } from "src/utils/links";
import { parseStreamingLogContent } from "src/utils/logs";

export type StepStatus = "cached" | "failed" | "success";

type LogDatum = TaskInstancesLogResponse["content"][number];

// Live progress for a running step (from s.progress()); display-only, read from log markers.
export type StepProgress = { done: number; message?: string; total?: number };

export type ParsedLogEntry = {
  element: JSX.Element | string | undefined;
  group?: {
    id: number;
    // AIP-103 Task Steps: a group header whose name starts with STEP_HEADER_PREFIX is a step.
    // stepStatus/stepDurationMs/stepOutputs come from the closing ::endgroup:: marker's fields;
    // stepStartTs/stepEndTs are the marker timestamps, used to detect untracked gaps between steps;
    // stepProgress is the latest ::step-progress:: marker seen while the step is running.
    isStep?: boolean;
    level: number;
    parentId?: number;
    stepDurationMs?: number;
    stepEndTs?: string;
    stepName?: string;
    stepOutputs?: Record<string, unknown>;
    stepProgress?: StepProgress;
    stepStartTs?: string;
    stepStatus?: StepStatus;
    type: "header" | "line";
  };
};

// One entry in the steps summary timeline: either a step, or an "untracked" gap between two steps
// (time spent in code that wasn't wrapped in a step()).
export type StepsTimelineEntry =
  | { durationMs: number; kind: "gap" }
  | {
      durationMs?: number;
      // The id of the step's log group, so the panel can expand/scroll to it in the raw log.
      groupId: number;
      kind: "step";
      name: string;
      outputs?: Record<string, unknown>;
      progress?: StepProgress;
      status?: StepStatus;
    };

// Build the steps summary from parsed logs: top-level steps in order, with an "untracked" gap entry
// inserted whenever the time between one step ending and the next starting exceeds the threshold.
export const buildStepsTimeline = (
  parsedLogs: Array<ParsedLogEntry>,
  gapThresholdMs = 5000,
): Array<StepsTimelineEntry> => {
  const stepGroups = parsedLogs
    .map((entry) => entry.group)
    .filter(
      (group): group is NonNullable<ParsedLogEntry["group"]> =>
        group?.type === "header" && group.isStep === true && group.level === 0,
    );
  const timeline: Array<StepsTimelineEntry> = [];
  let previousEndMs: number | undefined;

  for (const group of stepGroups) {
    const startMs = group.stepStartTs === undefined ? undefined : Date.parse(group.stepStartTs);
    const gap = previousEndMs === undefined || startMs === undefined ? undefined : startMs - previousEndMs;

    if (gap !== undefined && !Number.isNaN(gap) && gap >= gapThresholdMs) {
      timeline.push({ durationMs: gap, kind: "gap" });
    }

    timeline.push({
      durationMs: group.stepDurationMs,
      groupId: group.id,
      kind: "step",
      name: group.stepName ?? "",
      outputs: group.stepOutputs,
      // Only show progress while the step is still running (no terminal status yet).
      progress: group.stepStatus === undefined ? group.stepProgress : undefined,
      status: group.stepStatus,
    });

    // Reset (do not carry forward) when a step has no usable end time -- e.g. a step that never
    // closed because the worker was killed mid-step. Carrying the previous step's end forward would
    // make the next gap swallow this step's runtime and mislabel it as "untracked".
    const endMs = group.stepEndTs === undefined ? undefined : Date.parse(group.stepEndTs);

    previousEndMs = endMs === undefined || Number.isNaN(endMs) ? undefined : endMs;
  }

  return timeline;
};

// Must match STEP_HEADER_PREFIX in airflow.sdk.execution_time.step.
const STEP_HEADER_PREFIX = "Step: ";

// The step outcome rides on the closing ::endgroup:: marker as structured fields (it is consumed,
// never rendered). Reading the raw datum -- not the rendered text -- keeps the data clean and
// independent of the source/timestamp toggles.
const readStepEndFields = (
  datum: LogDatum,
): { durationMs?: number; outputs?: Record<string, unknown>; status?: StepStatus } => {
  if (typeof datum === "string") {
    return {};
  }
  const status = datum.step_status;
  const durationMs = datum.step_duration_ms;
  const outputs = datum.step_outputs;

  return {
    durationMs: typeof durationMs === "number" ? durationMs : undefined,
    outputs:
      typeof outputs === "object" && outputs !== null && !Array.isArray(outputs)
        ? (outputs as Record<string, unknown>)
        : undefined,
    status: status === "success" || status === "cached" || status === "failed" ? status : undefined,
  };
};

// Read a ::step-progress:: marker's fields off the raw datum (same approach as the end marker).
const readStepProgress = (datum: LogDatum): StepProgress | undefined => {
  if (typeof datum === "string" || typeof datum.step_progress_done !== "number") {
    return undefined;
  }

  return {
    done: datum.step_progress_done,
    message: typeof datum.step_progress_message === "string" ? datum.step_progress_message : undefined,
    total: typeof datum.step_progress_total === "number" ? datum.step_progress_total : undefined,
  };
};

// The outermost open step on the group stack. A ::step-progress:: marker is attached here (not the
// innermost) so progress reported from a step nested inside another lands on the top-level step the
// panel actually renders, rather than on a nested step that the timeline filters out.
const outermostOpenStepHeader = (
  groupStack: Array<{ id: number }>,
  headerById: Map<number, ParsedLogEntry>,
): ParsedLogEntry | undefined => {
  for (const open of groupStack) {
    const header = headerById.get(open.id);

    if (header?.group?.isStep) {
      return header;
    }
  }

  return undefined;
};

type Props = {
  accept?: "*/*" | "application/json" | "application/x-ndjson";
  dagId: string;
  limit?: number;
  logLevelFilters?: Array<string>;
  showSource?: boolean;
  showTimestamp?: boolean;
  sourceFilters?: Array<string>;
  taskInstance?: TaskInstanceResponse;
  tryNumber?: number;
};

type ParseLogsProps = {
  data: TaskInstancesLogResponse["content"];
  logLevelFilters?: Array<string>;
  showSource?: boolean;
  showTimestamp?: boolean;
  sourceFilters?: Array<string>;
  taskInstance?: TaskInstanceResponse;
  translate: TFunction;
  tryNumber: number;
};

const parseLogs = ({
  data,
  logLevelFilters,
  showSource,
  showTimestamp,
  sourceFilters,
  taskInstance,
  translate,
  tryNumber,
}: ParseLogsProps) => {
  let warning;
  let parsedLines;
  const sources: Array<string> = [];

  const logLink = taskInstance ? `${getTaskInstanceLink(taskInstance)}?try_number=${tryNumber}` : "";

  try {
    let lineNumber = 0;
    const lineNumbers = data.map((datum) => {
      const text = typeof datum === "string" ? datum : datum.event;

      if (text.includes("::group::") || text.includes("::endgroup::") || text.includes("::step-progress::")) {
        return undefined;
      }
      const current = lineNumber;

      lineNumber += 1;

      return current;
    });

    parsedLines = data
      .map((datum, index) => {
        if (typeof datum !== "string" && "logger" in datum) {
          const source = datum.logger as string;

          if (!sources.includes(source)) {
            sources.push(source);
          }
        }

        // Keep the raw datum alongside the rendered element: step boundaries and step fields are
        // read from the raw event/fields, not the rendered text (which the source/timestamp toggles
        // would otherwise leak into the parsed step name).
        return {
          datum,
          element: renderStructuredLog({
            index: lineNumbers[index] ?? index,
            logLevelFilters,
            logLink,
            logMessage: datum,
            renderingMode: "jsx",
            showSource,
            showTimestamp,
            sourceFilters,
            translate,
          }),
        };
      })
      .filter((parsedLine) => parsedLine.element !== "");
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : "An error occurred.";

    // eslint-disable-next-line no-console
    console.warn(`Error parsing logs: ${errorMessage}`);
    warning = "Unable to show logs. There was an error parsing logs.";

    return { data, warning };
  }

  const flatEntries: Array<ParsedLogEntry> = (() => {
    type Group = { id: number; level: number; name: string };
    const groupStack: Array<Group> = [];
    const result: Array<ParsedLogEntry> = [];
    const headerById = new Map<number, ParsedLogEntry>();
    let nextGroupId = 0;

    parsedLines.forEach(({ datum, element }) => {
      // Detect group boundaries on the RAW event (clean), not the rendered text. The raw event has
      // no appended source/loc fields, so a step name is never polluted by the source toggle.
      const event = typeof datum === "string" ? datum : datum.event;

      if (event.includes("::group::")) {
        const groupName = event.split("::group::")[1] as string;
        const id = nextGroupId;

        nextGroupId += 1;
        const level = groupStack.length;
        const parentGroup = groupStack[groupStack.length - 1];

        groupStack.push({ id, level, name: groupName });

        const isStep = groupName.startsWith(STEP_HEADER_PREFIX);
        const stepName = isStep ? groupName.slice(STEP_HEADER_PREFIX.length) : undefined;
        const startTs = typeof datum === "string" ? undefined : (datum.timestamp ?? undefined);
        const headerEntry: ParsedLogEntry = {
          element: stepName ?? groupName,
          group: {
            id,
            isStep,
            level,
            parentId: parentGroup?.id,
            stepName,
            stepStartTs: isStep ? startTs : undefined,
            type: "header",
          },
        };

        result.push(headerEntry);
        headerById.set(id, headerEntry);

        return;
      }

      if (event.includes("::step-progress::")) {
        // Attach the latest progress to the open top-level step (consumed, not rendered as a line).
        const progress = readStepProgress(datum);
        const header = outermostOpenStepHeader(groupStack, headerById);

        if (progress !== undefined && header?.group) {
          header.group.stepProgress = progress;
        }

        return;
      }

      if (event.includes("::endgroup::")) {
        const closed = groupStack.pop();
        const header = closed ? headerById.get(closed.id) : undefined;

        if (header?.group?.isStep) {
          const { durationMs, outputs, status } = readStepEndFields(datum);

          header.group.stepStatus = status;
          header.group.stepDurationMs = durationMs;
          header.group.stepOutputs = outputs;
          header.group.stepEndTs = typeof datum === "string" ? undefined : (datum.timestamp ?? undefined);
        }

        return;
      }

      const currentGroup = groupStack[groupStack.length - 1];

      if (groupStack.length > 0 && currentGroup) {
        result.push({
          element,
          group: { id: currentGroup.id, level: currentGroup.level, type: "line" },
        });
      } else {
        result.push({ element });
      }
    });

    // Handle unclosed groups: their lines are already in result as flat entries
    return result;
  })();

  // Extract TI identity fields from the first structured log line and insert a single preamble
  // entry after the "Pre Execute" group header (or at position 0 if absent), so they
  // appear once rather than repeated on every line.
  const tiContext = extractTIContext(data);

  if (tiContext !== undefined) {
    let insertAt = 0;
    let insertGroup: { id: number; level: number; parentId?: number; type: "header" | "line" } | undefined =
      undefined;
    const preExecuteIndex = flatEntries.findIndex(
      (entry) =>
        entry.group?.type === "header" &&
        typeof entry.element === "string" &&
        entry.element.startsWith("Pre Execute"),
    );

    const preExecuteGroup = preExecuteIndex === -1 ? undefined : flatEntries[preExecuteIndex];

    if (preExecuteGroup?.group !== undefined) {
      insertAt = preExecuteIndex + 1;
      insertGroup = {
        id: preExecuteGroup.group.id,
        level: preExecuteGroup.group.level,
        parentId: preExecuteGroup.group.id,
        type: "line",
      };
    }
    flatEntries.splice(insertAt, 0, {
      element: renderTIContextPreamble(tiContext, "jsx", "Task Identity"),
      group: insertGroup,
    });
  }

  return {
    parsedLogs: flatEntries,
    sources,
    warning,
  };
};

// Log truncation is performed in the frontend because the backend
// does not support yet pagination / limits on logs reading endpoint
const truncateData = (data: TaskInstancesLogResponse | undefined, limit?: number) => {
  if (!data?.content || limit === undefined || limit <= 0) {
    return data;
  }

  const streamingContent = parseStreamingLogContent(data);
  const truncatedContent =
    streamingContent.length > limit ? streamingContent.slice(-limit) : streamingContent;

  return {
    ...data,
    content: truncatedContent,
  };
};

export const useLogs = (
  {
    accept = "application/x-ndjson",
    dagId,
    limit,
    logLevelFilters,
    showSource,
    showTimestamp,
    sourceFilters,
    taskInstance,
    tryNumber = 1,
  }: Props,
  options?: Omit<UseQueryOptions<TaskInstancesLogResponse>, "queryFn" | "queryKey">,
) => {
  const { t: translate } = useTranslation("common");
  const refetchInterval = useAutoRefresh({ dagId });

  const { data, ...rest } = useTaskInstanceServiceGetLog(
    {
      accept,
      dagId,
      dagRunId: taskInstance?.dag_run_id ?? "",
      mapIndex: taskInstance?.map_index ?? -1,
      taskId: taskInstance?.task_id ?? "",
      tryNumber,
    },
    undefined,
    {
      enabled: Boolean(taskInstance),
      refetchInterval: (query) =>
        isStatePending(taskInstance?.state) ||
        dayjs(query.state.dataUpdatedAt).isBefore(taskInstance?.end_date)
          ? refetchInterval
          : false,
      ...options,
    },
  );

  const parsedData = parseLogs({
    data: parseStreamingLogContent(truncateData(data, limit)),
    logLevelFilters,
    showSource,
    showTimestamp,
    sourceFilters,
    taskInstance,
    translate,
    tryNumber,
  });

  // Build a 1:1 searchable text array from parsedLogs so search indices align
  // with the rendered output. Each entry maps to exactly one line.
  const searchableText: Array<string> = (parsedData.parsedLogs ?? []).map((entry) => {
    if (typeof entry.element === "string") {
      return entry.element;
    }

    return entry.element ? innerText(entry.element) : "";
  });

  return { parsedData: { ...parsedData, searchableText }, ...rest, fetchedData: data };
};
