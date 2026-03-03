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
import { Image } from "@chakra-ui/react";
import { useState } from "react";

import type { Theme } from "openapi/requests/types.gen";
import { AirflowPin } from "src/assets/AirflowPin";
import { useConfig } from "src/queries/useConfig";

type LogoProps = {
  readonly height?: string;
  readonly width?: string;
};

export const Logo = ({ height = "1.5em", width = "1.5em" }: LogoProps) => {
  const theme = useConfig("theme") as Theme | undefined;
  const logoUrl = theme?.logo_url;
  const [hasError, setHasError] = useState(false);

  if (typeof logoUrl === "string" && logoUrl.length > 0 && !hasError) {
    return <Image alt="Logo" height={height} onError={() => setHasError(true)} src={logoUrl} width={width} />;
  }

  return <AirflowPin height={height} width={width} />;
};
