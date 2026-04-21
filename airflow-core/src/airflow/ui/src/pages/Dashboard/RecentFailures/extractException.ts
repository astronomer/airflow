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

// Match Python-style exception lines like:
//   ValueError: invalid literal for int()
//   airflow.exceptions.AirflowSkipException: skipping
//   ConnectionError: timeout
const EXCEPTION_LINE = /^(\w+(?:\.\w+)*(?:Error|Exception|Failure|Timeout))\s*:\s*(.+)$/mu;

export type ExtractedException = {
  exceptionClass: string;
  message: string;
};

export const extractException = (logText: string): ExtractedException | undefined => {
  const lines = logText.split("\n");

  // Walk from the bottom — the last exception line is usually the one that
  // actually killed the task (earlier matches are often from caught/re-raised
  // inner exceptions).
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const match = EXCEPTION_LINE.exec(lines[index] ?? "");

    if (match?.[1] !== undefined && match[2] !== undefined) {
      return { exceptionClass: match[1], message: match[2].trim() };
    }
  }

  return undefined;
};
