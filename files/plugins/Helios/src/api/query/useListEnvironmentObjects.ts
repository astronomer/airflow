

const MOCK_ENVIRONMENT_OBJECTS = [
  {
    description: 'Environment 1 description',
    id: '1',
    name: 'Environment 1',
  },
];

export const useListEnvironmentObjects = () => {
  const data = {
    airflowVariables: MOCK_ENVIRONMENT_OBJECTS,
    connections: MOCK_ENVIRONMENT_OBJECTS,
    environmentVariables: MOCK_ENVIRONMENT_OBJECTS,
  };

  return { data, isLoading: false };
};