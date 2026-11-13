/** Explicit real inference through actual WebRTC; no routed model responses. */
import { expect, test } from '@playwright/test';
import type { APIRequestContext, Page, Request as BrowserRequest, Response } from '@playwright/test';
import { access as fileAccess, mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createRequire } from 'node:module';

const token = process.env.E2E_OPERATOR_TOKEN, runId = process.env.E2E_RUN_ID, coordination = process.env.E2E_COORDINATION_DIR;
if (!token || token.length < 16 || token.length > 512 || /\s/.test(token) || !runId || !/^[0-9a-f]{32}$/.test(runId) || !coordination) throw new Error('The isolated real-media credential, invocation and coordination directory are required.');
const profile = process.env.E2E_REAL_PROFILE ?? 'local_real';
if (profile !== 'local_real' && profile !== 'provider_real') throw new Error('A declared real inference profile is required.');
const output = resolve(process.env.E2E_REPORT_DIR ?? '.local/validation/real-browser');
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const runtimePackage = createRequire(import.meta.url)('@playwright/test/package.json') as { version: string };
type Phase = 'prepare' | 'submit' | 'join' | 'input' | 'cohort' | 'end' | 'reconnect' | 'slow_postgres' | 'held_supplier' | 'confirm';
type MintAttempt = { http_status: number; error_code: string; same_room: boolean; same_identity: boolean; same_task: boolean; same_invocation: boolean; same_body: boolean };
type MintJoin = { attempts: MintAttempt[]; overflowed: boolean; completed: boolean };
const observations = {
  schema_version: 1, mode: profile, run_id: runId, foreground_task_id: '', browser_version: '', playwright_version: runtimePackage.version, last_phase: 'prepare' as Phase,
  isolated_local_stack: true, real_http: true, native_room: false, native_agent: false, verified_real_profile: false,
  explicit_fixture_publication: false, fixture_input_committed: false, generated_audio_played: false, fresh_response_played: false, active_speech_interrupted: false,
  case_survived_voice_end: false, same_task_fresh_consumer: false, fresh_media_identities: false,
  cohort_pending_before_end: false, cohort_pending_after_end: false, cohort_completed_after_end: false,
  slow_pg_wait_observed: false, slow_pg_interrupt_while_held: false, slow_pg_mute_while_held: false,
  slow_supplier_quote_pending: false, slow_supplier_interrupt_while_held: false, slow_supplier_mute_while_held: false,
  no_mutation_before_human: false, exact_quote_confirmed: false, passwords_empty_before_screenshots: false,
  audio_current_time: 0, active_interrupt_seconds: 0, pg_interrupt_seconds: 0, supplier_interrupt_seconds: 0,
  unexpected_network_requests: 0, native_sessions: 0, background_accepted: 0, background_pending_at_end: 0, background_completed_after_end: 0,
  supplier_outcome: 'not_observed', delivery_state: 'not_observed',
  session_mint_http_status: 0, session_mint_error_code: 'not_observed', session_mint_joins: [] as MintJoin[],
};
type MediaIdentity = { room: string; identity: string; task_id: string; invocation_id: string };
const successfulIdentities: MediaIdentity[] = [];
const marker = (name: string): string => resolve(coordination!, name);
async function exists(name: string): Promise<boolean> { try { await fileAccess(marker(name)); return true; } catch { return false; } }
async function signal(name: string, value = '1\n'): Promise<void> { await writeFile(marker(name), value, { encoding: 'utf-8', flag: 'wx', mode: 0o600 }); }
async function wait(name: string, timeout = 45_000): Promise<void> { await expect.poll(() => exists(name), { intervals: [25, 50, 100], timeout, message: 'The actual owned dependency milestone must be observed' }).toBe(true); }
async function save(): Promise<void> { await mkdir(output, { recursive: true }); await writeFile(resolve(output, 'real-browser-observations.json'), JSON.stringify(observations, null, 2) + '\n'); }
async function access(page: Page): Promise<void> { await page.locator('#access-token').evaluate((element, value) => { (element as HTMLInputElement).value = value; element.dispatchEvent(new Event('input', { bubbles: true })); }, token!); }
async function projection(request: APIRequestContext): Promise<Record<string, unknown>> {
  const response = await request.get(`/api/business/cases/${observations.foreground_task_id}?limit=10`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => { throw new Error('The scoped local HTTP read did not complete.'); });
  expect(response.status()).toBe(200); const value = await response.json() as Record<string, unknown>; expect(value.task_id).toBe(observations.foreground_task_id); return value;
}
function observe(page: Page): void {
  page.on('request', (request) => {
    const url = new URL(request.url()); if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) observations.unexpected_network_requests += 1;
  });
}
async function resume(page: Page): Promise<void> {
  await page.goto('/'); await access(page);
  await page.locator('#business-resume-id').fill(observations.foreground_task_id);
  await page.locator('#business-resume').click();
  await expect(page.locator('#business-task-id')).toHaveText(observations.foreground_task_id);
  // The task identity is displayed before the scoped refresh has a validated
  // projection. Voice Join requires that actual projection, not its early echo.
  await expect(page.locator('#business-inquiry-state')).toHaveText('succeeded');
  await expect(page.locator('#business-case-id')).toHaveText(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12} \/ (0|[1-9][0-9]*)$/);
}
async function diagnostics(page: Page): Promise<Record<string, unknown>> { const raw = await page.locator('#voice-identity').textContent(); if (!raw || raw.length > 16384) throw new Error('Bounded native profile diagnostics are required.'); return JSON.parse(raw) as Record<string, unknown>; }
const sessionMintErrorCodes = new Set<string>(['business_unavailable', 'response_too_large', 'execution_not_found', 'unsupported_operation', 'stale_revision', 'transition_conflict', 'quote_expired', 'invalid_confirmation', 'case_cancelled', 'intent_committed', 'invalid_stored_state', 'schema_version_unsupported', 'session_in_use', 'source_quiesced', 'authentication_required', 'forbidden', 'route_not_found', 'method_not_allowed', 'request_timeout', 'idempotency_conflict', 'request_too_large', 'validation_error', 'rate_limited', 'capacity_exhausted', 'dependency_unavailable', 'dispatch_unavailable', 'storage_limit_reached', 'storage_unavailable', 'service_unavailable', 'http_error', 'internal_error']);
async function sessionMintCode(response: Response): Promise<string> {
  if (response.status() === 200) return 'none';
  // Error bodies stay transient; retain only a fixed category if bounded and
  // readable. The production client may already have cancelled a failed body.
  try {
    const length = await response.headerValue('content-length');
    if (length === null || !/^[0-9]{1,4}$/.test(length) || Number(length) > 4096) return 'unclassified';
    const body = await response.body(); if (body.byteLength > 4096) return 'unclassified';
    const value: unknown = JSON.parse(body.toString('utf8'));
    if (value !== null && typeof value === 'object' && !Array.isArray(value) && 'code' in value && typeof value.code === 'string' && sessionMintErrorCodes.has(value.code)) return value.code;
  } catch { /* Private parser/transport errors never enter evidence. */ }
  return 'unclassified';
}
function mintBinding(value: unknown): MediaIdentity | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join(',') !== 'identity,invocation_id,room,task_id') return null;
  const body = value as Record<string, unknown>;
  if (typeof body.room !== 'string' || !/^business-[a-z0-9][a-z0-9-]{0,47}$/.test(body.room) || typeof body.identity !== 'string' || !/^browser-[a-z0-9][a-z0-9-]{0,47}$/.test(body.identity) || typeof body.task_id !== 'string' || !uuid.test(body.task_id) || typeof body.invocation_id !== 'string' || !uuid.test(body.invocation_id)) return null;
  return { room: body.room, identity: body.identity, task_id: body.task_id, invocation_id: body.invocation_id };
}
function sessionRequest(request: BrowserRequest): boolean { return request.method() === 'POST' && new URL(request.url()).pathname === '/api/business/session'; }
async function join(page: Page): Promise<void> {
  observations.last_phase = 'join'; await page.locator('#voice-input-source').selectOption('scripted');
  expect(observations.session_mint_joins.length).toBeLessThan(4);
  const joined: MintJoin = { attempts: [], overflowed: false, completed: false }; observations.session_mint_joins.push(joined);
  const requests = new Map<BrowserRequest, MintAttempt>(), responses = new Map<BrowserRequest, Response>(), codes: Promise<void>[] = [];
  let count = 0, frozen: MediaIdentity | null = null, frozenBody: string | null = null;
  const observeRequest = (request: BrowserRequest): void => {
    if (!sessionRequest(request)) return;
    count += 1; if (count > 3) { joined.overflowed = true; return; }
    let body: MediaIdentity | null = null, raw: string | null = null;
    try { raw = request.postData(); body = mintBinding(request.postDataJSON()); } catch { /* Retain only failed binding booleans. */ }
    if (count === 1) { frozen = body; frozenBody = raw; }
    const attempt: MintAttempt = { http_status: 0, error_code: 'not_observed', same_room: body !== null && frozen !== null && body.room === frozen.room, same_identity: body !== null && frozen !== null && body.identity === frozen.identity, same_task: body !== null && frozen !== null && body.task_id === frozen.task_id && body.task_id === observations.foreground_task_id, same_invocation: body !== null && frozen !== null && body.invocation_id === frozen.invocation_id, same_body: raw !== null && frozenBody !== null && raw === frozenBody };
    joined.attempts.push(attempt); requests.set(request, attempt);
  };
  const observeResponse = (response: Response): void => {
    const attempt = requests.get(response.request()); if (!attempt) return;
    responses.set(response.request(), response); attempt.http_status = response.status(); attempt.error_code = response.status() === 200 ? 'none' : 'unclassified';
    if (joined.attempts.at(-1) === attempt) { observations.session_mint_http_status = attempt.http_status; observations.session_mint_error_code = attempt.error_code; }
    codes.push(sessionMintCode(response).then((code) => { attempt.error_code = code; if (joined.attempts.at(-1) === attempt) observations.session_mint_error_code = code; }));
  };
  const observeFailure = (request: BrowserRequest): void => { const attempt = requests.get(request); if (attempt && !responses.has(request)) { attempt.http_status = 0; attempt.error_code = 'transport_error'; if (joined.attempts.at(-1) === attempt) { observations.session_mint_http_status = 0; observations.session_mint_error_code = 'not_observed'; } } };
  page.on('request', observeRequest); page.on('response', observeResponse); page.on('requestfailed', observeFailure);
  try {
    await page.locator('#voice-connect').click();
    // The existing product client owns at most three identical mint attempts.
    // Its supported 503/504 recovery must finish before actual RTC/RoomIO proof.
    await expect(page.locator('#voice-connection')).toHaveText('Connected');
    await Promise.all(codes);
    expect(joined.overflowed).toBe(false); expect(joined.attempts.length).toBeGreaterThan(0); expect(joined.attempts.length).toBeLessThanOrEqual(3);
    for (const [index, attempt] of joined.attempts.entries()) {
      for (const field of ['same_room', 'same_identity', 'same_task', 'same_invocation', 'same_body'] as const) expect(attempt[field]).toBe(true);
      if (index < joined.attempts.length - 1) expect([503, 504].includes(attempt.http_status) || (attempt.http_status === 0 && attempt.error_code === 'transport_error')).toBe(true);
      else { expect(attempt.http_status).toBe(200); expect(attempt.error_code).toBe('none'); }
    }
    const minted = [...responses.values()].find((response) => response.status() === 200);
    expect(minted !== undefined).toBe(true); if (!minted) throw new Error('The current logical join requires a successful mint.');
    expect((await minted.json() as Record<string, unknown>).mode).toBe(profile);
    await expect(page.locator('#voice-microphone')).toBeEnabled();
    const state = await diagnostics(page); expect(state.mode).toBe(profile); expect(state.profile_configured).toBe(true); expect(state.profile_verified).toBe(true); await expect(page.locator('#voice-profile')).toHaveAttribute('data-inference-mode', profile); await expect(page.locator('#voice-profile')).toHaveAttribute('data-profile-state', 'matched'); expect(state.session_ready).toBe(true); expect(state.agent_present).toBe(true);
    if (frozen === null) throw new Error('The logical join requires its validated original binding.');
    successfulIdentities.push(frozen); joined.completed = true;
    observations.native_sessions += 1; observations.native_room = true; observations.native_agent = true; observations.verified_real_profile = true;
  } finally { page.off('request', observeRequest); page.off('response', observeResponse); page.off('requestfailed', observeFailure); }
}
async function audioTime(page: Page): Promise<number> { return page.locator('#voice-audio audio').evaluateAll((elements) => Math.max(0, ...elements.map((element) => { const audio = element as HTMLAudioElement; return audio.readyState >= 2 && audio.played.length > 0 ? audio.currentTime : 0; }))); }
async function played(page: Page, before: number): Promise<void> { await expect.poll(() => audioTime(page), { timeout: 45_000, message: 'Actual generated audio must advance in the browser media clock' }).toBeGreaterThan(before + 0.05); observations.audio_current_time = Math.max(observations.audio_current_time, await audioTime(page)); }
async function transcripts(page: Page): Promise<number> { return page.locator('#voice-transcripts li:not(.voice-empty)').count(); }
async function interrupted(page: Page): Promise<number> {
  const started = performance.now(); await page.locator('#voice-interrupt').click(); await expect(page.locator('#voice-turn')).toHaveText('Interrupted'); const seconds = (performance.now() - started) / 1000;
  expect(seconds).toBeGreaterThan(0); expect(seconds).toBeLessThanOrEqual(1.5); return seconds;
}
async function screenshot(page: Page, name: 'workspace.png' | 'case-completed.png'): Promise<void> {
  expect(await page.locator('input[type="password"]').evaluateAll((elements) => elements.every((element) => (element as HTMLInputElement).value === ''))).toBe(true);
  observations.passwords_empty_before_screenshots = true; await page.screenshot({ path: resolve(output, name), fullPage: true });
}
async function end(page: Page): Promise<void> { observations.last_phase = 'end'; await page.locator('#voice-end').click(); await expect(page.locator('#voice-connection')).toHaveText('Disconnected'); }

test.describe.serial('P1 actual model and media qualification', () => {
  test.beforeAll(async ({ browser }) => { await mkdir(output, { recursive: true }); observations.browser_version = browser.version(); expect(observations.playwright_version).toBe('1.65.0'); });
  // Failure output is fixed-schema numeric/boolean evidence. Model text stays
  // transient in the private page; Playwright trace/video/HAR remain disabled.
  test.afterEach(async () => { await save(); });

  test('runs actual fixture inference, ends with eight accepted inquiries, and resumes the same case', async ({ page, request }) => {
    observe(page); observations.last_phase = 'submit'; await page.goto('/'); await access(page);
    await page.locator('#business-booking').fill('DEMO-BK-001'); await page.locator('#business-check-in').fill('2030-12-10'); await page.locator('#business-investigation').check(); await page.locator('#business-submit').click(); await expect(page.locator('#business-task-id')).toHaveText(uuid);
    observations.foreground_task_id = (await page.locator('#business-task-id').innerText()).trim();
    await expect.poll(async () => ((await projection(request)).inquiry as { state: string }).state).toBe('succeeded');
    await join(page); await played(page, 0); await expect(page.locator('#voice-speech')).not.toHaveText('Speaking');
    const before = await audioTime(page), beforeText = await transcripts(page); observations.last_phase = 'input';
    await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-microphone')).toHaveAttribute('aria-pressed', 'true'); observations.explicit_fixture_publication = true;
    await page.locator('#voice-start').click(); await expect(page.locator('#voice-turn')).toHaveText('Capturing');
    // A declared 4.25s real capture covers the immutable 3.99s WAV. This timing
    // collects PCM, and never invents a business progress observation.
    await page.waitForTimeout(4250); await page.locator('#voice-commit').click(); await expect(page.locator('#voice-turn')).toHaveText('Committed'); observations.fixture_input_committed = true;
    await expect(page.locator('#voice-speech')).toHaveText('Speaking'); await played(page, before); await expect.poll(() => transcripts(page)).toBeGreaterThan(beforeText); observations.generated_audio_played = true;
    await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-microphone')).toHaveAttribute('aria-pressed', 'false');
    const afterInput = await projection(request); expect(afterInput.outcome).toBeNull(); expect((afterInput.confirmation as { state: string }).state).toBe('not_requested');
    await expect(page.locator('#voice-speech')).not.toHaveText('Speaking'); const beforeStatus = await audioTime(page);
    await page.locator('#voice-status-request').click(); await expect(page.locator('#voice-speech')).toHaveText('Speaking'); await played(page, beforeStatus); await expect(page.locator('#voice-speech')).toHaveText('Speaking');
    observations.active_interrupt_seconds = await interrupted(page); await expect(page.locator('#voice-speech')).not.toHaveText('Speaking'); observations.active_speech_interrupted = true;
    await screenshot(page, 'workspace.png'); observations.last_phase = 'cohort'; await signal('real-foreground-task', observations.foreground_task_id + '\n'); await signal('real-cohort-arm'); await wait('real-cohort-pending');
    observations.cohort_pending_before_end = true; observations.background_accepted = 8; observations.background_pending_at_end = 8;
    await end(page); const afterEnd = await projection(request); expect(afterEnd.outcome).toBeNull(); expect((afterEnd.confirmation as { state: string }).state).toBe('not_requested'); observations.case_survived_voice_end = true;
    await signal('real-voice-ended'); await wait('real-cohort-survived-end'); observations.cohort_pending_after_end = true; await wait('real-cohort-complete', 90_000); observations.cohort_completed_after_end = true; observations.background_completed_after_end = 8;
    observations.last_phase = 'reconnect'; await join(page); await played(page, 0); await expect(page.locator('#voice-speech')).not.toHaveText('Speaking'); const freshBefore = await audioTime(page), freshText = await transcripts(page);
    await page.locator('#voice-status-request').click(); await expect(page.locator('#voice-speech')).toHaveText('Speaking'); await played(page, freshBefore); await expect.poll(() => transcripts(page)).toBeGreaterThan(freshText); observations.fresh_response_played = true;
    const distinct = [...new Map(successfulIdentities.map((identity) => [identity.invocation_id, identity])).values()]; expect(distinct).toHaveLength(2);
    expect(distinct.every((identity) => identity.task_id === observations.foreground_task_id && uuid.test(identity.invocation_id))).toBe(true);
    expect(distinct[0]!.room !== distinct[1]!.room && distinct[0]!.identity !== distinct[1]!.identity).toBe(true);
    for (const identity of successfulIdentities) { const frozen = distinct.find((item) => item.invocation_id === identity.invocation_id)!; expect(identity.room === frozen.room && identity.identity === frozen.identity && identity.task_id === frozen.task_id).toBe(true); }
    observations.same_task_fresh_consumer = true; observations.fresh_media_identities = true; await end(page);
  });

  test('keeps real media control responsive during actual waits and requires exact human quote approval', async ({ page, request }) => {
    observe(page); await resume(page); await join(page); await played(page, 0); await expect(page.locator('#voice-speech')).not.toHaveText('Speaking');
    await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-microphone')).toHaveAttribute('aria-pressed', 'true');
    observations.last_phase = 'slow_postgres'; await signal('slow-pg-arm'); await wait('slow-pg-held'); await page.locator('#voice-status-request').click(); await wait('slow-pg-observed'); observations.slow_pg_wait_observed = true;
    observations.pg_interrupt_seconds = await interrupted(page); expect(await exists('slow-pg-released')).toBe(false); observations.slow_pg_interrupt_while_held = true;
    await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-microphone')).toHaveAttribute('aria-pressed', 'false'); expect(await exists('slow-pg-released')).toBe(false); observations.slow_pg_mute_while_held = true; await wait('slow-pg-released'); await end(page);
    await join(page); await played(page, 0); await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-microphone')).toHaveAttribute('aria-pressed', 'true'); await expect(page.locator('#business-request-quote')).toBeEnabled();
    observations.last_phase = 'held_supplier'; await signal('slow-supplier-arm'); await wait('slow-supplier-held');
    let settled = false; const quoteRequest = page.waitForRequest((item) => item.method() === 'POST' && new URL(item.url()).pathname === `/api/business/cases/${observations.foreground_task_id}/quote`);
    const quoteResponse = page.waitForResponse((item) => item.request().method() === 'POST' && new URL(item.url()).pathname === `/api/business/cases/${observations.foreground_task_id}/quote`); void quoteResponse.then(() => { settled = true; }, () => { settled = true; });
    await page.locator('#business-request-quote').click(); await quoteRequest; await signal('slow-supplier-requested'); expect(settled).toBe(false); observations.slow_supplier_quote_pending = true;
    observations.supplier_interrupt_seconds = await interrupted(page); expect(await exists('slow-supplier-released')).toBe(false); observations.slow_supplier_interrupt_while_held = true;
    await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-microphone')).toHaveAttribute('aria-pressed', 'false'); expect(await exists('slow-supplier-released')).toBe(false); expect(settled).toBe(false); observations.slow_supplier_mute_while_held = true;
    await signal('slow-supplier-controls-done'); await wait('slow-supplier-released'); expect((await quoteResponse).status()).toBe(200); await end(page);
    observations.last_phase = 'confirm'; const before = await projection(request); expect(before.outcome).toBeNull(); expect(before.effect).toBeNull(); expect((before.confirmation as { state: string }).state).toBe('required'); observations.no_mutation_before_human = true;
    // The producer independently checks supplier apply_calls/mutations=0 before
    // acknowledging this barrier. A projection alone cannot establish no effect.
    await signal('real-before-human'); await wait('real-zero-apply-observed');
    const quote = before.quote as { confirmation_payload: string }; expect(typeof quote.confirmation_payload).toBe('string'); await expect(page.locator('#business-confirm')).toBeDisabled(); await page.locator('#business-approval').check();
    const signalRequest = page.waitForRequest((item) => item.method() === 'POST' && new URL(item.url()).pathname === `/api/business/cases/${observations.foreground_task_id}/signal`);
    await page.locator('#business-confirm').click(); const sent = (await signalRequest).postDataJSON() as Record<string, unknown>; expect(sent.explicit).toBe(true); expect(sent.confirmation_payload).toBe(quote.confirmation_payload);
    await expect.poll(async () => ((await projection(request)).outcome as { state?: string } | null)?.state).toBe('succeeded'); const after = await projection(request); expect(after.effect).not.toBeNull(); observations.exact_quote_confirmed = true; observations.supplier_outcome = 'succeeded'; observations.delivery_state = String((after.delivery as { state: string }).state);
    expect(['pending', 'delivering', 'delivered', 'exhausted']).toContain(observations.delivery_state); expect(observations.unexpected_network_requests).toBe(0); await screenshot(page, 'case-completed.png');
  });
});
