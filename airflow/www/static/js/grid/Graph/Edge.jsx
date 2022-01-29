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

import React from 'react';
import { LinePath } from '@visx/shape';
// import { curveBundle } from '@visx/curve';
import {
  useTheme,
} from '@chakra-ui/react';

const Edge = ({ edge }) => {
  const { colors } = useTheme();
  return (
    <>
      {edge.sections.map((s) => (
        <LinePath
          key={s.id}
          stroke={colors.gray[400]}
          // curve={curveBundle}
          strokeWidth={1}
          x={(d) => d.x || 0}
          y={(d) => d.y || 0}
          data={[s.startPoint, ...(s.bendPoints || []), s.endPoint]}
        />
      ))}
    </>
  );
};

export default Edge;
