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

import React, { useState } from 'react';
import { Box, Code, Heading } from '@chakra-ui/react';
import { snakeCase } from 'lodash';
import type {
  ColumnDef, PaginationState, SortingState,
} from '@tanstack/react-table';

import { useDatasets } from 'src/api';
import Time from 'src/components/Time';
import NewTable from 'src/components/NewTable';
import type { Dataset } from 'src/types';

interface Info {
  getValue: <TTValue = unknown>() => TTValue;
}

const CodeCell = ({ getValue }: Info) => <Code>{getValue()}</Code>;
const TimeCell = ({ getValue }: Info) => <Time dateTime={getValue()} />;

const DatasetsList = () => {
  const limit = 25;
  const [pagination, setPagination] = useState<PaginationState>(
    {
      pageIndex: 0,
      pageSize: limit,
    },
  );
  const [sorting, setSorting] = useState<SortingState>([]);

  const sort = sorting[0];
  const order = sort ? `${sort.desc ? '-' : ''}${snakeCase(sort.id)}` : '';

  const offset = Math.ceil(pagination.pageIndex) * limit;
  const { data: { datasets, totalEntries } } = useDatasets({
    offset, limit, order,
  });

  const columns: ColumnDef<Dataset>[] = [
    {
      header: 'URI',
      accessorKey: 'uri',
      cell: (info) => info.getValue(),
    },
    {
      header: 'Extra',
      accessorKey: 'extra',
      cell: CodeCell,
      enableSorting: false,
    },
    {
      header: 'Created At',
      accessorKey: 'createdAt',
      cell: TimeCell,
    },
    {
      header: 'Updated At',
      accessorKey: 'updatedAt',
      cell: TimeCell,
    },
  ];

  return (
    <Box>
      <Heading mt={3} mb={2} fontWeight="normal">
        Datasets
      </Heading>
      <Box borderWidth={1}>
        <NewTable
          data={datasets}
          columns={columns}
          sort={{
            sorting,
            setSorting,
          }}
          pagination={{
            totalEntries,
            state: pagination,
            setPagination,
          }}
        />
      </Box>
    </Box>
  );
};

export default DatasetsList;
