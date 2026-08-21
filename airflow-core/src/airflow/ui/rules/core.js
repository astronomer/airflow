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
import { ERROR } from "./levels.js";

const allExtensions = "*.{j,t}s{x,}";

/**
 * Core ESLint rules.
 * @see [ESLint core rules](https://eslint.org/docs/latest/rules)
 */
export const coreRules = /** @type {const} @satisfies {FlatConfig.Config} */ ({
  files: [
    // Files in the root and src directories
    `{rules,src}/**/${allExtensions}`,
    // Files in the root directory
    allExtensions,
  ],
  rules: {
    /**
     * Disallow old octal literals.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const num = 071;
     * const result = 5 + 07;
     *
     * // ✅ Correct
     * const num = 0o71;
     * const result = 5 + 0o7;
     * ```
     * @see [no-octal](https://eslint.org/docs/latest/rules/no-octal)
     */
    "no-octal": ERROR,

    /**
     * Disallow the `React` type namespace. `@types/react` declares `export as
     * namespace React`, so `React.ReactNode` type-checks even in files that
     * never import React — only a syntax rule can catch those.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const Foo: React.FC<FooProps> = ({ bar }) => <div>{bar}</div>;
     * const node: React.ReactNode = null;
     *
     * // ✅ Correct
     * const Foo = ({ bar }: FooProps) => <div>{bar}</div>;
     * const node: ReactNode = null;
     * ```
     * @see [no-restricted-syntax](https://eslint.org/docs/latest/rules/no-restricted-syntax)
     */
    "no-restricted-syntax": [
      ERROR,
      {
        message:
          "Do not type components with `React.FC`. Annotate the props parameter instead: `const Foo = ({ bar }: FooProps) => ...`.",
        selector: "TSQualifiedName[left.name='React'][right.name=/^(FC|FunctionComponent|VFC)$/]",
      },
      {
        message:
          "Do not type components with `FC`. Annotate the props parameter instead: `const Foo = ({ bar }: FooProps) => ...`.",
        selector:
          "VariableDeclarator[init.type='ArrowFunctionExpression'] > Identifier > TSTypeAnnotation > TSTypeReference > Identifier[name=/^(FC|FunctionComponent|VFC)$/]",
      },
      {
        message:
          'Import React types by name instead of qualifying them with the `React` namespace: `import { type ReactElement } from "react"`, then use `ReactElement`.',
        selector: "TSQualifiedName[left.name='React']:not([right.name=/^(FC|FunctionComponent|VFC)$/])",
      },
    ],

    /**
     * Disallow assignments that can lead to race conditions due to usage of
     * `await` or `yield`.
     *
     * @see [require-atomic-updates](https://eslint.org/docs/latest/rules/require-atomic-updates)
     */
    "require-atomic-updates": ERROR,
  },
});
