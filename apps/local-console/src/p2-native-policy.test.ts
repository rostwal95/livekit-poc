import { describe, expect, it } from 'vitest';
import {
  freezeNativeInput,
  NativeInputs,
  NativeGenerations,
  NativeUiError,
  nativeReady,
  NATIVE_HISTORY_LIMIT,
  parseNativeAck,
  parseNativeGeneration,
  parseNativeSession,
  parseNativeTurnReply,
  turnPayload,
} from './p2-native-policy';

const inputId = '11111111-1111-4111-8111-111111111111';
const bindingId = '22222222-2222-4222-8222-222222222222';
const receiptId = '33333333-3333-4333-8333-333333333333';
const operationKey = '44444444-4444-4444-8444-444444444444';
const encode = (row: unknown): Uint8Array => new TextEncoder().encode(JSON.stringify(row));
const session = () => ({
  schemaVersion: 1,
  url: 'ws://127.0.0.1:17880',
  token: 'private.local.token',
  roomId: 'p2-native-fixture',
  participantId: 'browser-fixture',
  agentId: 'p2-agent-fixture',
  bindingId,
});
const ack = () => ({
  schemaVersion: 1,
  bindingId,
  inputId,
  channel: 'web_chat',
  status: 'accepted',
  receiptId,
  operationKey,
  acceptanceSequence: '1',
  code: null,
});
const ready = {
  'p2.session_ready': 'true',
  'p2.inference_mode': 'scripted',
  'lk.agent.state': 'listening',
};

describe('P2 native trusted session and readiness', () => {
  it('snapshots a fixed loopback session without retaining a mutable response', () => {
    const source = session();
    const result = parseNativeSession(source);
    source.roomId = 'changed';
    expect(result.roomId).toBe('p2-native-fixture');
    expect(Object.isFrozen(result)).toBe(true);
  });
  it.each([
    'https://remote.example',
    'ws://remote.example',
    'ws://127.0.0.1:17880/private',
    'ws://secret@127.0.0.1:17880',
    'ws://127.0.0.1:17880?secret=value',
    'ws://127.0.0.1:17880#secret',
  ])('rejects a session destination outside the local contract: %s', (url) => {
    expect(() => parseNativeSession({ ...session(), url })).toThrow(NativeUiError);
  });
  it.each([
    { ...session(), schemaVersion: true },
    { ...session(), bindingId: 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA' },
    { ...session(), token: '' },
    { ...session(), token: 'x'.repeat(8193) },
    { ...session(), token: 'secret\nvalue' },
    { ...session(), agentId: 'browser-fixture' },
    { ...session(), participantId: '../other' },
    { ...session(), injected: true },
  ])('rejects malformed session fields and scope selectors', (row) => {
    expect(() => parseNativeSession(row)).toThrow(NativeUiError);
  });
  it('does not evaluate untrusted response getters', () => {
    let calls = 0;
    const row = session();
    Object.defineProperty(row, 'token', {
      get: () => {
        calls++;
        return 'secret';
      },
      enumerable: true,
    });
    expect(() => parseNativeSession(row)).toThrow(NativeUiError);
    expect(calls).toBe(0);
  });
  it('requires the expected native agent, subscribed readiness and scripted mode', () => {
    const bound = parseNativeSession(session());
    expect(nativeReady(true, bound, bound.agentId, 'agent', ready)).toBe(true);
    expect(nativeReady(false, bound, bound.agentId, 'agent', ready)).toBe(false);
    expect(nativeReady(true, bound, 'foreign-agent', 'agent', ready)).toBe(false);
    expect(nativeReady(true, bound, bound.agentId, 'other', ready)).toBe(false);
    for (const changed of [
      { ...ready, 'p2.session_ready': 'false' },
      { ...ready, 'p2.inference_mode': 'provider_real' },
      { ...ready, 'lk.agent.state': 'initializing' },
      {},
    ])
      expect(nativeReady(true, bound, bound.agentId, 'agent', changed)).toBe(false);
  });
});

describe('P2 native input and truthful application acknowledgement', () => {
  it('preserves original message bytes and distinguishes identical text under new IDs', () => {
    const inputs = new NativeInputs();
    const text = '  investigate\nmy dates  ';
    inputs.add(freezeNativeInput(inputId, 'web_chat', text));
    inputs.add(freezeNativeInput(operationKey, 'web_chat', text));
    expect(inputs.values()).toHaveLength(2);
    expect(inputs.values()[0]?.body).toBe(text);
    expect(inputs.values().every((row) => row.status === 'pending' && row.receiptId === null)).toBe(
      true,
    );
  });
  it.each([
    '',
    '  ',
    'x'.repeat(2049),
    'é'.repeat(1025),
    'bad\u0000body',
    '\ud800',
    '\udfff',
    '\ud800suffix',
  ])('rejects empty, oversized UTF-8 or NUL input before admission', (body) => {
    expect(() => freezeNativeInput(inputId, 'web_chat', body)).toThrow(NativeUiError);
  });
  it('accepts the exact UTF-8 boundary and only a body-free voice turn placeholder', () => {
    expect(freezeNativeInput(inputId, 'web_chat', 'é'.repeat(1024)).body).toHaveLength(1024);
    expect(freezeNativeInput(inputId, 'voice_transcript', null).body).toBeNull();
    expect(() => freezeNativeInput(inputId, 'voice_transcript', 'a fabricated transcript')).toThrow(
      NativeUiError,
    );
  });
  it('retries the original logical identity and conflicts on changed semantics', () => {
    const inputs = new NativeInputs();
    const first = inputs.add(freezeNativeInput(inputId, 'web_chat', 'original'));
    expect(inputs.add(freezeNativeInput(inputId, 'web_chat', 'original'))).toBe(first);
    expect(() => inputs.add(freezeNativeInput(inputId, 'web_chat', 'changed'))).toThrow(
      NativeUiError,
    );
    expect(() => inputs.add(freezeNativeInput(inputId, 'voice_transcript', null))).toThrow(
      NativeUiError,
    );
    expect(inputs.values()).toHaveLength(1);
  });
  it('requires a committed receipt, operation and exact int64 acceptance sequence', () => {
    const parsed = parseNativeAck(
      encode({ ...ack(), acceptanceSequence: '9223372036854775807' }),
      bindingId,
    );
    expect(parsed.acceptanceSequence).toBe('9223372036854775807');
    expect(Object.isFrozen(parsed)).toBe(true);
    const inputs = new NativeInputs();
    inputs.add(freezeNativeInput(inputId, 'web_chat', 'original'));
    inputs.apply(parsed);
    expect(inputs.last()?.status).toBe('accepted');
    expect(inputs.last()?.operationKey).toBe(operationKey);
  });
  it.each([
    { ...ack(), receiptId: null },
    { ...ack(), operationKey: 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA' },
    { ...ack(), acceptanceSequence: 1 },
    { ...ack(), acceptanceSequence: '01' },
    { ...ack(), acceptanceSequence: '9223372036854775808' },
    { ...ack(), code: 'invalid_input' },
    { ...ack(), bindingId: inputId },
    { ...ack(), inputId: 'not-a-uuid' },
    { ...ack(), schemaVersion: true },
    { ...ack(), extra: 'secret' },
  ])('rejects malformed, changed-scope or inferred receipt fields', (row) => {
    expect(() => parseNativeAck(encode(row), bindingId)).toThrow(NativeUiError);
  });
  it('rejects duplicate keys, escaped aliases, malformed UTF-8 and oversized acknowledgements', () => {
    const valid = JSON.stringify(ack());
    for (const raw of [
      new TextEncoder().encode(
        valid.replace('"schemaVersion":1', '"schemaVersion":1,"schemaVersion":1'),
      ),
      new TextEncoder().encode(
        valid.replace('"schemaVersion":1', '"schemaVersion":1,"\\u0073chemaVersion":1'),
      ),
      new Uint8Array([0xff]),
      new Uint8Array(2049),
      new Uint8Array(),
    ])
      expect(() => parseNativeAck(raw, bindingId)).toThrow(NativeUiError);
  });
  it('rejects uncertainty labelled as definitive rejection and malformed unknown codes', () => {
    for (const [status, code] of [
      ['rejected', 'acknowledgement_unknown'],
      ['unknown', 'invalid_input'],
      ['unknown', 'forbidden'],
    ])
      expect(() =>
        parseNativeAck(
          encode({
            ...ack(),
            status,
            code,
            receiptId: null,
            operationKey: null,
            acceptanceSequence: null,
          }),
          bindingId,
        ),
      ).toThrow(NativeUiError);
  });
  it('keeps uncertain transport separate and permits a later committed acknowledgement', () => {
    const inputs = new NativeInputs();
    inputs.add(freezeNativeInput(inputId, 'web_chat', 'original'));
    inputs.uncertain(inputId);
    expect(inputs.last()?.status).toBe('unknown');
    expect(inputs.last()?.receiptId).toBeNull();
    inputs.apply(parseNativeAck(encode(ack()), bindingId));
    expect(inputs.last()?.status).toBe('accepted');
    inputs.uncertain(inputId);
    expect(inputs.last()?.status).toBe('accepted');
  });
  it('retains known original identity after late errors and rejects contradictory receipts', () => {
    const inputs = new NativeInputs();
    inputs.add(freezeNativeInput(inputId, 'web_chat', 'original'));
    inputs.apply(parseNativeAck(encode(ack()), bindingId));
    const unknown = parseNativeAck(
      encode({
        ...ack(),
        status: 'unknown',
        receiptId: null,
        operationKey: null,
        acceptanceSequence: null,
        code: 'acknowledgement_unknown',
      }),
      bindingId,
    );
    expect(inputs.apply(unknown)).toBe(false);
    expect(inputs.last()?.status).toBe('accepted');
    expect(() =>
      inputs.apply(parseNativeAck(encode({ ...ack(), receiptId: bindingId }), bindingId)),
    ).toThrow(NativeUiError);
    expect(inputs.last()?.receiptId).toBe(receiptId);
  });
  it('ignores unsolicited or wrong-modality acknowledgements', () => {
    const inputs = new NativeInputs();
    expect(inputs.apply(parseNativeAck(encode(ack()), bindingId))).toBe(false);
    inputs.add(freezeNativeInput(inputId, 'voice_transcript', null));
    expect(inputs.apply(parseNativeAck(encode(ack()), bindingId))).toBe(false);
    expect(inputs.last()?.status).toBe('pending');
  });
  it('retains replay and inspection at the finite local history cap', () => {
    const inputs = new NativeInputs();
    for (let n = 0; n < NATIVE_HISTORY_LIMIT; n++)
      inputs.add(
        freezeNativeInput(
          `${n.toString(16).padStart(8, '0')}-1111-4111-8111-111111111111`,
          'web_chat',
          'same body',
        ),
      );
    const last = inputs.last()!;
    expect(inputs.add(freezeNativeInput(last.inputId, last.channel, last.body))).toBe(last);
    expect(() => inputs.add(freezeNativeInput(inputId, 'web_chat', 'new'))).toThrow(NativeUiError);
    expect(inputs.values()).toHaveLength(NATIVE_HISTORY_LIMIT);
    expect(Object.isFrozen(inputs.values())).toBe(true);
  });
});

describe('P2 native canonical identifiers', () => {
  it('rejects final LF in every identifier and decimal field', () => {
    expect(() => freezeNativeInput(inputId + '\n', 'web_chat', 'original')).toThrow(NativeUiError);
    for (const row of [
      { ...session(), roomId: session().roomId + '\n' },
      { ...session(), participantId: session().participantId + '\n' },
      { ...session(), agentId: session().agentId + '\n' },
      { ...session(), bindingId: bindingId + '\n' },
    ])
      expect(() => parseNativeSession(row)).toThrow(NativeUiError);
    for (const row of [
      { ...ack(), inputId: inputId + '\n' },
      { ...ack(), receiptId: receiptId + '\n' },
      { ...ack(), operationKey: operationKey + '\n' },
      { ...ack(), acceptanceSequence: '1\n' },
    ])
      expect(() => parseNativeAck(encode(row), bindingId)).toThrow(NativeUiError);
  });
});

describe('P2 native manual turn correlation', () => {
  it('binds start and commit to one original ID and keeps interruption body-free', () => {
    expect(JSON.parse(turnPayload('p2.start_turn', inputId))).toEqual({
      schemaVersion: 1,
      inputId,
    });
    expect(turnPayload('p2.start_turn', inputId)).toBe(turnPayload('p2.commit_turn', inputId));
    expect(turnPayload('p2.interrupt', null)).toBe('{"schemaVersion":1}');
    expect(() => turnPayload('p2.interrupt', inputId)).toThrow(NativeUiError);
  });
  it('requires exact turn identity and method-specific outcome without claiming acceptance', () => {
    const raw = JSON.stringify({ schemaVersion: 1, status: 'turn_committed', inputId });
    expect(parseNativeTurnReply(raw, 'p2.commit_turn', inputId)).toBe('turn_committed');
    expect(() => parseNativeTurnReply(raw, 'p2.start_turn', inputId)).toThrow(NativeUiError);
    expect(() => parseNativeTurnReply(raw, 'p2.commit_turn', bindingId)).toThrow(NativeUiError);
    expect(() =>
      parseNativeTurnReply(
        raw.replace('"schemaVersion":1', '"schemaVersion":1,"schemaVersion":1'),
        'p2.commit_turn',
        inputId,
      ),
    ).toThrow(NativeUiError);
    expect(() => parseNativeTurnReply('x'.repeat(257), 'p2.commit_turn', inputId)).toThrow(
      NativeUiError,
    );
  });
});

describe('P2 source-qualified native generations', () => {
  const generationId = '55555555-5555-4555-8555-555555555555';
  const observation = () => ({
    schemaVersion: 1,
    bindingId,
    inputId,
    operationKey,
    generationId,
    status: 'started',
  });
  function accepted() {
    const input = new NativeInputs();
    input.add(freezeNativeInput(inputId, 'web_chat', 'original'));
    input.apply(parseNativeAck(encode(ack()), bindingId));
    return input;
  }
  it('binds a generation to an already accepted original input and operation', () => {
    const rows = new NativeGenerations();
    const inputs = accepted();
    expect(rows.apply(parseNativeGeneration(encode(observation()), bindingId), inputs)).toBe(true);
    expect(rows.completedInputs()).toBe(0);
    expect(
      rows.apply(
        parseNativeGeneration(encode({ ...observation(), status: 'completed' }), bindingId),
        inputs,
      ),
    ).toBe(true);
    expect(rows.completedInputs()).toBe(1);
    expect(inputs.last()?.status).toBe('accepted');
  });
  it('never creates acceptance from output or an unacknowledged input', () => {
    const rows = new NativeGenerations();
    const inputs = new NativeInputs();
    expect(rows.apply(parseNativeGeneration(encode(observation()), bindingId), inputs)).toBe(false);
    inputs.add(freezeNativeInput(inputId, 'web_chat', 'original'));
    expect(
      rows.apply(
        parseNativeGeneration(encode({ ...observation(), status: 'completed' }), bindingId),
        inputs,
      ),
    ).toBe(false);
    expect(inputs.last()?.status).toBe('pending');
    expect(rows.values()).toHaveLength(0);
  });
  it('ignores a generation for another operation even when the text ID matches', () => {
    const rows = new NativeGenerations();
    expect(
      rows.apply(
        parseNativeGeneration(encode({ ...observation(), operationKey: receiptId }), bindingId),
        accepted(),
      ),
    ).toBe(false);
    expect(rows.values()).toHaveLength(0);
  });
  it.each([
    { ...observation(), schemaVersion: true },
    { ...observation(), bindingId: inputId },
    { ...observation(), inputId: inputId + '\n' },
    { ...observation(), operationKey: null },
    { ...observation(), generationId: '55555555-5555-5555-8555-555555555555' },
    { ...observation(), status: 'played' },
    { ...observation(), body: 'secret' },
  ])('rejects malformed or unsupported generation claims', (row) => {
    expect(() => parseNativeGeneration(encode(row), bindingId)).toThrow(NativeUiError);
  });
  it('rejects duplicate fields, invalid UTF-8 and oversized generation events', () => {
    const valid = JSON.stringify(observation());
    for (const raw of [
      new TextEncoder().encode(
        valid.replace('"schemaVersion":1', '"schemaVersion":1,"schemaVersion":1'),
      ),
      new Uint8Array([0xff]),
      new Uint8Array(1025),
    ])
      expect(() => parseNativeGeneration(raw, bindingId)).toThrow(NativeUiError);
  });
  it('retains known terminal generation after stale starts and unknown observations', () => {
    const rows = new NativeGenerations();
    const inputs = accepted();
    rows.apply(
      parseNativeGeneration(encode({ ...observation(), status: 'completed' }), bindingId),
      inputs,
    );
    expect(rows.apply(parseNativeGeneration(encode(observation()), bindingId), inputs)).toBe(false);
    expect(
      rows.apply(
        parseNativeGeneration(encode({ ...observation(), status: 'unknown' }), bindingId),
        inputs,
      ),
    ).toBe(false);
    expect(rows.values()[0]?.status).toBe('completed');
  });
  it('resolves an uncertain generation with later known SDK completion', () => {
    const rows = new NativeGenerations();
    const inputs = accepted();
    rows.apply(
      parseNativeGeneration(encode({ ...observation(), status: 'unknown' }), bindingId),
      inputs,
    );
    rows.apply(
      parseNativeGeneration(encode({ ...observation(), status: 'completed' }), bindingId),
      inputs,
    );
    expect(rows.completedInputs()).toBe(1);
    expect(() =>
      rows.apply(
        parseNativeGeneration(encode({ ...observation(), status: 'interrupted' }), bindingId),
        inputs,
      ),
    ).toThrow(NativeUiError);
  });
  it('distinguishes repeated computation from distinct accepted inputs', () => {
    const rows = new NativeGenerations();
    const inputs = accepted();
    rows.apply(
      parseNativeGeneration(encode({ ...observation(), status: 'completed' }), bindingId),
      inputs,
    );
    rows.apply(
      parseNativeGeneration(
        encode({ ...observation(), generationId: receiptId, status: 'completed' }),
        bindingId,
      ),
      inputs,
    );
    expect(rows.values()).toHaveLength(2);
    expect(rows.completedInputs()).toBe(1);
    expect(inputs.values()).toHaveLength(1);
  });
  it('rejects reusing one generation reference for a different accepted input', () => {
    const rows = new NativeGenerations();
    const inputs = accepted();
    rows.apply(parseNativeGeneration(encode(observation()), bindingId), inputs);
    inputs.add(freezeNativeInput(receiptId, 'web_chat', 'different'));
    inputs.apply(
      parseNativeAck(
        encode({
          ...ack(),
          inputId: receiptId,
          receiptId: bindingId,
          operationKey: bindingId,
          acceptanceSequence: '2',
        }),
        bindingId,
      ),
    );
    expect(() =>
      rows.apply(
        parseNativeGeneration(
          encode({ ...observation(), inputId: receiptId, operationKey: bindingId }),
          bindingId,
        ),
        inputs,
      ),
    ).toThrow(NativeUiError);
  });
  it('retains replay and terminal observations at its finite generation cap', () => {
    const rows = new NativeGenerations();
    const inputs = accepted();
    for (let n = 0; n < 64; n++)
      rows.apply(
        parseNativeGeneration(
          encode({
            ...observation(),
            generationId: `${n.toString(16).padStart(8, '0')}-5555-4555-8555-555555555555`,
          }),
          bindingId,
        ),
        inputs,
      );
    expect(rows.values()).toHaveLength(64);
    const original = rows.values()[0]!;
    expect(rows.apply(original, inputs)).toBe(false);
    expect(
      rows.apply(
        parseNativeGeneration(encode({ ...original, status: 'completed' }), bindingId),
        inputs,
      ),
    ).toBe(true);
    expect(() =>
      rows.apply(parseNativeGeneration(encode(observation()), bindingId), inputs),
    ).toThrow(NativeUiError);
    expect(rows.values()).toHaveLength(64);
    expect(Object.isFrozen(rows.values())).toBe(true);
  });
});

describe('P2 native retry uncertainty', () => {
  it('does not infer original nonacceptance from a later expired-grant retry rejection', () => {
    const inputs = new NativeInputs();
    inputs.add(freezeNativeInput(inputId, 'web_chat', 'original'));
    inputs.uncertain(inputId);
    const denied = parseNativeAck(
      encode({
        ...ack(),
        status: 'rejected',
        receiptId: null,
        operationKey: null,
        acceptanceSequence: null,
        code: 'forbidden',
      }),
      bindingId,
    );
    expect(inputs.apply(denied)).toBe(false);
    expect(inputs.last()?.status).toBe('unknown');
    inputs.apply(parseNativeAck(encode({ ...ack(), status: 'replayed' }), bindingId));
    expect(inputs.last()?.status).toBe('replayed');
    expect(inputs.last()?.receiptId).toBe(receiptId);
  });
});
