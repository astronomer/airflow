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
import { describe, expect, it } from "vitest";

import { buildStepsTimeline, type ParsedLogEntry } from "./useLogs";

let idCounter = 0;

const nextId = (): number => {
  idCounter += 1;

  return idCounter;
};

const stepHeader = (name: string, startTs?: string, endTs?: string): ParsedLogEntry => ({
  element: name,
  group: {
    id: nextId(),
    isStep: true,
    level: 0,
    stepEndTs: endTs,
    stepName: name,
    stepStartTs: startTs,
    type: "header",
  },
});

describe("buildStepsTimeline", () => {
  it("inserts an untracked gap when the time between two steps exceeds the threshold", () => {
    const timeline = buildStepsTimeline([
      stepHeader("a", "2025-01-01T00:00:00.000Z", "2025-01-01T00:00:01.000Z"),
      stepHeader("b", "2025-01-01T00:00:08.000Z", "2025-01-01T00:00:09.000Z"),
    ]);

    expect(timeline.map((entry) => entry.kind)).toStrictEqual(["step", "gap", "step"]);
    const [, gap] = timeline;

    expect(gap?.kind === "gap" ? gap.durationMs : undefined).toBe(7000);
  });

  it("does not insert a gap when steps are back-to-back (below threshold)", () => {
    const timeline = buildStepsTimeline([
      stepHeader("a", "2025-01-01T00:00:00.000Z", "2025-01-01T00:00:01.000Z"),
      stepHeader("b", "2025-01-01T00:00:01.100Z", "2025-01-01T00:00:02.000Z"),
    ]);

    expect(timeline.map((entry) => entry.kind)).toStrictEqual(["step", "step"]);
  });

  it("does not mislabel an un-ended middle step's runtime as an untracked gap", () => {
    // b started but never closed (e.g. worker killed mid-step); c starts much later. The gap before
    // c must NOT be computed against a's end (which would swallow b's runtime).
    const timeline = buildStepsTimeline([
      stepHeader("a", "2025-01-01T00:00:00.000Z", "2025-01-01T00:00:01.000Z"),
      stepHeader("b", "2025-01-01T00:00:02.000Z", undefined),
      stepHeader("c", "2025-01-01T00:01:00.000Z", "2025-01-01T00:01:01.000Z"),
    ]);

    expect(timeline.map((entry) => entry.kind)).toStrictEqual(["step", "step", "step"]);
  });

  it("carries live progress only for a running step (no terminal status yet)", () => {
    const completed: ParsedLogEntry = {
      element: "extract",
      group: {
        id: nextId(),
        isStep: true,
        level: 0,
        stepName: "extract",
        stepProgress: { done: 3, total: 3 },
        stepStatus: "success",
        type: "header",
      },
    };
    const running: ParsedLogEntry = {
      element: "load",
      group: {
        id: nextId(),
        isStep: true,
        level: 0,
        stepName: "load",
        stepProgress: { done: 5, total: 8 },
        type: "header",
      },
    };

    const [done, run] = buildStepsTimeline([completed, running]);

    // Completed step: progress suppressed (it has a status). Running step: progress shown.
    expect(done?.kind === "step" ? done.progress : "sentinel").toBeUndefined();
    expect(run?.kind === "step" ? run.progress?.done : undefined).toBe(5);
  });

  it("ignores non-step groups and nested (non-top-level) steps", () => {
    const plainGroup: ParsedLogEntry = {
      element: "Pre Execute",
      group: { id: nextId(), isStep: false, level: 0, type: "header" },
    };
    const nestedStep: ParsedLogEntry = {
      element: "nested",
      group: { id: nextId(), isStep: true, level: 1, stepName: "nested", type: "header" },
    };

    const timeline = buildStepsTimeline([
      plainGroup,
      nestedStep,
      stepHeader("only", "2025-01-01T00:00:00.000Z", "2025-01-01T00:00:01.000Z"),
    ]);

    expect(timeline).toHaveLength(1);
    expect(timeline[0]?.kind === "step" ? timeline[0].name : undefined).toBe("only");
  });
});
