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

import React, { useEffect, useState } from 'react';
import { Box, Button } from '@chakra-ui/react';
import ELK from 'elkjs';
import { Zoom } from '@visx/zoom';

import useGraphData from '../api';

import Node from './Node';
import Edge from './Edge';

const generateGraph = ({ nodes, edges }) => ({
  id: 'root',
  layoutOptions: {
    'spacing.nodeNodeBetweenLayers': '40.0',
    'spacing.edgeNodeBetweenLayers': '10.0',
    'layering.strategy': 'INTERACTIVE',
    algorithm: 'layered',
    'spacing.edgeEdgeBetweenLayers': '10.0',
    'spacing.edgeNode': '10.0',
    'spacing.edgeEdge': '10.0',
    'spacing.nodeNode': '20.0',
  },
  children: nodes.children.map((n) => ({
    id: n.id,
    width: 125,
    height: 50,
  })),
  edges: edges.map((e) => ({ id: `${e.sourceId}-${e.targetId}`, sources: [e.sourceId], targets: [e.targetId] })),
});

const Nodes = ({
  data: {
    edges, children, height, width,
  },
}) => (
  <g height={height} width={width}>
    {edges.map((edge) => (
      <Edge key={edge.id} edge={edge} />
    ))}
    {children.map((node) => (node.children ? (
      <Node
        key={node.id}
        node={node}
      >
        <Nodes data={node} />
      </Node>
    ) : (
      <Node
        key={node.id}
        node={node}
      />
    )))}
  </g>
);

// const sampleGroupData = {
//   id: 'n0',
//   children: [
//     {
//       id: 'n1',
//       width: 125,
//       height: 50,
//     },
//     {
//       id: 'n2',
//       children: [
//         {
//           id: 'n2_1',
//           width: 125,
//           height: 50,
//         },
//         {
//           id: 'n2_2',
//           width: 125,
//           height: 50,
//           layoutOptions: {
//             'layering.layerChoiceConstraint': '0',
//           },
//         },
//       ],
//       layoutOptions: {
//         'elk.direction': 'RIGHT',
//         'layering.layerChoiceConstraint': '0',
//       },
//       edges: [
//         {
//           id: 'e1',
//           sources: [
//             'n2_1',
//           ],
//           targets: [
//             'n2_2',
//           ],
//         },
//       ],
//     },
//   ],
//   layoutOptions: {
//     'spacing.nodeNodeBetweenLayers': '40.0',
//     'spacing.edgeNodeBetweenLayers': '10.0',
//     'layering.strategy': 'INTERACTIVE',
//     algorithm: 'layered',
//     // mergeEdges: 'true',
//     'spacing.edgeEdgeBetweenLayers': '10.0',
//     'spacing.edgeNode': '10.0',
//     'spacing.edgeEdge': '10.0',
//     'spacing.nodeNode': '20.0',
//   },
//   edges: [
//     {
//       id: 'e0',
//       sources: [
//         'n1',
//       ],
//       targets: [
//         'n2',
//       ],
//     },
//   ],
// };

const Graph = () => {
  const [data, setData] = useState();
  const elk = new ELK();

  const { data: graphData } = useGraphData();

  useEffect(() => {
    if (graphData && graphData.nodes) {
      elk.layout(generateGraph(graphData))
        .then((g) => setData(g))
        .catch(console.error);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphData]);

  if (!data) return null;

  const initialTransform = {
    scaleX: 1,
    scaleY: 1,
    translateX: 0,
    translateY: 150,
    skewX: 0,
    skewY: 0,
  };
  const width = 1200;
  const height = 600;

  return (
    <Box position="relative" alignSelf="center" borderColor="gray.200" borderWidth={1}>
      <Zoom
        width={width}
        height={height}
        scaleXMin={1 / 4}
        scaleXMax={1}
        scaleYMin={1 / 4}
        scaleYMax={1}
        initialTransformMatrix={initialTransform}
      >
        {(zoom) => (
          <Box>
            <svg
              id="GRAPH"
              width={width}
              height={height}
              style={{ cursor: zoom.isDragging ? 'grabbing' : 'grab', touchAction: 'none' }}
              ref={zoom.containerRef}
            >
              <g transform={zoom.toString()}>
                <Nodes data={data} />
              </g>
              <rect
                width={width}
                height={height}
                rx={14}
                fill="transparent"
                onTouchStart={zoom.dragStart}
                onTouchMove={zoom.dragMove}
                onTouchEnd={zoom.dragEnd}
                onMouseDown={zoom.dragStart}
                onMouseMove={zoom.dragMove}
                onMouseUp={zoom.dragEnd}
                onMouseLeave={() => {
                  if (zoom.isDragging) zoom.dragEnd();
                }}
              />
            </svg>
            <Box>
              <Button onClick={zoom.reset} m={2}>Reset</Button>
            </Box>
          </Box>
        )}
      </Zoom>
    </Box>
  );
};

export default Graph;
