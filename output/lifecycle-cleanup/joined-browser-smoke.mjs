import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';

const root = '/Users/rostwal/Downloads/livekit-poc';
const out = path.resolve(process.env.LIFECYCLE_OUTPUT ?? path.join(root, 'output/lifecycle-cleanup'));
const { chromium } = createRequire(path.join(root, 'apps/local-console/package.json'))('@playwright/test');
const { profile } = JSON.parse(await fs.readFile(path.join(out, 'joined-profile.json'), 'utf8'));
const key = JSON.parse(await fs.readFile(path.join(profile, '.runtime/operator.json'), 'utf8')).bearer;
const proof = { mode: 'scripted', status: 'running', stages: [], pageErrors: 0,
  limits: 'Actual joined SDK/browser text, recorded voice and End smoke; no forced browser fault, provider or full release qualification.' };
const start = Date.now();
const save = async () => fs.writeFile(path.join(out, 'joined-browser-smoke.json'), JSON.stringify(proof, null, 2) + '\n');
const browser = await chromium.launch({ headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, colorScheme: 'dark' });
const page = await context.newPage();
page.on('pageerror', () => { proof.pageErrors++; });
const observe = () => page.evaluate(() => {
  const text = (selector) => document.querySelector(selector)?.textContent?.trim() ?? '';
  let evidence = {};
  try { evidence = JSON.parse(text('[data-cp-evidence]') || '{}'); } catch {}
  return { state: text('[data-cp-state]'), policy: text('[data-cp-policy-title]'),
    progress: text('[data-cp-progress]'), sms: text('[data-cp-sms-state]'),
    acceptedInputs: evidence.acceptedInputs ?? 0, sdkGenerations: evidence.sdkGenerationObservations ?? 0,
    roomOwned: evidence.roomOwned ?? false, previousRows: document.querySelectorAll('.cp-previous').length,
    played: [...document.querySelectorAll('audio')].some((el) => el.currentTime > 0.05),
    lastInput: evidence.lastInput ?? null };
});
const linked = (v) => Number(v.progress.match(/(\d+) linked to durable work/)?.[1] ?? 0);
async function until(label, predicate, seconds = 45) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const observed = await observe();
    if (predicate(observed)) {
      proof.stages.push({ stage: label, elapsedMs: Date.now() - start, observed });
      await save();
      return observed;
    }
    await page.waitForTimeout(100);
  }
  throw new Error('bounded_stage_timeout:' + label);
}
try {
  await page.goto('http://127.0.0.1:5179/channel-policy.html');
  await page.locator('[data-cp-setup] > summary').click();
  await page.locator('[data-cp-access]').fill(key);
  await page.getByRole('button', { name: 'Use key', exact: true }).click();
  await until('operator_ready', (v) => v.state === 'Ready to join', 15);
  assert.equal(await page.locator('[data-cp-access]').inputValue(), '');
  await page.locator('[data-cp-join]').click();
  const roomA = await until('room_a_ready', (v) => v.state === 'Ready');
  await page.locator('[data-cp-enable-audio]').click();
  await page.locator('[data-cp-message]').fill('Can I move my booking to a later date?');
  await page.locator('[data-cp-send]').click();
  const beforeEnd = await until('a_original_input_ack', (v) => v.acceptedInputs > roomA.acceptedInputs, 20);
  proof.endSchedule = { acceptedInputAckObserved: true, linkedBeforeEnd: linked(beforeEnd),
    sdkGenerationsBeforeEnd: beforeEnd.sdkGenerations, forcedDispatchHold: false };
  await page.locator('[data-cp-end]').click();
  await until('room_a_ended', (v) => v.state === 'Session ended');
  await until('original_input_linked_after_end', (v) => linked(v) >= 1, 30);
  await page.locator('[data-cp-sms-message]').fill('Any update on moving my booking?');
  await page.locator('[data-cp-sms]').click();
  await until('dormant_sms_accepted', (v) => v.sms.startsWith('The original SMS receipt'), 20);
  await until('dormant_sms_linked', (v) => linked(v) >= 2, 30);
  await page.locator('[data-cp-join]').click();
  const roomB = await until('room_b_ready_with_history', (v) => v.state === 'Ready' && v.previousRows > 0);
  await page.locator('[data-cp-enable-audio]').click();
  await page.locator('[data-cp-mode-voice]').click();
  await page.locator('[data-cp-prepare-voice]').click();
  await page.waitForFunction(() => !document.querySelector('[data-cp-start-voice]')?.disabled, undefined, { timeout: 15000 });
  await page.locator('[data-cp-start-voice]').click();
  await page.waitForTimeout(1600);
  await page.locator('[data-cp-commit-voice]').click();
  await until('b_recorded_voice_accepted', (v) => v.acceptedInputs > roomB.acceptedInputs, 25);
  await until('b_recorded_voice_linked', (v) => linked(v) >= 3, 30);
  await until('b_current_policy_and_playback', (v) => v.policy === 'Eligible under the policy' && v.played, 35);
  await page.screenshot({ path: path.join(out, 'joined-smoke.png') });
  await fs.writeFile(path.join(out, 'joined-browser-ready-for-stop.flag'), 'ready\n');
  const deadline = Date.now() + 130000;
  while (Date.now() < deadline) {
    try { await fs.access(path.join(out, 'joined-launcher-closed.flag')); break; } catch {}
    await page.waitForTimeout(100);
  }
  await fs.access(path.join(out, 'joined-launcher-closed.flag'));
  proof.stages.push({ stage: 'single_stop_observed_by_parent', elapsedMs: Date.now() - start });
  proof.status = 'passed';
} catch (error) {
  proof.status = 'failed';
  proof.code = error instanceof Error && error.message.startsWith('bounded_stage_timeout:')
    ? error.message : 'joined_smoke_failed';
  proof.lastObserved = await observe().catch(() => null);
  process.exitCode = 1;
} finally {
  await context.close();
  await browser.close();
  proof.browserClosed = true;
  await save();
  console.log(JSON.stringify({ status: proof.status, stages: proof.stages.length,
    browserClosed: proof.browserClosed, providerCalls: false }));
}
