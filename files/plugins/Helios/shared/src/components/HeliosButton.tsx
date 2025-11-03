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
import { Button, Icon } from "@chakra-ui/react";
import type { ButtonProps } from "@chakra-ui/react";
import { LuMoon, LuSun } from "react-icons/lu";

import { useColorMode } from "../context/useColorMode";

type HeliosButtonProps = {
  readonly variant?: "primary" | "secondary" | "danger" | "colorModeToggle";
} & Omit<ButtonProps, "variant">;

export const HeliosButton = ({ variant = "primary", children, onClick, ...props }: HeliosButtonProps) => {
  const { colorMode, toggleColorMode } = useColorMode();

  const variantStyles = {
    colorModeToggle: {
      bg: "blue.500",
      color: "white",
      _hover: { bg: "blue.600" },
    },
    danger: {
      bg: "red.500",
      color: "white",
      _hover: { bg: "red.600" },
    },
    primary: {
      bg: "blue.500",
      color: "white",
      _hover: { bg: "blue.600" },
    },
    secondary: {
      bg: "gray.200",
      color: "gray.800",
      _hover: { bg: "gray.300" },
    },
  };

  const handleClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    if (variant === "colorModeToggle") {
      toggleColorMode();
    }
    onClick?.(event);
  };

  // For colorModeToggle variant, show icon and text
  const buttonContent = variant === "colorModeToggle" ? (
    <>
      <Icon>{colorMode === "dark" ? <LuSun /> : <LuMoon />}</Icon>
      {children ?? `Toggle ${colorMode === "dark" ? "Light" : "Dark"} Mode`}
    </>
  ) : (
    children
  );

  return (
    <Button {...variantStyles[variant]} onClick={handleClick} {...props}>
      {buttonContent}
    </Button>
  );
};

