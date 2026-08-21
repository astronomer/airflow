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
/**
 * @import { FlatConfig } from "@typescript-eslint/utils/ts-eslint";
 */
import { fixupPluginRules } from "@eslint/compat";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

import { ERROR, WARN } from "./levels.js";

/**
 * ESLint React namespace.
 */
export const reactNamespace = "react";

/**
 * ESLint React Hooks namespace.
 */
export const reactHooksNamespace = "react-hooks";

/**
 * ESLint React Refresh namespace.
 */
export const reactRefreshNamespace = "react-refresh";

/**
 * ESLint React rules.
 *
 * @see [eslint-plugin-react](https://github.com/jsx-eslint/eslint-plugin-react#list-of-supported-rules)
 * @see [eslint-plugin-react-hooks](https://github.com/facebook/react/tree/main/packages/eslint-plugin-react-hooks#custom-configuration)
 */
export const reactRules = /** @type {const} @satisfies {FlatConfig.Config} */ ({
  plugins: {
    [reactHooksNamespace]: fixupPluginRules(reactHooks),
    [reactNamespace]: react,
    [reactRefreshNamespace]: reactRefresh,
  },
  rules: {
    // https://github.com/facebook/react/blob/3640f38/compiler/packages/babel-plugin-react-compiler/src/CompilerError.ts#L807-L1111
    [`${reactHooksNamespace}/todo`]: ERROR,

    /**
     * Enforce consistent usage of destructuring assignment of props, state,
     * and context
     *
     * @see [react/destructuring-assignment](https://github.com/jsx-eslint/eslint-plugin-react/blob/HEAD/docs/rules/destructuring-assignment.md)
     */
    [`${reactNamespace}/destructuring-assignment`]: [ERROR, "always"],

    /**
     * Disallow problematic leaked values from being rendered.
     *
     * @see [react/jsx-no-leaked-render](https://github.com/jsx-eslint/eslint-plugin-react/blob/HEAD/docs/rules/jsx-no-leaked-render.md)
     */
    [`${reactNamespace}/jsx-no-leaked-render`]: ERROR,

    /**
     * Disallow usage of deprecated methods.
     *
     * @see [react/no-deprecated](https://github.com/jsx-eslint/eslint-plugin-react/blob/HEAD/docs/rules/no-deprecated.md)
     */
    [`${reactNamespace}/no-deprecated`]: ERROR,

    /**
     * Enforce that props are read-only.
     *
     * @see [react/prefer-read-only-props](https://github.com/jsx-eslint/eslint-plugin-react/blob/HEAD/docs/rules/prefer-read-only-props.md)
     */
    [`${reactNamespace}/prefer-read-only-props`]: ERROR,

    /**
     * Enforce property declarations alphabetical sorting.
     *
     * @see [react/sort-prop-types](https://github.com/jsx-eslint/eslint-plugin-react/blob/HEAD/docs/rules/sort-prop-types.md)
     */
    [`${reactNamespace}/sort-prop-types`]: ERROR,

    /**
     * Validate that your components can safely be updated with fast refresh.
     *
     * @see [Allow constant export](https://github.com/ArnaudBarre/eslint-plugin-react-refresh?tab=readme-ov-file#allowconstantexport-v040)
     */
    [`${reactRefreshNamespace}/only-export-components`]: [WARN, { allowConstantExport: true }],
  },
  settings: { react: { version: "19" } },
});
