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
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTaskInstanceView } from "src/hooks/useTaskInstanceView";
import { type DurableHistory, useDurableHistory } from "src/queries/useDurableHistory";
import { Wrapper } from "src/utils/Wrapper";

import { DurableExecution } from "./DurableExecution";

vi.mock("src/queries/useDurableHistory", () => ({ useDurableHistory: vi.fn() }));
vi.mock("src/hooks/useTaskInstanceView", () => ({ useTaskInstanceView: vi.fn() }));

const buildTry = (
  tryNumber: number,
  decision: string,
  { priorStatus, seconds = null }: { readonly priorStatus?: string; readonly seconds?: number | null } = {},
) => ({
  decision,
  external_id: `application_${tryNumber}`,
  prior_status: priorStatus ?? null,
  recorded_at: "2026-11-08T01:24:00Z",
  time_not_rerun_seconds: seconds,
  try_number: tryNumber,
});

const SPARK_HISTORY: DurableHistory = {
  can_resume_failed_job: false,
  external_id_key: "spark_job_id",
  operator: "SparkSubmitOperator",
  tries: [
    buildTry(1, "submitted"),
    buildTry(2, "reconnected", { priorStatus: "RUNNING", seconds: 24 * 60 }),
    buildTry(3, "resubmitted", { priorStatus: "FAILED", seconds: 0 }),
  ],
};

const renderWith = (history: DurableHistory | undefined, state = "success") => {
  vi.mocked(useDurableHistory).mockReturnValue(history);
  vi.mocked(useTaskInstanceView).mockReturnValue({
    liveTaskInstance: { state },
  } as unknown as ReturnType<typeof useTaskInstanceView>);

  return render(
    <Wrapper>
      <DurableExecution />
    </Wrapper>,
  );
};

describe("DurableExecution", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists what each try did and sums the time not rerun once the task succeeded", () => {
    renderWith(SPARK_HISTORY);

    expect(screen.getByText("durableExecution.decision.submitted")).toBeInTheDocument();
    expect(screen.getByText("durableExecution.decision.reconnected")).toBeInTheDocument();
    expect(screen.getByText("durableExecution.decision.resubmitted")).toBeInTheDocument();
    expect(screen.getByText("durableExecution.explanation.resubmitted")).toBeInTheDocument();
    expect(screen.getByText("24m")).toBeInTheDocument();
    expect(screen.getAllByText("durableExecution.supports.no")).toHaveLength(1);
  });

  it("holds back the total while the task has not succeeded", () => {
    renderWith(SPARK_HISTORY, "up_for_retry");

    expect(screen.queryByText("24m")).not.toBeInTheDocument();
    expect(screen.getByText("durableExecution.total.onlyOnSuccess")).toBeInTheDocument();
  });

  it("says the engine did not report timing instead of showing zero", () => {
    renderWith({
      ...SPARK_HISTORY,
      tries: [
        buildTry(1, "submitted"),
        buildTry(2, "reconnected", { priorStatus: "RUNNING", seconds: null }),
      ],
    });

    expect(screen.getByText("durableExecution.timingNotReported")).toBeInTheDocument();
    expect(screen.getByText("durableExecution.total.notReported")).toBeInTheDocument();
  });

  it("warns about a resume that fell back and explains a declined resume", () => {
    renderWith({
      ...SPARK_HISTORY,
      can_resume_failed_job: true,
      tries: [
        buildTry(1, "submitted"),
        buildTry(2, "resume_fell_back", { priorStatus: "TERMINATED:FAILED", seconds: 0 }),
        buildTry(3, "resubmitted", { priorStatus: "TERMINATED:FAILED", seconds: 0 }),
      ],
    });

    expect(screen.getByText("durableExecution.fellBackWarning")).toBeInTheDocument();
    expect(screen.getByText("durableExecution.explanation.resubmittedDeclined")).toBeInTheDocument();
  });

  it("shows zero, not under a minute, when no retry saved work, and job IDs without quotes", () => {
    renderWith({
      ...SPARK_HISTORY,
      tries: [buildTry(1, "submitted"), buildTry(2, "resubmitted", { priorStatus: "FAILED", seconds: 0 })],
    });

    expect(screen.getByText("0m")).toBeInTheDocument();
    expect(screen.getByText("application_2")).toBeInTheDocument();
  });

  it("shows an empty message when the task has no history", () => {
    renderWith(undefined);

    expect(screen.getByText("durableExecution.empty")).toBeInTheDocument();
  });
});
