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

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataTable } from "./DataTable.tsx";
import { ColumnDef, PaginationState } from "@tanstack/react-table";
import "@testing-library/jest-dom";

const columns: ColumnDef<{ name: string }>[] = [
  {
    accessorKey: "name",
    header: "Name",
    cell: (info) => info.getValue(),
  },
];

const data = [
  { name: "John Doe" },
  { name: "Jane Doe" },
  { name: "Person 3" },
  { name: "Person 4" },
  { name: "Person 5" },
];

const pagination: PaginationState = { pageIndex: 0, pageSize: 1 };
const onStateChange = vi.fn();

describe("DataTable", () => {
  it("renders table with data", () => {
    render(
      <DataTable
        data={data}
        total={data.length}
        columns={columns}
        initialState={{ pagination, sorting: [] }}
        onStateChange={onStateChange}
        title="Name"
      />
    );

    expect(screen.getByText("John Doe")).toBeInTheDocument();
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
  });

  it("disables previous page button on first page", () => {
    render(
      <DataTable
        data={data}
        total={data.length}
        columns={columns}
        initialState={{ pagination, sorting: [] }}
        onStateChange={onStateChange}
        title="Name"
      />
    );

    expect(screen.getByTestId("previous-page")).toBeDisabled();
  });

  it("disables next button when on last page", () => {
    render(
      <DataTable
        data={data}
        total={data.length}
        columns={columns}
        initialState={{
          pagination: { pageIndex: 4, pageSize: 1 },
          sorting: [],
        }}
        onStateChange={() => {}}
        title="Name"
      />
    );

    expect(screen.getByTestId("next-page")).toBeDisabled();
  });

  it("shows second and second to last button when on third page", () => {
    render(
      <DataTable
        data={data}
        total={data.length}
        columns={columns}
        initialState={{
          pagination: { pageIndex: 2, pageSize: 1 },
          sorting: [],
        }}
        onStateChange={() => {}}
        title="Name"
      />
    );

    expect(screen.getByTestId("second-page")).toBeDefined();
    expect(screen.getByTestId("second-last-page")).toBeDefined();
  });

  it("shows ellipsis between 1 and current page when index > 2", () => {
    render(
      <DataTable
        data={data}
        total={data.length}
        columns={columns}
        initialState={{
          pagination: { pageIndex: 3, pageSize: 1 },
          sorting: [],
        }}
        onStateChange={() => {}}
        title="Name"
      />
    );

    expect(screen.getByTestId("ellipsis")).toBeDefined();
  });

  it("shows ellipsis between current page and last when index < 3", () => {
    render(
      <DataTable
        data={data}
        total={data.length}
        columns={columns}
        initialState={{
          pagination: { pageIndex: 1, pageSize: 1 },
          sorting: [],
        }}
        onStateChange={() => {}}
        title="Name"
      />
    );

    expect(screen.getByTestId("ellipsis")).toBeDefined();
  });

  it("Does not show any pagination when its only one page", () => {
    render(
      <DataTable
        data={data}
        total={data.length}
        columns={columns}
        initialState={{
          pagination: { pageIndex: 0, pageSize: 5 },
          sorting: [],
        }}
        onStateChange={() => {}}
        title="Name"
      />
    );

    expect(screen.queryByTestId("first-page")).toBeNull();
    expect(screen.queryByTestId("last-page")).toBeNull();
    expect(screen.queryByTestId("next-page")).toBeNull();
    expect(screen.queryByTestId("previous-page")).toBeNull();
  });
});
