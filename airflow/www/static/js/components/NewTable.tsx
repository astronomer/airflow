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

/*
 * Custom wrapper of react-table using Chakra UI components
*/

import React from 'react';
import {
  Flex,
  Table as ChakraTable,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  IconButton,
  Text,
} from '@chakra-ui/react';
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  OnChangeFn,
  PaginationState,
  SortingState,
  useReactTable,
} from '@tanstack/react-table';
import {
  MdKeyboardArrowLeft, MdKeyboardArrowRight,
} from 'react-icons/md';
import {
  TiArrowUnsorted, TiArrowSortedDown, TiArrowSortedUp,
} from 'react-icons/ti';

interface Props {
  columns: ColumnDef<any>[];
  data: any[];
  sort?: {
    sorting: SortingState;
    setSorting: OnChangeFn<SortingState>;
  };
  pagination?: {
    state: PaginationState;
    setPagination: OnChangeFn<PaginationState>;
    totalEntries: number;
  };
}

const Table = ({
  data,
  columns,
  sort,
  pagination,
}: Props) => {
  const table = useReactTable({
    data,
    columns,
    manualSorting: !!sort,
    manualPagination: !!pagination,
    pageCount: pagination ? pagination.totalEntries / pagination.state.pageSize : -1,
    state: {
      sorting: sort?.sorting,
      pagination: pagination?.state,
    },
    onPaginationChange: pagination?.setPagination,
    onSortingChange: sort?.setSorting,
    getSortedRowModel: getSortedRowModel(),
    getCoreRowModel: getCoreRowModel(),
  });

  const pageIndex = Math.ceil(pagination?.state.pageIndex ?? 0);
  const lowerCount = pageIndex * (pagination?.state.pageSize || 1) + 1;
  const upperCount = lowerCount + data.length - 1;

  return (
    <>
      <ChakraTable>
        <Thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <Tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <Th key={header.id}>
                  {header.isPlaceholder ? null : (
                    <Flex
                      onClick={header.column.getToggleSortingHandler()}
                      cursor={header.column.getCanSort() ? 'pointer' : undefined}
                    >
                      {flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )}
                      {header.column.getCanSort()
                        && ({
                          asc: <TiArrowSortedUp />,
                          desc: <TiArrowSortedDown />,
                        }[header.column.getIsSorted() as string] ?? <TiArrowUnsorted />)}
                    </Flex>
                  )}
                </Th>
              ))}
            </Tr>
          ))}
        </Thead>
        <Tbody>
          {table.getRowModel().rows.map((row) => (
            <Tr key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <Td key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </Td>
              ))}
            </Tr>
          ))}
        </Tbody>
      </ChakraTable>
      {(table.getCanPreviousPage() || table.getCanNextPage()) && (
        <Flex alignItems="center" justifyContent="flex-start" my={4}>
          <IconButton
            variant="ghost"
            onClick={table.previousPage}
            disabled={!table.getCanPreviousPage()}
            aria-label="Previous Page"
            title="Previous Page"
            icon={<MdKeyboardArrowLeft />}
          />
          <IconButton
            variant="ghost"
            onClick={table.nextPage}
            disabled={!table.getCanNextPage}
            aria-label="Next Page"
            title="Next Page"
            icon={<MdKeyboardArrowRight />}
          />
          {!!pagination && (
            <Text>
              {lowerCount}
              -
              {upperCount}
              {' of '}
              {pagination.totalEntries}
            </Text>
          )}
        </Flex>
      )}
    </>
  );
};

export default Table;
