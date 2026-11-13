/** One actual browser journey, three named groups. Scripted PCM, no hearing claim. */
import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
const output = process.env.P2_NATIVE_BROWSER_OUTPUT,
  token = process.env.P2_NATIVE_BROWSER_ACCESS;
const voice = process.env.P2_REHYDRATION_VOICE_ID,
  text = process.env.P2_REHYDRATION_TEXT_ID;
const newText = process.env.P2_REHYDRATION_NEW_TEXT_ID,
  sms = process.env.P2_REHYDRATION_SMS_ID;
if (
  !output ||
  !token ||
  [voice, text, newText, sms].some(
    (v) =>
      !v ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/u.test(v),
  )
)
  throw new Error('Explicit fixed browser input identities required.');
interface Input {
  inputId: string;
  channel: string;
  status: string;
  receiptId: string | null;
  operationKey: string | null;
  acceptanceSequence: string | null;
}
interface ResponseRow {
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
interface Historical {
  responseId: string;
  bindingId: string;
  generationId: string;
  sdkSpeechId: string;
  sdkState: string;
  browserState: string;
  historical: boolean;
}
interface Context {
  required: boolean;
  phase: string;
  ready: boolean;
  contextId: string | null;
  bindingId: string | null;
  caseId: string | null;
  caseRevision: string | null;
  caseSource: string | null;
  historyReceipts: string[];
  historyChannels: string[];
  pendingOperations: string[];
  historicalResponses: Historical[];
  actualReads: number;
  smsKnown: boolean;
}
interface Evidence {
  connection: string;
  ready: boolean;
  inputs: Input[];
  responses: ResponseRow[];
  rehydration: Context;
  observations: Record<string, number | boolean>;
}
const groups = [
  'room_a_real_voice_text_original_receipts',
  'dormant_sms_current_case_revision',
  'fresh_room_b_rehydration_and_new_reply',
];
let latest: Evidence | undefined;
async function evidence(page: Page): Promise<Evidence> {
  const raw = await page.locator('#native-evidence').textContent();
  if (!raw || raw.length > 131072) throw new Error('Bounded current browser evidence required.');
  latest = JSON.parse(raw) as Evidence;
  return latest;
}
async function reply(page: Page, inputId: string): Promise<ResponseRow> {
  await expect
    .poll(
      async () => (await evidence(page)).responses.find((r) => r.inputId === inputId)?.sdk_state,
    )
    .toBe('completed');
  await expect
    .poll(
      async () =>
        (await evidence(page)).responses.find((r) => r.inputId === inputId)?.generated_observed,
    )
    .toBe(true);
  await expect
    .poll(
      async () =>
        (await evidence(page)).responses.find((r) => r.inputId === inputId)?.observed_audio_ms ?? 0,
    )
    .toBeGreaterThan(100);
  let prior: ResponseRow | undefined;
  await expect
    .poll(
      async () => {
        const r = (await evidence(page)).responses.find((r) => r.inputId === inputId);
        if (!r) return false;
        if (!prior || r.observed_audio_ms !== prior.observed_audio_ms) {
          prior = r;
          return false;
        }
        return r.sampled_audio_ms - prior.sampled_audio_ms >= 250;
      },
      { intervals: [30, 50, 80], timeout: 10000 },
    )
    .toBe(true);
  const row = (await evidence(page)).responses.find((r) => r.inputId === inputId)!;
  expect(row.browser_state).toBe('unknown');
  expect(row.conflicted).toBe(false);
  return row;
}
async function accepted(page: Page, inputId: string): Promise<Input> {
  await expect
    .poll(async () => (await evidence(page)).inputs.find((r) => r.inputId === inputId)?.status)
    .toBe('accepted');
  const row = (await evidence(page)).inputs.find((r) => r.inputId === inputId)!;
  expect(row.receiptId).toBeTruthy();
  expect(row.operationKey).toBeTruthy();
  return row;
}
async function send(page: Page, inputId: string): Promise<Input> {
  await page.locator('#native-text-id').fill(inputId);
  await page.locator('#native-message').fill('INVESTIGATE');
  await page.locator('#native-send').click();
  return accepted(page, inputId);
}
async function end(page: Page): Promise<void> {
  await page.locator('#native-end').click();
  await expect(page.locator('#native-connection')).toHaveText('Disconnected');
  const v = await evidence(page);
  for (const key of ['active_io', 'active_readers', 'playback_meters'])
    expect(v.observations[key]).toBe(0);
  expect(v.observations.cleanup_incomplete).toBe(false);
  expect(v.observations.fixture_live).toBe(false);
}
async function passwordEmpty(page: Page): Promise<void> {
  expect(
    await page
      .locator('input[type="password"]')
      .evaluateAll((nodes) => nodes.every((n) => (n as HTMLInputElement).value === '')),
  ).toBe(true);
}

test('one case survives voice, text, room close, SMS and a fresh native reply', async ({
  page,
  request,
}) => {
  let stage = 'initializing',
    pageErrors = 0,
    unexpected = 0;
  const completed: string[] = [];
  page.on('pageerror', () => pageErrors++);
  page.on('request', (r) => {
    const url = new URL(r.url());
    if (
      !['http:', 'ws:', 'blob:', 'data:'].includes(url.protocol) ||
      (['http:', 'ws:'].includes(url.protocol) &&
        !['127.0.0.1', 'localhost'].includes(url.hostname))
    )
      unexpected++;
  });
  try {
    stage = 'authentication';
    expect((await request.post('/p2/session', { data: {} })).status()).toBe(401);
    expect(
      (
        await request.post('/p2/session', {
          headers: { Authorization: `Bearer ${token}` },
          data: { caseId: 'forged-case' },
        })
      ).status(),
    ).toBe(400);
    expect((await request.post('/p2/context', { data: { schemaVersion: 1 } })).status()).toBe(401);
    stage = 'join_a';
    await page.goto('/p2-native.html');
    await page.locator('#native-access').fill(token!);
    await page.locator('#native-join').click();
    await expect(page.locator('#native-readiness')).toHaveText('Native agent ready');
    let v = await evidence(page);
    expect(v.rehydration.required).toBe(true);
    expect(v.rehydration.caseRevision).toBe('1');
    expect(v.rehydration.historyReceipts).toHaveLength(0);
    expect(v.responses).toHaveLength(0);
    expect(v.inputs).toHaveLength(0);
    const bindingA = v.rehydration.bindingId;
    expect(bindingA).toBeTruthy();
    await page.locator('#native-playback-reports').uncheck();
    await page.locator('#native-enable-audio').click();
    await page.locator('summary').filter({ hasText: 'Input references' }).click();
    await page.locator('#native-voice-id').fill(voice!);
    stage = 'voice_a';
    await page.locator('#native-publish').click();
    await expect(page.locator('#native-start')).toBeEnabled();
    await page.locator('#native-start').click();
    await expect(page.locator('#native-turn')).toHaveText('Capturing committed voice input');
    // Finite actual fixture capture, never a synthetic progress/acceptance assertion.
    await page.waitForTimeout(800);
    await page.locator('#native-commit').click();
    const voiceInput = await accepted(page, voice!);
    expect(voiceInput.channel).toBe('voice_transcript');
    const voiceReply = await reply(page, voice!);
    stage = 'chat_a';
    const textInput = await send(page, text!);
    const textReply = await reply(page, text!);
    stage = 'refresh_a';
    await page.locator('#native-context-refresh').click();
    await expect
      .poll(async () => (await evidence(page)).rehydration.historyReceipts.length)
      .toBe(2);
    v = await evidence(page);
    const a = {
      bindingId: bindingA,
      contextId: v.rehydration.contextId,
      caseRevision: '1',
      inputs: [voiceInput, textInput],
      responses: [voiceReply, textReply],
    };
    let blockRead = true;
    await page.route('**/p2/context', async (route) => {
      if (blockRead)
        await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
      else await route.continue();
    });
    await page.locator('#native-context-refresh').click();
    await expect(page.locator('#native-context-phase')).toHaveText('Current read unavailable');
    expect((await evidence(page)).rehydration.contextId).toBe(a.contextId);
    await expect(page.locator('#native-send')).toBeDisabled();
    blockRead = false;
    await page.locator('#native-context-refresh').click();
    await expect(page.locator('#native-readiness')).toHaveText('Native agent ready');
    expect((await evidence(page)).rehydration.historyReceipts).toHaveLength(2);
    stage = 'end_a';
    await end(page);
    await passwordEmpty(page);
    completed.push(groups[0]!);
    stage = 'sms';
    await page
      .locator('summary')
      .filter({ hasText: 'Continue through the local SMS fixture' })
      .click();
    await page.locator('#native-access').fill(token!);
    await page.locator('#native-sms').click();
    await expect(page.locator('#native-sms-state')).toHaveText(
      'SMS accepted. Rejoin to load the current case.',
    );
    expect((await evidence(page)).rehydration.smsKnown).toBe(true);
    await passwordEmpty(page);
    completed.push(groups[1]!);
    stage = 'join_b';
    await page.locator('#native-access').fill(token!);
    await page.locator('#native-join').click();
    await expect(page.locator('#native-readiness')).toHaveText('Native agent ready');
    v = await evidence(page);
    const restored = v.rehydration;
    expect(restored.caseRevision).toBe('2');
    expect(restored.caseSource).toBe('standalone_reference_v1');
    expect(restored.bindingId).not.toBe(bindingA);
    expect(restored.historyReceipts).toHaveLength(3);
    expect(new Set(restored.historyChannels)).toEqual(
      new Set(['voice_transcript', 'web_chat', 'sms']),
    );
    for (const r of [voiceInput, textInput])
      expect(restored.historyReceipts).toContain(r.receiptId);
    expect(v.responses).toHaveLength(0);
    expect(v.observations.completed_inputs).toBe(0);
    expect(restored.historicalResponses).toHaveLength(2);
    expect(new Set(restored.historicalResponses.map((r) => r.responseId))).toEqual(
      new Set(a.responses.map((r) => r.responseId)),
    );
    for (const r of restored.historicalResponses) {
      expect(r.bindingId).toBe(bindingA);
      expect(r.historical).toBe(true);
      const panel = page.locator(`[data-historical-response="${r.responseId}"]`);
      await expect(panel).toBeVisible();
      expect(await panel.locator('button').count()).toBe(0);
    }
    await expect(page.locator('[data-context-fact="check-in"]')).toHaveText('2030-01-13');
    await passwordEmpty(page);
    await mkdir(output!, { recursive: true, mode: 0o700 });
    await page.screenshot({ path: resolve(output!, 'rehydration-restored.png'), fullPage: true });
    stage = 'new_reply_b';
    await page.locator('#native-enable-audio').click();
    const newInput = await send(page, newText!);
    const newReply = await reply(page, newText!);
    const b = {
      bindingId: restored.bindingId,
      contextId: restored.contextId,
      caseRevision: '2',
      historyReceipts: restored.historyReceipts,
      historyChannels: restored.historyChannels,
      historicalResponses: restored.historicalResponses,
      input: newInput,
      response: newReply,
    };
    expect(new Set([...a.inputs, newInput].map((r) => r.operationKey)).size).toBe(3);
    expect(new Set([...a.responses, newReply].map((r) => r.generationId)).size).toBe(3);
    stage = 'end_b';
    await end(page);
    expect((await evidence(page)).inputs).toHaveLength(3);
    await passwordEmpty(page);
    completed.push(groups[2]!);
    expect(unexpected).toBe(0);
    expect(pageErrors).toBe(0);
    await writeFile(
      resolve(output!, 'rehydration-browser-observations.json'),
      JSON.stringify({
        schemaVersion: 1,
        status: 'passed',
        mode: 'local_scripted_p2_rehydration_browser',
        groups: completed,
        sessions: { A: a, B: b },
        smsKnown: true,
        refreshFailureRetained: true,
        actualBrowserAudio: true,
        physicalHearingClaimed: false,
        readOnlyLoadGeneratedReplies: 0,
        cleanupComplete: true,
        pageErrors,
        unexpectedNetworkRequests: unexpected,
      }) + '\n',
      { mode: 0o600 },
    );
    stage = 'complete';
  } finally {
    await mkdir(output!, { recursive: true, mode: 0o700 });
    try {
      await evidence(page);
    } catch {
      /* Original bounded stage survives a page timeout. */
    }
    await writeFile(
      resolve(output!, 'rehydration-browser-context.json'),
      JSON.stringify({
        schemaVersion: 1,
        stage,
        groups: completed,
        pageErrors,
        unexpectedNetworkRequests: unexpected,
        connection: latest?.connection ?? null,
        ready: latest?.ready ?? null,
        phase: latest?.rehydration.phase ?? null,
        caseRevision: latest?.rehydration.caseRevision ?? null,
        inputStates: latest?.inputs.map((r) => r.status) ?? null,
        responseStates:
          latest?.responses.map((r) => ({
            sdkState: r.sdk_state,
            browserState: r.browser_state,
            generated: r.generated_observed,
            observedAudioMs: r.observed_audio_ms,
          })) ?? null,
      }) + '\n',
      { mode: 0o600 },
    );
  }
});
