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
import type { StructuredLogMessage, TaskInstancesLogResponse } from "openapi/requests/types.gen";

export type ExtractedException = {
  exceptionClass: string;
  message: string;
};

type ErrorDetail = {
  exc_notes?: Array<string>;
  exc_type?: string;
  exc_value?: string;
};

// Unanchored — Airflow's rendered log lines are prefixed with timestamp/level,
// so a start-of-line anchor would never match. Matches "Foo.Bar.Error: message"
// anywhere in a line; iteration picks the *last* occurrence since earlier
// matches are usually from inner/re-raised exceptions.
const EXCEPTION_PATTERN = /\b(?<cls>\w+(?:\.\w+)*(?:Error|Exception|Failure|Timeout))\s*:\s*(?<msg>[^\n]+)/gu;

const getErrorDetail = (entry: string | StructuredLogMessage): Array<ErrorDetail> | undefined => {
  if (typeof entry !== "object") {
    return undefined;
  }
  const detail = entry.error_detail;

  return Array.isArray(detail) ? (detail as Array<ErrorDetail>) : undefined;
};

const fromStructured = (
  content: Array<string> | Array<StructuredLogMessage>,
): ExtractedException | undefined => {
  // Walk from the bottom — the most recent error_detail killed the task.
  const reversed = [...content].reverse();
  const match = reversed
    .map(getErrorDetail)
    .find((detail): detail is Array<ErrorDetail> => detail !== undefined && detail.length > 0);

  const last = match?.at(-1);

  if (last?.exc_type !== undefined && last.exc_value !== undefined) {
    return { exceptionClass: last.exc_type, message: last.exc_value };
  }

  return undefined;
};

const toPlainText = (entry: string | StructuredLogMessage): string => {
  if (typeof entry === "string") {
    return entry;
  }

  return String(entry.event);
};

const fromRegex = (content: Array<string> | Array<StructuredLogMessage>): ExtractedException | undefined => {
  const text = content.map(toPlainText).join("\n");
  const matches = [...text.matchAll(EXCEPTION_PATTERN)];
  const lastMatch = matches.at(-1);
  const cls = lastMatch?.groups?.cls;
  const msg = lastMatch?.groups?.msg;

  if (cls !== undefined && msg !== undefined) {
    return { exceptionClass: cls, message: msg.trim() };
  }

  return undefined;
};

export const extractException = (
  content: TaskInstancesLogResponse["content"] | undefined,
): ExtractedException | undefined => {
  if (!content || content.length === 0) {
    return undefined;
  }

  return fromStructured(content) ?? fromRegex(content);
};
