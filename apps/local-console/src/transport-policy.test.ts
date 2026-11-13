import { readFileSync } from 'node:fs';
import { ParticipantKind } from 'livekit-client';
import { describe, expect, it } from 'vitest';
import { ECHO_PREFIX, MAX_REPLY_BYTES, MAX_TEXT_BYTES, readBoundedText, validateMessage } from './lab';
import { acceptAgentText, canUseAgentMedia, canControlMicrophone, isAgentSender, parseAudioDiagnostic } from './transport-policy';
import type { AgentSender } from './transport-policy';

interface EchoFixture {
  prefix: string;
  max_request_bytes: number;
  max_reply_bytes: number;
  boundary_cases: { name: string; unit: string; repeat: number; suffix: string; accepted: boolean }[];
}
interface DiagnosticFixture {
  valid: { type: string; frames: number; track_sid: string }[];
  invalid: { name: string; payload: unknown }[];
}
// This same fixture is asserted against actual Python diagnostic emission.
const fixture: DiagnosticFixture = JSON.parse(readFileSync(
  new URL('../../../contracts/local-transport/diagnostics.json', import.meta.url), 'utf8',
));
const echoFixture: EchoFixture = JSON.parse(readFileSync(
  new URL('../../../contracts/local-transport/text-echo.json', import.meta.url), 'utf8',
));
const encoder = new TextEncoder();
const agent: AgentSender = { identity: 'agent-fixture', kind: ParticipantKind.AGENT };
const peer: AgentSender = { identity: 'agent-pretender', kind: ParticipantKind.STANDARD };

describe('authenticated local transport observations', () => {
  it('accepts the Python-emitted shared audio fixtures for the matching track', () => {
    for (const payload of fixture.valid) {
      expect(parseAudioDiagnostic(JSON.stringify(payload), agent, payload.track_sid))
        .toBe(`Agent received ${payload.frames} audio frames.`);
    }
  });

  it.each(fixture.invalid)('rejects shared invalid payload: $name', ({ payload }) => {
    expect(parseAudioDiagnostic(JSON.stringify(payload), agent, 'TR_fixture')).toBeNull();
  });

  it('uses the actual SDK participant kind, never an agent-looking identity', () => {
    expect(isAgentSender(agent)).toBe(true);
    expect(isAgentSender(peer)).toBe(false);
    expect(isAgentSender(undefined)).toBe(false);
    expect(isAgentSender({ ...agent, identity: '' })).toBe(false);
    expect(isAgentSender({ ...agent, identity: 'a'.repeat(257) })).toBe(false);
    for (const kind of Object.values(ParticipantKind)) {
      if (typeof kind === 'number' && kind !== ParticipantKind.AGENT) {
        const sender = { ...agent, kind };
        expect(acceptAgentText('Echo: peer content', sender)).toBeNull();
        expect(parseAudioDiagnostic(JSON.stringify(fixture.valid[0]), sender)).toBeNull();
      }
    }
  });

  it('rejects missing senders and peer diagnostics even when their payload matches', () => {
    const text = JSON.stringify(fixture.valid[0]);
    expect(parseAudioDiagnostic(text, undefined)).toBeNull();
    expect(parseAudioDiagnostic(text, peer, 'TR_fixture')).toBeNull();
  });

  it('rejects another published track and an empty expected track', () => {
    const text = JSON.stringify(fixture.valid[0]);
    expect(parseAudioDiagnostic(text, agent, 'TR_other')).toBeNull();
    expect(parseAudioDiagnostic(text, agent, '')).toBeNull();
  });

  it('rejects malformed, oversized, unbounded and incomplete diagnostic data', () => {
    for (const text of ['', '{', 'true', 'null', '[]', '{}', '"audio.frames"',
      '{"type":"audio.frames","frames":1e309,"track_sid":"TR_fixture"}']) {
      expect(parseAudioDiagnostic(text, agent)).toBeNull();
    }
    expect(parseAudioDiagnostic(' '.repeat(MAX_TEXT_BYTES) + JSON.stringify(fixture.valid[0]), agent)).toBeNull();
    expect(parseAudioDiagnostic(JSON.stringify({ type: 'audio.frames', frames: 10, track_sid: `TR_${'a'.repeat(129)}` }), agent)).toBeNull();
  });

  it.each(echoFixture.boundary_cases)('preserves the shared UTF-8 echo boundary: $name', async (boundary) => {
    expect(MAX_TEXT_BYTES).toBe(echoFixture.max_request_bytes);
    expect(MAX_REPLY_BYTES).toBe(echoFixture.max_reply_bytes);
    expect(ECHO_PREFIX).toBe(echoFixture.prefix);
    const text = boundary.unit.repeat(boundary.repeat) + boundary.suffix;
    if (!boundary.accepted) {
      expect(() => validateMessage(text)).toThrow('16 KiB');
      return;
    }
    expect(encoder.encode(validateMessage(text)).byteLength).toBe(MAX_TEXT_BYTES);
    const reply = echoFixture.prefix + text;
    async function* stream(): AsyncGenerator<string> {
      yield echoFixture.prefix;
      yield text;
    }
    const received = await readBoundedText(stream(), MAX_REPLY_BYTES);
    expect(received).toBe(reply);
    expect(encoder.encode(received).byteLength).toBe(MAX_REPLY_BYTES);
    expect(acceptAgentText(received, agent)).toBe(reply);
    expect(acceptAgentText(received, peer)).toBeNull();
  });

  it('rejects and closes a reply one UTF-8 byte above its distinct limit', async () => {
    let closed = false;
    const reply = echoFixture.prefix + 'é'.repeat(MAX_TEXT_BYTES / 2);
    async function* stream(): AsyncGenerator<string> {
      try { yield reply; yield 'a'; } finally { closed = true; }
    }
    await expect(readBoundedText(stream(), MAX_REPLY_BYTES)).rejects.toThrow('limit');
    expect(closed).toBe(true);
    expect(acceptAgentText(reply + 'a', agent)).toBeNull();
  });

  it('keeps audio diagnostic size at the original limit rather than the chat reply limit', async () => {
    const body = JSON.stringify(fixture.valid[0]);
    const exact = ' '.repeat(MAX_TEXT_BYTES - encoder.encode(body).byteLength) + body;
    expect(parseAudioDiagnostic(exact, agent, 'TR_fixture')).toBe('Agent received 10 audio frames.');
    expect(parseAudioDiagnostic(' ' + exact, agent, 'TR_fixture')).toBeNull();
    async function* stream(): AsyncGenerator<string> { yield exact; yield ' '; }
    await expect(readBoundedText(stream())).rejects.toThrow('limit');
  });

  it('accepts bounded agent text while refusing peer, empty and oversized text', () => {
    expect(acceptAgentText('Echo: hello', agent)).toBe('Echo: hello');
    expect(acceptAgentText('Echo: hello', peer)).toBeNull();
    expect(acceptAgentText('Echo: hello', undefined)).toBeNull();
    expect(acceptAgentText('', agent)).toBeNull();
    expect(acceptAgentText('a'.repeat(MAX_TEXT_BYTES), agent)).toHaveLength(MAX_TEXT_BYTES);
    expect(acceptAgentText('😀'.repeat(Math.floor(MAX_REPLY_BYTES / 4) + 1), agent)).toBeNull();
  });
});

describe('session admission before agent arrival', () => {
  it.each([
    ['connected', false, false],
    ['connected', true, true],
    ['reconnecting', true, false],
    ['disconnected', true, false],
    ['connecting', true, false],
  ] as const)('state %s with agent=%s enables media=%s', (state, present, allowed) => {
    expect(canUseAgentMedia(state, present)).toBe(allowed);
  });
});

it('keeps microphone stop available after agent departure, without permitting a new publication', () => {
  expect(canControlMicrophone('connected', false, true)).toBe(true);
  expect(canControlMicrophone('connected', false, false)).toBe(false);
  expect(canControlMicrophone('connected', true, false)).toBe(true);
});
