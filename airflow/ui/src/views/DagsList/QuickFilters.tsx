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

import { useSearchParams } from "react-router-dom";
import { Button, ButtonProps, Checkbox, HStack } from "@chakra-ui/react";
import { Select as ReactSelect } from "chakra-react-select";
import { useTableURLState } from "src/components/DataTable/useTableUrlState";

const QuickFilterButton = ({ children, ...rest }: ButtonProps) => (
  <Button
    borderRadius={20}
    fontWeight="normal"
    colorScheme="blue"
    variant="outline"
    {...rest}
  >
    {children}
  </Button>
);

type QuickFilterProps = {
  isLoading?: boolean;
};

const PAUSED_PARAM = "paused";

export const QuickFilters = ({ isLoading }: QuickFilterProps) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const showPaused = searchParams.get(PAUSED_PARAM) === "true";

  const { tableURLState, setTableURLState } = useTableURLState();
  const { sorting, pagination } = tableURLState;

  return (
    <>
      <HStack>
        <HStack>
          <QuickFilterButton isActive>All</QuickFilterButton>
          <QuickFilterButton isDisabled>Failed</QuickFilterButton>
          <QuickFilterButton isDisabled>Running</QuickFilterButton>
          <QuickFilterButton isDisabled>Successful</QuickFilterButton>
        </HStack>
        <Checkbox
          disabled={isLoading}
          isChecked={showPaused}
          onChange={() => {
            if (showPaused) searchParams.delete(PAUSED_PARAM);
            else searchParams.set(PAUSED_PARAM, "true");
            setSearchParams(searchParams);
            setTableURLState({
              sorting,
              pagination: { ...pagination, pageIndex: 0 },
            });
          }}
        >
          Show Paused DAGs
        </Checkbox>
      </HStack>
      <ReactSelect placeholder="Filter by tag" isDisabled />
    </>
  );
};
