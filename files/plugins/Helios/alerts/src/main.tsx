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
import { ChakraProvider, createSystem, defaultConfig } from "@chakra-ui/react";

import { AlertsPage } from "./pages/AlertsPage";

type AlertsPluginProps = {
  readonly customConfig?: Record<string, unknown>;
};

export const AlertsPlugin = ({ customConfig }: AlertsPluginProps) => {
  // Use Airflow's customConfig if provided, otherwise fall back to default
  const system = customConfig ? createSystem(defaultConfig, customConfig) : createSystem(defaultConfig);

  return (
    <ChakraProvider value={system}>
      <AlertsPage />
    </ChakraProvider>
  );
};

// Register as global for Airflow plugin system
(globalThis as Record<string, unknown>).AirflowPlugin = AlertsPlugin;

export default AlertsPlugin;

