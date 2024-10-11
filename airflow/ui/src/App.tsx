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
import { Alert, Spinner } from "@chakra-ui/react";
import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { DagsList } from "src/pages/DagsList";

import { BaseLayout } from "./layouts/BaseLayout";
import { mockPlugins } from "./mockPlugins";

export const App = () => (
  <Routes>
    <Route element={<BaseLayout />} path="/">
      <Route element={<Navigate to="dags" />} index />
      <Route element={<DagsList />} path="dags" />
      {mockPlugins
        .filter((plugin) => plugin.location === "nav")
        .map((plugin) => {
          const Plugin = lazy(() =>
            import(/* @vite-ignore */ plugin.src).catch((error: unknown) => {
              console.error("Component Failed Loading:", error);

              return {
                default: <Alert>Could not find plugin component</Alert>,
              };
            }),
          );

          return (
            <Route
              element={
                <Suspense fallback={<Spinner />}>
                  <Plugin />
                </Suspense>
              }
              key={plugin.title}
              path={plugin.route}
            />
          );
        })}
    </Route>
  </Routes>
);
