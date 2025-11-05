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
import { createIcon } from "@chakra-ui/react";

export const AlertCircleFilledIcon = createIcon({
  defaultProps: {
    fill: "none",
    height: "1.5em",
    width: "1.5em",
  },
  displayName: "Alert",
  path: (
    <path
      clipRule="evenodd"
      d="M2.5 12a9.5 9.5 0 1 1 19 0 9.5 9.5 0 0 1-19 0Zm9.995-4.59a.5.5 0 0 0-.992.09v5.25l.008.09a.5.5 0 0 0 .992-.09V7.5l-.008-.09Zm.255 8.715a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z"
      fill="currentColor"
      fillRule="evenodd"
    />
  ),
  viewBox: "0 0 24 24",
});

