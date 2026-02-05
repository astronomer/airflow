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
import { HStack, Link, Table } from "@chakra-ui/react";
import { useTranslation } from "react-i18next";
import { Link as RouterLink, useParams } from "react-router-dom";

import { usePartitionedDagRunServiceGetPartitionedDagRun } from "openapi/queries";
import Time from "src/components/Time";
import { ClipboardRoot, ClipboardIconButton } from "src/components/ui";

export const Details = () => {
  const { t: translate } = useTranslation("common");
  const { dagId = "", partitionKey = "" } = useParams();

  const { data } = usePartitionedDagRunServiceGetPartitionedDagRun({
    dagId,
    partitionKey,
  });

  if (!data) {
    return undefined;
  }

  return (
    <Table.Root striped>
      <Table.Body>
        <Table.Row>
          <Table.Cell>{translate("dagRun.partitionKey")}</Table.Cell>
          <Table.Cell>{data.partition_key}</Table.Cell>
        </Table.Row>
        <Table.Row>
          <Table.Cell>{translate("partitionedDagRunDetail.id")}</Table.Cell>
          <Table.Cell>
            <HStack>
              {String(data.id)}
              <ClipboardRoot value={String(data.id)}>
                <ClipboardIconButton />
              </ClipboardRoot>
            </HStack>
          </Table.Cell>
        </Table.Row>
        <Table.Row>
          <Table.Cell>{translate("dagId")}</Table.Cell>
          <Table.Cell>
            <Link asChild color="fg.info">
              <RouterLink to={`/dags/${dagId}`}>{dagId}</RouterLink>
            </Link>
          </Table.Cell>
        </Table.Row>
        <Table.Row>
          <Table.Cell>{translate("table.createdAt")}</Table.Cell>
          <Table.Cell>
            <Time datetime={data.created_at} />
          </Table.Cell>
        </Table.Row>
        <Table.Row>
          <Table.Cell>{translate("partitionedDagRunDetail.updatedAt")}</Table.Cell>
          <Table.Cell>
            <Time datetime={data.updated_at} />
          </Table.Cell>
        </Table.Row>
        <Table.Row>
          <Table.Cell>{translate("state")}</Table.Cell>
          <Table.Cell>{data.created_dag_run_id === undefined ? "pending" : "fulfilled"}</Table.Cell>
        </Table.Row>
        {data.created_dag_run_id === undefined ? undefined : (
          <Table.Row>
            <Table.Cell>{translate("partitionedDagRunDetail.createdDagRunId")}</Table.Cell>
            <Table.Cell>
              <Link asChild color="fg.info">
                <RouterLink to={`/dags/${dagId}/runs/${data.created_dag_run_id}`}>
                  {data.created_dag_run_id}
                </RouterLink>
              </Link>
            </Table.Cell>
          </Table.Row>
        )}
        <Table.Row>
          <Table.Cell>{translate("partitionedDagRunDetail.totalRequiredAssets")}</Table.Cell>
          <Table.Cell>{String(data.total_required)}</Table.Cell>
        </Table.Row>
        <Table.Row>
          <Table.Cell>{translate("partitionedDagRunDetail.receivedAssets")}</Table.Cell>
          <Table.Cell>{String(data.total_received)}</Table.Cell>
        </Table.Row>
      </Table.Body>
    </Table.Root>
  );
};
