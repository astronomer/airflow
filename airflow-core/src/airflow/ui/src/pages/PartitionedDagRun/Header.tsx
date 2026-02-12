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
import { Box, Link } from "@chakra-ui/react";
import { useTranslation } from "react-i18next";
import { FiDatabase } from "react-icons/fi";
import { Link as RouterLink } from "react-router-dom";

import type { PartitionedDagRunDetailResponse } from "openapi/requests/types.gen";
import { HeaderCard } from "src/components/HeaderCard";
import Time from "src/components/Time";

type Props = {
  readonly data: PartitionedDagRunDetailResponse;
};

export const Header = ({ data }: Props) => {
  const { t: translate } = useTranslation("common");

  const {
    created_at: createdAt,
    created_dag_run_id: createdDagRunId,
    dag_id: dagId,
    partition_key: partitionKey,
    updated_at: updatedAt,
  } = data;

  const status = createdDagRunId === null ? "pending" : "fulfilled";

  return (
    <Box>
      <HeaderCard
        icon={<FiDatabase />}
        stats={[
          {
            label: translate("dagRun.partitionKey"),
            value: partitionKey,
          },
          {
            label: translate("dagId"),
            value: (
              <Link asChild color="fg.info">
                <RouterLink to={`/dags/${dagId}`}>{dagId}</RouterLink>
              </Link>
            ),
          },
          {
            label: translate("table.createdAt"),
            value: <Time datetime={createdAt} />,
          },
          ...(updatedAt === null
            ? []
            : [
                {
                  label: translate("partitionedDagRunDetail.updatedAt"),
                  value: <Time datetime={updatedAt} />,
                },
              ]),
          {
            label: translate("state"),
            value: status,
          },
        ]}
        title={`${dagId} #${partitionKey}`}
      />
    </Box>
  );
};
