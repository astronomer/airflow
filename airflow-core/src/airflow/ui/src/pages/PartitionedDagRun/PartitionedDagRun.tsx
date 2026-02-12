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
import { Box } from "@chakra-ui/react";
import { ReactFlow, Controls, Background } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useTranslation } from "react-i18next";
import { FiDatabase } from "react-icons/fi";
import { MdDetails } from "react-icons/md";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { Outlet, useParams } from "react-router-dom";

import { usePartitionedDagRunServiceGetPartitionedDagRun } from "openapi/queries";
import type { PartitionedDagRunAssetResponse } from "openapi/requests/types.gen";
import { ErrorAlert } from "src/components/ErrorAlert";
import { edgeTypes, nodeTypes } from "src/components/Graph/graphTypes";
import { useGraphLayout } from "src/components/Graph/useGraphLayout";
import { ProgressBar } from "src/components/ui";
import { useColorMode } from "src/context/colorMode";
import { NavTabs } from "src/layouts/Details/NavTabs";
import { useDependencyGraph } from "src/queries/useDependencyGraph";
import { getReactFlowThemeStyle } from "src/theme";

import { Header } from "./Header";

export const PartitionedDagRun = () => {
  const { t: translate } = useTranslation(["common", "dag"]);
  const { colorMode = "light" } = useColorMode();
  const { dagId = "", partitionKey = "" } = useParams();

  const { data, error, isLoading } = usePartitionedDagRunServiceGetPartitionedDagRun({
    dagId,
    partitionKey,
  });

  const assets: Array<PartitionedDagRunAssetResponse> = data?.assets ?? [];

  // IDs of received assets to highlight in the graph
  const receivedIds = new Set(
    assets
      .filter((ak: PartitionedDagRunAssetResponse) => ak.received)
      .map((ak: PartitionedDagRunAssetResponse) => `asset:${String(ak.asset_id)}`),
  );

  // Dependency graph for the DAG
  const { data: depData = { edges: [], nodes: [] } } = useDependencyGraph(`dag:${dagId}`);
  const { data: graphData } = useGraphLayout({
    ...depData,
    direction: "RIGHT",
    openGroupIds: [],
  });

  const nodes = graphData?.nodes.map((node) => ({
    ...node,
    data: { ...node.data, isSelected: receivedIds.has(node.id) },
  }));

  const tabs = [
    { icon: <FiDatabase />, label: translate("asset_other"), value: "." },
    { icon: <MdDetails />, label: translate("dag:tabs.details"), value: "details" },
  ];

  return (
    <Box flex={1} minH={0}>
      <ProgressBar size="xs" visibility={isLoading ? "visible" : "hidden"} />
      <ErrorAlert error={error} />
      <PanelGroup direction="horizontal" style={{ height: "100%" }}>
        <Panel defaultSize={30} id="expression-panel" minSize={15} order={1}>
          <Box height="100%" position="relative">
            <ReactFlow
              colorMode={colorMode}
              defaultEdgeOptions={{ zIndex: 1 }}
              edges={graphData?.edges ?? []}
              edgeTypes={edgeTypes}
              fitView
              maxZoom={1.5}
              minZoom={0.25}
              nodes={nodes}
              nodesDraggable={false}
              nodeTypes={nodeTypes}
              onlyRenderVisibleElements
              style={getReactFlowThemeStyle(colorMode)}
            >
              <Background />
              <Controls showInteractive={false} />
            </ReactFlow>
          </Box>
        </Panel>
        <PanelResizeHandle className="resize-handle">
          <Box bg="border.emphasized" cursor="col-resize" h="100%" w={0.5} />
        </PanelResizeHandle>
        <Panel defaultSize={70} id="details-panel" minSize={30} order={2}>
          <Box display="flex" flexDirection="column" h="100%">
            {data === undefined ? undefined : <Header data={data} />}
            <NavTabs tabs={tabs} />
            <Box flexGrow={1} overflow="auto" px={2}>
              <Outlet />
            </Box>
          </Box>
        </Panel>
      </PanelGroup>
    </Box>
  );
};
