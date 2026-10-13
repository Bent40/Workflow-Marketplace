import { defineConfig } from 'vitest/config';

// Test framework is initialized — `automate` should NOT halt for missing framework.
export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'node',
  },
});
