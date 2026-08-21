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
  Popover,
  Portal,
  Select,
  VStack,
  type ListCollection,
  type SelectValueChangeDetails,
} from "@chakra-ui/react";
import type { Dispatch, SetStateAction } from "react";
import { useTranslation } from "react-i18next";
import { MdSettings } from "react-icons/md";

import { DagVersionSelect } from "src/components/DagVersionSelect";
import { DirectionDropdown } from "src/components/Graph/DirectionDropdown";
import { IconButton, Switch } from "src/components/ui";
import type { VersionIndicatorOptions } from "src/constants/showVersionIndicatorOptions";

import { DagRunSelect } from "./DagRunSelect";
import { VersionIndicatorSelect } from "./VersionIndicatorSelect";

type RunOption = { label: string; value: string };

type GraphPanelOptionsProps = {
  readonly dagId: string;
  readonly limit: number;
  readonly setShowAllDependencies: (value: boolean) => void;
  readonly showAllDependencies: boolean;
};

/**
 * Options shown in the panel popover while the graph view is active.
 */
export const GraphPanelOptions = ({
  dagId,
  limit,
  setShowAllDependencies,
  showAllDependencies,
}: GraphPanelOptionsProps) => {
  const { t: translate } = useTranslation();

  return (
    <>
      <DagVersionSelect />
      <DagRunSelect limit={limit} />

      <Switch
        checked={showAllDependencies}
        data-testid="show-all-dependencies"
        onCheckedChange={(details) => setShowAllDependencies(details.checked)}
      >
        {translate("dag:panel.dependencies.allDagDependencies")}
      </Switch>

      <DirectionDropdown graphId={dagId} />
    </>
  );
};

type GridPanelOptionsProps = {
  readonly displayRunOptions: ListCollection<RunOption>;
  readonly limit: number;
  readonly onLimitChange: (
    details: SelectValueChangeDetails<{ label: string; value: Array<string> }>,
  ) => void;
  readonly setShowVersionIndicatorMode: Dispatch<SetStateAction<VersionIndicatorOptions>>;
  readonly showVersionIndicatorMode: VersionIndicatorOptions;
};

/**
 * Options shown in the panel popover while the grid or gantt view is active.
 */
export const GridPanelOptions = ({
  displayRunOptions,
  limit,
  onLimitChange,
  setShowVersionIndicatorMode,
  showVersionIndicatorMode,
}: GridPanelOptionsProps) => {
  const { t: translate } = useTranslation();

  return (
    <>
      <Select.Root
        // @ts-expect-error The expected option type is incorrect
        collection={displayRunOptions}
        data-testid="display-dag-run-options"
        onValueChange={onLimitChange}
        size="sm"
        value={[limit.toString()]}
      >
        <Select.Label>{translate("dag:panel.dagRuns.label")}</Select.Label>
        <Select.Control>
          <Select.Trigger>
            <Select.ValueText />
          </Select.Trigger>
          <Select.IndicatorGroup>
            <Select.Indicator />
          </Select.IndicatorGroup>
        </Select.Control>
        <Select.Positioner>
          <Select.Content>
            {displayRunOptions.items.map((option) => (
              <Select.Item item={option} key={option.value}>
                {option.label}
              </Select.Item>
            ))}
          </Select.Content>
        </Select.Positioner>
      </Select.Root>
      <VStack alignItems="flex-start" px={1}>
        <VersionIndicatorSelect onChange={setShowVersionIndicatorMode} value={showVersionIndicatorMode} />
      </VStack>
    </>
  );
};

type PanelOptionsPopoverProps = { readonly dagView: string } & GraphPanelOptionsProps & GridPanelOptionsProps;

/**
 * The settings popover in the details panel header. Owns Chakra's
 * trigger/portal/positioner/content chain so callers only render one element.
 */
export const PanelOptionsPopover = ({
  dagId,
  dagView,
  displayRunOptions,
  limit,
  onLimitChange,
  setShowAllDependencies,
  setShowVersionIndicatorMode,
  showAllDependencies,
  showVersionIndicatorMode,
}: PanelOptionsPopoverProps) => {
  const { t: translate } = useTranslation();

  return (
    // oxlint-disable-next-line jsx-a11y/no-autofocus
    <Popover.Root autoFocus={false} positioning={{ placement: "bottom-end" }}>
      <Popover.Trigger asChild>
        <IconButton label={translate("dag:panel.buttons.options")}>
          <MdSettings />
        </IconButton>
      </Popover.Trigger>
      <Portal>
        <Popover.Positioner>
          <Popover.Content>
            <Popover.Arrow />
            <Popover.Body display="flex" flexDirection="column" gap={4} maxH="70vh" overflowY="auto" p={2}>
              {dagView === "graph" ? (
                <GraphPanelOptions
                  dagId={dagId}
                  limit={limit}
                  setShowAllDependencies={setShowAllDependencies}
                  showAllDependencies={showAllDependencies}
                />
              ) : (
                <GridPanelOptions
                  displayRunOptions={displayRunOptions}
                  limit={limit}
                  onLimitChange={onLimitChange}
                  setShowVersionIndicatorMode={setShowVersionIndicatorMode}
                  showVersionIndicatorMode={showVersionIndicatorMode}
                />
              )}
            </Popover.Body>
          </Popover.Content>
        </Popover.Positioner>
      </Portal>
    </Popover.Root>
  );
};
