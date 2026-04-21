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

/* eslint-disable i18next/no-literal-string --
   POC: strings will be localized before any real PR. */
import { Flex, Link, Spinner, Text } from "@chakra-ui/react";
import { useMemo } from "react";
import { Link as RouterLink } from "react-router-dom";

import type { TaskInstanceResponse } from "openapi/requests/types.gen";
import { useLogs } from "src/queries/useLogs";
import { getTaskInstanceLink } from "src/utils/links";
import { parseStreamingLogContent } from "src/utils/logs";

import { extractException } from "./extractException";

type Props = {
  readonly taskInstance: TaskInstanceResponse;
  readonly truncated?: boolean;
};

export const TaskFailureLine = ({ taskInstance, truncated = true }: Props) => {
  const { fetchedData, isLoading } = useLogs(
    {
      dagId: taskInstance.dag_id,
      taskInstance,
      tryNumber: taskInstance.try_number,
    },
    { refetchInterval: false, retry: false },
  );

  const extracted = useMemo(() => extractException(parseStreamingLogContent(fetchedData)), [fetchedData]);

  // The Task Instance Logs view is the index route under /tasks/{task_id},
  // so getTaskInstanceLink (no /logs suffix) lands directly on it.
  const taskLogsHref = getTaskInstanceLink(taskInstance);

  return (
    <Flex align="baseline" fontFamily="mono" fontSize="xs" gap={2} minW={0}>
      <Link _hover={{ color: "fg", textDecoration: "underline" }} asChild color="fg.info" flexShrink={0}>
        <RouterLink to={taskLogsHref}>{taskInstance.task_id}</RouterLink>
      </Link>
      {isLoading ? (
        <Flex align="center" gap={1}>
          <Spinner size="xs" />
          <Text color="fg.muted">reading log…</Text>
        </Flex>
      ) : extracted ? (
        <Flex
          align="baseline"
          gap={1}
          minW={0}
          overflow="hidden"
          whiteSpace={truncated ? "nowrap" : "normal"}
          wordBreak="break-word"
        >
          <Text as="span" color="red.fg" flexShrink={0} fontWeight="bold">
            {extracted.exceptionClass}:
          </Text>
          <Text
            as="span"
            color="fg"
            minW={0}
            overflow={truncated ? "hidden" : "visible"}
            textOverflow={truncated ? "ellipsis" : "clip"}
            whiteSpace={truncated ? "nowrap" : "normal"}
          >
            {extracted.message}
          </Text>
        </Flex>
      ) : (
        <Text color="fg.muted" fontStyle="italic">
          (no exception detected)
        </Text>
      )}
    </Flex>
  );
};
