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
import { useParams } from "react-router-dom";

import { useTaskStateStoreServiceGetTaskStateStore } from "openapi/queries";

import { useTaskInstanceCoordinates } from "src/hooks/useTaskInstanceCoordinates";
import { useTaskInstanceView } from "src/hooks/useTaskInstanceView";
import { isStatePending, useAutoRefresh } from "src/utils";

// Written by ResumableJobMixin in the Task SDK, straight to the metadata DB so a custom state
// backend cannot turn it into a reference this page has no way to resolve.
export const DURABLE_HISTORY_KEY = "__airflow_resumable_history__";

export type DurableTryRecord = {
  readonly decision: string;
  readonly external_id: unknown;
  readonly prior_status: string | null;
  readonly recorded_at: string;
  readonly time_not_rerun_seconds: number | null;
  readonly try_number: number | null;
};

export type DurableHistory = {
  readonly can_resume_failed_job: boolean;
  readonly external_id_key: string;
  readonly operator: string;
  readonly tries: Array<DurableTryRecord>;
};

const isDurableHistory = (value: unknown): value is DurableHistory =>
  typeof value === "object" && value !== null && Array.isArray((value as { tries?: unknown }).tries);

export const useDurableHistory = ({ enabled = true }: { readonly enabled?: boolean } = {}) => {
  const { dagId = "", mapIndex = "-1", runId = "", taskId = "" } = useParams();
  const coordinates = useTaskInstanceCoordinates();
  const { liveTaskInstance } = useTaskInstanceView();
  const refetchInterval = useAutoRefresh({ dagId });

  const { data } = useTaskStateStoreServiceGetTaskStateStore(
    {
      ...coordinates,
      dagId,
      dagRunId: runId,
      key: DURABLE_HISTORY_KEY,
      mapIndex: parseInt(mapIndex, 10),
      taskId,
    },
    undefined,
    {
      enabled: enabled && Boolean(dagId) && Boolean(runId) && Boolean(taskId),
      refetchInterval: isStatePending(liveTaskInstance?.state) && refetchInterval,
      // A missing key is the normal case for tasks that are not durable.
      retry: false,
    },
  );

  return isDurableHistory(data?.value) ? data.value : undefined;
};
