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
import dayjs from "dayjs";
import dayjsDuration from "dayjs/plugin/duration";
import relativeTime from "dayjs/plugin/relativeTime";
import tz from "dayjs/plugin/timezone";

dayjs.extend(dayjsDuration);
dayjs.extend(relativeTime);
dayjs.extend(tz);

export const DEFAULT_DATETIME_FORMAT = "YYYY-MM-DD HH:mm:ss";
export const DEFAULT_DATETIME_FORMAT_WITH_TZ = `${DEFAULT_DATETIME_FORMAT} z`;

export const renderDuration = (
  durationSeconds: number | null | undefined,
  withMilliseconds: boolean = true,
): string | undefined => {
  if (durationSeconds === null || durationSeconds === undefined || durationSeconds <= 0.01) {
    return undefined;
  }

  // If under 60 seconds, render milliseconds
  if (durationSeconds < 60 && withMilliseconds) {
    return dayjs.duration(Number(durationSeconds.toFixed(3)), "seconds").format("HH:mm:ss.SSS");
  }

  // If under 1 day, render as HH:mm:ss otherwise include the number of days
  return durationSeconds < 86_400
    ? dayjs.duration(durationSeconds, "seconds").format("HH:mm:ss")
    : dayjs.duration(durationSeconds, "seconds").format("D[d]HH:mm:ss");
};

// Short, scannable duration. Prefers the largest unit that keeps precision
// meaningful for triage ("5.8s", "1m 32s", "2h 14m", "3d 5h") rather than the
// HH:MM:SS format — a dashboard of dozens of rows reads faster this way.
export const renderHumanizedDuration = (durationSeconds: number | null | undefined): string | undefined => {
  if (durationSeconds === null || durationSeconds === undefined || durationSeconds <= 0.01) {
    return undefined;
  }

  if (durationSeconds < 60) {
    return `${Number(durationSeconds.toFixed(1))}s`;
  }

  if (durationSeconds < 3600) {
    const minutes = Math.floor(durationSeconds / 60);
    const seconds = Math.round(durationSeconds - minutes * 60);

    return seconds === 0 ? `${minutes}m` : `${minutes}m ${seconds}s`;
  }

  if (durationSeconds < 86_400) {
    const wholeHours = Math.floor(durationSeconds / 3600);
    const minutes = Math.round((durationSeconds - wholeHours * 3600) / 60);

    return minutes === 0 ? `${wholeHours}h` : `${wholeHours}h ${minutes}m`;
  }

  const days = Math.floor(durationSeconds / 86_400);
  const hours = Math.round((durationSeconds - days * 86_400) / 3600);

  return hours === 0 ? `${days}d` : `${days}d ${hours}h`;
};

export const getDuration = (
  startDate?: string | null,
  endDate?: string | null,
  withMilliseconds: boolean = true,
) => {
  if (startDate === undefined || startDate === null) {
    return undefined;
  }

  const end = endDate ?? dayjs().toISOString();
  const seconds = dayjs.duration(dayjs(end).diff(startDate)).asSeconds();

  return renderDuration(seconds, withMilliseconds);
};

export const formatDate = (
  date: number | string | null | undefined,
  timezone: string,
  format: string = DEFAULT_DATETIME_FORMAT,
) => {
  if (date === null || date === undefined || !dayjs(date).isValid()) {
    return dayjs().tz(timezone).format(format);
  }

  return dayjs(date).tz(timezone).format(format);
};

export const getRelativeTime = (date: string | null | undefined): string => {
  if (date === null || date === "" || date === undefined) {
    return "";
  }

  return dayjs(date).fromNow();
};

export const getTimezoneOffsetString = (timezone: string): string => dayjs().tz(timezone).format("Z");

export const getTimezoneTooltipLabel = (timezone: string): string => {
  const now = dayjs().tz(timezone);

  return `${timezone} — ${now.format(DEFAULT_DATETIME_FORMAT_WITH_TZ)}`;
};
