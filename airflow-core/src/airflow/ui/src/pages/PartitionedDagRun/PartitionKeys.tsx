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
import { Badge, Link } from "@chakra-ui/react";
import type { ColumnDef } from "@tanstack/react-table";
import { useTranslation } from "react-i18next";
import { Link as RouterLink, useParams } from "react-router-dom";

import { usePartitionedDagRunServiceGetPartitionedDagRun } from "openapi/queries";
import type { PartitionedDagRunAssetResponse } from "openapi/requests/types.gen";
import { DataTable } from "src/components/DataTable";

const getColumns = (translate: (key: string) => string): Array<ColumnDef<PartitionedDagRunAssetResponse>> => [
  {
    accessorKey: "asset_name",
    cell: ({ row }) => (
      <Link asChild color="fg.info" fontWeight="bold">
        <RouterLink to={`/assets/${row.original.asset_id}`}>{row.original.asset_name}</RouterLink>
      </Link>
    ),
    enableSorting: false,
    header: translate("assets:name"),
  },
  {
    accessorKey: "asset_uri",
    enableSorting: false,
    header: translate("dashboard:uri"),
  },
  {
    accessorKey: "received",
    cell: ({ row }) => (
      <Badge colorPalette={row.original.received ? "green" : "gray"}>
        {row.original.received ? "Received" : "Waiting"}
      </Badge>
    ),
    enableSorting: false,
    header: translate("state"),
  },
];

export const PartitionKeys = () => {
  const { t: translate } = useTranslation("common");
  const { dagId = "", partitionKey = "" } = useParams();

  const { data, isFetching, isLoading } = usePartitionedDagRunServiceGetPartitionedDagRun({
    dagId,
    partitionKey,
  });

  const assets = data?.assets ?? [];

  const columns = getColumns(translate);

  return (
    <DataTable
      columns={columns}
      data={assets}
      isFetching={isFetching}
      isLoading={isLoading}
      modelName="common:asset"
      total={assets.length}
    />
  );
};
