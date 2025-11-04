import React from 'react';

import { createIcon } from '@chakra-ui/react';

export const AlertCircleFilledIcon = createIcon({
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
      d="M2.5 12a9.5 9.5 0 1 1 19 0 9.5 9.5 0 0 1-19 0Zm9.995-4.59a.5.5 0 0 0-.992.09v5.25l.008.09a.5.5 0 0 0 .992-.09V7.5l-.008-.09Zm.255 8.715a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z"
      fill="currentColor"
      fillRule="evenodd"
    />
  ),
});
