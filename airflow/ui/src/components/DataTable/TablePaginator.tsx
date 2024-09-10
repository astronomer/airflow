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

import { Table as TanStackTable } from "@tanstack/react-table";
import { Box, Button, ButtonProps } from "@chakra-ui/react";
import { FiChevronLeft, FiChevronRight } from "react-icons/fi";

type PaginatorProps<TData> = {
  table: TanStackTable<TData>;
};

const PageButton = (props: ButtonProps) => (
  <Button {...props} size="sm" colorScheme="blue" variant="ghost" />
);

export const TablePaginator = <TData,>({ table }: PaginatorProps<TData>) => {
  const currentPageNumber = table.getState().pagination.pageIndex + 1;
  const lastPageNumber = table.getPageCount();

  if (table.getPageCount() <= 1) return null;
  return (
    <Box>
      <PageButton
        onClick={() => table.previousPage()}
        isDisabled={!table.getCanPreviousPage()}
        data-testid="previous-page"
      >
        <FiChevronLeft size="1.25rem" />
      </PageButton>
      <PageButton
        onClick={() => table.firstPage()}
        isActive={currentPageNumber === 1}
        data-testid="first-page"
      >
        {1}
      </PageButton>
      {currentPageNumber - 1 > 2 && (
        <PageButton isDisabled minW={0} px={1} data-testid="ellipsis">
          ...
        </PageButton>
      )}
      {currentPageNumber - 1 === 2 && (
        <PageButton
          onClick={() => table.setPageIndex(currentPageNumber - 2)}
          data-testid="second-page"
        >
          {currentPageNumber - 1}
        </PageButton>
      )}
      {currentPageNumber !== 1 && currentPageNumber !== lastPageNumber && (
        <PageButton isActive data-testid="middle-page">
          {currentPageNumber}
        </PageButton>
      )}
      {lastPageNumber - currentPageNumber > 2 && (
        <PageButton isDisabled minW={0} px={1} data-testid="ellipsis">
          ...
        </PageButton>
      )}
      {lastPageNumber - currentPageNumber === 2 && (
        <PageButton
          onClick={() => table.setPageIndex(lastPageNumber - 2)}
          data-testid="second-last-page"
        >
          {lastPageNumber - 1}
        </PageButton>
      )}
      <PageButton
        onClick={() => table.lastPage()}
        isActive={currentPageNumber === lastPageNumber}
        data-testid="last-page"
      >
        {lastPageNumber}
      </PageButton>
      <PageButton
        onClick={() => table.nextPage()}
        isDisabled={!table.getCanNextPage()}
        data-testid="next-page"
      >
        <FiChevronRight size="1.25rem" />
      </PageButton>
    </Box>
  );
};
