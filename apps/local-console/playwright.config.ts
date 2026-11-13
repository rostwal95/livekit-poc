import { defineConfig } from '@playwright/test';
import { resolve } from 'node:path';

const baseURL = process.env.E2E_BASE_URL;
if (!baseURL) throw new Error('E2E_BASE_URL must name the isolated local console.');
const origin = new URL(baseURL);
if (origin.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(origin.hostname) || origin.username || origin.password || origin.search || origin.hash) throw new Error('The browser gate requires a credential-free loopback HTTP origin.');
const output = resolve(process.env.E2E_REPORT_DIR ?? '.local/validation/browser');
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
export default defineConfig({
  testDir: './e2e', testMatch: '**/*.pw.ts', timeout: 90_000,
  expect: { timeout: 30_000 }, workers: 1, fullyParallel: false, retries: 0,
  outputDir: resolve(output, 'browser-artifacts'), preserveOutput: 'never',
  reporter: [['line'], ['json', { outputFile: resolve(output, 'playwright.json') }]],
  use: {
    baseURL, browserName: 'chromium', headless: true,
    viewport: { width: 1440, height: 1100 }, reducedMotion: 'reduce',
    trace: 'off', video: 'off', screenshot: 'off', serviceWorkers: 'block',
    launchOptions: {
      ...(executablePath ? { executablePath } : {}),
      args: ['--autoplay-policy=no-user-gesture-required'],
    },
  },
});
