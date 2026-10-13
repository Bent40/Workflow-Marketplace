import { defineConfig } from '@playwright/test';

// Minimal Playwright config so the test framework is considered initialized.
export default defineConfig({
  testDir: './tests',
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
  },
});
