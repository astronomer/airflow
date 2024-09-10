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

import {
  ColumnDef,
  Table as TanStackTable,
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  getPaginationRowModel,
  OnChangeFn,
  Row,
  useReactTable,
  TableState as ReactTableState,
  Updater,
} from "@tanstack/react-table";
import {
  Table as ChakraTable,
  Heading,
  HStack,
  TableContainer,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
  useColorModeValue,
  VStack,
} from "@chakra-ui/react";
import React, { Fragment, useCallback, useRef } from "react";
import {
  TiArrowSortedDown,
  TiArrowSortedUp,
  TiArrowUnsorted,
} from "react-icons/ti";

import { pluralize } from "src/utils/pluralize";

import type { TableState } from "./types";
import { TablePaginator } from "./TablePaginator";
import createSkeleton from "./createSkeleton";

type DataTableProps<TData> = {
  data: TData[];
  total?: number;
  columns: ColumnDef<TData>[];
  renderSubComponent?: (props: {
    row: Row<TData>;
  }) => React.ReactElement | null;
  getRowCanExpand?: (row: Row<TData>) => boolean;
  initialState?: TableState;
  onStateChange?: (state: TableState) => void;
  isLoading?: boolean;
  title: string;
};

export const DataTable = <TData,>({
  data,
  total = 0,
  columns,
  renderSubComponent = () => null,
  getRowCanExpand = () => false,
  initialState,
  onStateChange,
  isLoading,
  title,
}: DataTableProps<TData>) => {
  const ref = useRef<{ tableRef: TanStackTable<TData> | undefined }>({
    tableRef: undefined,
  });
  const handleStateChange = useCallback<OnChangeFn<ReactTableState>>(
    (updater: Updater<ReactTableState>) => {
      if (ref.current.tableRef && onStateChange) {
        const current = ref.current.tableRef.getState();
        const next = typeof updater === "function" ? updater(current) : updater;

        // Only use the controlled state
        const nextState = {
          sorting: next.sorting,
          pagination: next.pagination,
        };

        onStateChange(nextState);
      }
    },
    [onStateChange]
  );

  const table = useReactTable({
    data,
    columns,
    getRowCanExpand,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    onStateChange: handleStateChange,
    ...(isLoading ? createSkeleton(25, columns) : {}),
    rowCount: total,
    manualPagination: true,
    manualSorting: true,
    state: initialState,
  });

  ref.current.tableRef = table;

  const theadBg = useColorModeValue("white", "gray.800");

  return (
    <VStack alignItems="none" mt={2} spacing={0}>
      <HStack justifyContent="space-between">
        <Heading size="md" pt={2}>
          {pluralize(title, total)}
        </Heading>
        <TablePaginator table={table} />
      </HStack>
      <TableContainer overflowY="auto" maxH="calc(100vh - 10rem)">
        <ChakraTable colorScheme="blue">
          <Thead position="sticky" top={0} bg={theadBg} zIndex={1}>
            {table.getHeaderGroups().map((headerGroup) => (
              <Tr key={headerGroup.id}>
                {headerGroup.headers.map(
                  ({ column, id, colSpan, getContext, isPlaceholder }) => {
                    const sort = column.getIsSorted();
                    const canSort = column.getCanSort();
                    return (
                      <Th
                        key={id}
                        colSpan={colSpan}
                        whiteSpace="nowrap"
                        cursor={column.getCanSort() ? "pointer" : undefined}
                        onClick={column.getToggleSortingHandler()}
                      >
                        {isPlaceholder ? null : (
                          <>
                            {flexRender(column.columnDef.header, getContext())}
                          </>
                        )}
                        {canSort && !sort && (
                          <TiArrowUnsorted
                            aria-label="unsorted"
                            style={{ display: "inline" }}
                            size="1em"
                          />
                        )}
                        {canSort &&
                          sort &&
                          (sort === "desc" ? (
                            <TiArrowSortedDown
                              aria-label="sorted descending"
                              style={{ display: "inline" }}
                              size="1em"
                            />
                          ) : (
                            <TiArrowSortedUp
                              aria-label="sorted ascending"
                              style={{ display: "inline" }}
                              size="1em"
                            />
                          ))}
                      </Th>
                    );
                  }
                )}
              </Tr>
            ))}
          </Thead>
          <Tbody>
            {table.getRowModel().rows.map((row) => {
              return (
                <Fragment key={row.id}>
                  <Tr>
                    {/* first row is a normal row */}
                    {row.getVisibleCells().map((cell) => {
                      return (
                        <Td key={cell.id}>
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </Td>
                      );
                    })}
                  </Tr>
                  {row.getIsExpanded() && (
                    <Tr>
                      {/* 2nd row is a custom 1 cell row */}
                      <Td colSpan={row.getVisibleCells().length}>
                        {renderSubComponent({ row })}
                      </Td>
                    </Tr>
                  )}
                </Fragment>
              );
            })}
          </Tbody>
        </ChakraTable>
      </TableContainer>
    </VStack>
  );
};
