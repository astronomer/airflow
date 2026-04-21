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
import { Box, Flex, Heading, VStack } from "@chakra-ui/react";
import dayjs from "dayjs";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PiBooks } from "react-icons/pi";

import { useDashboardServiceHistoricalMetrics } from "openapi/queries";
import { ErrorAlert } from "src/components/ErrorAlert";
import TimeRangeSelector from "src/components/TimeRangeSelector";
import { useAutoRefresh } from "src/utils";

import { DagRunMetrics } from "./DagRunMetrics";
import { MetricSectionSkeleton } from "./MetricSectionSkeleton";

const defaultHour = "24";

export const HistoricalMetrics = () => {
  const { t: translate } = useTranslation("dashboard");
  const now = dayjs();
  const [startDate, setStartDate] = useState(now.subtract(Number(defaultHour), "hour").toISOString());
  const [endDate, setEndDate] = useState(now.toISOString());

  const refetchInterval = useAutoRefresh({ checkPendingRuns: true });

  const { data, error, isLoading } = useDashboardServiceHistoricalMetrics(
    {
      startDate,
    },
    undefined,
    {
      refetchInterval,
    },
  );

  return (
    <Box width="100%">
      <Flex color="fg.muted" my={2}>
        <PiBooks />
        <Heading ml={1} size="xs">
          {translate("history")}
        </Heading>
      </Flex>
      <ErrorAlert error={error} />
      <VStack alignItems="left" gap={2}>
        <TimeRangeSelector
          defaultValue={defaultHour}
          endDate={endDate}
          setEndDate={setEndDate}
          setStartDate={setStartDate}
          startDate={startDate}
        />
        {isLoading ? <MetricSectionSkeleton /> : undefined}
        {!isLoading && data !== undefined ? (
          <DagRunMetrics
            dagRunStates={data.dag_run_states}
            startDate={startDate}
            stateCountLimit={data.state_count_limit}
          />
        ) : undefined}
      </VStack>
    </Box>
  );
};
