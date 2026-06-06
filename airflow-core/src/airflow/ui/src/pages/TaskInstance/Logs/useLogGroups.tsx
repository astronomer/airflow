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
import { useEffect, useState } from "react";

import type { ParsedLogEntry } from "src/queries/useLogs";

type VisibleItem = { entry: ParsedLogEntry; originalIndex: number };

/**
 * Manages log group expand/collapse state and computes the list of
 * visible entries for the virtualizer. Handles nested groups and
 * auto-expanding collapsed groups when search navigates into them.
 */
export const useLogGroups = ({
  currentMatchLineIndex,
  expanded,
  focusedStep,
  parsedLogs,
  searchMatchIndices,
  stepsOnly = false,
}: {
  currentMatchLineIndex?: number;
  expanded: boolean;
  focusedStep?: { groupId: number; seq: number };
  parsedLogs: Array<ParsedLogEntry>;
  searchMatchIndices?: Set<number>;
  stepsOnly?: boolean;
}) => {
  // Build parent map for nested visibility checks
  const groupHeaders = parsedLogs.filter(
    (entry): entry is { group: NonNullable<ParsedLogEntry["group"]> } & ParsedLogEntry =>
      entry.group?.type === "header",
  );
  const allGroupIds = new Set(groupHeaders.map((entry) => entry.group.id));
  // eslint-disable-next-line react-hooks/exhaustive-deps -- React Compiler auto-memoizes this
  const groupParentMap = new Map<number, number | undefined>(
    groupHeaders.map((entry) => [entry.group.id, entry.group.parentId]),
  );

  const [expandedGroups, setExpandedGroups] = useState<Set<number>>(() =>
    expanded ? new Set(allGroupIds) : new Set<number>(),
  );

  // Sync expandedGroups when expanded prop changes (toggle all)
  useEffect(() => {
    if (expanded) {
      setExpandedGroups(new Set(allGroupIds));
    } else {
      setExpandedGroups(new Set<number>());
    }
    // Only react to the expanded prop, not allGroupIds
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded]);

  const toggleGroup = (groupId: number) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);

      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }

      return next;
    });
  };

  // Check if all ancestors of a group are expanded
  const isGroupAncestryExpanded = (groupId: number): boolean => {
    const parentId = groupParentMap.get(groupId);

    if (parentId === undefined) {
      return true;
    }

    return expandedGroups.has(parentId) && isGroupAncestryExpanded(parentId);
  };

  const isEntryVisible = (entry: ParsedLogEntry): boolean => {
    // "Steps only" view: collapse everything down to the step headers, hiding loose lines and
    // non-step groups -- a compact CI-pipeline-style summary.
    if (stepsOnly) {
      return entry.group?.type === "header" && Boolean(entry.group.isStep);
    }

    if (!entry.group) {
      return true;
    }

    if (entry.group.type === "header") {
      return isGroupAncestryExpanded(entry.group.id);
    }

    return expandedGroups.has(entry.group.id) && isGroupAncestryExpanded(entry.group.id);
  };

  // Build visible items list with index mapping
  const visibleItems: Array<VisibleItem> = [];
  const originalToVisibleIndex = new Map<number, number>();

  for (let idx = 0; idx < parsedLogs.length; idx += 1) {
    const entry = parsedLogs[idx];

    if (entry && isEntryVisible(entry)) {
      originalToVisibleIndex.set(idx, visibleItems.length);
      visibleItems.push({ entry, originalIndex: idx });
    }
  }

  // Map search match indices from original to visible indices
  const visibleSearchMatchIndices = searchMatchIndices
    ? new Set(
        [...searchMatchIndices]
          .map((idx) => originalToVisibleIndex.get(idx))
          .filter((idx): idx is number => idx !== undefined),
      )
    : undefined;

  const visibleCurrentMatchIndex =
    currentMatchLineIndex === undefined ? undefined : originalToVisibleIndex.get(currentMatchLineIndex);

  // Visible index of the step header the panel asked to focus (a header is always visible once its
  // ancestry is expanded), so the log view can scroll to it.
  const focusedHeaderOriginalIndex =
    focusedStep === undefined
      ? -1
      : parsedLogs.findIndex(
          (entry) => entry.group?.type === "header" && entry.group.id === focusedStep.groupId,
        );
  const focusVisibleIndex =
    focusedHeaderOriginalIndex === -1 ? undefined : originalToVisibleIndex.get(focusedHeaderOriginalIndex);

  // Expand the focused step group (and its ancestors) ONCE per panel click. It depends only on the
  // focusedStep object (new identity per click via its seq), NOT on expandedGroups -- otherwise it
  // would re-assert expansion whenever the set changed and the user could never collapse the group
  // again. The chain is added with a functional update so expandedGroups isn't needed in the closure.
  useEffect(() => {
    if (focusedStep === undefined) {
      return;
    }
    const chain: Array<number> = [];
    let currentId: number | undefined = focusedStep.groupId;

    while (currentId !== undefined) {
      chain.push(currentId);
      currentId = groupParentMap.get(currentId);
    }

    setExpandedGroups((prev) => new Set([...prev, ...chain]));
  }, [focusedStep, groupParentMap]);

  // Auto-expand group (and all ancestors) when search navigates to a match inside a collapsed group
  useEffect(() => {
    if (currentMatchLineIndex === undefined) {
      return;
    }
    const entry = parsedLogs[currentMatchLineIndex];

    if (!entry?.group) {
      return;
    }

    const groupsToExpand: Array<number> = [];

    if (entry.group.type === "line" && !expandedGroups.has(entry.group.id)) {
      groupsToExpand.push(entry.group.id);
    }

    // Walk up the parent chain
    let currentId: number | undefined = entry.group.id;

    while (currentId !== undefined) {
      const parentId = groupParentMap.get(currentId);

      if (parentId !== undefined && !expandedGroups.has(parentId)) {
        groupsToExpand.push(parentId);
      }
      currentId = parentId;
    }

    if (groupsToExpand.length > 0) {
      setExpandedGroups((prev) => new Set([...prev, ...groupsToExpand]));
    }
  }, [currentMatchLineIndex, parsedLogs, expandedGroups, groupParentMap]);

  return {
    expandedGroups,
    focusVisibleIndex,
    originalToVisibleIndex,
    toggleGroup,
    visibleCurrentMatchIndex,
    visibleItems,
    visibleSearchMatchIndices,
  };
};
