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
import { Flex, Heading, VStack } from "@chakra-ui/react";
import { useState } from "react";
import { CgRedo } from "react-icons/cg";

import { ActionAccordion } from "src/components/ActionAccordion";
import type { TaskActionProps } from "src/components/MarkAs/utils";
import Time from "src/components/Time";
import { Button, Dialog } from "src/components/ui";
import SegmentedControl from "src/components/ui/SegmentedControl";
import { useClearTaskInstances } from "src/queries/useClearTaskInstances";
import { useClearTaskInstancesDryRun } from "src/queries/useClearTaskInstancesDryRun";
import { usePatchTaskInstance } from "src/queries/usePatchTaskInstance";

type Props = {
  readonly onClose: () => void;
  readonly open: boolean;
  readonly taskActionProps: TaskActionProps;
};

export const ClearTaskInstanceDialog = ({
  onClose,
  open,
  taskActionProps: {
    dagId,
    dagRunId,
    logicalDate,
    mapIndex = -1,
    note: taskNote,
    startDate,
    taskDisplayName,
    taskId,
  },
}: Props) => {
  const { isPending, mutate } = useClearTaskInstances({
    dagId,
    dagRunId,
    onSuccessConfirm: onClose,
  });

  const [selectedOptions, setSelectedOptions] = useState<Array<string>>([]);

  const onlyFailed = selectedOptions.includes("onlyFailed");
  const past = selectedOptions.includes("past");
  const future = selectedOptions.includes("future");
  const upstream = selectedOptions.includes("upstream");
  const downstream = selectedOptions.includes("downstream");

  // eslint-disable-next-line unicorn/no-null
  const [note, setNote] = useState<string | null>(taskNote ?? null);
  const { isPending: isPendingPatchDagRun, mutate: mutatePatchTaskInstance } = usePatchTaskInstance({
    dagId,
    dagRunId,
    mapIndex,
    taskId,
  });

  const { data } = useClearTaskInstancesDryRun({
    dagId,
    options: {
      enabled: open,
    },
    requestBody: {
      dag_run_id: dagRunId,
      include_downstream: downstream,
      include_future: future,
      include_past: past,
      include_upstream: upstream,
      only_failed: onlyFailed,
      task_ids: [taskId],
    },
  });

  const affectedTasks = data ?? {
    task_instances: [],
    total_entries: 0,
  };

  return (
    <Dialog.Root lazyMount onOpenChange={onClose} open={open} size="xl">
      <Dialog.Content backdrop>
        <Dialog.Header>
          <VStack align="start" gap={4}>
            <Heading size="xl">
              <strong>Clear Task Instance:</strong> {taskDisplayName ?? taskId} <Time datetime={startDate} />
            </Heading>
          </VStack>
        </Dialog.Header>

        <Dialog.CloseTrigger />

        <Dialog.Body width="full">
          <Flex justifyContent="center">
            <SegmentedControl
              multiple
              onChange={setSelectedOptions}
              options={[
                { disabled: !Boolean(logicalDate), label: "Past", value: "past" },
                { disabled: !Boolean(logicalDate), label: "Future", value: "future" },
                { label: "Upstream", value: "upstream" },
                { label: "Downstream", value: "downstream" },
                { label: "Only Failed", value: "onlyFailed" },
              ]}
            />
          </Flex>
          <ActionAccordion
            affectedTasks={affectedTasks}
            note={taskNote === undefined ? undefined : note}
            setNote={setNote}
          />
          <Flex justifyContent="end" mt={3}>
            <Button
              colorPalette="blue"
              disabled={affectedTasks.total_entries === 0}
              loading={isPending || isPendingPatchDagRun}
              onClick={() => {
                mutate({
                  dagId,
                  requestBody: {
                    dag_run_id: dagRunId,
                    dry_run: false,
                    include_downstream: downstream,
                    include_future: future,
                    include_past: past,
                    include_upstream: upstream,
                    only_failed: onlyFailed,
                    task_ids: [taskId],
                  },
                });
                if (taskNote !== undefined && note !== taskNote) {
                  mutatePatchTaskInstance({
                    dagId,
                    dagRunId,
                    mapIndex,
                    requestBody: { note },
                    taskId,
                  });
                }
              }}
            >
              <CgRedo /> Confirm
            </Button>
          </Flex>
        </Dialog.Body>
      </Dialog.Content>
    </Dialog.Root>
  );
};
