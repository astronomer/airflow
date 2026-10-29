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
import { SearchParamsKeys } from "src/constants/searchParams";

const EXECUTION_PARAMS = [
  SearchParamsKeys.TRY_NUMBER,
  SearchParamsKeys.REGION_ID,
  SearchParamsKeys.REGION_INDEX,
];

/**
 * A copy of `searchParams` without the params that pin one execution or try.
 *
 * The loop filter is deliberately not among them: a pass is where you are in a loop, not a row,
 * so it survives moving between the loop's tasks. Pages drop a loop that is out of their scope.
 */
export const stripExecutionParams = (searchParams: string | URLSearchParams): URLSearchParams => {
  const stripped = new URLSearchParams(searchParams);

  for (const key of EXECUTION_PARAMS) {
    stripped.delete(key);
  }

  return stripped;
};

/**
 * The query a tab link should carry: the filters the page was reached with, plus whatever the
 * tab pins itself.
 *
 * Without this a tab link resolves to an empty query, so the grid and Gantt filters that got you
 * to the page are dropped the moment you move across its tabs. A tab's own params win, which is
 * how a tab keeps pointing at one try or one iteration's row.
 */
export const mergeTabSearch = (
  currentSearch: string | URLSearchParams,
  tabSearch?: string,
): string | undefined => {
  const merged = stripExecutionParams(currentSearch);

  for (const [key, value] of new URLSearchParams(tabSearch ?? "")) {
    merged.set(key, value);
  }

  return merged.toString() || undefined;
};

/**
 * Point a link at one execution. A task inside a loop has a row per iteration, so a link with
 * no coordinate is ambiguous and the API rejects it; the newest iteration is the sensible
 * landing place from a view that shows the task once.
 */
export const setExecutionCoordinates = (
  searchParams: URLSearchParams,
  regionId: string | null | undefined,
  regionIndex: number | null | undefined,
): URLSearchParams => {
  if (regionId !== null && regionId !== undefined && regionIndex !== null && regionIndex !== undefined) {
    searchParams.set(SearchParamsKeys.REGION_ID, regionId);
    searchParams.set(SearchParamsKeys.REGION_INDEX, String(regionIndex));
    // The coordinate decides which row is shown, and it is the newest pass here rather than
    // whichever one was being read. Carrying the old pass label over would leave the breadcrumb
    // and the Gantt naming a pass the page is not on, and Clear acting on a row nothing names.
    searchParams.delete(SearchParamsKeys.ITERATION);
    searchParams.delete(SearchParamsKeys.LOOP_ID);
  }

  return searchParams;
};
