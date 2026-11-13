#!/usr/bin/env node
/**
 * Records the joined three-project showcase as a narrated demo video.
 *
 * Needs a running showcase (`make channel-policy-demo-start-provider` or the
 * scripted `make channel-policy-demo-start`) on a fresh profile, because the
 * showcase window holds sixteen inputs and this journey adds four.
 *
 *   node scripts/record-channel-policy-demo.mjs <operator-key-file> <output-dir>
 *
 * Writes the raw page video, the captured agent/user audio, steps.json and, when
 * ffmpeg is available (FFMPEG or PATH), channel-policy-demo.mp4 plus a poster PNG.
 * The narration overlay exists only in the recording, never in the product UI.
 */
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { chromium } = createRequire(path.join(APP, 'package.json'))('@playwright/test');
const ORIGIN = process.env.DEMO_ORIGIN ?? 'http://127.0.0.1:5179';
const [keyFile, outArg] = process.argv.slice(2);
if (!keyFile || !outArg) {
  console.error('usage: record-channel-policy-demo.mjs <operator-key-file> <output-dir>');
  process.exit(2);
}
const out = path.resolve(outArg);
await fs.mkdir(out, { recursive: true });
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
      speech: q('[data-cp-speech]'),
      policy: q('[data-cp-policy-title]'),
      progress: q('[data-cp-progress]'),
      sms: q('[data-cp-sms-state]'),
      live: document.querySelectorAll('.cp-message.cp-live').length,
      agents: document.querySelectorAll('.cp-message-agent').length,
    };
  });
async function until(label, predicate, seconds) {
  const end = Date.now() + seconds * 1000;
  let last;
  while (Date.now() < end) {
    last = await view();
    if (predicate(last)) {
      mark(label, { state: last.state, policy: last.policy, progress: last.progress });
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
          zIndex: '2147483647',
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
const pause = (ms) => page.waitForTimeout(ms);

let failure = null;
try {
  await page.goto(ORIGIN + '/channel-policy.html', { waitUntil: 'networkidle' });
  const key = JSON.parse(await fs.readFile(keyFile, 'utf8')).bearer;
  await page.locator('[data-cp-setup] > summary').click();
  await page.locator('[data-cp-access]').fill(key);
  await page.getByRole('button', { name: 'Use key', exact: true }).click();
  await until('unlocked', (v) => ['Ready to join', 'Session ended'].includes(v.state), 15);
  await page.locator('[data-cp-setup]').evaluate((details) => {
    details.open = false;
  });
  mark('trim');
  await caption(
    'One case. Every conversation.',
    'Three local projects: P1 durable case authority, P2 channel continuity, P3 delegated policy checks.',
  );
  await pause(3500);

  await caption(
    'Join a LiveKit voice session',
    'P2 opens a native agent room. Deepgram, OpenAI and ElevenLabs run for real in this mode.',
  );
  await page.locator('[data-cp-join]').click();
  const ready = await until('ready', (v) => v.state === 'Ready', 45);
  await page.locator('[data-cp-enable-audio]').click();
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
  await until('text-linked', (v) => linked(v) >= linked(ready) + 1, 30);
  await until('text-reply', (v) => v.agents >= 1, 30);
  await spoken('text-spoken');
  await caption(
    'The background check lands',
    'P3’s specialist answers against the case revision; the panel shows the applicable result as of its read time.',
  );
  await until('policy', (v) => v.policy === 'Eligible under the policy', 45);
  await pause(4000);

  await caption(
    'Speak instead',
    'A declared recorded clip plays into the real RTC track. Deepgram transcribes it; the agent answers from the trusted result.',
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
  await pause(5000);
  await page.locator('[data-cp-commit-voice]').click();
  await until('voice-linked', (v) => linked(v) >= linked(beforeVoice) + 1, 45);
  await until('voice-reply', (v) => v.agents >= beforeVoice.agents + 1, 45);
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
  const rejoined = await until('rejoined', (v) => v.state === 'Ready', 45);
  await page.locator('[data-cp-enable-audio]').click();
  await page.locator('[data-cp-mode-text]').click();
  await page.locator('[data-cp-message]').click();
  await page
    .locator('[data-cp-message]')
    .pressSequentially('What did the policy check find?', { delay: 28 });
  await pause(500);
  await page.locator('[data-cp-send]').click();
  await until('question-reply', (v) => v.agents >= rejoined.agents + 1, 45);
  await spoken('question-spoken');
  await page.screenshot({ path: path.join(out, 'channel-policy-demo.png') });
  await pause(3000);

  await caption(
    'Model replies never authorize changes',
    'Exact quote confirmation stays outside the conversation. Every count and result above is an as-of source observation.',
  );
  await page.locator('[data-cp-end]').click();
  await until('final-ended', (v) => v.state === 'Session ended', 45);
  await pause(4000);
  mark('done');
} catch (error) {
  failure = error;
  mark('error', { message: String(error?.message ?? error).slice(0, 400) });
  await page.screenshot({ path: path.join(out, 'error.png') }).catch(() => {});
}

const audio = await page
  .evaluate(async () => {
    const tap = window.__demoAudio;
    if (!tap || tap.wallStart === null) return null;
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
if (!failure && spawnSync(ffmpeg, ['-version'], { stdio: 'ignore' }).status === 0) {
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
    path.join(out, 'channel-policy-demo.mp4'),
  );
  const result = spawnSync(ffmpeg, args, { stdio: 'inherit' });
  mark(result.status === 0 ? 'mp4' : 'mp4-failed');
} else if (!failure) {
  mark('mp4-skipped', { reason: 'ffmpeg not found; set FFMPEG or install ffmpeg' });
}
process.exit(failure ? 1 : 0);
