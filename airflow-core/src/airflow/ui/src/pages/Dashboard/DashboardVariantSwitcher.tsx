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
// POC-only UI: floating switcher that toggles between dashboard
// layout variants via the `?variant=` URL param. Remove before any
// real PR ships.

/* eslint-disable i18next/no-literal-string --
   POC: variant labels are developer-facing, not user-facing; i18n-pass
   will happen before any real PR. */
import { Box, Button, ButtonGroup, Text } from "@chakra-ui/react";
import { useSearchParams } from "react-router-dom";

export type DashboardVariant = "v1" | "v2" | "v3";

const VARIANT_LABELS: Record<DashboardVariant, string> = {
  v1: "V1 Minimal",
  v2: "V2 Triage hero",
  v3: "V3 Split",
};

const VARIANT_KEYS: Array<DashboardVariant> = ["v1", "v2", "v3"];

export const useDashboardVariant = (): DashboardVariant => {
  const [params] = useSearchParams();
  const raw = params.get("variant");

  return (VARIANT_KEYS as Array<string>).includes(raw ?? "") ? (raw as DashboardVariant) : "v1";
};

export const DashboardVariantSwitcher = () => {
  const [params, setParams] = useSearchParams();
  const current = useDashboardVariant();

  const setVariant = (next: DashboardVariant) => {
    const updated = new URLSearchParams(params);

    if (next === "v1") {
      updated.delete("variant");
    } else {
      updated.set("variant", next);
    }
    setParams(updated, { replace: true });
  };

  return (
    <Box
      bg="bg.panel"
      borderColor="border"
      borderRadius="md"
      borderWidth={1}
      bottom={4}
      boxShadow="lg"
      position="fixed"
      px={3}
      py={2}
      right={4}
      zIndex="tooltip"
    >
      <Text color="fg.muted" fontSize="2xs" mb={1} textTransform="uppercase">
        POC: Dashboard variant
      </Text>
      <ButtonGroup attached size="xs" variant="outline">
        {VARIANT_KEYS.map((key) => (
          <Button
            colorPalette={current === key ? "blue" : undefined}
            key={key}
            onClick={() => setVariant(key)}
            variant={current === key ? "solid" : "outline"}
          >
            {VARIANT_LABELS[key]}
          </Button>
        ))}
      </ButtonGroup>
    </Box>
  );
};
