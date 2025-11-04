import { Heading, VStack } from "@chakra-ui/react";

import { DagCard } from "./DagCard";
import { StarsIcon } from "../StarsIcon";
import { DAGS_WITH_RECENT_FAILURES } from "./data";


export const LogSummaries = () => {

  return (
    <VStack gap={2} mt={4} w="100%" alignItems="stretch">
      <Heading size="md" display="flex"  color="#c2aef0" alignItems="center" gap={2}>
      <StarsIcon  />
      Astro summary of recent DAG failures
      </Heading>
      {DAGS_WITH_RECENT_FAILURES.map((dag) => (
        <DagCard key={dag.dagId} dagSummary={dag} />
      ))}
    </VStack>
  );
};