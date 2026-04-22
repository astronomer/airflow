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

import { useImportErrorServiceGetImportErrors } from "openapi/queries";
import type { DAGResponse } from "openapi/requests/types.gen";
import { DagImportErrorAccordion } from "src/components/DagImportErrorAccordion";

import { selectLatestMatchingImportError } from "./selectLatestMatchingImportError";

const IMPORT_ERROR_FETCH_LIMIT = 100;

type Props = {
  readonly dag: Pick<DAGResponse, "bundle_name" | "is_stale" | "relative_fileloc">;
};

export const StaleDagImportErrorBanner = ({ dag }: Props) => {
  const relativeFileloc = dag.relative_fileloc ?? "";
  const shouldFetch = dag.is_stale && relativeFileloc.length > 0;

  const { data } = useImportErrorServiceGetImportErrors(
    {
      filenamePattern: relativeFileloc,
      limit: IMPORT_ERROR_FETCH_LIMIT,
      offset: 0,
      orderBy: ["-timestamp"],
    },
    undefined,
    { enabled: shouldFetch },
  );

  if (!shouldFetch) {
    return undefined;
  }

  const matched = selectLatestMatchingImportError(data?.import_errors, relativeFileloc, dag.bundle_name);

  if (matched === undefined) {
    return undefined;
  }

  const itemValue = String(matched.import_error_id);

  return (
    <Box data-testid="stale-dag-import-error-banner" mb={2}>
      <DagImportErrorAccordion defaultValue={[itemValue]} importErrors={[matched]} showFileErrorIndicator />
    </Box>
  );
};
