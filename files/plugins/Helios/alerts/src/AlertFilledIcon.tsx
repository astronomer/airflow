import { createIcon } from '@chakra-ui/react';

export const AlertFilledIcon = createIcon({
  displayName: 'Alert',
  viewBox: '0 0 24 24',
  defaultProps: {
    width: '1.5em',
    height: '1.5em',
    fill: 'none',
  },
  path: (
    <path
      clipRule="evenodd"
      d="M10.267 3.873a2 2 0 0 1 3.462 0l8.248 14.25a2 2 0 0 1-1.731 3.001H3.75a2 2 0 0 1-1.731-3.002l8.248-14.249Zm1.978 6.287a.5.5 0 0 0-.992.09V14l.008.09a.5.5 0 0 0 .992-.09v-3.75l-.008-.09Zm.255 7.215a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z"
      fill="currentColor"
      fillRule="evenodd"
    />
  ),
});
