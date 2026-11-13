import { defineConfig } from '@playwright/test';
import { resolve } from 'node:path';
const baseURL = process.env.P3_NATIVE_BROWSER_ORIGIN,
  output = process.env.P3_NATIVE_BROWSER_OUTPUT;
if (!baseURL || !output)
  throw new Error('Explicit P3 native browser origin and output are required.');
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
  throw new Error('The P3 native browser gate requires an explicit loopback origin.');
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/p3-background.media.ts',
  timeout: 60000,
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
    viewport: { width: 1440, height: 1000 },
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
