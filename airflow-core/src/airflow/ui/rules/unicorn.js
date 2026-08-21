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
import unicorn from "eslint-plugin-unicorn";

import { ERROR } from "./levels.js";

/**
 * ESLint `unicorn` namespace.
 */
export const unicornNamespace = "unicorn";

/**
 * ESLint `unicorn` rules.
 * @see [eslint-plugin-unicorn](https://github.com/sindresorhus/eslint-plugin-unicorn#rules)
 */
export const unicornRules = /** @type {const} @satisfies {FlatConfig.Config} */ ({
  plugins: { [unicornNamespace]: unicorn },
  rules: {
    /**
     * Improve regexes by making them shorter, consistent, and safer.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const regex = /[0-9]/;
     * const regex = /[^0-9]/;
     * const regex = /[a-zA-Z0-9_]/;
     * const regex = /[a-z0-9_]/i;
     * const regex = /[^a-zA-Z0-9_]/;
     * const regex = /[^a-z0-9_]/i;
     * const regex = /[0-9]\.[a-zA-Z0-9_]\-[^0-9]/i;
     *
     * // ✅ Correct
     * const regex = /\d/;
     * const regex = /\D/;
     * const regex = /\w/;
     * const regex = /\w/i;
     * const regex = /\W/;
     * const regex = /\W/i;
     * const regex = /\d\.\w\-\D/i;
     * ```
     * @see [unicorn/better-regex](https://github.com/sindresorhus/eslint-plugin-unicorn/blob/main/docs/rules/better-regex.md)
     */
    [`${unicornNamespace}/better-regex`]: ERROR,

    /**
     * Use destructured variables over properties.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const { a } = foo;
     * console.log(a, foo.b);
     * console.log(foo.a);
     *
     * const { a: { b } } = foo;
     * console.log(foo.a.c);
     *
     * const { bar } = foo;
     * const { a } = foo.bar;
     *
     * // ✅ Correct
     * const { a } = foo;
     * console.log(a);
     * console.log(foo.a, foo.b);
     * console.log(a, foo.b());
     *
     * const { a } = foo.bar;
     * console.log(foo.bar);
     * ```
     * @see [unicorn/consistent-destructuring](https://github.com/sindresorhus/eslint-plugin-unicorn/blob/main/docs/rules/consistent-destructuring.md)
     */
    [`${unicornNamespace}/consistent-destructuring`]: ERROR,

    /**
     * Enforce the use of built-in methods instead of unnecessary polyfills.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const assign = require("object-assign");
     * ```
     * @see [unicorn/no-unnecessary-polyfills](https://github.com/sindresorhus/eslint-plugin-unicorn/blob/main/docs/rules/no-unnecessary-polyfills.md)
     */
    [`${unicornNamespace}/no-unnecessary-polyfills`]: ERROR,
  },
});
