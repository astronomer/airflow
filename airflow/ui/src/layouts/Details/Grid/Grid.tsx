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
import { Table, Box } from "@chakra-ui/react";
import { useParams } from "react-router-dom";

import { useGridServiceGridData, useStructureServiceStructureData } from "openapi/queries";

import { DagRunHeader } from "./DagRunHeader/DagRunHeader";
import { TaskRows } from "./TaskRows";

export const Grid = () => {
  const { dagId = "" } = useParams();
  const { data: structure } = useStructureServiceStructureData({
    dagId,
  });

  const nodes = structure?.nodes ?? [];

  const { data: gridData } = useGridServiceGridData({
    dagId,
    limit: 25,
    offset: 0,
    orderBy: "-start_date",
  });

  return (
    <Box
      height="100%"
      mt={8}
      overflow="auto"
      overscrollBehavior="auto"
      pb={4}
      position="relative"
      width="100%"
    >
      <Table.Root borderColor="transparent" borderRightWidth="16px">
        <Table.Header>
          <DagRunHeader dagRuns={gridData?.dag_runs ?? []} />
        </Table.Header>
        <Table.Body>
          <TaskRows dagRuns={gridData?.dag_runs ?? []} nodes={nodes} />
        </Table.Body>
      </Table.Root>
    </Box>
  );
};
