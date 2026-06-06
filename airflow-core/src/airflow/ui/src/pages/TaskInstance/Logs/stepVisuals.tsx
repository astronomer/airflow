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
import type { IconType } from "react-icons";
import { FiAlertTriangle, FiCheckCircle, FiClock, FiXCircle, FiZap } from "react-icons/fi";

import type { StepStatus } from "src/queries/useLogs";

// The visual states a step can be in. StepStatus comes from the end marker; "running" and
// "interrupted" are derived for an open step (no end marker) depending on whether the task instance
// itself has ended -- a still-running task means the step is running; a terminal task means the step
// never finished (e.g. the worker was killed mid-step).
export type StepVisualState = StepStatus | "interrupted" | "running";

// AIP-103 Task Steps: visual treatment per state. Shared by the log view and the steps panel.
export const STEP_STATUS_VISUALS: Record<StepVisualState, { color: string; icon: IconType }> = {
  cached: { color: "fg.info", icon: FiZap },
  failed: { color: "fg.error", icon: FiXCircle },
  interrupted: { color: "fg.warning", icon: FiAlertTriangle },
  running: { color: "fg.muted", icon: FiClock },
  success: { color: "fg.success", icon: FiCheckCircle },
};

// Resolve the visual state of a step: its terminal status if known, else interrupted (the task ended
// without the step closing) or running.
export const resolveStepVisualState = (
  status: StepStatus | undefined,
  taskTerminal: boolean,
): StepVisualState => status ?? (taskTerminal ? "interrupted" : "running");

export const formatStepDuration = (ms: number): string => {
  // Thresholds are on raw ms (not rounded seconds) to avoid a discontinuity where e.g. 59.5s would
  // round to 60 and jump straight to "1m 0s".
  if (ms < 1000) {
    return `${ms}ms`;
  }
  if (ms < 60_000) {
    return `${(ms / 1000).toFixed(1)}s`;
  }
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m ${seconds}s`;
};

// Step output values are user-supplied; cap the chip label so one large value can't blow out the row.
export const MAX_OUTPUT_CHIP_LENGTH = 60;

// Render a step output value (from s.output(key, value)) as a compact chip label. Numbers get a
// thousands separator (e.g. 12043 -> "12,043"); objects/arrays are JSON-stringified.
export const formatOutputValue = (value: unknown): string => {
  if (typeof value === "number") {
    return value.toLocaleString();
  }
  if (typeof value === "string" || typeof value === "boolean") {
    return String(value);
  }

  return JSON.stringify(value);
};

// "rows: 12,043", truncated with the full value available in a tooltip.
export const outputChipLabel = (key: string, value: unknown): { full: string; label: string } => {
  const full = `${key}: ${formatOutputValue(value)}`;
  const label = full.length > MAX_OUTPUT_CHIP_LENGTH ? `${full.slice(0, MAX_OUTPUT_CHIP_LENGTH - 1)}…` : full;

  return { full, label };
};
