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

import {
  Button,
  ButtonProps,
  Input,
  InputGroup,
  InputGroupProps,
  InputLeftElement,
  InputProps,
  InputRightElement,
} from "@chakra-ui/react";
import { FiSearch } from "react-icons/fi";

export const SearchBar = ({
  groupProps,
  inputProps,
  buttonProps,
}: {
  groupProps?: InputGroupProps;
  inputProps?: InputProps;
  buttonProps?: ButtonProps;
}) => (
  <InputGroup {...groupProps}>
    <InputLeftElement pointerEvents="none">
      <FiSearch />
    </InputLeftElement>
    <Input placeholder="Search DAGs" pr={150} {...inputProps} />
    <InputRightElement width={150}>
      <Button
        variant="ghost"
        colorScheme="blue"
        width={140}
        height="1.75rem"
        fontWeight="normal"
        {...buttonProps}
      >
        Advanced Search
      </Button>
    </InputRightElement>
  </InputGroup>
);
