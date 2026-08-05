import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    // Story W0 AC1. Was `[]` — no setup file existed at all, which is why
    // `@testing-library/jest-dom` has never been imported and why nothing was
    // intercepting HTTP. This registers the MSW server for the whole suite.
    setupFiles: ['./src/test/setup.ts'],
  },
  server: {
    fs: {
      // `src/test/contract.ts` imports docs/contracts/book-api.v1.json from the
      // repo root — outside this package. Vite refuses to serve it otherwise.
      allow: [path.resolve(__dirname, '../..')],
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@hie/shared': path.resolve(__dirname, '../../packages/shared'),
    },
  },
});
