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
import { chakra, type HTMLChakraProps } from "@chakra-ui/react";
import { useColorMode } from "@helios/shared";

type Props = {
  readonly contextBg?: "dark" | "light";
} & HTMLChakraProps<"svg">;

export const AstroALogo = ({ contextBg, ...otherProps }: Props) => {
  const { colorMode } = useColorMode();
  const colorPreference = contextBg || colorMode;
  const isDark = colorPreference === "dark";
  const gradientId = `gradient-${isDark ? "dark" : "light"}`;

  return (
    <chakra.svg
      data-testid="astro-a-logo"
      viewBox="0 0 300 300"
      xmlns="http://www.w3.org/2000/svg"
      {...otherProps}
    >
      <defs>
        <linearGradient
          data-testid="logo-gradient"
          id={gradientId}
          x1="20.007%"
          x2="82.19%"
          y1="-5.531%"
          y2="89.303%"
        >
          <stop offset="0%" stopColor={isDark ? "#dbcdf6" : "#9478d2"} />
          <stop offset="100%" stopColor={isDark ? "#fff" : "#59418d"} />
        </linearGradient>
      </defs>
      <path
        d="M146.087.082C105.76 1.387 68.36 18.316 40.77 47.752c-56.956 60.766-53.855 156.54 6.91 213.496 21.313 19.976 46.943 32.534 73.686 37.838l8.016-20.042c-24.386-4.075-47.869-15.11-67.22-33.247-52.244-48.971-54.91-131.315-5.94-183.56 23.722-25.309 55.88-39.867 90.55-40.989 1.438-.047 2.874-.068 4.308-.068 26.15 0 51.2 7.757 72.535 22.222l8.028-20.075C207.677 8.12 179.957 0 151.094 0c-1.666 0-3.334.027-5.007.082Zm15.288 76.637h-21.019l-.253.633-53.515 133.786-.552 1.38h23.774l.248-.641 13.13-33.76h57.706l13.295 33.765.25.637H218.975l-.553-1.381-34.554-86.387-.253-.632H159.84l.533 1.37 12.256 31.502h-41.012l30.697-78.9.534-1.372h-1.473Z"
        fill={`url(#${gradientId})`}
        fillRule="evenodd"
        transform="translate(17.25)"
      />
    </chakra.svg>
  );
};
