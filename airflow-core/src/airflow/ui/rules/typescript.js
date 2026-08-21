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
import typescript from "@typescript-eslint/eslint-plugin";
import typescriptParser from "@typescript-eslint/parser";

import { ERROR } from "./levels.js";

/**
 * ESLint TypeScript namespace.
 */
export const typescriptNamespace = "@typescript-eslint";

/**
 * ESLint TypeScript rules.
 * @see [@typescript-eslint/eslint-plugin](https://typescript-eslint.io/rules/)
 */
export const typescriptRules = /** @type {const} @satisfies {FlatConfig.Config} */ ({
  files: ["**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx"],
  languageOptions: {
    parser: typescriptParser,
    parserOptions: {
      ecmaFeatures: {
        /**
         * Enable global strict mode.
         */
        impliedStrict: true,

        /**
         * JSX enabled by default (even if it's not a React project).
         */
        jsx: true,
      },
      /**
       * Self explanatory. Use the latest ECMAScript version.
       */
      ecmaVersion: "latest",

      /**
       * Get `tsconfig.json` from the root directory.
       */
      project: [
        `${import.meta.dirname}/../tsconfig.app.json`,
        `${import.meta.dirname}/../tsconfig.dev.json`,
        `${import.meta.dirname}/../tsconfig.node.json`,
      ],

      /**
       * Default to ESM.
       */
      sourceType: "module",
    },
  },
  plugins: { [typescriptNamespace]: typescript },
  rules: {
    /**
     * Avoid await on non thenable values.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const foo = await 42;
     *
     * // ✅ Correct
     * const bar = await Promise.resolve(42);
     * ```
     * @see [@typescript-eslint/await-thenable](https://typescript-eslint.io/rules/await-thenable/)
     */
    [`${typescriptNamespace}/await-thenable`]: ERROR,

    /**
     * Require `return` statements to either always or never specify values.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const foo = (): undefined => {}
     * const bar = (flag: boolean): undefined => {
     *   if (flag) {
     *     return foo()
     *   }
     *   return;
     * }
     * const baz = async (flag: boolean): Promise<undefined> {
     *   if (flag) {
     *     return;
     *  }
     *   return foo();
     * }
     *
     * // ✅ Correct
     * const foo = (): void => {}
     * const bar = (flag: boolean): void => {
     *   if (flag) {
     *     return foo()
     *   }
     *   return;
     * }
     * const baz = async (flag: boolean): Promise<void | number> {
     *   if (flag) {
     *     return 42;
     *  }
     *   return;
     * }
     * ```
     * @see [@typescript-eslint/consistent-return](https://typescript-eslint.io/rules/consistent-return)
     * @see [consistent-return](https://eslint.org/docs/latest/rules/consistent-return)
     */
    [`${typescriptNamespace}/consistent-return`]: ERROR,

    /**
     * Enforce specifying generic type arguments on constructor name of
     * a constructor call.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const x = 1;
     * type T = number;
     * export { x, T };
     *
     * // ✅ Correct
     * const x = 1;
     * type T = number;
     * export { x, type T };
     * ```
     * @see [@typescript-eslint/consistent-type-exports](https://typescript-eslint.io/rules/consistent-type-exports/)
     */
    [`${typescriptNamespace}/consistent-type-exports`]: [
      ERROR,
      { fixMixedExportsWithInlineTypeSpecifier: true },
    ],

    /**
     * Enforce `dot.notation` instead of `square["bracket"]["notation"]`.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const foo = bar["baz"];
     *
     * // ✅ Correct
     * const foo = bar.baz;
     * const bar = foo[foo]; // Dynamic access is allowed.
     * ```
     * @see [@typescript-eslint/dot-notation](https://typescript-eslint.io/rules/dot-notation/)
     */
    [`${typescriptNamespace}/dot-notation`]: ERROR,

    /**
     * Consistent naming:
     *
     * -   `camelCase`, `PascalCase` and `UPPER_CASE` for variables and enum members.
     * -   `camelCase` and `PascalCase` for functions.
     * -   `camelCase` for parameters, class properties, and class methods.
     * -   `PascalCase` for classes, enums, interfaces, type aliases, type literals and type parameters.
     *
     * @see [@typescript-eslint/naming-convention](https://typescript-eslint.io/rules/naming-convention/)
     */
    [`${typescriptNamespace}/naming-convention`]: [
      ERROR,
      {
        format: null,
        leadingUnderscore: "allow",
        selector: "default",
        trailingUnderscore: "forbid",
      },
      {
        format: ["camelCase", "PascalCase", "UPPER_CASE"],
        selector: ["variable", "enumMember"],
      },
      {
        format: ["camelCase", "PascalCase"],
        selector: "function",
      },
      {
        format: ["camelCase"],
        leadingUnderscore: "allow",
        selector: ["autoAccessor", "parameter", "classProperty", "classMethod"],
        trailingUnderscore: "forbid",
      },
      {
        format: ["PascalCase"],
        leadingUnderscore: "allow",
        selector: ["class", "enum", "interface", "typeAlias", "typeLike", "typeParameter"],
      },
    ],

    /**
     * Disallow using the `delete` operator on array values.
     *
     * @see [@typescript-eslint/no-array-delete](https://typescript-eslint.io/rules/no-array-delete/)
     */
    [`${typescriptNamespace}/no-array-delete`]: ERROR,

    /**
     * Avoid `.toString()` without a useful return type.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const foo = ({}).toString();
     *
     * // ✅ Correct
     * const foo = (42).toString();
     * ```
     * @see [@typescript-eslint/no-base-to-string](https://typescript-eslint.io/rules/no-base-to-string/)
     */
    [`${typescriptNamespace}/no-base-to-string`]: ERROR,

    /**
     * Require expressions of type void to appear in statement position.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const response = alert('Are you sure?');
     * console.log(alert('Are you sure?'));
     *
     * // ✅ Correct
     * alert('Hello, world!');
     * ```
     * @see [@typescript-eslint/no-confusing-void-expression](https://typescript-eslint.io/rules/no-confusing-void-expression/)
     */
    [`${typescriptNamespace}/no-confusing-void-expression`]: [
      ERROR,
      { ignoreArrowShorthand: true, ignoreVoidOperator: true },
    ],

    /**
     * Disallow duplicate constituents of union and intersection types.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * type StringOrNumber = string | string | number;
     * type ThisOrThat = { that: string } & { that: string };
     *
     * // ✅ Correct
     * type StringOrNumber = string | number;
     * type ThisOrThat = { this: string } & { that: string };
     * ```
     * @see [@typescript-eslint/no-duplicate-type-constituents](https://typescript-eslint.io/rules/no-duplicate-type-constituents/)
     */
    [`${typescriptNamespace}/no-duplicate-type-constituents`]: ERROR,

    /**
     * Let's avoid floating (unhandled) promises.
     *
     * @example
     * ```typescript
     * const example = async () => "foo";
     *
     * // ❌ Incorrect
     * example();
     *
     * // ✅ Correct
     * void example();
     * example().then(console.log).catch(console.error);`
     * ```
     * @see [@typescript-eslint/no-floating-promises](https://typescript-eslint.io/rules/no-floating-promises/)
     */
    [`${typescriptNamespace}/no-floating-promises`]: ERROR,

    /**
     * Use `for/of`, or better yet `map` or `forEach`.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * for (const key in foo) {
     *   console.log(key);
     * }
     *
     * // ✅ Correct
     * Object.keys(foo).forEach(console.log);
     *
     * for (const key of Object.keys(foo)) {
     *   console.log(key);
     * }
     * ```
     * @see [@typescript-eslint/no-for-in-array](https://typescript-eslint.io/rules/no-for-in-array/)
     */
    [`${typescriptNamespace}/no-for-in-array`]: ERROR,

    /**
     * This is super insecure, avoid it at all costs.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const timeout = setTimeout("alert(`Hi!`);", 100);
     * const fn = new Function("a", "b", "return a + b");
     *
     * // ✅ Correct
     * const timeout = setTimeout(() => alert(`Hi!`), 100);
     * const fn = (a, b) => a + b;
     * ```
     * @see [@typescript-eslint/no-implied-eval](https://typescript-eslint.io/rules/no-implied-eval/)
     */
    [`${typescriptNamespace}/no-implied-eval`]: ERROR,

    /**
     * Avoid using `this` outside a class.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * function foo() {
     *   console.log(this);
     * }
     *
     * // ✅ Correct
     * class Foo {
     *   public bar() {
     *     console.log(this);
     *   }
     * }
     * ```
     * @see [@typescript-eslint/no-invalid-this](https://typescript-eslint.io/rules/no-invalid-this/)
     */
    [`${typescriptNamespace}/no-invalid-this`]: ERROR,

    /**
     * Disallow the `void` operator except when used to discard a value.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * void (() => undefined)();
     *
     * // ✅ Correct
     * void (() => "value")();
     * ```
     * @see [@typescript-eslint/no-meaningless-void-operator](https://typescript-eslint.io/rules/no-meaningless-void-operator/)
     */
    [`${typescriptNamespace}/no-meaningless-void-operator`]: ERROR,

    /**
     * Avoid missuses of promises.
     *
     * @example
     * ```typescript
     * const aPromise = Promise.resolve("foo");
     *
     * // ❌ Incorrect
     * aPromise ? "foo" : "bar";
     *
     * // ✅ Correct
     * (await aPromise) ? "foo" : "bar";
     * ```
     * @see [@typescript-eslint/no-misused-promises](https://typescript-eslint.io/rules/no-misused-promises/)
     */
    [`${typescriptNamespace}/no-misused-promises`]: ERROR,

    /**
     * Disallow enums from having both number and string members.
     *
     * @example
     * ```typescript
     * const aPromise = Promise.resolve("foo");
     *
     * // ❌ Incorrect
     * const enum Status {
     *   Unknown,
     *   Closed = 1,
     *   Open = 'open',
     * }
     *
     * // ✅ Correct
     * const enum Status {
     *   Unknown = 0,
     *   Closed = 2,
     *   Open = 4,
     * }
     * ```
     * @see [@typescript-eslint/no-mixed-enums](https://typescript-eslint.io/rules/no-mixed-enums/)
     */
    [`${typescriptNamespace}/no-mixed-enums`]: ERROR,

    /**
     * Disallow members of unions and intersections that do nothing or override type information.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * type UnionAny = any | 'foo';
     * type UnionUnknown = unknown | 'foo';
     * type UnionNever = never | 'foo';
     * type UnionBooleanLiteral = boolean | false;
     * type UnionNumberLiteral = number | 1;
     * type UnionStringLiteral = string | 'foo';
     * type IntersectionAny = any & 'foo';
     * type IntersectionUnknown = string & unknown;
     * type IntersectionNever = string | never;
     * type IntersectionBooleanLiteral = boolean & false;
     * type IntersectionNumberLiteral = number & 1;
     * type IntersectionStringLiteral = string & 'foo';
     * ```
     * @see [@typescript-eslint/no-redundant-type-constituents](https://typescript-eslint.io/rules/no-redundant-type-constituents/)
     */
    [`${typescriptNamespace}/no-redundant-type-constituents`]: ERROR,

    /**
     * If it's a `boolean`, use it as such.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * if (foo === true) // …
     *
     * // ✅ Correct
     * if (foo) // …
     * ```
     * @see [@typescript-eslint/no-unnecessary-boolean-literal-compare](https://typescript-eslint.io/rules/no-unnecessary-boolean-literal-compare/)
     */
    [`${typescriptNamespace}/no-unnecessary-boolean-literal-compare`]: ERROR,

    /**
     * Avoid conditions with values that can't be falsy.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const check = (value: "foo" | "bar") => {
     *   if (value) // value will never be falsy
     * }
     *
     * // ✅ Correct
     * const check = (value: string) => {
     *   if (value) // Necessary, since value might be ""
     * }
     * ```
     * @see [@typescript-eslint/no-unnecessary-condition](https://typescript-eslint.io/rules/no-unnecessary-condition/)
     */
    [`${typescriptNamespace}/no-unnecessary-condition`]: ERROR,

    /**
     * Disallow unnecessary namespace qualifiers.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * enum A {
     *   B,
     *   C = A.B,
     * }
     *
     * // ✅ Correct
     * enum A {
     *   B,
     *   C = B,
     * }
     * ```
     * @see [@typescript-eslint/no-unnecessary-qualifier](https://typescript-eslint.io/rules/no-unnecessary-qualifier/)
     */
    [`${typescriptNamespace}/no-unnecessary-qualifier`]: ERROR,

    /**
     * Disallow unnecessary template expressions.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * `${'a'}${'b'}`
     *
     * // ✅ Correct
     * "ab"
     * ```
     * @see [@typescript-eslint/no-unnecessary-template-expression](https://typescript-eslint.io/rules/no-unnecessary-template-expression/)
     */
    [`${typescriptNamespace}/no-unnecessary-template-expression`]: ERROR,

    /**
     * If the type assertion is the same, skip it.
     *
     * @example
     * ```typescript
     * const example = <Value = string>(value: Value) => value;
     *
     * // ❌ Incorrect
     * example<string>("hello");
     *
     * // ✅ Correct
     * example("hello");
     * ```
     * @see [@typescript-eslint/no-unnecessary-type-arguments](https://typescript-eslint.io/rules/no-unnecessary-type-arguments/)
     */
    [`${typescriptNamespace}/no-unnecessary-type-arguments`]: ERROR,

    /**
     * Don't assert something that doesn't need assertion.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const foo = "bar" as string;
     * ```
     * @see [@typescript-eslint/no-unnecessary-type-assertion](https://typescript-eslint.io/rules/no-unnecessary-type-assertion/)
     */
    [`${typescriptNamespace}/no-unnecessary-type-assertion`]: ERROR,

    /**
     * Disallow type parameters that only appear once.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const second = <A, B>(a: A, b: B): B => b;
     *
     * // ✅ Correct
     * const second = <B>(a: unknown, b: B): B => b;
     * ```
     * @see [@typescript-eslint/no-unnecessary-type-parameters](https://typescript-eslint.io/rules/no-unnecessary-type-parameters/)
     */
    [`${typescriptNamespace}/no-unnecessary-type-parameters`]: ERROR,

    /**
     * Disallows calling an function with an `any` type value.
     *
     * @see [@typescript-eslint/no-unsafe-argument](https://typescript-eslint.io/rules/no-unsafe-argument/)
     */
    [`${typescriptNamespace}/no-unsafe-argument`]: ERROR,

    /**
     * Avoid `any` assignments.
     *
     * @see [@typescript-eslint/no-unsafe-assignment](https://typescript-eslint.io/rules/no-unsafe-assignment/)
     */
    [`${typescriptNamespace}/no-unsafe-assignment`]: ERROR,

    /**
     * Avoid calling `any`.
     *
     * @see [@typescript-eslint/no-unsafe-call](https://typescript-eslint.io/rules/no-unsafe-call/)
     */
    [`${typescriptNamespace}/no-unsafe-call`]: ERROR,

    /**
     * Disallow comparing an enum value with a non-enum value.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const enum Fruit {
     *   Apple = 0,
     * }
     *
     * declare let fruit: Fruit;
     *
     * fruit === 0;
     *
     * // ✅ Correct
     * const enum Fruit {
     *   Apple = 0,
     * }
     *
     * declare let fruit: Fruit;
     *
     * fruit === Fruit.Apple;
     * ```
     * @see [@typescript-eslint/no-unsafe-enum-comparison](https://typescript-eslint.io/rules/no-unsafe-enum-comparison/)
     */
    [`${typescriptNamespace}/no-unsafe-enum-comparison`]: ERROR,

    /**
     * Avoid accessing `any` members.
     *
     * @see [@typescript-eslint/no-unsafe-member-access](https://typescript-eslint.io/rules/no-unsafe-member-access/)
     */
    [`${typescriptNamespace}/no-unsafe-member-access`]: ERROR,

    /**
     * Avoid returning `any`.
     *
     * @see [@typescript-eslint/no-unsafe-return](https://typescript-eslint.io/rules/no-unsafe-return/)
     */
    [`${typescriptNamespace}/no-unsafe-return`]: ERROR,

    /**
     * Require unary negation to take a number.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * declare const a: string;
     * -a;
     *
     * // ✅ Correct
     * declare const a: number;
     * -a;
     * ```
     * @see [@typescript-eslint/no-unsafe-unary-minus](https://typescript-eslint.io/rules/no-unsafe-unary-minus/)
     */
    [`${typescriptNamespace}/no-unsafe-unary-minus`]: ERROR,

    /**
     * If you'll throw, throw errors, not literals.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * throw 'foo';
     *
     * // ✅ Correct
     * throw new Error('foo');
     * ```
     * @see [@typescript-eslint/only-throw-error](https://typescript-eslint.io/rules/only-throw-error/)
     * @see [no-throw-literal](https://eslint.org/docs/latest/rules/no-throw-literal)
     */
    [`${typescriptNamespace}/only-throw-error`]: ERROR,

    /**
     * Require destructuring from arrays and/or objects.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const foo = array[0];
     * const bar = array[5];
     *
     * // ✅ Correct
     * const { [0]: foo, [5]: bar } = array;
     * ```
     * @see [@typescript-eslint/prefer-destructuring](https://typescript-eslint.io/rules/prefer-destructuring/)
     */
    [`${typescriptNamespace}/prefer-destructuring`]: ERROR,

    /**
     * Enforce the use of `Array#find` over `Array#filter` followed by when looking for a single result.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * [1, 2, 3].filter(x => x > 1)[0];
     *
     * // ✅ Correct
     * [1, 2, 3].find(x => x > 1);
     * ```
     * @see [@typescript-eslint/prefer-find](https://typescript-eslint.io/rules/prefer-find/)
     */
    [`${typescriptNamespace}/prefer-find`]: ERROR,

    /**
     * Avoid `indexOf` and use `includes` instead.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * foo.indexOf("bar") !== -1;
     *
     * // ✅ Correct
     * foo.includes("bar");
     * ```
     * @see [@typescript-eslint/prefer-includes](https://typescript-eslint.io/rules/prefer-includes/)
     */
    [`${typescriptNamespace}/prefer-includes`]: ERROR,

    /**
     * Use `??` instead of a ternary.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const foo = bar !== null && bar !== undefined ? bar : "baz";
     *
     * // ✅ Correct
     * const foo = bar ?? "baz";
     * ```
     * @see [@typescript-eslint/prefer-nullish-coalescing](https://typescript-eslint.io/rules/prefer-nullish-coalescing/)
     */
    [`${typescriptNamespace}/prefer-nullish-coalescing`]: [
      ERROR,
      {
        ignoreConditionalTests: false,
        ignoreMixedLogicalExpressions: false,
      },
    ],

    /**
     * Use `?.` instead of checking every property.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const foo = bar && bar.baz && bar.baz.qux;
     *
     * // ✅ Correct
     * const foo = bar?.baz?.qux;
     * ```
     * @see [@typescript-eslint/prefer-optional-chain](https://typescript-eslint.io/rules/prefer-optional-chain/)
     */
    [`${typescriptNamespace}/prefer-optional-chain`]: ERROR,

    /**
     * In classes, private members should be read only.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * class Foo {
     *   private neverModified = "bar";
     * }
     *
     * // ✅ Correct
     * class Foo {
     *   private readonly neverModified = "bar";
     * }
     * ```
     * @see [@typescript-eslint/prefer-readonly](https://typescript-eslint.io/rules/prefer-readonly/)
     */
    [`${typescriptNamespace}/prefer-readonly`]: ERROR,

    /**
     * Enforce using type parameter when calling `Array#reduce` instead
     * of casting.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * [1, 2, 3].reduce((array, item) => [...array, item * 2], [] as ReadonlyArray<number>);
     *
     * // ✅ Correct
     * [1, 2, 3].reduce<ReadonlyArray<number>>((array, item) => [...array, item * 2], []);
     * ```
     * @see [@typescript-eslint/prefer-reduce-type-parameter](https://typescript-eslint.io/rules/prefer-reduce-type-parameter)
     */
    [`${typescriptNamespace}/prefer-reduce-type-parameter`]: ERROR,

    /**
     * Enforce `RegExp#exec` over `String#match` if no global flag is
     * provided.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * 'something'.match(/thing/);
     *
     * // ✅ Correct
     * /thing/.exec('something');
     * ```
     * @see [@typescript-eslint/prefer-regexp-exec](https://typescript-eslint.io/rules/prefer-regexp-exec)
     */
    [`${typescriptNamespace}/prefer-regexp-exec`]: ERROR,

    /**
     * Enforce that `this` is used when only `this` type is returned.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * class Example {
     *   someMethod(): Example {
     *     return this;
     *   }
     * }
     *
     * // ✅ Correct
     * class Example {
     *   someMethod(): this {
     *     return this;
     *   }
     * }
     * ```
     * @see [@typescript-eslint/prefer-return-this-type](https://typescript-eslint.io/rules/prefer-return-this-type)
     */
    [`${typescriptNamespace}/prefer-return-this-type`]: ERROR,

    /**
     * Enforce using `String#startsWith` and `String#endsWith` over
     * other equivalent methods of checking substrings.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * // starts with
     * foo[0] === 'b';
     * foo.charAt(0) === 'b';
     * foo.indexOf('bar') === 0;
     * foo.slice(0, 3) === 'bar';
     * foo.substring(0, 3) === 'bar';
     * foo.match(/^bar/) != null;
     * /^bar/.test(foo);
     *
     * // ends with
     * foo[foo.length - 1] === 'b';
     * foo.charAt(foo.length - 1) === 'b';
     * foo.lastIndexOf('bar') === foo.length - 3;
     * foo.slice(-3) === 'bar';
     * foo.substring(foo.length - 3) === 'bar';
     * foo.match(/bar$/) != null;
     * /bar$/.test(foo);
     *
     * // ✅ Correct
     * // starts with
     * foo.startsWith('bar');
     *
     * // ends with
     * foo.endsWith('bar');
     * ```
     * @see [@typescript-eslint/prefer-string-starts-ends-with](https://typescript-eslint.io/rules/prefer-string-starts-ends-with)
     */
    [`${typescriptNamespace}/prefer-string-starts-ends-with`]: ERROR,

    /**
     * Always use `Array#sort` with a comparing function.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * foo.sort();
     *
     * // ✅ Correct
     * foo.sort((a, z) => a - z);
     * ```
     * @see [@typescript-eslint/require-array-sort-compare](https://typescript-eslint.io/rules/require-array-sort-compare/)
     */
    [`${typescriptNamespace}/require-array-sort-compare`]: ERROR,

    /**
     * Use `await` if you are using `async`.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const foo = async () => "bar";
     *
     * // ✅ Correct
     * const foo = async () => await "bar";
     * ```
     * @see [@typescript-eslint/require-await](https://typescript-eslint.io/rules/require-await/)
     */
    [`${typescriptNamespace}/require-await`]: ERROR,

    /**
     * Use `+` with the same type (`number` or `string`).
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const foo = "bar" + 42;
     *
     * // ✅ Correct
     * const foo = "bar" + "baz";
     * ```
     * @see [@typescript-eslint/restrict-plus-operands](https://typescript-eslint.io/rules/restrict-plus-operands/)
     */
    [`${typescriptNamespace}/restrict-plus-operands`]: ERROR,

    /**
     * Only use strings or numbers inside template expressions.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * const foo = `bar${true}`;
     * const bar = `baz${undefined}`;
     *
     * // ✅ Correct
     * const foo = `bar${42}`;
     * const bar = `baz${"qux"}`;
     * const baz = `qux${undefined ?? "default"}`;
     * ```
     * @see [@typescript-eslint/restrict-template-expressions](https://typescript-eslint.io/rules/restrict-template-expressions/)
     */
    [`${typescriptNamespace}/restrict-template-expressions`]: [ERROR, { allowNumber: true }],

    /**
     * Comparisons should be applied to booleans only (not
     * falsy/truthy).
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * if (foo) // …
     * if (!foo) // …
     *
     * // ✅ Correct
     * if (foo !== "") // …
     * if (foo === undefined) // …
     * ```
     * @see [@typescript-eslint/strict-boolean-expressions](https://typescript-eslint.io/rules/strict-boolean-expressions/)
     */
    [`${typescriptNamespace}/strict-boolean-expressions`]: [ERROR, { allowNullableBoolean: true }],

    /**
     * If you'll use switch, make sure to cover every possible value.
     *
     * @see [@typescript-eslint/switch-exhaustiveness-check](https://typescript-eslint.io/rules/switch-exhaustiveness-check/)
     */
    [`${typescriptNamespace}/switch-exhaustiveness-check`]: ERROR,

    /**
     * Enforce typing arguments in `.catch()` callbacks as `unknown`.
     *
     * @example
     * ```typescript
     * // ❌ Incorrect
     * Promise.reject(new Error('I will reject!')).catch(error => {
     *   console.log(error);
     * });
     *
     * Promise.reject(new Error('I will reject!')).catch((error: any) => {
     *   console.log(error);
     * });
     *
     * Promise.reject(new Error('I will reject!')).catch((error: Error) => {
     *   console.log(error);
     * });
     *
     * // ✅ Correct
     * Promise.reject(new Error('I will reject!')).catch((error: unknown) => {
     *   console.log(error);
     * });
     * ```
     * @see [@typescript-eslint/use-unknown-in-catch-callback-variable](https://typescript-eslint.io/rules/use-unknown-in-catch-callback-variable/)
     */
    [`${typescriptNamespace}/use-unknown-in-catch-callback-variable`]: ERROR,
  },
});
