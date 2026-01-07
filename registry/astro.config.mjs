import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwind from '@astrojs/tailwind';

export default defineConfig({
  // For surge.sh deployment, use root base
  // For airflow.apache.org, change back to: base: '/registry',
  site: 'https://faithful-war.surge.sh',
  base: '/',
  integrations: [
    react(),
    tailwind(),
  ],
  output: 'static',
  build: {
    assets: '_assets',
  },
  vite: {
    ssr: {
      noExternal: ['d3', 'd3-*'],
    },
  },
});
