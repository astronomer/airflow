import { Box, Heading, Link, Text } from "@chakra-ui/react";
import { useEffect, useState } from "react";

export type DagSummary = {
  dagId: string;
  time: string;
  recentRuns: {
    id: string;
    time: string;
    state: string;
    summary?: string;
  }[];
};

type Props = {
  dagSummary: DagSummary;
}

export const DagCard = ({ dagSummary }: Props) => {
  const [selectedRun, setSelectedRun] = useState<string | undefined>(undefined);

  useEffect(() => {
    const firstFailure = dagSummary.recentRuns.find((run) => run.state === "failed");
    if (firstFailure) {
      setSelectedRun(firstFailure.id);
    }
  }, [dagSummary.recentRuns]);

  const selectedRunSummary = dagSummary.recentRuns.find((run) => run.id === selectedRun)?.summary;

  return (
    <Box borderRadius="md" borderWidth="1px" p={2} px={4} display="flex" alignItems="center" gap={2}>
      <Box w="250px">
        <Heading size="sm">
        <Link href={`/dags/${dagSummary.dagId}/runs/${selectedRun}`}>
          {dagSummary.dagId}</Link></Heading>
        <Text color="fg.muted" fontSize="sm">Last failed {dagSummary.time}</Text>
        
      </Box>
      <Box flex="1">
        <Box display="flex" alignItems="center" gap={2} mt={2} mb={4} ml={2}>
          {dagSummary.recentRuns.map((run) => (
            <Box
              key={run.id}
              borderRadius="full"
              onClick={() => run.state === "failed" ? setSelectedRun(run.id) : undefined}
              boxSize={3}
              bg={run.state === "failed" ? "red.500" : "green.300"}
              opacity={run.state === "failed" ? 1 : 0.3}
              cursor={run.state === "failed" ? "pointer" : "default"}
              outline={run.id === selectedRun ? "2px solid" : "none"}
              outlineOffset="1px"
              outlineColor="#7352ba"
              position="relative"
              _after={{
                content: '""',
                position: "absolute",
              // INSERT_YOUR_CODE
                ...(run.state === "failed" && run.id === selectedRun
                  ? {
                      // Triangle only for failed runs, rotated 180 degrees
                      content: '""',
                      boxSize: 3,
                      display: "block",
                      left: "50%",
                      top: 4.5,
                      transform: "translateX(-50%) rotate(180deg)",
                      borderLeft: "6px solid transparent",
                      borderRight: "6px solid transparent",
                      borderTop: "12px solid #A0AEC0", // gray.400 from Chakra
                      borderBottom: "none",
                      borderTopColor: 'bg.muted'
                    }
                  : {}),
              }}
            />
          ))}
        </Box>
        {selectedRunSummary && (
            <>
              <Box bg="bg.muted" borderColor="border.muted" display="inline-block" px={2} py={1} borderRadius="md" fontSize="sm">
                {selectedRunSummary}{" "}
              <Link href={`/dags/${dagSummary.dagId}/runs/${selectedRun}`} color="fg.info">View run</Link>
              </Box>
            </>
        )}
      </Box>
      
    </Box>
  );
};