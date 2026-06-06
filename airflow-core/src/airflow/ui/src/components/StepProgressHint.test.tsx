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
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Wrapper } from "src/utils/Wrapper";

import StepProgressHint from "./StepProgressHint";

// Mock the generated task-store query hook so the test exercises the render/parse logic without a
// network layer (and therefore without MSW teardown noise). vi.hoisted lets the mock factory (which
// vitest hoists above the imports) reference the spy.
const { mockUseTaskStore } = vi.hoisted(() => ({ mockUseTaskStore: vi.fn() }));

vi.mock("openapi/queries", () => ({
  useTaskStoreServiceGetTaskStore: mockUseTaskStore,
}));

const renderHint = () => render(<StepProgressHint dagId="d" runId="r" taskId="sync" />, { wrapper: Wrapper });

afterEach(() => {
  mockUseTaskStore.mockReset();
});

describe("StepProgressHint", () => {
  it("renders the running step name and percent/message progress", () => {
    mockUseTaskStore.mockReturnValue({
      data: {
        value: {
          done: 8,
          message: "copying orders_2026_08.parquet",
          name: "copy",
          status: "running",
          total: 12,
        },
      },
    });

    renderHint();

    expect(screen.getByTestId("step-progress-hint")).toBeInTheDocument();
    expect(screen.getByText("8/12 (67%) · copying orders_2026_08.parquet")).toBeInTheDocument();
  });

  it("renders nothing for a finished (non-running) step", () => {
    mockUseTaskStore.mockReturnValue({
      data: { value: { duration_ms: 1200, name: "copy", status: "success" } },
    });

    renderHint();

    expect(screen.queryByTestId("step-progress-hint")).not.toBeInTheDocument();
  });

  it("renders nothing when there is no step-state value yet", () => {
    mockUseTaskStore.mockReturnValue({ data: undefined });

    renderHint();

    expect(screen.queryByTestId("step-progress-hint")).not.toBeInTheDocument();
  });

  it("ignores a value that is not a step-state object", () => {
    mockUseTaskStore.mockReturnValue({ data: { value: "not-an-object" } });

    renderHint();

    expect(screen.queryByTestId("step-progress-hint")).not.toBeInTheDocument();
  });

  it("shows an indeterminate count (no bar) when total is absent", () => {
    mockUseTaskStore.mockReturnValue({
      data: { value: { done: 5, message: "page 5", name: "scan", status: "running" } },
    });

    renderHint();

    expect(screen.getByText("5 · page 5")).toBeInTheDocument();
  });
});
