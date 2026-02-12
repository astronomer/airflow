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
import { Link, Text } from "@chakra-ui/react";
import type { ColumnDef } from "@tanstack/react-table";
import { useTranslation } from "react-i18next";
import { Link as RouterLink } from "react-router-dom";

import { usePartitionedDagRunServiceGetPartitionedDagRuns } from "openapi/queries";
import type { DagRunState, PartitionedDagRunResponse } from "openapi/requests/types.gen";
import { AssetProgressCell } from "src/components/AssetProgressCell";
import { DataTable } from "src/components/DataTable";
import { ErrorAlert } from "src/components/ErrorAlert";
import { StateBadge } from "src/components/StateBadge";
import Time from "src/components/Time";
import { TruncatedText } from "src/components/TruncatedText";

const getColumns = (
  translate: (key: string, options?: Record<string, unknown>) => string,
): Array<ColumnDef<PartitionedDagRunResponse>> => [
  {
    accessorKey: "partition_key",
    cell: ({ row }) => (
      <Link asChild color="fg.info" fontWeight="bold">
        <RouterLink
          to={`/partitioned_dag_runs/${row.original.dag_id ?? ""}/${encodeURIComponent(row.original.partition_key)}`}
        >
          {row.original.partition_key}
        </RouterLink>
      </Link>
    ),
    enableSorting: false,
    header: translate("common:dagRun.partitionKey"),
  },
  {
    accessorKey: "dag_id",
    cell: ({ row }) => (
      <Link asChild color="fg.info">
        <RouterLink to={`/dags/${row.original.dag_id ?? ""}`}>{row.original.dag_id}</RouterLink>
      </Link>
    ),
    enableSorting: false,
    header: translate("common:dagId"),
  },
  {
    accessorKey: "created_dag_run_id",
    cell: ({ row }) => {
      const runId = row.original.created_dag_run_id;

      return runId !== null && runId !== undefined ? (
        <Link asChild color="fg.info" fontWeight="bold">
          <RouterLink to={`/dags/${row.original.dag_id ?? ""}/runs/${runId}`}>
            <TruncatedText text={runId} />
          </RouterLink>
        </Link>
      ) : undefined;
    },
    enableSorting: false,
    header: translate("common:runId"),
  },
  {
    accessorKey: "state",
    cell: ({ row }) => (
      <StateBadge state={row.original.state as DagRunState}>{row.original.state}</StateBadge>
    ),
    enableSorting: false,
    header: translate("common:state"),
  },
  {
    accessorKey: "created_at",
    cell: ({ row }) => (
      <Text>
        <Time datetime={row.original.created_at} />
      </Text>
    ),
    enableSorting: false,
    header: translate("common:table.createdAt"),
  },
  {
    accessorKey: "total_received",
    cell: ({ row }) => (
      <AssetProgressCell
        dagId={row.original.dag_id ?? ""}
        partitionKey={row.original.partition_key}
        totalReceived={row.original.total_received}
        totalRequired={row.original.total_required}
      />
    ),
    enableSorting: false,
    header: translate("partitionedDagRunDetail.receivedAssets"),
  },
];

export const PartitionedDagRuns = () => {
  const { t: translate } = useTranslation(["common", "dag"]);

  const { data, error, isFetching, isLoading } = usePartitionedDagRunServiceGetPartitionedDagRuns();

  const partitionedDagRuns = data?.partitioned_dag_runs ?? [];
  const total = data?.total ?? 0;
  const columns = getColumns(translate);

  return (
    <>
      <ErrorAlert error={error} />
      <DataTable
        columns={columns}
        data={partitionedDagRuns}
        isFetching={isFetching}
        isLoading={isLoading}
        modelName="partitionedDagRun"
        total={total}
      />
    </>
  );
};
