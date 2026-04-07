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
import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Wrapper } from "src/utils/Wrapper";

import { Code } from "./Code";

// Monaco Editor cannot run in jsdom — render a thin stub that exposes props as data attributes.
vi.mock("@monaco-editor/react", () => ({
  default: vi.fn(
    ({ options, value }: { options?: { lineNumbers?: string; wordWrap?: string }; value?: string }) => (
      <div
        data-line-numbers={options?.lineNumbers}
        data-testid="monaco-editor"
        data-value={value}
        data-word-wrap={options?.wordWrap}
      />
    ),
  ),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");

  return {
    ...actual,
    useParams: () => ({ dagId: "test_dag" }),
  };
});

vi.mock("openapi/queries", () => ({
  useConfigServiceGetConfigs: vi.fn(() => ({
    data: { default_wrap: false },
    isLoading: false,
  })),
  useDagServiceGetDagDetails: vi.fn(() => ({
    data: {
      dag_id: "test_dag",
      fileloc: "/dags/test_dag.py",
      last_parse_duration: 0.5,
      last_parsed_time: "2025-01-01T00:00:00Z",
      relative_fileloc: "test_dag.py",
    },
    error: undefined,
    isLoading: false,
  })),
  useDagSourceServiceGetDagSource: vi.fn(() => ({
    data: { content: "print('hello world')" },
    error: undefined,
    isLoading: false,
  })),
  useDagVersionServiceGetDagVersion: vi.fn(() => ({
    /* eslint-disable unicorn/no-null */
    data: { bundle_url: null, bundle_version: null, version_number: 1 },
    /* eslint-enable unicorn/no-null */
    isLoading: false,
  })),
  useDagVersionServiceGetDagVersions: vi.fn(() => ({
    data: { dag_versions: [{ version_number: 1 }], total_entries: 1 },
    isLoading: false,
  })),
}));

vi.mock("src/hooks/useSelectedVersion", () => ({
  default: vi.fn(() => 1),
}));

vi.mock("src/components/DagVersionSelect", () => ({
  // eslint-disable-next-line react/jsx-no-useless-fragment
  DagVersionSelect: () => <></>,
}));

vi.mock("./FileLocation", () => ({
  // eslint-disable-next-line react/jsx-no-useless-fragment
  FileLocation: () => <></>,
}));

vi.mock("./CodeDiffViewer", () => ({
  CodeDiffViewer: ({
    modifiedCode,
    originalCode,
  }: {
    readonly modifiedCode?: string;
    readonly originalCode?: string;
  }) => <div data-modified={modifiedCode} data-original={originalCode} data-testid="code-diff-viewer" />,
}));

vi.mock("./VersionCompareSelect", () => ({
  VersionCompareSelect: ({ onVersionChange }: { readonly onVersionChange?: (v: number) => void }) => (
    <button data-testid="version-compare-select" onClick={() => onVersionChange?.(2)} type="button">
      Compare v2
    </button>
  ),
}));

const { useConfigServiceGetConfigs, useDagSourceServiceGetDagSource, useDagVersionServiceGetDagVersions } =
  await import("openapi/queries");

afterEach(() => vi.clearAllMocks());

describe("Code", () => {
  it("passes source code content as value to the editor", () => {
    render(
      <Wrapper>
        <Code />
      </Wrapper>,
    );

    expect(screen.getByTestId("monaco-editor")).toHaveAttribute("data-value", "print('hello world')");
  });

  it("shows 'No Code Found' when the source endpoint returns 404", () => {
    vi.mocked(useDagSourceServiceGetDagSource).mockReturnValue({
      data: undefined,
      error: { status: 404 } as ReturnType<typeof useDagSourceServiceGetDagSource>["error"],
      isLoading: false,
    } as ReturnType<typeof useDagSourceServiceGetDagSource>);

    render(
      <Wrapper>
        <Code />
      </Wrapper>,
    );

    expect(screen.getByTestId("monaco-editor")).toHaveAttribute("data-value", "No Code Found");
  });

  it("passes lineNumbers: 'on' in editor options", () => {
    render(
      <Wrapper>
        <Code />
      </Wrapper>,
    );

    expect(screen.getByTestId("monaco-editor")).toHaveAttribute("data-line-numbers", "on");
  });

  it("initializes with wordWrap off when defaultWrap config is false", () => {
    render(
      <Wrapper>
        <Code />
      </Wrapper>,
    );

    expect(screen.getByTestId("monaco-editor")).toHaveAttribute("data-word-wrap", "off");
    expect(screen.getByRole("button", { name: "Wrap" })).toBeInTheDocument();
  });

  it("initializes with wordWrap on when defaultWrap config is true", () => {
    vi.mocked(useConfigServiceGetConfigs).mockReturnValue({
      data: { default_wrap: true },
      isLoading: false,
    } as ReturnType<typeof useConfigServiceGetConfigs>);

    render(
      <Wrapper>
        <Code />
      </Wrapper>,
    );

    expect(screen.getByTestId("monaco-editor")).toHaveAttribute("data-word-wrap", "on");
    expect(screen.getByRole("button", { name: "Unwrap" })).toBeInTheDocument();
  });

  it("toggles wordWrap when the wrap button is clicked", () => {
    render(
      <Wrapper>
        <Code />
      </Wrapper>,
    );

    const wrapButton = screen.getByRole("button", { name: "Wrap" });

    fireEvent.click(wrapButton);
    expect(screen.getByTestId("monaco-editor")).toHaveAttribute("data-word-wrap", "on");
    expect(screen.getByRole("button", { name: "Unwrap" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Unwrap" }));
    expect(screen.getByTestId("monaco-editor")).toHaveAttribute("data-word-wrap", "off");
  });

  it("renders CodeDiffViewer when a compare version is selected", () => {
    vi.mocked(useDagVersionServiceGetDagVersions).mockReturnValue({
      data: {
        dag_versions: [{ version_number: 1 }, { version_number: 2 }],
        total_entries: 2,
      },
      isLoading: false,
    } as ReturnType<typeof useDagVersionServiceGetDagVersions>);

    render(
      <Wrapper>
        <Code />
      </Wrapper>,
    );

    // Open the compare version dropdown
    fireEvent.click(screen.getByRole("button", { name: "Diff" }));

    // Select a version to compare
    fireEvent.click(screen.getByTestId("version-compare-select"));

    expect(screen.getByTestId("code-diff-viewer")).toBeInTheDocument();
    expect(screen.queryByTestId("monaco-editor")).not.toBeInTheDocument();
  });
});
