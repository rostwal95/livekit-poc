/** Actual local RTC observation windows; no provider, hardware or human-hearing claim. */
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
const output = process.env.P2_NATIVE_BROWSER_OUTPUT;
const token = process.env.P2_NATIVE_BROWSER_ACCESS;
const ids = ['NORMAL', 'INTERRUPT', 'MISSING'].map((name) => process.env[`P2_PLAYBACK_${name}_ID`]);
const duration = Number(process.env.P2_PLAYBACK_FIXTURE_MS);
if (
  !output ||
  !token ||
  ids.some((id) => !id) ||
  !Number.isFinite(duration) ||
  duration < 1000 ||
  duration > 4000
)
  throw new Error('Explicit playback fixture settings required.');
interface Row {
  responseId: string;
  generationId: string;
  inputId: string;
  operationKey: string;
  sdkSpeechId: string;
  observationCount: number;
  generated_observed: boolean;
  sdk_state: string;
  browser_state: string;
  conflicted: boolean;
  observed_audio_ms: number;
  sampled_audio_ms: number;
}
interface Evidence {
  inputs: {
    inputId: string;
    receiptId: string | null;
    operationKey: string | null;
    status: string;
  }[];
  responses: Row[];
  observations: Record<string, number | boolean>;
}
let lastEvidence: Evidence | undefined;
async function evidence(page: Page): Promise<Evidence> {
  const text = await page.locator('#native-evidence').textContent();
  if (!text || text.length > 131072) throw new Error('Bounded evidence required.');
  lastEvidence = JSON.parse(text) as Evidence;
  return lastEvidence;
}
async function response(page: Page, inputId: string): Promise<Row | undefined> {
  return (await evidence(page)).responses.find((row) => row.inputId === inputId);
}
async function send(page: Page, inputId: string): Promise<void> {
  await page.locator('#native-text-id').fill(inputId);
  await page.locator('#native-message').fill('INVESTIGATE');
  await page.locator('#native-send').click();
  await expect
    .poll(async () => (await evidence(page)).inputs.find((row) => row.inputId === inputId)?.status)
    .toBe('accepted');
  await expect.poll(async () => (await response(page, inputId))?.responseId).toBeTruthy();
}
async function quiet(page: Page, inputId: string): Promise<void> {
  let previous: Row | undefined;
  await expect
    .poll(
      async () => {
        const now = await response(page, inputId);
        if (!now) return false;
        if (!previous || now.observed_audio_ms !== previous.observed_audio_ms) {
          previous = now;
          return false;
        }
        return now.sampled_audio_ms - previous.sampled_audio_ms >= 250;
      },
      { timeout: 10000, intervals: [30, 50, 80] },
    )
    .toBe(true);
}
test('normal output, measured interruption and missing client completion', async ({ page }) => {
  let interruptTriggerAudioMs = 0;
  let stage = 'initializing',
    pageErrors = 0,
    unexpected = 0;
  const rows: Row[] = [];
  page.on('pageerror', () => pageErrors++);
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (
      !['http:', 'ws:', 'blob:', 'data:'].includes(url.protocol) ||
      (['http:', 'ws:'].includes(url.protocol) &&
        !['127.0.0.1', 'localhost'].includes(url.hostname))
    )
      unexpected++;
  });
  try {
    stage = 'join';
    await page.goto('/p2-native.html');
    await page.locator('#native-access').fill(token!);
    await page.locator('#native-join').click();
    await expect(page.locator('#native-readiness')).toHaveText('Native agent ready');
    await page.locator('#native-enable-audio').click();
    await page.locator('summary').filter({ hasText: 'Input references' }).click();
    await expect(page.locator('#native-text-id')).toBeVisible();
    await evidence(page);
    stage = 'normal';
    let responseReadUnavailable = true;
    await page.route('**/p2/response', async (route) => {
      if (responseReadUnavailable)
        await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
      else await route.continue();
    });
    await send(page, ids[0]!);
    const normalResponseId = (await response(page, ids[0]!))!.responseId;
    const normalCard = page.locator(`[data-response-id="${normalResponseId}"]`);
    await expect(normalCard).toHaveAttribute('data-read-status', 'unavailable');
    responseReadUnavailable = false;
    await normalCard.locator('[data-action="refresh"]').click();
    await expect(normalCard).toHaveAttribute('data-read-status', 'available');
    await expect(normalCard.locator('[data-lane="read-status"]')).toHaveText(
      'Latest observed source evidence',
    );
    await expect(page.locator('#native-status')).not.toContainText(
      'Response evidence is unavailable',
    );
    await expect
      .poll(async () => (await response(page, ids[0]!))?.observed_audio_ms ?? 0)
      .toBeGreaterThanOrEqual(duration * 0.75);
    await expect.poll(async () => (await response(page, ids[0]!))?.sdk_state).toBe('completed');
    await quiet(page, ids[0]!);
    const normal = (await response(page, ids[0]!))!;
    await expect(
      page.locator(`[data-response-id="${normal.responseId}"] [data-lane="generated"]`),
    ).toHaveText('The workflow panel shows the latest durable state.');
    await page
      .locator(`[data-response-id="${normal.responseId}"] [data-action="complete"]`)
      .click();
    await expect
      .poll(async () => (await response(page, ids[0]!))?.browser_state)
      .toBe('completed_reported');
    expect((await response(page, ids[0]!))?.generated_observed).toBe(true);
    rows.push((await response(page, ids[0]!))!);
    stage = 'interrupt';
    await send(page, ids[1]!);
    await expect
      .poll(async () => (await response(page, ids[1]!))?.observed_audio_ms ?? 0, {
        intervals: [10, 20],
        timeout: 10000,
      })
      .toBeGreaterThanOrEqual(duration * 0.4);
    const atInterrupt = (await response(page, ids[1]!))!;
    interruptTriggerAudioMs = atInterrupt.observed_audio_ms;
    expect(atInterrupt.observed_audio_ms / duration).toBeGreaterThanOrEqual(0.35);
    expect(atInterrupt.observed_audio_ms / duration).toBeLessThanOrEqual(0.65);
    await page
      .locator(`[data-response-id="${atInterrupt.responseId}"] [data-action="interrupt"]`)
      .click();
    await expect.poll(async () => (await response(page, ids[1]!))?.sdk_state).toBe('interrupted');
    await expect.poll(async () => (await response(page, ids[1]!))?.browser_state).toBe('partial');
    const interrupted = (await response(page, ids[1]!))!;
    expect(interrupted.generated_observed).toBe(true);
    expect(interrupted.conflicted).toBe(false);
    await quiet(page, ids[1]!);
    expect((await evidence(page)).responses.filter((row) => row.inputId === ids[1])).toHaveLength(
      1,
    );
    const finalInterrupted = (await response(page, ids[1]!))!;
    expect(finalInterrupted.observed_audio_ms).toBeGreaterThanOrEqual(interruptTriggerAudioMs);
    expect(finalInterrupted.observed_audio_ms).toBeLessThan(duration * 0.85);
    await expect(
      page.locator(`[data-response-id="${finalInterrupted.responseId}"] [data-lane="generated"]`),
    ).toHaveText('The workflow panel shows the latest durable state.');
    await expect(
      page.locator(`[data-response-id="${finalInterrupted.responseId}"] [data-lane="sdk"]`),
    ).toContainText('interrupted');
    await page
      .locator(`[data-response-id="${finalInterrupted.responseId}"] [data-action="refresh"]`)
      .click();
    await expect(
      page.locator(`[data-response-id="${finalInterrupted.responseId}"]`),
    ).toHaveAttribute('data-read-status', 'available');
    rows.push(finalInterrupted);
    expect(
      await page
        .locator('input[type="password"]')
        .evaluateAll((nodes) => nodes.every((node) => (node as HTMLInputElement).value === '')),
    ).toBe(true);
    await mkdir(output!, { recursive: true });
    await page.screenshot({ path: resolve(output!, 'playback-interrupted.png'), fullPage: true });
    stage = 'missing';
    await page.locator('#native-playback-reports').uncheck();
    await send(page, ids[2]!);
    await expect.poll(async () => (await response(page, ids[2]!))?.sdk_state).toBe('completed');
    await expect
      .poll(async () => (await response(page, ids[2]!))?.observed_audio_ms ?? 0)
      .toBeGreaterThan(100);
    const missing = (await response(page, ids[2]!))!;
    expect(missing.generated_observed).toBe(true);
    expect(missing.browser_state).toBe('unknown');
    expect(missing.conflicted).toBe(false);
    rows.push(missing);
    stage = 'cleanup';
    await page.locator('#native-end').click();
    await expect(page.locator('#native-connection')).toHaveText('Disconnected');
    const ended = await evidence(page);
    expect(ended.observations.active_io).toBe(0);
    expect(ended.observations.active_readers).toBe(0);
    expect(ended.observations.playback_meters).toBe(0);
    expect(ended.observations.playback_meter_creating).toBe(false);
    expect(ended.observations.cleanup_incomplete).toBe(false);
    expect(ended.inputs).toHaveLength(3);
    expect(ended.responses).toHaveLength(3);
    expect(new Set(rows.map((row) => row.operationKey)).size).toBe(3);
    expect(unexpected).toBe(0);
    expect(pageErrors).toBe(0);
    stage = 'complete';
    await writeFile(
      resolve(output!, 'playback-browser-observations.json'),
      JSON.stringify({
        schemaVersion: 1,
        status: 'passed',
        mode: 'local_scripted_p2_playback_browser',
        fixtureDurationMs: duration,
        interruptTriggerAudioMs,
        rows,
        actualBrowserAudio: true,
        physicalHearingClaimed: false,
        clientReportsWithheldForMissing: true,
        evidenceReadRecoveryVerified: true,
        cleanupComplete: true,
        pageErrors,
        unexpectedNetworkRequests: unexpected,
      }) + '\n',
    );
  } finally {
    await mkdir(output!, { recursive: true });
    let snapshot = lastEvidence;
    try {
      snapshot = await evidence(page);
    } catch {
      // Test timeout may close the page; the original finite stage still survives.
    }
    await writeFile(
      resolve(output!, 'playback-browser-context.json'),
      JSON.stringify({
        schemaVersion: 1,
        stage,
        pageErrors,
        unexpectedNetworkRequests: unexpected,
        inputStates: snapshot?.inputs.map((row) => row.status) ?? null,
        responses:
          snapshot?.responses.map((row) => ({
            sdkState: row.sdk_state,
            browserState: row.browser_state,
            generatedObserved: row.generated_observed,
            observationCount: row.observationCount,
            observedAudioMs: row.observed_audio_ms,
            sampledAudioMs: row.sampled_audio_ms,
          })) ?? null,
      }) + '\n',
      { mode: 0o600 },
    );
  }
});
