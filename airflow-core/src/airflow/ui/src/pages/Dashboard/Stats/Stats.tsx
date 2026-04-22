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
import { Flex } from "@chakra-ui/react";

import {
  useImportErrorServiceGetImportErrors,
  usePluginServiceImportErrors,
  useTaskInstanceServiceGetHitlDetails,
} from "openapi/queries";
import { NeedsReviewButton } from "src/components/NeedsReviewButton";
import { useAutoRefresh } from "src/utils";

import { DAGImportErrors } from "./DAGImportErrors";
import { PluginImportErrors } from "./PluginImportErrors";

export const Stats = () => {
  const refetchInterval = useAutoRefresh({ checkPendingRuns: true });
  const { data: hitlData } = useTaskInstanceServiceGetHitlDetails(
    { dagId: "~", dagRunId: "~", responseReceived: false, state: ["deferred"] },
    undefined,
    { refetchInterval },
  );
  const { data: dagImportErrorsData } = useImportErrorServiceGetImportErrors({ limit: 1 });
  const { data: pluginImportErrorsData } = usePluginServiceImportErrors();

  const hitlCount = hitlData?.hitl_details.length ?? 0;
  const dagImportErrorsCount = dagImportErrorsData?.total_entries ?? 0;
  const pluginImportErrorsCount = pluginImportErrorsData?.total_entries ?? 0;

  if (hitlCount === 0 && dagImportErrorsCount === 0 && pluginImportErrorsCount === 0) {
    return undefined;
  }

  return (
    <Flex flexWrap="wrap" gap={4}>
      <NeedsReviewButton />
      <DAGImportErrors />
      <PluginImportErrors />
    </Flex>
  );
};
