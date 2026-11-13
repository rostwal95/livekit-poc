import { describe, expect, it } from 'vitest';
import {
  NativeInputs,
  parseNativeAck,
  freezeNativeInput,
  parseNativeSession,
} from './p2-native-policy';
import {
  NativeResponses,
  parseResponseMapping,
  parseResponseView,
  playbackPayload,
  interruptPayload,
  validateInterruptReply,
  validatePlaybackReply,
} from './p2-response-policy';
const uuid = (n: number) => `${n.toString().padStart(8, '0')}-1111-4111-8111-111111111111`;
const encode = (v: unknown) => new TextEncoder().encode(JSON.stringify(v));
function fixture() {
  const session = parseNativeSession({
    schemaVersion: 1,
    url: 'ws://127.0.0.1:17880',
    token: 'private.fixture',
    roomId: 'room',
    participantId: 'browser',
    agentId: 'agent',
    bindingId: uuid(1),
  });
  const inputs = new NativeInputs();
  inputs.add(freezeNativeInput(uuid(2), 'web_chat', 'INVESTIGATE'));
  inputs.apply(
    parseNativeAck(
      encode({
        schemaVersion: 1,
        bindingId: uuid(1),
        inputId: uuid(2),
        channel: 'web_chat',
        status: 'accepted',
        receiptId: uuid(3),
        operationKey: uuid(4),
        acceptanceSequence: '1',
        code: null,
      }),
      uuid(1),
    ),
  );
  const mapping = {
    schemaVersion: 1 as const,
    bindingId: uuid(1),
    generationId: uuid(5),
    inputId: uuid(2),
    operationKey: uuid(4),
    responseId: uuid(6),
    sdkSpeechId: 'speech_fixture',
    observationCount: 2,
  };
  const envelope = {
    schemaVersion: 1,
    status: 'known',
    result: {
      anchor: {
        schemaVersion: 1,
        responseId: uuid(6),
        generationId: uuid(5),
        sdkSpeechId: 'speech_fixture',
        bindingId: uuid(1),
        inputId: uuid(2),
        receiptId: uuid(3),
        operationKey: uuid(4),
        caseRevision: '9007199254740993',
        scope: { tenantId: 'tenant', accountId: 'account' },
        providerScope: { tenantId: 'tenant', provider: 'livekit', providerAccountId: 'local' },
        caseId: 'case',
        conversationId: 'conversation',
        roomId: 'room',
        participantId: 'browser',
      },
      receipt: {
        responseId: uuid(6),
        receiptId: uuid(7),
        anchorDigest: 'a'.repeat(64),
        responseSequence: '1',
        acceptedAt: '2026-11-11T00:00:00.000Z',
      },
      observationCount: 2,
      generatedText: 'Complete generated text',
      sdkState: 'interrupted',
      sdkText: 'Observed SDK segment',
      browserState: 'partial',
      conflicted: false,
    },
  };
  return {
    session,
    inputs,
    mapping,
    envelope,
    parse: () => parseResponseView(encode(envelope), mapping, session, inputs),
  };
}
describe('source-qualified response policy', () => {
  it('keeps generated text, synchronized SDK text and browser report separate', () => {
    const f = fixture(),
      view = f.parse();
    expect(view.generatedText).toBe('Complete generated text');
    expect(view.sdkText).toBe('Observed SDK segment');
    expect(view.sdkState).toBe('interrupted');
    expect(view.browserState).toBe('partial');
    expect(view.anchor.caseRevision).toBe('9007199254740993');
    expect(Object.isFrozen(view.anchor.scope)).toBe(true);
  });
  it('leaves missing playback unknown despite completed SDK output', () => {
    const f = fixture();
    f.envelope.result.sdkState = 'completed';
    f.envelope.result.browserState = 'unknown';
    expect(f.parse().browserState).toBe('unknown');
  });
  it('preserves client-reported completion wording without a human ACK', () => {
    const f = fixture();
    f.envelope.result.sdkState = 'completed';
    f.envelope.result.browserState = 'completed_reported';
    expect(f.parse().browserState).toBe('completed_reported');
    expect(Object.hasOwn(f.parse(), 'humanAck')).toBe(false);
  });
  it.each([
    'responseId',
    'generationId',
    'sdkSpeechId',
    'bindingId',
    'inputId',
    'receiptId',
    'operationKey',
    'roomId',
    'participantId',
  ] as const)('rejects an anchor with another %s', (key) => {
    const f = fixture();
    f.envelope.result.anchor[key] =
      key === 'sdkSpeechId' || key === 'roomId' || key === 'participantId' ? 'other' : uuid(9);
    expect(f.parse).toThrow();
  });
  it.each([true, -1, 65, 1.5, '2', null])('rejects malformed observation counts %s', (value) => {
    const f = fixture();
    const envelope = { ...f.envelope, result: { ...f.envelope.result, observationCount: value } };
    expect(() => parseResponseView(encode(envelope), f.mapping, f.session, f.inputs)).toThrow();
  });
  it.each(['', 'x'.repeat(4097), '\ud800'])('rejects malformed/overflow full text', (text) => {
    const f = fixture();
    f.envelope.result.generatedText = text;
    expect(f.parse).toThrow();
  });
  it('rejects contradictory optimistic output and unknown extra authority', () => {
    const f = fixture();
    f.envelope.result.browserState = 'completed_reported';
    expect(f.parse).toThrow();
    f.envelope.result.conflicted = true;
    expect(f.parse().conflicted).toBe(true);
    expect(() =>
      parseResponseView(
        encode({ ...f.envelope, result: { ...f.envelope.result, humanAck: true } }),
        f.mapping,
        f.session,
        f.inputs,
      ),
    ).toThrow();
  });
  it('rejects duplicate nested/escaped keys, malformed UTF8 and oversized reads', () => {
    const f = fixture(),
      raw = JSON.stringify(f.envelope);
    for (const data of [
      new TextEncoder().encode(
        raw.replace('"tenantId":"tenant"', '"tenantId":"tenant","tenantId":"tenant"'),
      ),
      new TextEncoder().encode(
        raw.replace('"responseId":', '"responseId":"x","\\u0072esponseId":'),
      ),
      new Uint8Array([255]),
      new Uint8Array(65537),
    ])
      expect(() => parseResponseView(data, f.mapping, f.session, f.inputs)).toThrow();
  });
  it('rejects malformed mapping, duplicate keys and wrong binding', () => {
    const f = fixture();
    expect(parseResponseMapping(encode(f.mapping), uuid(1))).toEqual(f.mapping);
    for (const m of [
      { ...f.mapping, source: 'browser' },
      { ...f.mapping, bindingId: uuid(9) },
      { ...f.mapping, observationCount: true },
      { ...f.mapping, sdkSpeechId: 'speech\n' },
    ])
      expect(() => parseResponseMapping(encode(m), uuid(1))).toThrow();
    expect(() =>
      parseResponseMapping(
        new TextEncoder().encode(
          JSON.stringify(f.mapping).replace(
            '"schemaVersion":1',
            '"schemaVersion":1,"schemaVersion":1',
          ),
        ),
        uuid(1),
      ),
    ).toThrow();
  });
  it('ignores unmapped input and stale reads; accepted facts survive read failure', () => {
    const f = fixture(),
      state = new NativeResponses();
    expect(state.apply(f.mapping, new NativeInputs())).toBe(false);
    expect(state.apply(f.mapping, f.inputs)).toBe(true);
    expect(state.inspect(f.parse())).toBe(true);
    expect(state.apply({ ...f.mapping, observationCount: 3 }, f.inputs)).toBe(true);
    expect(state.inspect(f.parse())).toBe(false);
    expect(state.values()[0]?.view?.generatedText).toBe('Complete generated text');
  });
  it('rejects response relinking and generation reuse', () => {
    const f = fixture(),
      state = new NativeResponses();
    state.apply(f.mapping, f.inputs);
    expect(() =>
      state.apply({ ...f.mapping, sdkSpeechId: 'other', observationCount: 3 }, f.inputs),
    ).toThrow();
    expect(() => state.apply({ ...f.mapping, responseId: uuid(9) }, f.inputs)).toThrow();
  });
  it('retains monotonic actual PCM samples and rejects invented/foreign values', () => {
    const f = fixture(),
      state = new NativeResponses();
    state.apply(f.mapping, f.inputs);
    expect(state.sample({ responseId: uuid(6), observedAudioMs: 700, sampledAudioMs: 800 })).toBe(
      true,
    );
    for (const value of [
      { responseId: uuid(9), observedAudioMs: 900, sampledAudioMs: 900 },
      { responseId: uuid(6), observedAudioMs: 699, sampledAudioMs: 900 },
      { responseId: uuid(6), observedAudioMs: 900, sampledAudioMs: 800 },
      { responseId: uuid(6), observedAudioMs: NaN, sampledAudioMs: 900 },
      { responseId: uuid(6), observedAudioMs: 900, sampledAudioMs: 180001 },
    ])
      expect(state.sample(value)).toBe(false);
  });
  it('binds interruption and playback acknowledgements to original exact identities', () => {
    expect(JSON.parse(interruptPayload(uuid(6)))).toEqual({
      schemaVersion: 1,
      responseId: uuid(6),
    });
    validateInterruptReply(
      JSON.stringify({ schemaVersion: 1, status: 'interruption_requested', responseId: uuid(6) }),
      uuid(6),
    );
    expect(() =>
      validateInterruptReply(
        JSON.stringify({ schemaVersion: 1, status: 'completed', responseId: uuid(6) }),
        uuid(6),
      ),
    ).toThrow();
    expect(JSON.parse(playbackPayload(uuid(8), uuid(6), 'partial', 700))).toEqual({
      schemaVersion: 1,
      eventId: uuid(8),
      responseId: uuid(6),
      state: 'partial',
      observedAudioMs: 700,
    });
    const ack = {
      schemaVersion: 1,
      status: 'known',
      result: {
        eventId: uuid(8),
        responseId: uuid(6),
        receiptId: uuid(9),
        observationSequence: '2',
        payloadDigest: 'b'.repeat(64),
        acceptedAt: '2026-11-11T00:00:00.000Z',
      },
    };
    validatePlaybackReply(JSON.stringify(ack), uuid(6), uuid(8));
    expect(() => validatePlaybackReply(JSON.stringify(ack), uuid(6), uuid(9))).toThrow();
  });
});

describe('response identity and retained observation boundaries', () => {
  it('snapshots an admitted mapping instead of retaining caller-owned mutable state', () => {
    const f = fixture();
    const state = new NativeResponses();
    state.apply(f.mapping, f.inputs);
    f.mapping.sdkSpeechId = 'retargeted_speech';
    f.mapping.observationCount = 64;
    expect(state.values()[0]?.mapping.sdkSpeechId).toBe('speech_fixture');
    expect(state.values()[0]?.mapping.observationCount).toBe(2);
    expect(Object.isFrozen(state.values()[0]?.mapping)).toBe(true);
  });
  it('rejects the first parsed view if it belongs to another mapping of the same response ID', () => {
    const f = fixture();
    const state = new NativeResponses();
    state.apply(f.mapping, f.inputs);
    const other = { ...f.mapping, generationId: uuid(12) };
    f.envelope.result.anchor.generationId = other.generationId;
    const foreign = parseResponseView(encode(f.envelope), other, f.session, f.inputs);
    expect(() => state.inspect(foreign)).toThrow();
    expect(state.values()[0]?.view).toBeNull();
    expect(state.values()[0]?.mapping.generationId).toBe(uuid(5));
  });
  it('rejects inconsistent equal-count reads while preserving the original interrupted facts', () => {
    const f = fixture();
    const state = new NativeResponses();
    state.apply(f.mapping, f.inputs);
    const original = f.parse();
    state.inspect(original);
    expect(state.inspect(f.parse())).toBe(true);
    f.envelope.result.sdkState = 'completed';
    f.envelope.result.sdkText = 'optimistic replacement';
    f.envelope.result.browserState = 'completed_reported';
    expect(() => state.inspect(f.parse())).toThrow();
    expect(state.values()[0]?.view).toEqual(original);
  });
  it('retains original references at capacity and allows an exact existing mapping update', () => {
    const f = fixture();
    const state = new NativeResponses();
    state.apply(f.mapping, f.inputs);
    for (let n = 0; n < 63; n++) {
      state.apply(
        { ...f.mapping, responseId: uuid(100 + n), generationId: uuid(200 + n) },
        f.inputs,
      );
    }
    expect(state.values()).toHaveLength(64);
    expect(() =>
      state.apply({ ...f.mapping, responseId: uuid(500), generationId: uuid(501) }, f.inputs),
    ).toThrow();
    expect(state.apply({ ...f.mapping, observationCount: 3 }, f.inputs)).toBe(true);
    expect(state.values()).toHaveLength(64);
    expect(state.values()[0]?.mapping.responseId).toBe(uuid(6));
  });
  it('does not erase accepted or source observations when a later evidence read is unavailable', () => {
    const f = fixture();
    const state = new NativeResponses();
    state.apply(f.mapping, f.inputs);
    state.inspect(f.parse());
    const original = state.values()[0];
    expect(() =>
      parseResponseView(
        encode({ schemaVersion: 1, status: 'unknown', result: null }),
        f.mapping,
        f.session,
        f.inputs,
      ),
    ).toThrow();
    expect(state.values()[0]).toBe(original);
    expect(f.inputs.values()[0]?.receiptId).toBe(uuid(3));
  });
  it('retains copied PCM observations without allowing a caller to revise their recorded window', () => {
    const f = fixture();
    const state = new NativeResponses();
    state.apply(f.mapping, f.inputs);
    const sample = { responseId: uuid(6), observedAudioMs: 0, sampledAudioMs: 800 };
    expect(state.sample(sample)).toBe(true);
    sample.observedAudioMs = 800;
    expect(state.values()[0]?.sample?.observedAudioMs).toBe(0);
    expect(Object.isFrozen(state.values()[0]?.sample)).toBe(true);
    expect(state.values()[0]?.view).toBeNull();
  });
  it('accepts exact UTF8 text bounds including paired supplementary Unicode', () => {
    const f = fixture();
    f.envelope.result.generatedText = '🙂'.repeat(1024);
    expect(f.parse().generatedText).toBe('🙂'.repeat(1024));
    f.envelope.result.generatedText += 'a';
    expect(f.parse).toThrow();
  });
  it.each(['0', '01', '+1', '1.0', '9223372036854775808', '1\n'])(
    'rejects noncanonical or overflowing revision %s',
    (revision) => {
      const f = fixture();
      f.envelope.result.anchor.caseRevision = revision;
      expect(f.parse).toThrow();
    },
  );
  it('preserves signed-int64 decimal identities without a JavaScript number round trip', () => {
    const f = fixture();
    f.envelope.result.anchor.caseRevision = '9223372036854775807';
    f.envelope.result.receipt.responseSequence = '9223372036854775807';
    expect(f.parse().receipt.responseSequence).toBe('9223372036854775807');
    expect(f.parse().anchor.caseRevision).toBe('9223372036854775807');
  });
  it.each(['2026-02-30T00:00:00.000Z', '2026-11-11T00:00:00+00:00', '2026-11-11T00:00:00.000Z\n'])(
    'rejects noncanonical response receipt time %s',
    (acceptedAt) => {
      const f = fixture();
      f.envelope.result.receipt.acceptedAt = acceptedAt;
      expect(f.parse).toThrow();
    },
  );
  it('keeps original playback event bytes stable on replay and never infers completion from a duration', () => {
    const first = playbackPayload(uuid(8), uuid(6), 'partial', 180000);
    expect(playbackPayload(uuid(8), uuid(6), 'partial', 180000)).toBe(first);
    expect(JSON.parse(first)).toEqual({
      schemaVersion: 1,
      eventId: uuid(8),
      responseId: uuid(6),
      state: 'partial',
      observedAudioMs: 180000,
    });
    expect(first).not.toContain('acknowledged');
  });
  it.each([-1, 180001, 1.5, Number.NaN, Number.POSITIVE_INFINITY])(
    'rejects invalid playback duration %s',
    (duration) => {
      expect(() => playbackPayload(uuid(8), uuid(6), 'partial', duration)).toThrow();
    },
  );
  it('rejects duplicate playback receipts and mismatched original event or response identities', () => {
    const ack = {
      schemaVersion: 1,
      status: 'known',
      result: {
        acceptedAt: '2026-11-11T00:00:00.000Z',
        eventId: uuid(8),
        observationSequence: '1',
        payloadDigest: 'b'.repeat(64),
        receiptId: uuid(9),
        responseId: uuid(6),
      },
    };
    const raw = JSON.stringify(ack);
    expect(() =>
      validatePlaybackReply(
        raw.replace('"status":"known"', '"status":"known","status":"known"'),
        uuid(6),
        uuid(8),
      ),
    ).toThrow();
    expect(() => validatePlaybackReply(raw, uuid(10), uuid(8))).toThrow();
    expect(() => validatePlaybackReply(raw, uuid(6), uuid(10))).toThrow();
    ack.result.observationSequence = '9223372036854775808';
    expect(() => validatePlaybackReply(JSON.stringify(ack), uuid(6), uuid(8))).toThrow();
  });
});
