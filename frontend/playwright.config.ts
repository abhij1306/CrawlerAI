import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  retries: 1,
  use: {
    baseURL: 'http://127.0.0.1:3001',
    trace: 'on-first-retry',
  },
  projects: [
    {
      // Desktop: the existing default viewport, unchanged.
      name: 'desktop',
      use: { ...devices['Desktop Chrome'] },
      testIgnore: /mobile\.spec\.ts/,
    },
    {
      name: 'mobile',
      use: { ...devices['Pixel 7'] },
      testMatch: /mobile\.spec\.ts/,
    },
  ],
  webServer: {
    command: 'vp dev',
    url: 'http://127.0.0.1:3001',
    reuseExistingServer: true,
    env: {
      VITE_API_BASE_URL: 'http://127.0.0.1:8001',
    },
  },
});
