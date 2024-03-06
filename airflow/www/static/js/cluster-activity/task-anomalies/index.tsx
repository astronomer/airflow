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

import React, { useState, useEffect } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  Flex,
  Heading,
  Table,
  Thead,
  Tr,
  Th,
  Tbody,
  Td,
  Box,
  Tooltip,
} from "@chakra-ui/react";
import InfoTooltip from "src/components/InfoTooltip";
import FilterBar from "src/cluster-activity/nav/FilterBar";
import useFilters from "src/cluster-activity/useFilters";
import { useTaskAnomaliesData } from "src/api";
import LoadingWrapper from "src/components/LoadingWrapper";

const mockTaskAnomalies = [
  {
    taskId: "task_0",
    period: "Last Month",
    duration: 960,
    deviation: "1.8 SDs",
    median: 850,
  },
  {
    taskId: "task_1",
    period: "Last Month",
    duration: 1200,
    deviation: "2.0 SDs",
    median: 1150,
  },
  {
    taskId: "task_2",
    period: "Last Week",
    duration: 300,
    deviation: "1.5 SDs",
    median: 250,
  },
];

const TaskAnomalies = () => {
  const {
    filters: { startDate, endDate },
  } = useFilters();
  const { data: fetchedData, isError } = useTaskAnomaliesData(
    startDate,
    endDate
  );

  const [data, setData] = useState([]);

  useEffect(() => {
    setData(mockTaskAnomalies);
  }, [fetchedData]);

  return (
    <Flex w="100%">
      <Card w="100%">
        <CardHeader>
          <Flex alignItems="center">
            <Heading size="md">Task Anomalies</Heading>
            <InfoTooltip
              label="Based on historical data. You can adjust the period by setting a different start and end date filter."
              size={18}
            />
          </Flex>
        </CardHeader>
        <CardBody>
          <FilterBar />
          <Flex direction="column" minH="200px" alignItems="center">
            <LoadingWrapper hasData={!!data} isError={isError}>
              <Box w="100%">
                <Table variant="striped">
                  <Thead>
                    <Tr>
                      <Th>Task ID</Th>
                      <Th>Period</Th>
                      <Th>Duration (s)</Th>
                      <Th>Median (s)</Th>
                      <Th>Deviation</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {data &&
                      data.map((d) => (
                        <Tr key={d.taskId}>
                          <Td>
                            <Tooltip label="Unique identifier for the task">
                              <span>{d.taskId}</span>
                            </Tooltip>
                          </Td>
                          <Td>
                            <Tooltip label="Time frame of the anomaly (e.g., Last Month, Last Week)">
                              <span>{d.period}</span>
                            </Tooltip>
                          </Td>
                          <Td>
                            <Tooltip label="Actual time taken for the task to complete in seconds">
                              <span>{d.duration}</span>
                            </Tooltip>
                          </Td>
                          <Td>
                            <Tooltip label="Typical time taken for task completion based on historical data, in seconds">
                              <span>{d.median}</span>
                            </Tooltip>
                          </Td>
                          <Td>
                            <Tooltip
                              label={`Deviation from the median time, indicating the significance of the anomaly (${d.deviation})`}
                            >
                              <span>{d.deviation}</span>
                            </Tooltip>
                          </Td>
                        </Tr>
                      ))}
                  </Tbody>
                </Table>
              </Box>
            </LoadingWrapper>
          </Flex>
        </CardBody>
      </Card>
    </Flex>
  );
};

export default TaskAnomalies;
