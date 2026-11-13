import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const output = process.env.P2_NATIVE_BROWSER_OUTPUT;
const token = process.env.P2_NATIVE_BROWSER_ACCESS;
const textId = process.env.P2_NATIVE_TEXT_ID;
const voiceId = process.env.P2_NATIVE_VOICE_ID;
if (!output || !token || !textId || !voiceId)
  throw new Error('Explicit isolated native browser configuration is required.');
const observations: Record<string, string | number | boolean> = {
  schema_version: 1,
  browser_version: '',
  unexpected_network_requests: 0,
  unauthed_mint_rejected: false,
  selector_mint_rejected: false,
  ready: false,
  text_accepted: false,
  text_replayed_original_identity: false,
  voice_accepted: false,
  repeated_voice_commit_original_identity: false,
  returned_native_text: false,
  native_audio_advanced: false,
  no_hardware_microphone: true,
  fixture_track_stopped: false,
  disconnected: false,
  cleanup_complete: false,
};
let stage = 'initializing';
let pageErrors = 0;
const connections = new Set([
  'Disconnected',
  'Joining',
  'Connected',
  'Reconnecting',
  'Closing',
  'Cleanup incomplete',
]);
interface Input {
  inputId: string;
  channel: string;
  status: string;
  receiptId: string | null;
  operationKey: string | null;
  acceptanceSequence: string | null;
}
interface Evidence {
  connection: string;
  ready: boolean;
  inputs: Input[];
  observations: Record<string, unknown>;
}
async function evidence(page: Page): Promise<Evidence> {
  const raw = await page.locator('#native-evidence').textContent({ timeout: 1000 });
  if (raw === null || raw.length > 131072) throw new Error('Native evidence is unavailable.');
  return JSON.parse(raw) as Evidence;
}
async function save(): Promise<void> {
  await mkdir(output!, { recursive: true });
  await writeFile(
    resolve(output!, 'native-browser-observations.json'),
    JSON.stringify(observations, null, 2) + '\n',
  );
}

test('committed native text and fixture voice share durable P2 acceptance', async ({
  page,
  browser,
  request,
}) => {
  observations.browser_version = browser.version();
  page.on('pageerror', () => {
    pageErrors = Math.min(1000, pageErrors + 1);
  });
  page.on('request', (event) => {
    const url = new URL(event.url());
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))
      observations.unexpected_network_requests =
        Number(observations.unexpected_network_requests) + 1;
  });
  try {
    stage = 'mint_authentication';
    const unauthenticated = await request.post('/p2/session', { data: {} });
    expect(unauthenticated.status()).toBe(401);
    observations.unauthed_mint_rejected = true;
    stage = 'mint_selector';
    const selector = await request.post('/p2/session', {
      headers: { Authorization: `Bearer ${token}` },
      data: { caseId: 'other-case' },
    });
    expect(selector.status()).toBe(400);
    observations.selector_mint_rejected = true;
    stage = 'page_loading';
    await page.goto('/p2-native.html');
    await page.locator('#native-access').evaluate((element, value) => {
      (element as HTMLInputElement).value = value;
    }, token!);
    stage = 'rtc_connect';
    await page.locator('#native-join').click();
    await expect(page.locator('#native-connection')).toHaveText('Connected');
    stage = 'native_ready';
    await expect(page.locator('#native-readiness')).toHaveText('Native agent ready');
    expect(await page.locator('#native-access').inputValue()).toBe('');
    observations.ready = true;
    await page.locator('summary').filter({ hasText: 'Input references' }).click();
    await page.locator('#native-text-id').fill(textId!);
    await page.locator('#native-voice-id').fill(voiceId!);
    await page.locator('#native-message').fill('INVESTIGATE');
    stage = 'text_acceptance';
    await page.locator('#native-send').click();
    await expect
      .poll(async () => (await evidence(page)).inputs.find((row) => row.inputId === textId)?.status)
      .toBe('accepted');
    const first = (await evidence(page)).inputs.find((row) => row.inputId === textId)!;
    expect(first.receiptId).toMatch(/^[0-9a-f-]{36}$/);
    expect(first.operationKey).toMatch(/^[0-9a-f-]{36}$/);
    observations.text_accepted = true;
    stage = 'text_replay';
    await page.locator('#native-retry').click();
    await expect
      .poll(async () => (await evidence(page)).inputs.find((row) => row.inputId === textId)?.status)
      .toBe('replayed');
    const repeated = (await evidence(page)).inputs.find((row) => row.inputId === textId)!;
    expect([repeated.receiptId, repeated.operationKey, repeated.acceptanceSequence]).toEqual([
      first.receiptId,
      first.operationKey,
      first.acceptanceSequence,
    ]);
    observations.text_replayed_original_identity = true;
    stage = 'returned_text';
    await expect
      .poll(async () => Number((await evidence(page)).observations.native_transcriptions))
      .toBeGreaterThan(0);
    observations.returned_native_text = true;
    stage = 'returned_audio';
    await page.locator('#native-enable-audio').click();
    await expect
      .poll(() =>
        page.locator('#native-audio audio').evaluateAll((elements) =>
          Math.max(
            0,
            ...elements.map((element) => {
              const audio = element as HTMLAudioElement;
              return audio.played.length > 0 && audio.readyState >= 2 ? audio.currentTime : 0;
            }),
          ),
        ),
      )
      .toBeGreaterThan(0.05);
    observations.native_audio_advanced = true;
    await expect
      .poll(async () => Number((await evidence(page)).observations.completed_inputs))
      .toBe(1);
    stage = 'voice_capture';
    await page.locator('#native-publish').click();
    await expect(page.locator('#native-start')).toBeEnabled();
    await page.locator('#native-start').click();
    await expect(page.locator('#native-turn')).toHaveText('Capturing committed voice input');
    // This bounded wait captures a finite WAV segment; it does not invent UI progress.
    await page.waitForTimeout(800);
    stage = 'voice_acceptance';
    await page.locator('#native-commit').click();
    await expect
      .poll(
        async () => (await evidence(page)).inputs.find((row) => row.inputId === voiceId)?.status,
      )
      .toBe('accepted');
    const voice = (await evidence(page)).inputs.find((row) => row.inputId === voiceId)!;
    expect(voice.channel).toBe('voice_transcript');
    observations.voice_accepted = true;
    stage = 'voice_replay';
    await expect(page.locator('#native-commit')).toBeEnabled();
    await page.locator('#native-commit').click();
    await expect(page.locator('#native-commit')).toBeEnabled();
    const afterRepeat = (await evidence(page)).inputs;
    expect(afterRepeat).toHaveLength(2);
    expect(afterRepeat.find((row) => row.inputId === voiceId)?.receiptId).toBe(voice.receiptId);
    expect(afterRepeat.find((row) => row.inputId === voiceId)?.operationKey).toBe(
      voice.operationKey,
    );
    observations.repeated_voice_commit_original_identity = true;
    stage = 'generation_completion';
    await expect
      .poll(async () => Number((await evidence(page)).observations.completed_inputs))
      .toBe(2);
    observations.correlated_native_replies = true;
    await expect(page.locator('#native-turn')).toHaveText(
      'Voice input durably accepted · native reply complete',
    );
    expect(
      await page
        .locator('input[type="password"]')
        .evaluateAll((elements) =>
          elements.every((element) => (element as HTMLInputElement).value === ''),
        ),
    ).toBe(true);
    await mkdir(output!, { recursive: true });
    await page.screenshot({ path: resolve(output!, 'native-workspace.png'), fullPage: true });
    stage = 'cleanup';
    await page.locator('#native-end').click();
    await expect(page.locator('#native-connection')).toHaveText('Disconnected');
    observations.disconnected = true;
    const finished = await evidence(page);
    expect(finished.observations.fixture_live).toBe(false);
    observations.fixture_track_stopped = true;
    expect(finished.observations.active_readers).toBe(0);
    expect(finished.observations.active_io).toBe(0);
    expect(finished.observations.cleanup_incomplete).toBe(false);
    observations.cleanup_complete = true;
    expect(observations.unexpected_network_requests).toBe(0);
    expect(pageErrors).toBe(0);
    stage = 'complete';
  } finally {
    const rawConnection = await page
      .locator('#native-connection')
      .textContent({ timeout: 1000 })
      .catch(() => null);
    const connection =
      rawConnection !== null && connections.has(rawConnection) ? rawConnection : 'unobserved';
    let inputStatuses: string[] = [];
    const keys = ['sent', 'accepted', 'replayed', 'rejected', 'unknown', 'invalid_ack'];
    const counts: Record<string, number | null> = Object.fromEntries(
      keys.map((key) => [key, null]),
    );
    try {
      const snapshot = await evidence(page);
      inputStatuses = snapshot.inputs
        .slice(0, 32)
        .map((row) =>
          ['pending', 'accepted', 'replayed', 'rejected', 'unknown'].includes(row.status)
            ? row.status
            : 'unobserved',
        );
      for (const key of keys) {
        const sample = snapshot.observations[key];
        if (
          typeof sample === 'number' &&
          Number.isSafeInteger(sample) &&
          sample >= 0 &&
          sample <= 1000000
        )
          counts[key] = sample;
      }
    } catch {
      /* Closed diagnostics remain unobserved when the page did not initialize. */
    }
    await mkdir(output!, { recursive: true });
    await writeFile(
      resolve(output!, 'native-browser-context.json'),
      JSON.stringify({ schemaVersion: 1, stage, connection, pageErrors, inputStatuses, counts }) +
        '\n',
    );
    await save();
  }
});
