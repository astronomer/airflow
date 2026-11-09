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
import type { ReactNode } from "react";

import { Badge, Box, Code, Flex, Grid, Heading, HStack, Text, VStack } from "@chakra-ui/react";
import { useTranslation } from "react-i18next";

import Time from "src/components/Time";

import { useTaskInstanceView } from "src/hooks/useTaskInstanceView";
import { type DurableTryRecord, useDurableHistory } from "src/queries/useDurableHistory";

const DECISION_COLORS: Record<string, string> = {
  already_succeeded: "green",
  reconnected: "blue",
  resubmitted: "gray",
  resume_fell_back: "red",
  resumed: "purple",
  submitted: "gray",
};

const RETRY_DECISIONS_THAT_SAVE = new Set(["already_succeeded", "reconnected", "resumed"]);

const formatSavedDuration = (seconds: number): string => {
  if (seconds === 0) {
    return "0m";
  }
  const minutes = Math.round(seconds / 60);

  if (minutes < 1) {
    return "<1m";
  }

  return minutes < 60
    ? `${minutes}m`
    : `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
};

const SupportRow = ({ label, supported }: { readonly label: string; readonly supported: boolean }) => {
  const { t: translate } = useTranslation("dag");

  return (
    <Flex justifyContent="space-between">
      <Text>{label}</Text>
      <Text color={supported ? "fg.success" : "fg.error"} fontWeight="semibold">
        {translate(supported ? "durableExecution.supports.yes" : "durableExecution.supports.no")}
      </Text>
    </Flex>
  );
};

const Card = ({ children }: { readonly children: ReactNode }) => (
  <Box borderRadius="lg" borderWidth="1px" p={4}>
    {children}
  </Box>
);

const TryEntry = ({
  canResume,
  entry,
}: {
  readonly canResume: boolean;
  readonly entry: DurableTryRecord;
}) => {
  const { t: translate } = useTranslation("dag");
  const explanationKey =
    entry.decision === "resubmitted" && canResume
      ? "durableExecution.explanation.resubmittedDeclined"
      : `durableExecution.explanation.${entry.decision}`;
  const seconds = entry.time_not_rerun_seconds;

  return (
    <Box borderLeftColor={`${DECISION_COLORS[entry.decision] ?? "gray"}.solid`} borderLeftWidth="3px" pl={4}>
      <HStack gap={3} mb={2}>
        <Text fontWeight="semibold">
          {translate("durableExecution.try", { number: entry.try_number ?? "?" })}
        </Text>
        <Badge colorPalette={DECISION_COLORS[entry.decision] ?? "gray"} variant="subtle">
          {translate(`durableExecution.decision.${entry.decision}`)}
        </Badge>
        <Text color="fg.muted" fontSize="sm">
          <Time datetime={entry.recorded_at} />
        </Text>
      </HStack>
      <Grid columnGap={4} fontSize="sm" rowGap={1} templateColumns="160px 1fr">
        <Text color="fg.muted">{translate("durableExecution.externalId")}</Text>
        <Code variant="plain">
          {typeof entry.external_id === "string" ? entry.external_id : JSON.stringify(entry.external_id)}
        </Code>
        <Text color="fg.muted">{translate("durableExecution.whatHappened")}</Text>
        <Text>{translate(explanationKey, { status: entry.prior_status ?? "" })}</Text>
        {RETRY_DECISIONS_THAT_SAVE.has(entry.decision) ? (
          <>
            <Text color="fg.muted">{translate("durableExecution.notRerun")}</Text>
            <Text>
              {seconds === null
                ? translate("durableExecution.timingNotReported")
                : translate("durableExecution.avoided", { duration: formatSavedDuration(seconds) })}
            </Text>
          </>
        ) : undefined}
      </Grid>
    </Box>
  );
};

export const DurableExecution = () => {
  const { t: translate } = useTranslation("dag");
  const history = useDurableHistory();
  const { liveTaskInstance } = useTaskInstanceView();

  if (history === undefined) {
    return <Text p={2}>{translate("durableExecution.empty")}</Text>;
  }

  const retries = history.tries.filter((entry) => entry.decision !== "submitted");
  const reported = retries.filter((entry) => entry.time_not_rerun_seconds !== null);
  const totalSeconds = reported.reduce((sum, entry) => sum + (entry.time_not_rerun_seconds ?? 0), 0);
  const fellBack = history.tries.filter((entry) => entry.decision === "resume_fell_back");
  const succeeded = liveTaskInstance?.state === "success";

  return (
    <Grid gap={4} p={2} templateColumns={{ base: "1fr", lg: "2fr 1fr" }}>
      <Card>
        <Heading mb={1} size="md">
          {translate("durableExecution.title")}
        </Heading>
        <Text color="fg.muted" fontSize="sm" mb={4}>
          {translate("durableExecution.subtitle", { operator: history.operator })}
        </Text>
        <VStack alignItems="stretch" gap={5}>
          {history.tries.map((entry) => (
            <TryEntry
              canResume={history.can_resume_failed_job}
              entry={entry}
              key={`${entry.try_number}-${entry.recorded_at}`}
            />
          ))}
        </VStack>
      </Card>
      <VStack alignItems="stretch" gap={4}>
        <Card>
          <HStack mb={2}>
            <Heading size="sm">{translate("durableExecution.total.title")}</Heading>
            <Badge variant="subtle">{translate("durableExecution.total.estimate")}</Badge>
          </HStack>
          {succeeded && reported.length > 0 ? (
            <>
              <Text color="fg.success" fontSize="3xl" fontWeight="semibold">
                {formatSavedDuration(totalSeconds)}
              </Text>
              <Text color="fg.muted" fontSize="sm">
                {translate("durableExecution.total.explanation")}
              </Text>
            </>
          ) : (
            <Text color="fg.muted" fontSize="sm">
              {succeeded
                ? translate("durableExecution.total.notReported")
                : translate("durableExecution.total.onlyOnSuccess")}
            </Text>
          )}
        </Card>
        <Card>
          <Heading mb={3} size="sm">
            {translate("durableExecution.supports.title")}
          </Heading>
          <VStack alignItems="stretch" fontSize="sm" gap={2}>
            <SupportRow label={translate("durableExecution.supports.reconnect")} supported />
            <SupportRow label={translate("durableExecution.supports.skipFinished")} supported />
            <SupportRow
              label={translate("durableExecution.supports.resumeFailed")}
              supported={history.can_resume_failed_job}
            />
          </VStack>
        </Card>
        {fellBack.length > 0 ? (
          <Box bg="bg.error" borderRadius="lg" color="fg.error" fontSize="sm" p={3}>
            {translate("durableExecution.fellBackWarning", { count: fellBack.length })}
          </Box>
        ) : undefined}
        <Box bg="bg.warning" borderRadius="lg" color="fg.warning" fontSize="sm" p={3}>
          {translate("durableExecution.clearNote")}
        </Box>
      </VStack>
    </Grid>
  );
};
