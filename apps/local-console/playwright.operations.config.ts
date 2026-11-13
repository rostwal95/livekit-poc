import { defineConfig } from '@playwright/test';
import { isAbsolute, resolve } from 'node:path';
const baseURL = process.env.P2_OPERATIONS_BROWSER_ORIGIN;
const output = process.env.P2_OPERATIONS_BROWSER_OUTPUT;
if (!baseURL || !output || !isAbsolute(output))
  throw new Error('Explicit operations browser origin and private output are required.');
const origin = new URL(baseURL);
if (
  origin.protocol !== 'http:' ||
  origin.hostname !== '127.0.0.1' ||
  !origin.port ||
  origin.username ||
  origin.password ||
  origin.pathname !== '/' ||
  origin.search ||
  origin.hash
)
  throw new Error('A fixed literal loopback operations origin is required.');
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/p2-operations.browser.ts',
  timeout: 90000,
  expect: { timeout: 15000 },
  workers: 1,
  fullyParallel: false,
  retries: 0,
  outputDir: resolve(output, 'browser-artifacts'),
  preserveOutput: 'never',
  reporter: [['line'], ['json', { outputFile: resolve(output, 'playwright.json') }]],
  use: {
    baseURL,
    browserName: 'chromium',
    headless: true,
    viewport: { width: 1440, height: 1100 },
    reducedMotion: 'reduce',
    trace: 'off',
    video: 'off',
    screenshot: 'off',
    serviceWorkers: 'block',
    launchOptions: {
      ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
        ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
        : {}),
    },
  },
});
