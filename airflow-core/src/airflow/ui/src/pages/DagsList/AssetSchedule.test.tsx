/* eslint-disable unicorn/no-null */
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
import i18n from "i18next";
import * as OpenApiQueries from "openapi/queries";
import type { PropsWithChildren } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { BaseWrapper } from "src/utils/Wrapper";

import "../../i18n/config";
import { AssetSchedule } from "./AssetSchedule";

vi.mock("openapi/queries", async () => {
  const actual = await vi.importActual("openapi/queries");

  return {
    ...actual,
    useAssetServiceGetDagAssetQueuedEvents: vi.fn(),
    useAssetServiceNextRunAssets: vi.fn(),
  };
});

const mockUseAssetServiceGetDagAssetQueuedEvents = OpenApiQueries.useAssetServiceGetDagAssetQueuedEvents as Mock;
const mockUseAssetServiceNextRunAssets = OpenApiQueries.useAssetServiceNextRunAssets as Mock;

const Wrapper = ({ children }: PropsWithChildren) => (
  <BaseWrapper>
    <MemoryRouter>{children}</MemoryRouter>
  </BaseWrapper>
);

describe("AssetSchedule", () => {
  beforeAll(async () => {
    await i18n.init({
      defaultNS: "dags",
      fallbackLng: "en",
      interpolation: { escapeValue: false },
      lng: "en",
      ns: ["dags", "common"],
      resources: {
        en: {
          dags: {
            assetSchedule: "{{count}} of {{total}} assets updated",
          },
        },
      },
    });
  });

  beforeEach(() => {
    mockUseAssetServiceNextRunAssets.mockReset();
    mockUseAssetServiceGetDagAssetQueuedEvents.mockReset();
  });

  it("deduplicates queued events by asset id when counting pending assets", () => {
    mockUseAssetServiceNextRunAssets.mockReturnValue({
      data: {
        events: [
          { id: 1, lastUpdate: null, name: "asset-a", uri: "asset://a" },
          { id: 2, lastUpdate: null, name: "asset-b", uri: "asset://b" },
        ],
      },
      isLoading: false,
    });
    mockUseAssetServiceGetDagAssetQueuedEvents.mockReturnValue({
      data: {
        queued_events: [
          { asset_id: 1, created_at: "2026-03-01T00:00:00Z", dag_display_name: "example", dag_id: "example" },
          { asset_id: 1, created_at: "2026-03-02T00:00:00Z", dag_display_name: "example", dag_id: "example" },
        ],
        total_entries: 2,
      },
      error: undefined,
      isLoading: false,
    });

    render(<AssetSchedule dagId="example" timetableSummary="Asset" />, { wrapper: Wrapper });

    expect(screen.getByRole("button")).toHaveTextContent("1 of 2 assets updated");
  });

  it("treats 404 queued-events response as zero pending assets", () => {
    mockUseAssetServiceNextRunAssets.mockReturnValue({
      data: {
        events: [
          { id: 1, lastUpdate: "2026-03-03T00:00:00Z", name: "asset-a", uri: "asset://a" },
          { id: 2, lastUpdate: null, name: "asset-b", uri: "asset://b" },
        ],
      },
      isLoading: false,
    });
    mockUseAssetServiceGetDagAssetQueuedEvents.mockReturnValue({
      data: undefined,
      error: { status: 404 },
      isLoading: false,
    });

    render(
      <AssetSchedule dagId="example" latestRunAfter="2026-03-02T00:00:00Z" timetableSummary="Asset" />,
      { wrapper: Wrapper },
    );

    expect(screen.getByRole("button")).toHaveTextContent("0 of 2 assets updated");
  });
});
