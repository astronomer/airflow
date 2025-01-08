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
import type { GridDAGRunwithTIs, NodeResponse } from "openapi/requests/types.gen";
import { useOpenGroups } from "src/context/openGroups";

import { TaskRow } from "./TaskRow";

type Props = {
  dagRuns: Array<GridDAGRunwithTIs>;
  depth?: number;
  nodes: Array<NodeResponse>;
};

export const TaskRows = ({ dagRuns, depth = 0, nodes }: Props) => {
  const { openGroupIds } = useOpenGroups();

  return nodes.map((node) =>
    node.type === "task" ? (
      <>
        <TaskRow
          dagRuns={dagRuns}
          depth={depth}
          isOpen={openGroupIds.includes(node.id)}
          key={node.id}
          task={node}
        />
        {node.children && openGroupIds.includes(node.id) ? (
          <TaskRows dagRuns={dagRuns} depth={depth + 1} key={`child-${node.id}`} nodes={node.children} />
        ) : undefined}
      </>
    ) : undefined,
  );
};
