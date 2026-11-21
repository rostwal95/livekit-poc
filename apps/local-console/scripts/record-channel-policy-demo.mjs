#!/usr/bin/env node
/** Drive the isolated scripted demo and record its observed browser journey. */
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const REPOSITORY = path.resolve(APP, '../..');
const { chromium } = createRequire(path.join(APP, 'package.json'))('@playwright/test');
const origin = new URL(process.env.DEMO_ORIGIN ?? 'http://127.0.0.1:5189');
if (
  origin.protocol !== 'http:' ||
  origin.hostname !== '127.0.0.1' ||
  origin.username ||
  origin.password ||
  origin.pathname !== '/' ||
  origin.search ||
  origin.hash
) {
  throw new Error('Expected a local demo origin.');
}
const [outputDirectory, ...flags] = process.argv.slice(2);
if (!outputDirectory || flags.some((flag) => flag !== '--verify')) {
  console.error('usage: record-channel-policy-demo.mjs <private-output-directory> [--verify]');
  process.exit(2);
}
const verify = flags.includes('--verify');
const name = 'demo';
const out = path.resolve(outputDirectory);
await fs.mkdir(out, { recursive: true, mode: 0o700 });

function operatorKey() {
  const result = spawnSync(path.join(REPOSITORY, 'demo'), ['key'], {
    cwd: REPOSITORY,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  });
  const key = (result.stdout ?? '').trim();
  if (result.status !== 0 || !/^[A-Za-z0-9_-]{32,128}$/.test(key))
    throw new Error('Run ./demo up before recording the demo.');
  return key;
}
const key = operatorKey();
const VIEWPORT = { width: 1440, height: 960 };

/** In-page tap: the agent's remote audio elements and the declared voice clip. */
function audioTap() {
  const Base = window.AudioContext;
  const original = Base.prototype.createMediaStreamDestination;
  let tap = null;
  const ensure = () => {
    if (tap) return tap;
    const context = new Base();
    const destination = original.call(context);
    // Chrome starts the recording timeline at the first audible frame; an
    // inaudible keep-alive tone anchors it to the recorder's start instead.
    const keepAlive = context.createOscillator();
    const level = context.createGain();
    keepAlive.frequency.value = 20;
    level.gain.value = 0.0001;
    keepAlive.connect(level).connect(destination);
    keepAlive.start();
    const recorder = new MediaRecorder(destination.stream, { mimeType: 'audio/webm;codecs=opus' });
    const chunks = [];
    recorder.ondataavailable = (event) => event.data.size && chunks.push(event.data);
    tap = { context, destination, recorder, chunks, wallStart: null, seen: new WeakSet() };
    window.__demoAudio = tap;
    // The recording timeline only advances while the context runs, so start the
    // recorder (and its wall-clock anchor) once the context is actually running.
    const begin = () => {
      if (context.state !== 'running' || recorder.state !== 'inactive') return;
      recorder.start(1000);
      tap.wallStart = Date.now();
    };
    context.addEventListener('statechange', begin);
    document.addEventListener('pointerdown', () => context.resume().catch(() => {}), true);
    context
      .resume()
      .then(begin)
      .catch(() => {});
    begin();
    return tap;
  };
  const connect = (stream) => {
    const t = ensure();
    if (t.seen.has(stream)) return;
    t.seen.add(stream);
    try {
      t.context.createMediaStreamSource(stream).connect(t.destination);
    } catch {
      // A stream without audio tracks has nothing to record.
    }
  };
  Base.prototype.createMediaStreamDestination = function (...args) {
    const node = original.apply(this, args);
    if (!tap || this !== tap.context) connect(node.stream);
    return node;
  };
  const property = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'srcObject');
  Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', {
    ...property,
    set(value) {
      property.set.call(this, value);
      if (value instanceof MediaStream && value.getAudioTracks().length) connect(value);
    },
  });
  ensure();
}

const steps = [];
const t0 = Date.now();
const mark = (step, extra = {}) => {
  const row = { step, ms: Date.now() - t0, ...extra };
  steps.push(row);
  console.log(JSON.stringify(row));
};

const browser = await chromium.launch({
  headless: true,
  args: ['--autoplay-policy=no-user-gesture-required'],
});
const context = await browser.newContext({
  viewport: VIEWPORT,
  colorScheme: 'dark',
  recordVideo: { dir: out, size: VIEWPORT },
});
await context.addInitScript(audioTap);
const page = await context.newPage();
const pageCreated = Date.now();

const view = () =>
  page.evaluate(() => {
    const q = (s) => document.querySelector(s)?.textContent?.trim() ?? '';
    return {
      state: q('[data-cp-state]'),
      native: q('[data-cp-native]'),
      mode: q('[data-cp-mode-label]'),
      previous: document.querySelectorAll('.cp-previous').length,
      audioTime: Math.max(
        0,
        ...[...document.querySelectorAll('[data-cp-audio] audio')].map(
          (element) => element.currentTime,
        ),
      ),
      speech: q('[data-cp-speech]'),
      textUnknown: document.querySelector('[data-cp-retry-text]')?.hidden === false,
      policy: q('[data-cp-policy-title]'),
      progress: q('[data-cp-progress]'),
      sms: q('[data-cp-sms-state]'),
      live: document.querySelectorAll('.cp-message.cp-live').length,
      agents: document.querySelectorAll('.cp-message-agent').length,
    };
  });
const business = () =>
  page.evaluate(() => {
    const q = (s) => document.querySelector(s)?.textContent?.trim() ?? '';
    return {
      task: q('#business-task-id'),
      stage: q('#business-state-title'),
      inquiry: q('#business-inquiry-state'),
      consent: q('#business-confirmation-state'),
      consentDisabled: document.querySelector('#business-confirm')?.disabled === true,
      outcome: q('#business-outcome-state'),
      delivery: q('#business-delivery-state'),
      approvable: document.querySelector('#business-approval')?.disabled === false,
    };
  });
async function until(label, predicate, seconds, read = view) {
  const end = Date.now() + seconds * 1000;
  let last;
  while (Date.now() < end) {
    last = await read();
    if (predicate(last)) {
      mark(label, {
        state: last.state ?? last.stage,
        policy: last.policy,
        progress: last.progress,
      });
      return last;
    }
    await page.waitForTimeout(250);
  }
  throw new Error(`${label} timed out: ${JSON.stringify(last)}`);
}
const linked = (v) => Number(/(\d+) linked/.exec(v.progress)?.[1] ?? 0);
const spoken = (label) =>
  until(label, (v) => v.live === 0 && v.speech !== 'Native SDK: speaking', 60);

async function caption(title, detail = '') {
  await page.evaluate(
    ([heading, body]) => {
      let card = document.getElementById('demo-caption');
      if (!card) {
        card = document.createElement('div');
        card.id = 'demo-caption';
        card.setAttribute('aria-hidden', 'true');
        card.innerHTML = '<strong></strong><span></span>';
        Object.assign(card.style, {
          position: 'fixed',
          left: '50%',
          bottom: '18px',
          transform: 'translateX(-50%)',
          width: 'min(1040px, 92vw)',
          padding: '14px 22px',
          borderRadius: '12px',
          border: '1px solid rgba(110, 231, 255, 0.55)',
          background: 'rgba(8, 12, 18, 0.92)',
          boxShadow: '0 12px 40px rgba(0, 0, 0, 0.45)',
          color: '#e8eef5',
          font: '500 17px/1.45 system-ui, -apple-system, Segoe UI, sans-serif',
          zIndex: '2147483646',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
          transition: 'opacity 240ms ease',
        });
        card.firstElementChild.style.cssText = 'color:#6ee7ff;font-size:18px;font-weight:650';
        card.lastElementChild.style.cssText = 'color:#b9c4d0;font-size:16px';
        document.body.append(card);
      }
      card.firstElementChild.textContent = heading;
      card.lastElementChild.textContent = body;
      card.style.opacity = heading ? '1' : '0';
    },
    [title, detail],
  );
  mark('caption', { title });
}
/** A full-page section card; credentials are only ever entered beneath it. */
async function titleCard(kicker, title = '', detail = '') {
  await page.evaluate(
    ([eyebrow, heading, body]) => {
      let card = document.getElementById('demo-title');
      if (!card) {
        card = document.createElement('div');
        card.id = 'demo-title';
        card.setAttribute('aria-hidden', 'true');
        card.innerHTML = '<small></small><strong></strong><span></span>';
        Object.assign(card.style, {
          position: 'fixed',
          inset: '0',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          gap: '14px',
          background: '#0b0e13',
          color: '#e8eef5',
          font: '500 18px/1.5 system-ui, -apple-system, Segoe UI, sans-serif',
          textAlign: 'center',
          zIndex: '2147483647',
          pointerEvents: 'none',
          transition: 'opacity 320ms ease',
        });
        card.children[0].style.cssText =
          'color:#6ee7ff;font:600 13px/1.4 ui-monospace,Menlo,monospace;letter-spacing:.16em';
        card.children[1].style.cssText = 'font-size:44px;font-weight:500;letter-spacing:-.01em';
        card.children[2].style.cssText = 'color:#b9c4d0;max-width:720px';
        document.body.append(card);
      }
      card.children[0].textContent = eyebrow;
      card.children[1].textContent = heading;
      card.children[2].textContent = body;
      card.style.opacity = eyebrow ? '1' : '0';
    },
    [kicker, title, detail],
  );
  mark('title', { title: kicker ? title : null });
}
const pause = (ms) => page.waitForTimeout(verify ? Math.min(ms, 500) : ms);
const collectAudio = () =>
  page
    .evaluate(async () => {
      const tap = window.__demoAudio;
      if (!tap || tap.wallStart === null || tap.recorder.state === 'inactive') return null;
      await new Promise((resolve) => {
        tap.recorder.onstop = resolve;
        tap.recorder.stop();
      });
      const bytes = new Uint8Array(await new Blob(tap.chunks).arrayBuffer());
      let text = '';
      for (let i = 0; i < bytes.length; i += 0x8000)
        text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      return { data: btoa(text), wallStart: tap.wallStart };
    })
    .catch(() => null);

function confirmPage(expectedPath) {
  const current = new URL(page.url());
  if (current.origin !== origin.origin || current.pathname !== expectedPath)
    throw new Error('The demo redirected to an unexpected page.');
}

async function unlockShowcase() {
  confirmPage('/channel-policy.html');
  await page.locator('[data-cp-setup] > summary').click();
  await page.locator('[data-cp-access]').evaluate((element, value) => {
    element.value = value;
    element.dispatchEvent(new Event('input', { bubbles: true }));
  }, key);
  await page.getByRole('button', { name: 'Use key', exact: true }).click();
  await until('unlocked', (v) => ['Ready to join', 'Session ended'].includes(v.state), 15);
  await page.locator('[data-cp-setup]').evaluate((details) => {
    details.open = false;
  });
}

async function showcase() {
  await caption(
    'One case across two sessions',
    'Three local projects: P1 durable case authority, P2 channel continuity, P3 delegated policy checks.',
  );
  await pause(3500);

  await caption(
    'Join a LiveKit voice session',
    'LiveKit runs the native voice session. The local demo uses scripted recognition and replies.',
  );
  await page.locator('[data-cp-join]').click();
  const ready = await until('ready', (v) => v.state === 'Ready', 45);
  if (ready.mode !== 'LOCAL / SCRIPTED' || linked(ready) !== 0)
    throw new Error('Recording requires a fresh scripted demo.');
  await page.locator('[data-cp-enable-audio]').click();
  const audioBeforeText = (await view()).audioTime;
  await pause(2500);

  await caption(
    'Ask by text',
    'P2 durably records the input, dispatches it to P1 as work, and P3 runs the policy check in the background.',
  );
  await page.locator('[data-cp-message]').click();
  await page
    .locator('[data-cp-message]')
    .pressSequentially('Hi, can I move my booking to a later date?', { delay: 28 });
  await pause(600);
  await page.locator('[data-cp-send]').click();
  const firstText = await until(
    'text-observed',
    (v) => linked(v) >= linked(ready) + 1 || v.textUnknown,
    30,
  );
  if (linked(firstText) === linked(ready)) {
    await caption(
      'Reconcile the original text turn',
      'The browser retries the original input identity after an unknown acknowledgement.',
    );
    await page.locator('[data-cp-retry-text]').click();
  }
  await until('text-linked', (v) => linked(v) >= linked(ready) + 1, 30);
  await until('text-reply', (v) => v.agents >= 1, 30);
  await until('text-audio-advanced', (v) => v.audioTime > audioBeforeText + 0.2, 30);
  await spoken('text-spoken');
  await caption(
    'The background check lands',
    'P3’s specialist answers against the case revision; the panel shows the applicable result as of its read time.',
  );
  await until('policy', (v) => v.policy === 'Eligible under the policy', 45);
  await pause(4000);

  await caption(
    'Speak instead',
    'A local clip travels over WebRTC. Scripted recognition assigns its transcript and the agent replies.',
  );
  await page.locator('[data-cp-mode-voice]').click();
  await page.locator('[data-cp-prepare-voice]').click();
  await page.waitForFunction(
    () => !document.querySelector('[data-cp-start-voice]')?.disabled,
    undefined,
    { timeout: 15000 },
  );
  const beforeVoice = await view();
  await page.locator('[data-cp-start-voice]').click();
  mark('voice-started');
  await page.waitForTimeout(5000);
  await page.locator('[data-cp-commit-voice]').click();
  await until('voice-linked', (v) => linked(v) >= linked(beforeVoice) + 1, 45);
  await until('voice-reply', (v) => v.agents >= beforeVoice.agents + 1, 45);
  await until('voice-audio-advanced', (v) => v.audioTime > beforeVoice.audioTime + 0.2, 30);
  await spoken('voice-spoken');
  await pause(2500);

  await caption(
    'Leave the call',
    'Ending the session releases the room. Durable work and results stay with P1 and P2.',
  );
  await page.locator('[data-cp-end]').click();
  await until('ended', (v) => v.state === 'Session ended', 45);
  await pause(2500);

  await caption(
    'Follow up by SMS',
    'A simulated SMS from the linked sender routes to the same case. It becomes new durable work without any open room.',
  );
  const smsField = page.locator('[data-cp-sms-message]');
  await page.evaluate(() => {
    const section = document.querySelector('[data-cp-dormant]');
    const bottom = section.getBoundingClientRect().bottom + window.scrollY;
    window.scrollTo({ top: Math.max(0, bottom - window.innerHeight + 150), behavior: 'smooth' });
  });
  await pause(1200);
  const beforeSms = await view();
  await smsField.click();
  await smsField.pressSequentially('Any update on moving my booking?', { delay: 28 });
  await pause(500);
  await page.locator('[data-cp-sms]').click();
  await until('sms-accepted', (v) => v.sms.startsWith('The original SMS receipt'), 30);
  await until('sms-linked', (v) => linked(v) >= linked(beforeSms) + 1, 45);
  await pause(3500);

  await caption(
    'Rejoin and pick up where you left off',
    'The new session rehydrates the case. Earlier messages stay visible as the previous session.',
  );
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await pause(1200);
  await page.locator('[data-cp-join]').click();
  await until(
    'rejoined',
    (v) =>
      v.state === 'Ready' &&
      v.previous >= 2 &&
      linked(v) === 3 &&
      v.policy === 'Eligible under the policy',
    45,
  );
  await page.screenshot({ path: path.join(out, name + '.png') });
  await pause(3000);

  await caption(
    'Model replies never authorize changes',
    'Exact quote confirmation stays outside the conversation. Every count and result above is an as-of source observation.',
  );
  await page.locator('[data-cp-end]').click();
  await until('final-ended', (v) => v.state === 'Session ended', 45);
  await pause(4000);
}

async function businessCase() {
  confirmPage('/operator.html');
  // A changing future date keeps repeated takes valid against the supplier fixture.
  const day = 10 + (Math.floor(Date.now() / 60000) % 18);
  const checkIn = process.env.DEMO_CHECK_IN ?? `2030-12-${String(day).padStart(2, '0')}`;
  await page.locator('#access-token').evaluate((element, value) => {
    element.value = value;
    element.dispatchEvent(new Event('input', { bubbles: true }));
  }, key);
  await page.getByRole('button', { name: 'Use key', exact: true }).click();
  await page.evaluate(() => {
    const top = document.querySelector('#business-form').getBoundingClientRect().top;
    window.scrollTo({ top: Math.max(0, top + window.scrollY - 210) });
  });
  await pause(1200);
  await titleCard('');
  await caption(
    'Start a durable case',
    'The operator submits a confirmed investigation. P1 persists the case before any supplier call.',
  );
  await pause(1500);
  await page.locator('#business-check-in').fill(checkIn);
  await page.locator('#business-investigation').check();
  await pause(700);
  await page.locator('#business-submit').click();
  await until('case-accepted', (v) => /^[0-9a-f-]{36}$/.test(v.task), 20, business);
  await caption(
    'The investigation runs on a leased worker',
    'The browser holds no workflow state. A PostgreSQL lease owns each step, and every field here is read back from storage.',
  );
  await until('inquiry-succeeded', (v) => v.inquiry === 'succeeded', 90, business);
  await pause(2500);

  await caption(
    'Request a trusted quote',
    'The supplier authority prices the exact change and binds its revision. No model output can supply or alter it.',
  );
  await page.locator('#business-request-quote').click();
  await until(
    'quote-required',
    (v) => v.consent === 'required' && v.approvable && v.consentDisabled,
    30,
    business,
  );
  await pause(3000);

  await caption(
    'Exact human confirmation',
    'Only explicit approval of this exact quote authorizes the booking change. It is committed once with its revision.',
  );
  await pause(1500);
  await page.locator('#business-approval').check();
  await pause(900);
  await page.locator('#business-confirm').click();
  await until('consent-committed', (v) => v.consent === 'committed', 30, business);

  await caption(
    'Supplier outcome, then delivery',
    'The worker applies the change once, records the supplier outcome and delivers the completion. Each is a separate fact.',
  );
  await until('outcome-succeeded', (v) => v.outcome === 'succeeded', 90, business);
  await until('delivery-delivered', (v) => v.delivery === 'delivered', 60, business);
  await pause(4500);
}

let failure = null;
let audio = null;
try {
  await page.goto(new URL('/', origin).href, { waitUntil: 'networkidle' });
  confirmPage('/');
  mark('trim');
  await pause(3000);
  await page.locator('a[href="/channel-policy.html"]').click();
  await page.waitForLoadState('networkidle');
  await titleCard(
    'CONTINUITY FOR LIVEKIT AGENTS',
    'Voice, text and simulated SMS',
    'Follow one travel case through a disconnect, background policy work and a fresh room.',
  );
  await unlockShowcase();
  await pause(1500);
  await titleCard('');
  await showcase();
  audio = await collectAudio();
  if (!audio || audio.data.length === 0) throw new Error('LiveKit audio was not captured.');
  await page.goto(new URL('/operator.html', origin).href, { waitUntil: 'networkidle' });
  await titleCard(
    'DURABLE BOOKING CASE',
    'From investigation to exact approval',
    'An operator reviews a specific revision and approves the quote.',
  );
  await pause(2000);
  await businessCase();
  await caption('');
  await titleCard(
    'CONTINUITY FOR LIVEKIT AGENTS',
    'Run the demo with Docker Compose',
    'The README links the walkthrough, architecture and verification.',
  );
  await pause(3600);
  mark('done');
} catch (error) {
  failure = error;
  mark('error', {
    message: String(error?.message ?? error)
      .replaceAll(key, '[redacted]')
      .slice(0, 400),
  });
  await page.screenshot({ path: path.join(out, 'error.png') }).catch(() => {});
}

const video = page.video();
await context.close();
await browser.close();
const rawVideo = path.join(out, 'raw-video.webm');
await fs.rename(await video.path(), rawVideo);
const trimRow = steps.find((row) => row.step === 'trim');
const timing = {
  pageCreatedMs: pageCreated - t0,
  audioOffsetMs: audio ? audio.wallStart - pageCreated : null,
  trimMs: trimRow ? trimRow.ms - (pageCreated - t0) : 0,
};
await fs.writeFile(path.join(out, 'steps.json'), JSON.stringify({ timing, steps }, null, 1));
let rawAudio = null;
if (audio) {
  rawAudio = path.join(out, 'raw-audio.webm');
  await fs.writeFile(rawAudio, Buffer.from(audio.data, 'base64'));
}

const ffmpeg = process.env.FFMPEG ?? 'ffmpeg';
if (!failure && !verify && spawnSync(ffmpeg, ['-version'], { stdio: 'ignore' }).status === 0) {
  const args = ['-y', '-loglevel', 'error', '-i', rawVideo];
  if (rawAudio) args.push('-itsoffset', String(timing.audioOffsetMs / 1000), '-i', rawAudio);
  args.push('-map', '0:v');
  if (rawAudio) args.push('-map', '1:a', '-c:a', 'aac', '-b:a', '128k');
  args.push(
    '-ss',
    String(Math.max(0, timing.trimMs - 300) / 1000),
    '-c:v',
    'libx264',
    '-preset',
    'slow',
    '-crf',
    '27',
    '-pix_fmt',
    'yuv420p',
    '-movflags',
    '+faststart',
    path.join(out, name + '.mp4'),
  );
  const result = spawnSync(ffmpeg, args, { stdio: 'inherit' });
  mark(result.status === 0 ? 'mp4' : 'mp4-failed');
  if (result.status !== 0) failure = new Error('MP4 encoding failed.');
} else if (!failure && !verify) {
  mark('mp4-unavailable', { reason: 'Set FFMPEG to an FFmpeg executable.' });
  failure = new Error('FFmpeg is unavailable.');
}
process.exit(failure ? 1 : 0);
