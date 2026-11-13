/** One real native RTC TEXT journey. Fixture markers synchronize; they grant no authority. */
import { test, expect, type Page } from '@playwright/test';
import { constants } from 'node:fs';
import { lstat, open, writeFile, link, unlink } from 'node:fs/promises';
import { isAbsolute, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { parseNativeJson } from '../src/p3-background-wire';
const output = process.env.P3_NATIVE_BROWSER_OUTPUT,
  access = process.env.P3_NATIVE_BROWSER_ACCESS;
if (!output || !isAbsolute(output) || !access || !/^[A-Za-z0-9_-]{43}(?![\s\S])/u.test(access))
  throw new Error('Explicit private P3 native browser fixture required.');
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/u,
  HASH = /^[0-9a-f]{64}(?![\s\S])/u;
const EVALUATE = 'evaluate the synthetic policy',
  QUESTION = 'what does read only mean?';
const USEFUL = 'A read-only policy review can explain the rule; it cannot change the booking.';
const FINAL = 'The synthetic policy result is available; it does not authorize a booking change.';
const groups = [
  'native_text_held_followup',
  'original_result_outdated_applicability',
  'read_failure_retry_and_forget',
] as const;
interface Identity {
  sessionId: string;
  caseId: string;
  delegationId: string;
  requestRevision: number;
  inputFingerprint: string;
}
interface Observation {
  state: string;
  workId: string | null;
  requestRevision: number;
  inputFingerprint: string;
  ownedRun: boolean;
  hasResult: boolean;
  applicability: string | null;
  resultSha256: string | null;
  disposition: string | null;
  attemptId: string | null;
  appReadCompletedAtMs: number;
}
interface Evidence {
  schemaVersion: 1;
  session: Identity | null;
  observation: Observation | null;
  phase: string;
  code: string | null;
  ready: boolean;
  ownedClient: number;
  actualRequests: number;
  actualSends: number;
  observationKnown: boolean;
  historical: boolean;
  messages: number;
  cleanupComplete: boolean;
}
interface ParentMarker {
  schema_version: 1;
  stage: string;
  session_id: string;
  work_id: string;
  request_revision: number;
  input_fingerprint: string;
  observed_case_revision: string;
}
const phases = [
  'idle',
  'joining',
  'connected',
  'reconnecting',
  'ending',
  'cleanup_incomplete',
  'disconnected',
];
const codes = [
  'invalid',
  'access_denied',
  'unavailable',
  'unknown',
  'overloaded',
  'closed',
  'cleanup_incomplete',
];
let latest: Evidence | null = null;
function record(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    Object.keys(value).length !== fields.length ||
    Object.keys(value).some((key) => !fields.includes(key))
  )
    throw new Error('Closed browser evidence required.');
  return value as Record<string, unknown>;
}
function count(value: unknown, maximum: number): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0 || value > maximum)
    throw new Error('Bounded browser counter required.');
  return value;
}
function bool(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new Error('Boolean browser observation required.');
  return value;
}
function text(value: unknown, pattern: RegExp): string {
  if (typeof value !== 'string' || !pattern.test(value))
    throw new Error('Scoped browser reference required.');
  return value;
}
function choice(value: unknown, values: readonly string[]): string {
  if (typeof value !== 'string' || !values.includes(value))
    throw new Error('Finite browser state required.');
  return value;
}
async function evidence(page: Page): Promise<Evidence> {
  const raw = await page.locator('[data-p3-evidence]').textContent();
  if (!raw) throw new Error('Browser evidence unavailable.');
  const v = record(parseNativeJson(raw, 4096), [
    'schemaVersion',
    'session',
    'observation',
    'phase',
    'code',
    'ready',
    'ownedClient',
    'actualRequests',
    'actualSends',
    'observationKnown',
    'historical',
    'messages',
    'cleanupComplete',
  ]);
  if (v.schemaVersion !== 1) throw new Error('Browser evidence version mismatch.');
  let session: Identity | null = null,
    observation: Observation | null = null;
  if (v.session !== null) {
    const s = record(v.session, [
      'sessionId',
      'caseId',
      'delegationId',
      'requestRevision',
      'inputFingerprint',
    ]);
    session = {
      sessionId: text(s.sessionId, UUID),
      caseId: text(s.caseId, /^[a-z][a-z0-9_-]{0,63}(?![\s\S])/u),
      delegationId: text(s.delegationId, /^[a-z][a-z0-9_-]{0,63}(?![\s\S])/u),
      requestRevision: count(s.requestRevision, 1000000),
      inputFingerprint: text(s.inputFingerprint, HASH),
    };
    if (session.requestRevision < 1)
      throw new Error('Positive original request revision required.');
  }
  if (v.observation !== null) {
    const o = record(v.observation, [
      'state',
      'workId',
      'requestRevision',
      'inputFingerprint',
      'ownedRun',
      'hasResult',
      'applicability',
      'resultSha256',
      'disposition',
      'attemptId',
      'appReadCompletedAtMs',
    ]);
    observation = {
      state: choice(o.state, ['no_work', 'work', 'result', 'outdated', 'unknown']),
      workId: o.workId === null ? null : text(o.workId, UUID),
      requestRevision: count(o.requestRevision, 1000000),
      inputFingerprint: text(o.inputFingerprint, HASH),
      ownedRun: bool(o.ownedRun),
      hasResult: bool(o.hasResult),
      applicability:
        o.applicability === null
          ? null
          : choice(o.applicability, [
              'missing',
              'candidate',
              'clarification',
              'outdated',
              'case_cancelled',
              'expired',
              'execution_ineligible',
              'unavailable',
            ]),
      resultSha256: o.resultSha256 === null ? null : text(o.resultSha256, HASH),
      disposition:
        o.disposition === null
          ? null
          : choice(o.disposition, [
              'eligible_at_commit',
              'cancelled',
              'expired',
              'superseded',
              'lease_expired',
            ]),
      attemptId: o.attemptId === null ? null : text(o.attemptId, UUID),
      appReadCompletedAtMs: count(o.appReadCompletedAtMs, 4102444800000),
    };
    if (
      !session ||
      session.requestRevision !== observation.requestRevision ||
      session.inputFingerprint !== observation.inputFingerprint
    )
      throw new Error('Browser read binding mismatch.');
  }
  latest = {
    schemaVersion: 1,
    session,
    observation,
    phase: choice(v.phase, phases),
    code: v.code === null ? null : choice(v.code, codes),
    ready: bool(v.ready),
    ownedClient: count(v.ownedClient, 1),
    actualRequests: count(v.actualRequests, 1),
    actualSends: count(v.actualSends, 1),
    observationKnown: bool(v.observationKnown),
    historical: bool(v.historical),
    messages: count(v.messages, 32),
    cleanupComplete: bool(v.cleanupComplete),
  };
  return latest;
}
async function verifyOutput(): Promise<void> {
  const s = await lstat(output!);
  if (
    !s.isDirectory() ||
    s.isSymbolicLink() ||
    s.uid !== process.getuid?.() ||
    (s.mode & 0o777) !== 0o700
  )
    throw new Error('Private owned browser output required.');
}
async function save(name: string, value: unknown): Promise<void> {
  const bytes = JSON.stringify(value) + '\n';
  if (Buffer.byteLength(bytes) > 4096) throw new Error('Bounded browser proof required.');
  await verifyOutput();
  const path = resolve(output!, name),
    pending = path + '.' + process.pid + '.pending';
  await writeFile(pending, bytes, { flag: 'wx', mode: 0o600 });
  try {
    await link(pending, path);
  } finally {
    await unlink(pending);
  }
}
async function readParent(name: string): Promise<ParentMarker | null> {
  const path = resolve(output!, name);
  let before;
  try {
    before = await lstat(path);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw new Error('Parent marker unavailable.');
  }
  if (
    before.nlink === 2 &&
    before.isFile() &&
    before.uid === process.getuid?.() &&
    (before.mode & 0o777) === 0o600
  )
    return null; // Complete atomic hardlink publication may be transient.
  if (
    !before.isFile() ||
    before.isSymbolicLink() ||
    before.uid !== process.getuid?.() ||
    before.nlink !== 1 ||
    (before.mode & 0o777) !== 0o600 ||
    before.size > 4096
  )
    throw new Error('Unsafe parent marker.');
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const opened = await file.stat();
    if (
      opened.ino !== before.ino ||
      opened.dev !== before.dev ||
      opened.size !== before.size ||
      opened.uid !== before.uid ||
      opened.mode !== before.mode ||
      opened.nlink !== 1 ||
      opened.mtimeMs !== before.mtimeMs ||
      opened.ctimeMs !== before.ctimeMs
    )
      throw new Error('Parent marker changed.');
    const rawBytes = Buffer.alloc(4097);
    let used = 0;
    while (used < rawBytes.byteLength) {
      const part = await file.read(rawBytes, used, rawBytes.byteLength - used, used);
      if (part.bytesRead === 0) break;
      used += part.bytesRead;
    }
    if (used > 4096 || used !== opened.size)
      throw new Error('Parent marker changed or exceeded its byte bound.');
    let bytes: string;
    try {
      bytes = new TextDecoder('utf-8', { fatal: true }).decode(rawBytes.subarray(0, used));
    } catch {
      throw new Error('Invalid parent marker encoding.');
    }
    const final = await file.stat();
    if (
      final.ino !== opened.ino ||
      final.dev !== opened.dev ||
      final.size !== opened.size ||
      final.uid !== opened.uid ||
      final.mode !== opened.mode ||
      final.nlink !== 1 ||
      final.mtimeMs !== opened.mtimeMs ||
      final.ctimeMs !== opened.ctimeMs
    )
      throw new Error('Parent marker changed.');
    const finalPath = await lstat(path);
    if (
      !finalPath.isFile() ||
      finalPath.isSymbolicLink() ||
      finalPath.ino !== final.ino ||
      finalPath.dev !== final.dev ||
      finalPath.size !== final.size ||
      finalPath.uid !== final.uid ||
      finalPath.mode !== final.mode ||
      finalPath.nlink !== 1 ||
      finalPath.mtimeMs !== final.mtimeMs ||
      finalPath.ctimeMs !== final.ctimeMs
    )
      throw new Error('Parent marker path changed.');
    const v = record(parseNativeJson(bytes, 4096), [
      'schema_version',
      'stage',
      'session_id',
      'work_id',
      'request_revision',
      'input_fingerprint',
      'observed_case_revision',
    ]);
    if (v.schema_version !== 1 || v.request_revision !== 1)
      throw new Error('Parent marker version mismatch.');
    return {
      schema_version: 1,
      stage: choice(v.stage, ['peer_held', 'case_advanced', 'specialist_released']),
      session_id: text(v.session_id, UUID),
      work_id: text(v.work_id, UUID),
      request_revision: 1,
      input_fingerprint: text(v.input_fingerprint, HASH),
      observed_case_revision: choice(v.observed_case_revision, ['1', '2']),
    };
  } finally {
    await file.close();
  }
}
async function waitParent(
  name: string,
  stage: string,
  revision: string,
  expected: Identity,
  workId?: string,
): Promise<ParentMarker> {
  let marker: ParentMarker | null = null;
  await expect
    .poll(
      async () => {
        marker = await readParent(name);
        return marker !== null;
      },
      { timeout: 10000, intervals: [10, 20, 40, 80] },
    )
    .toBe(true);
  if (!marker) throw new Error('Parent marker not observed.');
  const actual = marker as ParentMarker;
  expect(actual).toMatchObject({
    stage,
    observed_case_revision: revision,
    session_id: expected.sessionId,
    request_revision: expected.requestRevision,
    input_fingerprint: expected.inputFingerprint,
  });
  if (workId) expect(actual.work_id).toBe(workId);
  return actual;
}
test('one native policy session stays responsive and displays an original outdated result', async ({
  page,
}) => {
  await verifyOutput();
  let stage = 'opening',
    primary: unknown;
  let sdkRequests = 0,
    joinRequested = false,
    eagerSdk = false;
  let readRequests = 0,
    intercepted = 0,
    pageErrors = 0,
    externalRequests = 0,
    finalReply = false;
  let session: Identity | null = null,
    workId: string | null = null;
  let held: Evidence | null = null,
    outdated: Evidence | null = null,
    failed: Evidence | null = null,
    recovered: Evidence | null = null,
    forgotten: Evidence | null = null;
  const outcomes: { name: string; status: 'passed' }[] = [];
  page.on('pageerror', () => {
    pageErrors++;
  });
  page.on('request', (request) => {
    try {
      const url = new URL(request.url());
      if (url.pathname === '/v1/p3-native/observation') readRequests++;
      if (url.pathname.startsWith('/assets/livekit-client.esm-') && url.pathname.endsWith('.js')) {
        sdkRequests++;
        if (!joinRequested) eagerSdk = true;
      }
      if (
        !['data:', 'blob:'].includes(url.protocol) &&
        !['127.0.0.1', 'localhost'].includes(url.hostname)
      )
        externalRequests++;
    } catch {
      externalRequests++;
    }
  });
  async function refresh(): Promise<Evidence> {
    if (readRequests >= 16) throw new Error('Declared browser read ceiling reached.');
    await expect(page.locator('[data-p3-refresh]')).toBeEnabled();
    await page.locator('[data-p3-refresh]').click();
    await expect
      .poll(async () => (await evidence(page)).actualRequests, {
        timeout: 5000,
        intervals: [10, 20, 40, 80],
      })
      .toBe(0);
    return evidence(page);
  }
  async function screenshot(name: string): Promise<void> {
    await expect(page.locator('[data-p3-token]')).toHaveValue('');
    await page.screenshot({ path: resolve(output!, name), fullPage: true });
  }
  try {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto('/p3-background.html');
    // Initial short-desktop layout is checked before Join and outside the held invoke window.
    const firstViewport = await page.evaluate(async () => {
      await document.fonts.ready;
      return [
        '[data-p3-compose-form]',
        '[data-p3-message]',
        '[data-p3-send]',
        'h1',
        '.p3-connection',
        '.p3-result .p3-card-heading',
      ].map((selector) => {
        const box = document.querySelector(selector)!.getBoundingClientRect();
        return {
          selector,
          visible:
            box.width > 0 &&
            box.height > 0 &&
            box.top >= 0 &&
            box.bottom <= innerHeight &&
            box.left >= 0 &&
            box.right <= innerWidth,
        };
      });
    });
    expect(firstViewport.every((item) => item.visible)).toBe(true);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await expect(
      page.getByRole('heading', { name: 'Keep the conversation moving.' }),
    ).toBeVisible();
    await page.locator('[data-p3-setup] > summary').focus();
    await page.keyboard.press('Enter');
    expect(eagerSdk).toBe(false);
    expect(sdkRequests).toBe(0);
    await page.locator('[data-p3-token]').fill(access!);
    joinRequested = true;
    await page.locator('[data-p3-token]').press('Enter');
    await expect
      .poll(
        async () => {
          const e = await evidence(page);
          return e.phase === 'connected' && e.ready && e.session !== null;
        },
        { timeout: 15000 },
      )
      .toBe(true);
    expect(eagerSdk).toBe(false);
    expect(sdkRequests).toBeGreaterThanOrEqual(1);
    session = (await evidence(page)).session;
    if (!session) throw new Error('Authenticated session identity not observed.');
    await expect(page.locator('[data-p3-token]')).toHaveValue('');
    await expect(page.locator('[data-p3-message]')).toBeFocused();
    await test.step(groups[0], async () => {
      stage = 'held_followup';
      await page.locator('[data-p3-message]').fill(EVALUATE);
      await page.locator('[data-p3-message]').press('Enter');
      const marker = await waitParent('parent-peer-held.json', 'peer_held', '1', session!);
      held = await refresh();
      workId = held.observation?.workId ?? null;
      expect(held.observation).toMatchObject({
        state: 'work',
        workId: marker.work_id,
        requestRevision: 1,
        inputFingerprint: session!.inputFingerprint,
        ownedRun: true,
        hasResult: false,
        resultSha256: null,
        applicability: 'missing',
      });
      if (!workId) throw new Error('Actual held work not observed.');
      await expect(page.locator('[data-p3-message]')).toBeEnabled();
      await page.locator('[data-p3-message]').fill(QUESTION);
      await page.locator('[data-p3-message]').press('Enter');
      const reply = page
        .locator('.p3-message-agent .p3-message-text')
        .filter({ hasText: USEFUL })
        .first();
      await expect(reply).toBeVisible({ timeout: 5000 });
      const text = await reply.textContent();
      if (text !== USEFUL) throw new Error('Useful reply mismatch.');
      await save('browser-followup-observed.json', {
        schema_version: 1,
        stage: 'held_followup_observed',
        session_id: session!.sessionId,
        work_id: workId,
        request_revision: session!.requestRevision,
        input_fingerprint: session!.inputFingerprint,
        useful_reply_sha256: createHash('sha256').update(text).digest('hex'),
        no_result: true,
      });
      outcomes.push({ name: groups[0], status: 'passed' });
    });
    await test.step(groups[1], async () => {
      stage = 'outdated_result';
      await waitParent('parent-case-advanced.json', 'case_advanced', '2', session!, workId!);
      await waitParent(
        'parent-result-released.json',
        'specialist_released',
        '2',
        session!,
        workId!,
      );
      for (let count = 0; count < 12; count++) {
        outdated = await refresh();
        if (outdated.observation?.state === 'outdated') break;
        await page.waitForTimeout(50);
      }
      expect(outdated?.observation).toMatchObject({
        state: 'outdated',
        workId,
        requestRevision: 1,
        inputFingerprint: session!.inputFingerprint,
        hasResult: true,
        applicability: 'outdated',
      });
      expect([
        'eligible_at_commit',
        'cancelled',
        'expired',
        'superseded',
        'lease_expired',
      ]).toContain(outdated?.observation?.disposition);
      expect(outdated?.observation?.resultSha256).toMatch(HASH);
      expect(outdated?.observation?.attemptId).toMatch(UUID);
      await expect(page.locator('[data-p3-card]')).toContainText('Historical result · outdated');
      finalReply = await page
        .locator('.p3-message-agent .p3-message-text')
        .filter({ hasText: FINAL })
        .first()
        .isVisible();
      // Keyboard, reflow and captures are outside the actual specialist hold.
      const beforeDraft = await evidence(page);
      await page.locator('[data-p3-message]').fill('line one');
      await page.locator('[data-p3-message]').press('Shift+Enter');
      await page.locator('[data-p3-message]').pressSequentially('line two');
      await expect(page.locator('[data-p3-message]')).toHaveValue('line one\nline two');
      expect((await evidence(page)).messages).toBe(beforeDraft.messages);
      await page.locator('[data-p3-message]').fill('');
      await page.locator('[data-p3-card] summary').focus();
      await page.keyboard.press('Enter');
      await page.keyboard.press('Tab');
      expect(await page.evaluate(() => document.activeElement === document.body)).toBe(false);
      await screenshot('p3-native-outdated-desktop.png');
      await page.setViewportSize({ width: 360, height: 800 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      await screenshot('p3-native-outdated-mobile.png');
      outcomes.push({ name: groups[1], status: 'passed' });
    });
    await test.step(groups[2], async () => {
      stage = 'read_recovery';
      const intercept = async (route: import('@playwright/test').Route) => {
        intercepted++;
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          headers: { 'Cache-Control': 'no-store' },
          body: '{"schema_version":1,"kind":"native-policy.error","code":"unavailable"}',
        });
      };
      await page.route('**/v1/p3-native/observation', intercept);
      failed = await refresh();
      await page.unroute('**/v1/p3-native/observation', intercept);
      expect(failed).toMatchObject({ code: 'unavailable', historical: true });
      expect(failed.observation).toEqual(outdated!.observation);
      expect(intercepted).toBe(1);
      recovered = await refresh();
      expect(recovered).toMatchObject({ code: null, historical: false });
      expect(recovered.observation).toMatchObject({
        state: 'outdated',
        workId,
        resultSha256: outdated!.observation!.resultSha256,
        attemptId: outdated!.observation!.attemptId,
        disposition: outdated!.observation!.disposition,
      });
      stage = 'forget';
      await page.locator('[data-p3-forget]').click();
      await expect
        .poll(
          async () => {
            const e = await evidence(page);
            return (
              e.ownedClient === 0 &&
              e.actualRequests === 0 &&
              e.actualSends === 0 &&
              e.cleanupComplete
            );
          },
          { timeout: 10000 },
        )
        .toBe(true);
      forgotten = await evidence(page);
      expect(forgotten).toMatchObject({
        session: null,
        observation: null,
        messages: 0,
        ready: false,
      });
      await expect(page.locator('[data-p3-token]')).toHaveValue('');
      await expect(page.locator('[data-p3-message]')).toHaveValue('');
      await screenshot('p3-native-forgotten-mobile.png');
      expect(await evidence(page)).toMatchObject({
        session: null,
        observation: null,
        messages: 0,
        ownedClient: 0,
      });
      outcomes.push({ name: groups[2], status: 'passed' });
    });
    expect(pageErrors).toBe(0);
    expect(externalRequests).toBe(0);
    stage = 'complete';
    await save('browser-proof.json', {
      schema_version: 1,
      status: 'passed',
      mode: 'local_scripted_p3_native_text',
      groups: outcomes,
      session_id: session.sessionId,
      work_id: workId,
      request_revision: session.requestRevision,
      input_fingerprint: session.inputFingerprint,
      useful_reply_sha256: createHash('sha256').update(USEFUL).digest('hex'),
      final_reply_observed: finalReply,
      states: {
        held: {
          state: held!.observation!.state,
          owned_run: held!.observation!.ownedRun,
          result_observed: held!.observation!.hasResult,
        },
        outdated: {
          state: outdated!.observation!.state,
          result_sha256: outdated!.observation!.resultSha256,
          attempt_id: outdated!.observation!.attemptId,
          disposition: outdated!.observation!.disposition,
          applicability: outdated!.observation!.applicability,
        },
        failed: {
          code: failed!.code,
          historical: failed!.historical,
          original_facts_retained: true,
        },
        recovered: {
          state: recovered!.observation!.state,
          result_sha256: recovered!.observation!.resultSha256,
          historical: recovered!.historical,
        },
        forgotten: {
          owned_client: forgotten!.ownedClient,
          actual_requests: forgotten!.actualRequests,
          actual_sends: forgotten!.actualSends,
          cleanup_complete: forgotten!.cleanupComplete,
          private_facts_cleared:
            forgotten!.session === null &&
            forgotten!.observation === null &&
            forgotten!.messages === 0,
          password_empty: true,
          composer_empty: true,
        },
      },
      counters: {
        browser_read_requests: readRequests,
        fixture_read_interceptions: intercepted,
        page_errors: pageErrors,
        external_requests: externalRequests,
      },
      screenshots: [
        'p3-native-outdated-desktop.png',
        'p3-native-outdated-mobile.png',
        'p3-native-forgotten-mobile.png',
      ],
    });
  } catch (error) {
    primary = error;
  } finally {
    if (primary) {
      try {
        await page.locator('[data-p3-forget]').click({ timeout: 1000 });
      } catch {
        /* Parent retains actual process/service cleanup ownership. */
      }
    }
    try {
      await save('browser-context.json', {
        schema_version: 1,
        status: primary ? 'failed' : 'passed',
        stage,
        phase: latest?.phase ?? null,
        code: latest?.code ?? null,
        owned_client: latest?.ownedClient ?? null,
        actual_requests: latest?.actualRequests ?? null,
        cleanup_complete: latest?.cleanupComplete ?? false,
        page_errors: pageErrors,
        external_requests: externalRequests,
      });
    } catch {
      if (!primary) primary = new Error('Browser diagnostic retention unavailable.');
    }
  }
  if (primary) throw primary;
});
