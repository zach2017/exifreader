import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './specs',
  fullyParallel: false,
  forbidOnly: true,
  retries: 1,
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: './test-results/html-report', open: 'never' }]],
  timeout: 120_000,
  expect: { timeout: 30_000 },
  use: {
    baseURL: process.env.WEB_URL || 'http://localhost:8080',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
