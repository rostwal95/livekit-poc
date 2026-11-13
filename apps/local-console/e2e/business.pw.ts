/** Real local HTTP, PostgreSQL worker and native WebRTC gate. No routed/mock projection data. */
import { expect, test } from '@playwright/test';
import type { APIRequestContext, Page } from '@playwright/test';
import { access as fileAccess, mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createRequire } from 'node:module';

const token = process.env.E2E_OPERATOR_TOKEN;
if (!token || token.length < 16 || token.length > 512 || /\s/.test(token)) throw new Error('E2E_OPERATOR_TOKEN must contain the isolated local operator credential.');
const booking = process.env.E2E_BOOKING_REFERENCE ?? 'DEMO-BK-001';
const date = process.env.E2E_NEW_CHECK_IN ?? '2030-12-10';
const output = resolve(process.env.E2E_REPORT_DIR ?? '.local/validation/browser');
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
let taskId = '';
const runtimePackage = createRequire(import.meta.url)('@playwright/test/package.json') as { version: string };
type LastPhase = 'submit' | 'resume' | 'join' | 'input' | 'interrupt' | 'reconnect' | 'slow_postgres' | 'held_supplier' | 'confirm';
const observations = { schema_version: 1, last_phase: 'submit' as LastPhase, last_status: '', voice_diagnostics_observed: false, voice_connected: false, voice_agent_present: false, voice_session_ready: false, voice_displayed_transcripts: 0, voice_text_sender_rejected_closed: 0, voice_text_sender_rejected_missing: 0, voice_text_sender_rejected_non_agent: 0, voice_text_sender_rejected_no_selection: 0, voice_text_sender_rejected_identity_mismatch: 0, voice_text_sender_rejected_local: 0, voice_text_streams_received: 0, voice_text_chunks_received: 0, voice_text_received_bytes: 0, voice_text_sender_rejected: 0, voice_text_capacity_rejected: 0, voice_text_read_completed: 0, voice_text_read_failed: 0, voice_text_completed_bytes: 0, voice_text_after_read_rejected: 0, voice_text_callback_accepted: 0, voice_text_callback_rejected: 0, voice_text_callback_stale: 0, browser_version: '', playwright_version: runtimePackage.version, isolated_local_stack: true, real_http: true, native_room: false, native_agent: false, explicit_input_publication: false, scripted_browser_input: false, scripted_input_stopped: false, input_committed: false, native_submit_acknowledged: false, audio_played: false, audio_current_time: 0, native_status_requested: false, speech_interrupt_acknowledged: false, active_speech_interrupted: false, same_task_reconnected: false, fresh_room_reconnected: false, native_reconnect_status_verified: false, case_survived_voice_end: false, reload_resumed_same_task: false, microphone_denial_verified: false, slow_pg_native_wait_observed: false, slow_pg_native_interrupt_acknowledged: false, slow_pg_media_control_responsive: false, slow_pg_replay_same_task: false, slow_supplier_quote_pending: false, slow_supplier_native_interrupt_acknowledged: false, slow_supplier_media_control_responsive: false, slow_supplier_quote_resumed: false, exact_quote_confirmed: false, supplier_outcome: 'not_observed', delivery_state: 'not_observed', unexpected_network_requests: 0 };
async function snapshotSetupStatus(page: Page): Promise<void> {
  try { const status = page.locator('#voice-status'); if (await status.count() === 1) observations.last_status = (await status.textContent({ timeout: 1000 }) ?? '').trim().slice(0, 512); }
  catch { /* Closed or unavailable UI leaves no raw exception in evidence. */ }
}
async function snapshotVoiceDiagnostics(page: Page): Promise<void> {
  try {
    const raw = await page.locator('#voice-identity').textContent(); if (!raw) return;
    const value = JSON.parse(raw) as { connected?: unknown; agent_present?: unknown; session_ready?: unknown; displayed_transcripts?: unknown; text_diagnostics?: unknown };
    const counts = value.text_diagnostics as Record<string, unknown> | undefined;
    const keys = ['sender_rejected_closed', 'sender_rejected_missing', 'sender_rejected_non_agent', 'sender_rejected_no_selection', 'sender_rejected_identity_mismatch', 'sender_rejected_local', 'streams_received', 'chunks_received', 'received_bytes', 'sender_rejected', 'capacity_rejected', 'read_completed', 'read_failed', 'completed_bytes', 'after_read_rejected', 'callback_accepted', 'callback_rejected', 'callback_stale'] as const;
    if (!counts || keys.some((key) => typeof counts[key] !== 'number' || !Number.isSafeInteger(counts[key]) || Number(counts[key]) < 0 || Number(counts[key]) > 1_000_000_000) || typeof value.connected !== 'boolean' || typeof value.agent_present !== 'boolean' || typeof value.session_ready !== 'boolean' || typeof value.displayed_transcripts !== 'number' || !Number.isSafeInteger(value.displayed_transcripts) || value.displayed_transcripts < 0 || value.displayed_transcripts > 40) return;
    observations.voice_connected = value.connected; observations.voice_agent_present = value.agent_present; observations.voice_session_ready = value.session_ready; observations.voice_displayed_transcripts = value.displayed_transcripts;
    for (const key of keys) observations[`voice_text_${key}`] = Number(counts[key]); observations.voice_diagnostics_observed = true;
  } catch { /* Missing/closed pages remain explicitly unobserved; no raw diagnostics are retained. */ }
}
async function save(): Promise<void> { await mkdir(output, { recursive: true }); await writeFile(resolve(output, 'business-browser-observations.json'), JSON.stringify(observations, null, 2) + '\n', 'utf-8'); }
async function screenshot(page: Page, name: 'workspace.png' | 'case-completed.png'): Promise<void> {
  expect(await page.locator('input[type="password"]').evaluateAll((elements) => elements.every((element) => (element as HTMLInputElement).value === '')), 'All private input fields must be empty before image capture').toBe(true);
  await mkdir(output, { recursive: true }); await page.screenshot({ path: resolve(output, name), fullPage: true });
}
async function access(page: Page): Promise<void> {
  await expect(page.locator('#access-token')).toBeVisible();
  // Pass the private input as an evaluation argument; no trace/video/HAR or screenshots are recorded.
  await page.locator('#access-token').evaluate((element, value) => { (element as HTMLInputElement).value = value; element.dispatchEvent(new Event('input', { bubbles: true })); }, token!);
}
async function getProjection(request: APIRequestContext): Promise<Record<string, unknown>> {
  const response = await request.get(`/api/business/cases/${taskId}?limit=10`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => { throw new Error('The scoped local HTTP read did not complete.'); });
  expect(response.status(), 'Scoped case GET must authenticate against the actual local API').toBe(200);
  const value: unknown = await response.json();
  expect(value && typeof value === 'object', 'Actual projection is an object').toBe(true);
  const projection = value as Record<string, unknown>;
  expect(projection.task_id).toBe(taskId); return projection;
}
function observeNetwork(page: Page): void { page.on('request', (request) => { const url = new URL(request.url()); if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) observations.unexpected_network_requests += 1; }); }
async function resume(page: Page): Promise<void> {
  observations.last_phase = 'resume';
  await page.goto('/'); await access(page); await page.locator('#business-resume-id').fill(taskId); await page.locator('#business-resume').click();
  await expect(page.locator('#business-task-id')).toHaveText(taskId); await expect(page.locator('#business-state-badge')).toHaveText('Persisted observation'); await expect.poll(() => page.locator('#access-token').evaluate((element) => (element as HTMLInputElement).value === ''), { message: 'Private credential input must be cleared' }).toBe(true);
}
async function join(page: Page, source: 'scripted' | 'microphone' = 'scripted', phase: 'join' | 'reconnect' = 'join'): Promise<void> {
  observations.last_phase = phase;
  await page.locator('#voice-input-source').selectOption(source);
  await page.locator('#voice-connect').click(); await expect(page.locator('#voice-connection')).toHaveText('Connected'); await expect(page.locator('#voice-speech')).not.toHaveText('Agent absent'); await expect(page.locator('#voice-microphone')).toBeEnabled();
}

test.describe.serial('P1 actual local business and native voice', () => {
  test.beforeAll(async ({ browser }) => { observations.browser_version = browser.version(); expect(observations.playwright_version).toBe('1.65.0'); expect(observations.browser_version).toMatch(/^\d+\.\d+\.\d+\.\d+$/); });
  test.afterEach(async ({ page }) => { await snapshotSetupStatus(page); await snapshotVoiceDiagnostics(page); await save(); });
  test('accepts a managed case, exchanges native speech and reconnects the same task', async ({ page, request }) => {
    observations.last_phase = 'submit'; observeNetwork(page); await page.goto('/'); await access(page);
    await page.locator('#business-booking').fill(booking); await page.locator('#business-check-in').fill(date); await page.locator('#business-investigation').check(); await page.locator('#business-submit').click();
    await expect(page.locator('#business-task-id')).toHaveText(uuid); taskId = (await page.locator('#business-task-id').innerText()).trim(); await expect.poll(() => page.locator('#access-token').evaluate((element) => (element as HTMLInputElement).value === ''), { message: 'Private credential input must be cleared' }).toBe(true);
    const accepted = await getProjection(request); expect(accepted.outcome).toBeNull();
    const rooms: { room: string; identity: string; task_id: string; invocation_id: string }[] = [];
    page.on('request', (request) => { if (request.method() !== 'POST' || new URL(request.url()).pathname !== '/api/business/session') return; const body = request.postDataJSON() as { room: string; identity: string; task_id: string; invocation_id: string }; rooms.push({ room: body.room, identity: body.identity, task_id: body.task_id, invocation_id: body.invocation_id }); });
    await join(page); observations.native_room = true; observations.native_agent = true;
    await expect(page.locator('#voice-microphone')).toHaveAttribute('aria-pressed', 'false'); observations.last_phase = 'input';
    await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-microphone-state')).toHaveText('Prerecorded input publishing'); observations.explicit_input_publication = true; observations.scripted_browser_input = true;
    await page.locator('#voice-start').click(); await expect(page.locator('#voice-turn')).toHaveText('Capturing');
    // This is test audio capture duration, never a product progress transition.
    await page.waitForTimeout(800); await page.locator('#voice-commit').click(); await expect(page.locator('#voice-turn')).toHaveText('Committed'); observations.input_committed = true;
    await expect.poll(() => page.locator('#voice-audio audio').evaluateAll((elements) => Math.max(0, ...elements.map((element) => { const audio = element as HTMLAudioElement; return audio.readyState >= 2 && audio.played.length > 0 ? audio.currentTime : 0; }))), { timeout: 30_000, message: 'Native received audio must actually advance in a browser media element' }).toBeGreaterThan(0.05);
    observations.audio_current_time = await page.locator('#voice-audio audio').evaluateAll((elements) => Math.max(0, ...elements.map((element) => (element as HTMLAudioElement).currentTime))); observations.audio_played = true; await screenshot(page, 'workspace.png');
    await expect(page.locator('#voice-transcripts .voice-empty')).toHaveCount(0);
    await expect(page.locator('#voice-transcripts')).toContainText('Your investigation was accepted and continues independently.'); observations.native_submit_acknowledged = true;
    const audioBeforeStatus = await page.locator('#voice-audio audio').evaluateAll((elements) => Math.max(0, ...elements.map((element) => (element as HTMLAudioElement).currentTime)));
    await page.locator('#voice-status-request').click(); await expect(page.locator('#voice-status')).toContainText('Status requested through the native text input'); observations.native_status_requested = true;
    await expect(page.locator('#voice-speech')).toHaveText('Speaking');
    await expect.poll(() => page.locator('#voice-audio audio').evaluateAll((elements) => Math.max(0, ...elements.map((element) => (element as HTMLAudioElement).currentTime))), { message: 'The selected native agent must be speaking while received audio advances' }).toBeGreaterThan(audioBeforeStatus + 0.02);
    await expect(page.locator('#voice-speech')).toHaveText('Speaking'); observations.last_phase = 'interrupt'; await page.locator('#voice-interrupt').click(); await expect(page.locator('#voice-turn')).toHaveText('Interrupted'); observations.speech_interrupt_acknowledged = true;
    await expect(page.locator('#voice-speech')).not.toHaveText('Speaking'); observations.active_speech_interrupted = true;
    await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-microphone-state')).toHaveText('Prerecorded input stopped'); observations.scripted_input_stopped = true;
    await page.locator('#voice-end').click(); await expect(page.locator('#voice-connection')).toHaveText('Disconnected');
    const afterEnd = await getProjection(request); expect((afterEnd.confirmation as Record<string, unknown>).state).not.toBe('cancelled'); expect(afterEnd.outcome).toBeNull(); observations.case_survived_voice_end = true;
    await join(page, 'scripted', 'reconnect');
    const invocations = [...new Map(rooms.map((room) => [room.invocation_id, room])).values()]; expect(invocations).toHaveLength(2);
    const first = invocations[0]!, resumed = invocations[1]!; expect(first.room !== resumed.room && first.identity !== resumed.identity && first.invocation_id !== resumed.invocation_id).toBe(true); expect(first.task_id === taskId && resumed.task_id === taskId).toBe(true); expect(uuid.test(first.invocation_id) && uuid.test(resumed.invocation_id)).toBe(true);
    for (const room of rooms) { const frozen = invocations.find((item) => item.invocation_id === room.invocation_id)!; expect(room.room === frozen.room && room.identity === frozen.identity && room.task_id === frozen.task_id).toBe(true); }
    await page.locator('#voice-status-request').click(); await expect(page.locator('#voice-status')).toContainText('Status requested through the native text input');
    await expect(page.locator('#voice-transcripts')).toContainText('The workflow panel shows the latest durable state.'); observations.native_reconnect_status_verified = true; observations.same_task_reconnected = true; observations.fresh_room_reconnected = true;
    await page.locator('#voice-end').click(); await expect(page.locator('#voice-connection')).toHaveText('Disconnected'); expect(observations.unexpected_network_requests).toBe(0);
  });

  test('reloads with no credentials or case in browser storage and explicitly resumes scoped state', async ({ page, request }) => {
    observeNetwork(page); await resume(page); await page.reload();
    await expect.poll(() => page.locator('#access-token').evaluate((element) => (element as HTMLInputElement).value === ''), { message: 'Private credential input must be cleared' }).toBe(true); await expect(page.locator('#business-task-id')).toHaveText('Not observed');
    const state = await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length })); expect(state).toEqual({ local: 0, session: 0 });
    await access(page); await page.locator('#business-resume-id').fill(taskId); await page.locator('#business-resume').click(); await expect(page.locator('#business-task-id')).toHaveText(taskId); await expect(page.locator('#business-state-badge')).toHaveText('Persisted observation'); expect((await getProjection(request)).task_id).toBe(taskId); observations.reload_resumed_same_task = true;
  });

  test('handles explicitly denied microphone permission without cancelling accepted work', async ({ page, context, request }) => {
    observeNetwork(page); await context.grantPermissions([], { origin: new URL(process.env.E2E_BASE_URL!).origin }); await resume(page);
    const permission = await page.evaluate(async () => (await navigator.permissions.query({ name: 'microphone' as PermissionName })).state); expect(permission).toBe('denied');
    await join(page, 'microphone'); observations.last_phase = 'input'; await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-status')).toContainText('Microphone permission or capture was not acknowledged'); await expect(page.locator('#voice-microphone')).toHaveAttribute('aria-pressed', 'false'); await expect(page.locator('#voice-start')).toBeDisabled();
    await page.locator('#voice-end').click(); await expect(page.locator('#voice-connection')).toHaveText('Disconnected'); const current = await getProjection(request); expect(current.outcome).toBeNull(); expect((current.confirmation as Record<string, unknown>).state).not.toBe('cancelled'); observations.microphone_denial_verified = true;
  });

  test('keeps native media control responsive during an observed PostgreSQL advisory wait', async ({ page, request }) => {
    const directory = process.env.E2E_COORDINATION_DIR;
    if (!directory) throw new Error('E2E_COORDINATION_DIR is required for the isolated slow-PostgreSQL gate.');
    const marker = (name: string): string => resolve(directory, name);
    const exists = async (name: string): Promise<boolean> => { try { await fileAccess(marker(name)); return true; } catch { return false; } };
    const wait = async (name: string): Promise<void> => { await expect.poll(() => exists(name), { intervals: [25, 50, 100], timeout: 30_000, message: `Isolated fault helper must publish ${name}` }).toBe(true); };
    observeNetwork(page); await resume(page); const before = await getProjection(request);
    await join(page); await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-microphone-state')).toHaveText('Prerecorded input publishing');
    await page.locator('#voice-start').click(); await expect(page.locator('#voice-turn')).toHaveText('Capturing'); await page.waitForTimeout(800);
    observations.last_phase = 'slow_postgres'; await mkdir(directory, { recursive: true }); await writeFile(marker('slow-pg-arm'), '1\n', 'utf-8'); await wait('slow-pg-held');
    await page.locator('#voice-commit').click(); await expect(page.locator('#voice-turn')).toHaveText('Committed'); await wait('slow-pg-observed'); observations.slow_pg_native_wait_observed = true;
    // The helper proves a native-container advisory waiter and releases 500ms later.
    // Muting must complete during that observed wait; a delay alone never counts as evidence.
    await page.locator('#voice-interrupt').click(); await expect(page.locator('#voice-turn')).toHaveText('Interrupted');
    expect(await exists('slow-pg-released'), 'The native speech interrupt must acknowledge while its PostgreSQL access is still blocked').toBe(false); observations.slow_pg_native_interrupt_acknowledged = true;
    await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-microphone-state')).toHaveText('Prerecorded input stopped');
    expect(await exists('slow-pg-released'), 'Local microphone control must finish while native PostgreSQL access is still blocked').toBe(false); observations.slow_pg_media_control_responsive = true; await wait('slow-pg-released');
    await page.locator('#voice-end').click(); await expect(page.locator('#voice-connection')).toHaveText('Disconnected');
    const replay = await request.post('/api/business/investigations', { headers: { Authorization: `Bearer ${token}` }, data: { ...(before.inquiry as { request: Record<string, unknown> }).request, idempotency_key: before.request_key } }).catch(() => { throw new Error('The original local investigation replay did not complete.'); });
    expect(replay.status()).toBe(200); const receipt = await replay.json() as { created: boolean; task_id: string }; expect(receipt.created).toBe(false); expect(receipt.task_id).toBe(taskId);
    await join(page); await page.locator('#voice-end').click(); await expect(page.locator('#voice-connection')).toHaveText('Disconnected'); expect((await getProjection(request)).task_id).toBe(taskId); observations.slow_pg_replay_same_task = true;
  });

  test('keeps native media responsive while the actual supplier quote read is held', async ({ page, request }) => {
    const directory = process.env.E2E_COORDINATION_DIR;
    if (!directory) throw new Error('E2E_COORDINATION_DIR is required for the isolated held-supplier gate.');
    const marker = (name: string): string => resolve(directory, name);
    const exists = async (name: string): Promise<boolean> => { try { await fileAccess(marker(name)); return true; } catch { return false; } };
    const wait = async (name: string): Promise<void> => { await expect.poll(() => exists(name), { intervals: [25, 50, 100], timeout: 30_000, message: `Isolated fault helper must publish ${name}` }).toBe(true); };
    observeNetwork(page); await resume(page); await join(page);
    await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-microphone-state')).toHaveText('Prerecorded input publishing'); await expect(page.locator('#business-request-quote')).toBeEnabled();
    observations.last_phase = 'held_supplier'; await mkdir(directory, { recursive: true }); await writeFile(marker('slow-supplier-arm'), '1\n', 'utf-8'); await wait('slow-supplier-held');
    let responseSettled = false;
    const quoteRequest = page.waitForRequest((request) => request.method() === 'POST' && new URL(request.url()).pathname === `/api/business/cases/${taskId}/quote`);
    const quoteResponse = page.waitForResponse((response) => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/business/cases/${taskId}/quote`);
    void quoteResponse.then(() => { responseSettled = true; }, () => { responseSettled = true; });
    await page.locator('#business-request-quote').click(); await quoteRequest; await writeFile(marker('slow-supplier-requested'), '1\n', 'utf-8');
    expect(responseSettled, 'The real supplier-backed quote HTTP response must still be pending').toBe(false); observations.slow_supplier_quote_pending = true;
    await page.locator('#voice-interrupt').click(); await expect(page.locator('#voice-turn')).toHaveText('Interrupted');
    expect(await exists('slow-supplier-released'), 'Native interrupt must acknowledge before the supplier lock is released').toBe(false); observations.slow_supplier_native_interrupt_acknowledged = true;
    await page.locator('#voice-microphone').click(); await expect(page.locator('#voice-microphone-state')).toHaveText('Prerecorded input stopped');
    expect(await exists('slow-supplier-released'), 'Local mute must finish before the supplier lock is released').toBe(false); expect(responseSettled, 'The quote response remains pending while independent native media controls complete').toBe(false); observations.slow_supplier_media_control_responsive = true;
    await writeFile(marker('slow-supplier-controls-done'), '1\n', 'utf-8'); await wait('slow-supplier-released'); expect((await quoteResponse).status()).toBe(200); await expect(page.locator('#business-confirmation-state')).toHaveText('required'); observations.slow_supplier_quote_resumed = true;
    await page.locator('#voice-end').click(); await expect(page.locator('#voice-connection')).toHaveText('Disconnected'); const current = await getProjection(request); expect(current.task_id).toBe(taskId); expect(current.outcome).toBeNull();
  });

  test('confirms the exact current quote explicitly and observes supplier outcome apart from delivery', async ({ page, request }) => {
    observeNetwork(page); await resume(page); observations.last_phase = 'confirm'; await expect(page.locator('#business-confirmation-state')).toHaveText('required'); await expect(page.locator('#business-approval')).toBeEnabled();
    const before = await getProjection(request), quote = before.quote as Record<string, unknown>; expect(typeof quote.confirmation_payload).toBe('string');
    await expect(page.locator('#business-confirm')).toBeDisabled(); await page.locator('#business-approval').check();
    const command = page.waitForRequest((request) => request.method() === 'POST' && new URL(request.url()).pathname === `/api/business/cases/${taskId}/signal`);
    await page.locator('#business-confirm').click(); const sent = (await command).postDataJSON() as Record<string, unknown>; expect(sent.explicit).toBe(true); expect(sent.confirmation_payload).toBe(quote.confirmation_payload);
    await expect(page.locator('#business-confirmation-state')).toHaveText('committed');
    await expect.poll(async () => (await getProjection(request)).outcome, { timeout: 45_000 }).not.toBeNull();
    const current = await getProjection(request), outcome = current.outcome as Record<string, unknown>, delivery = current.delivery as Record<string, unknown> | null;
    expect(outcome.state).toBe('succeeded'); expect(current.effect).not.toBeNull(); expect(current.delivery).not.toBeNull();
    await expect(page.locator('#business-outcome-state')).toHaveText('succeeded'); observations.exact_quote_confirmed = true; observations.supplier_outcome = String(outcome.state); observations.delivery_state = String(delivery?.state ?? 'not_observed'); expect(['pending', 'delivering', 'delivered', 'exhausted']).toContain(observations.delivery_state); expect(observations.unexpected_network_requests).toBe(0); await screenshot(page, 'case-completed.png');
  });
});
