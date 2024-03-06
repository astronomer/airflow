import React, { useState, useEffect } from "react";
import { Card, CardBody, Flex, Table, Tbody, Tr, Td, Box, Thead, Th } from "@chakra-ui/react";
import useFilters from "src/cluster-activity/useFilters";
import { useResourceAnomaliesData } from "src/api";
import LoadingWrapper from "src/components/LoadingWrapper";

const ResourceAnomalies = () => {
  const { filters: { startDate, endDate } } = useFilters();
  const { data: fetchedData, isError } = useResourceAnomaliesData(startDate, endDate);

  const [data, setData] = useState({}); // Assuming fetchedData should be an object

  useEffect(() => {

    if(fetchedData && typeof fetchedData === 'object' && !Array.isArray(fetchedData)) {
      setData(fetchedData);
    }
  }, [fetchedData]);
  const dataEntries = data ? Object.entries(data) : [];

  return (
    <Flex w="100%">
      <Card w="100%">
        <CardBody>
          <Flex direction="column" minH="200px" alignItems="center">
            <LoadingWrapper hasData={!!dataEntries.length} isError={isError}>
              <Box w="100%">
                <Table variant="striped">
                  <Thead>
                    <Tr>
                      <Th>Key</Th>
                      <Th>Value</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {dataEntries.map(([key, value]) => (
                      <Tr key={key}>
                        <Td>{key}</Td>
                        <Td>{value.toString()}</Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              </Box>
            </LoadingWrapper>
          </Flex>
        </CardBody>
      </Card>
    </Flex>
  );
};

export default ResourceAnomalies;





