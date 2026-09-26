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
import { Badge, Text } from "@chakra-ui/react";
import type { ColumnDef } from "@tanstack/react-table";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { useDagRunServiceGetDagRun, useDagRunStateStoreServiceListDagRunStateStore } from "openapi/queries";
import type { DagRunStateStoreResponse } from "openapi/requests";

import { DataTable } from "src/components/DataTable";
import { useTableURLState } from "src/components/DataTable/useTableUrlState";
import { ErrorAlert } from "src/components/ErrorAlert";
import { StoreValueCell } from "src/components/StoreValueCell";
import Time from "src/components/Time";

import { isStatePending, useAutoRefresh } from "src/utils";

const getColumns = (translate: (key: string) => string): Array<ColumnDef<DagRunStateStoreResponse>> => [
  {
    accessorKey: "key",
    cell: ({ row: { original } }) => <Text>{original.key}</Text>,
    header: translate("common:key"),
  },
  {
    accessorKey: "value",
    cell: ({ row: { original } }) => <StoreValueCell value={original.value} />,
    enableSorting: false,
    header: translate("common:value"),
  },
  {
    accessorKey: "updated_at",
    cell: ({ row: { original } }) => <Time datetime={original.updated_at} />,
    header: translate("common:table.updatedAt"),
  },
  {
    accessorKey: "expires_at",
    cell: ({ row: { original } }) =>
      Boolean(original.expires_at) ? (
        <Time datetime={original.expires_at} />
      ) : (
        <Badge colorPalette="gray" variant="subtle">
          {translate("dagRunStateStore.expiresAt.never")}
        </Badge>
      ),
    header: translate("dagRunStateStore.expiresAt.column"),
  },
];

export const DagRunStateStore = () => {
  const { dagId = "", runId = "" } = useParams();
  const refetchInterval = useAutoRefresh({ dagId });

  const { data: dagRun } = useDagRunServiceGetDagRun({ dagId, dagRunId: runId });

  const { t: translate } = useTranslation(["dag", "common"]);
  const { setTableURLState, tableURLState } = useTableURLState();
  const { pagination } = tableURLState;

  const { data, error, isFetching, isLoading } = useDagRunStateStoreServiceListDagRunStateStore(
    {
      dagId,
      dagRunId: runId,
      limit: pagination.pageSize,
      offset: pagination.pageIndex * pagination.pageSize,
    },
    undefined,
    { refetchInterval: isStatePending(dagRun?.state) ? refetchInterval : false },
  );

  return (
    <>
      <ErrorAlert error={error} />
      <DataTable
        columns={getColumns(translate)}
        data={data?.dag_run_state_store ?? []}
        displayMode="table"
        hideRowCountHeading
        initialState={tableURLState}
        isFetching={isFetching}
        isLoading={isLoading}
        modelName="dag:dagRunStateStore.entry"
        noRowsMessage={translate("dagRunStateStore.emptyStore")}
        onStateChange={setTableURLState}
        total={data?.total_entries ?? 0}
      />
    </>
  );
};
