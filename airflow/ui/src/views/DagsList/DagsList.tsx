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

import { ColumnDef } from "@tanstack/react-table";
import { useSearchParams } from "react-router-dom";
import { Badge, HStack, VStack } from "@chakra-ui/react";

import { DAG } from "openapi/requests/types.gen";
import { useDagServiceGetDags } from "openapi/queries";
import { DataTable } from "../../components/DataTable";
import { useTableURLState } from "../../components/DataTable/useTableUrlState";
import { PauseToggle } from "../../components/PauseToggle";
import { QuickFilters } from "./QuickFilters";
import { SearchBar } from "./SearchBar";

const columns: ColumnDef<DAG>[] = [
  {
    accessorKey: "is_paused",
    header: "",
    enableSorting: false,
    cell: ({ row }) => (
      <PauseToggle
        dagId={row.original.dag_id!}
        isPaused={row.original.is_paused!}
      />
    ),
  },
  {
    accessorKey: "dag_id",
    header: "DAG",
    cell: ({ row }) => row.original.dag_display_name,
  },
  {
    accessorKey: "timetable_summary",
    header: "Schedule",
    cell: (info) => (info.getValue() === "None" ? undefined : info.getValue()),
    enableSorting: false,
  },
  {
    accessorKey: "next_dagrun",
    header: "Next DAG Run",
    enableSorting: false,
  },
  {
    accessorKey: "tags",
    header: "Tags",
    cell: ({ row }) => (
      <HStack>
        {row.original.tags?.map((tag) => (
          <Badge key={tag.name}>{tag.name}</Badge>
        ))}
      </HStack>
    ),
    enableSorting: false,
  },
];

const PAUSED_PARAM = "paused";

export const DagsList = () => {
  const [searchParams] = useSearchParams();

  const showPaused = searchParams.get(PAUSED_PARAM) === "true";

  const { tableURLState, setTableURLState } = useTableURLState();
  const { sorting, pagination } = tableURLState;

  // TODO: update API to accept multiple orderBy params
  const sort = sorting[0];
  const orderBy = sort ? `${sort.desc ? "-" : ""}${sort.id}` : undefined;

  const { data, isLoading } = useDagServiceGetDags({
    limit: pagination.pageSize,
    offset: pagination.pageIndex * pagination.pageSize,
    onlyActive: true,
    paused: showPaused === true ? undefined : false, // undefined returns all dags
    orderBy,
  });

  return (
    <>
      <VStack alignItems="none">
        <SearchBar
          inputProps={{ isDisabled: true }}
          buttonProps={{ isDisabled: true }}
        />
        <HStack justifyContent="space-between">
          <QuickFilters isLoading={isLoading} />
        </HStack>
      </VStack>
      <DataTable
        data={data?.dags || []}
        total={data?.total_entries || 0}
        columns={columns}
        initialState={tableURLState}
        onStateChange={setTableURLState}
        isLoading={isLoading}
        title="DAG"
      />
    </>
  );
};
