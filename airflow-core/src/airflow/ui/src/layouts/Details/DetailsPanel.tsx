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
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FaChevronLeft, FaChevronRight } from "react-icons/fa";
import { LuFileWarning } from "react-icons/lu";
import { PanelResizeHandle } from "react-resizable-panels";
import { Outlet } from "react-router-dom";

import type { DAGWarningCollectionResponse } from "openapi/requests/types.gen";
import { DAGWarningsModal } from "src/components/DAGWarningsModal";
import { IconButton, ProgressBar } from "src/components/ui";

import { NavTabs, type NavTab } from "./NavTabs";

type ResizeHandleProps = {
  readonly direction: string;
  readonly onCollapse: () => void;
  readonly onDragEnd: () => void;
};

/**
 * The draggable divider between the main and details panels, with the button
 * that collapses the details panel.
 */
export const DetailsPanelResizeHandle = ({ direction, onCollapse, onDragEnd }: ResizeHandleProps) => {
  const { t: translate } = useTranslation();

  return (
    <PanelResizeHandle
      className="resize-handle"
      onDragging={(isDragging) => {
        if (!isDragging) {
          onDragEnd();
        }
      }}
    >
      <Box
        alignItems="center"
        bg="border.emphasized"
        cursor="col-resize"
        display="flex"
        h="100%"
        justifyContent="center"
        position="relative"
        w={0.5}
      >
        <IconButton
          bg="fg.subtle"
          borderRadius="full"
          boxShadow="md"
          cursor="pointer"
          insetInlineStart="50%"
          label={translate("common:collapseDetailsPanel")}
          onClick={onCollapse}
          position="absolute"
          size="2xs"
          top="50%"
          transform={direction === "ltr" ? "translate(-50%, -50%)" : "translate(50%, -50%)"}
          zIndex={2}
        >
          {direction === "ltr" ? <FaChevronRight /> : <FaChevronLeft />}
        </IconButton>
      </Box>
    </PanelResizeHandle>
  );
};

type DetailsPanelBodyProps = {
  readonly children: ReactNode;
  readonly error: unknown;
  readonly isLoading?: boolean;
  readonly onWarningsClose: () => void;
  readonly onWarningsOpen: () => void;
  readonly outletContext?: unknown;
  readonly tabs: Array<NavTab>;
  readonly warningData?: DAGWarningCollectionResponse;
  readonly warningsOpen: boolean;
};

/**
 * Contents of the details panel: the caller's children, the Dag warnings
 * affordance, the tab bar, and the routed outlet.
 */
export const DetailsPanelBody = ({
  children,
  error,
  isLoading,
  onWarningsClose,
  onWarningsOpen,
  outletContext,
  tabs,
  warningData,
  warningsOpen,
}: DetailsPanelBodyProps) => {
  const { t: translate } = useTranslation();
  const hasWarnings = Boolean(error) || (warningData?.dag_warnings.length ?? 0) > 0;

  return (
    <Box display="flex" flexDirection="column" h="100%" paddingInlineStart={4} position="relative">
      {children}
      {hasWarnings ? (
        <>
          <IconButton
            colorPalette={Boolean(error) ? "red" : "orange"}
            label={`${translate("common:dagWarnings")} (${warningData?.total_entries ?? 0 + Number(error)})`}
            margin="2"
            marginBottom="-1"
            onClick={onWarningsOpen}
            rounded="full"
            variant="solid"
          >
            <LuFileWarning />
          </IconButton>

          <DAGWarningsModal
            error={error}
            onClose={onWarningsClose}
            open={warningsOpen}
            warnings={warningData?.dag_warnings}
          />
        </>
      ) : undefined}
      <ProgressBar size="xs" visibility={isLoading ? "visible" : "hidden"} />
      <NavTabs tabs={tabs} />
      <Box flexGrow={1} overflow="auto" px={2}>
        <Outlet context={outletContext} />
      </Box>
    </Box>
  );
};
