import { describe, expect, it } from 'vitest';
import {
  json,
  parseStatus,
  parseGrant,
  parseFact,
  parseCurrent,
  parseCase,
  parseProgress,
  parseSms,
  smsCommand,
  startCommand,
  endCommand,
  encodeRequest,
  errorCode,
  safeCode,
} from './channel-policy-wire';
import { policyCopy } from './channel-policy-panel';
const O = '11111111-1111-4111-8111-111111111111',
  C = '22222222-2222-4222-8222-222222222222',
  B = '33333333-3333-4333-8333-333333333333',
  T = '2026-11-13T12:00:00.000Z';
const start = startCommand({
  schemaVersion: 1,
  ownerEpoch: O,
  expectedGeneration: '0',
  commandId: C,
});
const end = endCommand({
  schemaVersion: 1,
  ownerEpoch: O,
  generation: '1',
  originalStartCommandId: C,
});
const status = () => ({
  schemaVersion: 1,
  ownerEpoch: O,
  generation: '0',
  originalStartCommandId: null,
  stage: 'idle',
  asOf: T,
  nodeCursor: {
    nodeEpoch: B,
    generation: '9',
    recoveryRequired: false,
    endpoint: { host: '127.0.0.1', port: 11029 },
  },
  sdkReady: false,
  workerRunning: false,
  expiresAt: null,
});
const grant = () => ({
  schemaVersion: 1,
  ownerEpoch: O,
  generation: '1',
  originalStartCommandId: C,
  mode: 'scripted',
  stage: 'waiting_browser',
  rtc: {
    url: 'ws://127.0.0.1:7880',
    token: 'abc.def.ghi',
    roomId: 'cp_room_a',
    participantId: 'browser_a',
    agentId: 'agent_a',
    bindingId: B,
    expiresAt: T,
  },
});
const counts = () => ({
  native: 1,
  sms: 1,
  pending: 1,
  running: 0,
  dispatched: 1,
  blocked: 0,
  exhausted: 0,
  uncertain: 0,
  workKnown: 1,
});
describe('joined Parent browser v1 boundary', () => {
  it('keeps Parent CAS and diagnostic Node cursor distinct and copied', () => {
    const value = status(),
      got = parseStatus(value);
    expect(got.generation).toBe('0');
    expect(got.nodeCursor.generation).toBe('9');
    value.nodeCursor.generation = '10';
    expect(got.nodeCursor.generation).toBe('9');
    expect(Object.isFrozen(got.nodeCursor.endpoint)).toBe(true);
  });
  it('accepts only a trusted-mode grant bound to exact original Start and next generation', () => {
    expect(parseGrant(grant(), start).rtc.bindingId).toBe(B);
    expect(parseGrant(grant(), start).mode).toBe('scripted');
    expect(parseGrant({ ...grant(), mode: 'provider_real' }, start).mode).toBe('provider_real');
    expect(
      parseGrant({ ...grant(), rtc: { ...grant().rtc, url: 'ws://127.0.0.1:17880' } }, start).rtc
        .url,
    ).toBe('ws://127.0.0.1:17880');
    for (const value of [
      { ...grant(), generation: '2' },
      { ...grant(), originalStartCommandId: B },
      { ...grant(), mode: 'local_real' },
      { ...grant(), mode: 'cloud' },
      { ...grant(), stage: 'ready' },
    ])
      expect(() => parseGrant(value, start)).toThrow();
  });
  it('denies foreign endpoints or credentials and unknown grant fields', () => {
    for (const rtc of [
      { ...grant().rtc, url: 'wss://example.com' },
      ...[
        'ws://127.0.0.1',
        'ws://127.0.0.1:0',
        'ws://127.0.0.1:017880',
        'ws://127.0.0.1:65536',
        'ws://127.0.0.1:17880/',
        'ws://user@127.0.0.1:17880',
        'ws://127.0.0.1:17880#x',
        'ws://localhost:17880',
      ].map((url) => ({ ...grant().rtc, url })),
      { ...grant().rtc, url: 'ws://127.0.0.1:7880/?token=x' },
      { ...grant().rtc, token: 'raw bearer' },
    ])
      expect(() => parseGrant({ ...grant(), rtc }, start)).toThrow();
    expect(() => parseGrant({ ...grant(), nativeBearer: 'secret' }, start)).toThrow();
  });
  it('rejects contradictory ready/idle worker status before display', () => {
    expect(() => parseStatus({ ...status(), sdkReady: true })).toThrow();
    expect(() => parseStatus({ ...status(), workerRunning: true })).toThrow();
    expect(() => parseStatus({ ...status(), generation: '1' })).toThrow();
  });
  it('never reads accessors or inherited/unknown request fields', () => {
    let reads = 0;
    const value = {
      schemaVersion: 1,
      get ownerEpoch() {
        reads++;
        throw new Error('private');
      },
      expectedGeneration: '0',
      commandId: C,
    };
    expect(() => startCommand(value)).toThrow();
    expect(reads).toBe(0);
    expect(() => startCommand({ ...start, tenantId: 'foreign' })).toThrow();
  });
  it.each(['00', '+1', '1.0', '1e0', '-1', '1000001'])(
    'rejects noncanonical/out-of-range Parent generation %s',
    (value) => {
      expect(() => endCommand({ ...end, generation: value })).toThrow();
    },
  );
  it('rejects nested duplicate JSON keys, malformed UTF8 text and oversized raw frames', () => {
    expect(() => json('{"x":{"x":1,"x":2}}')).toThrow();
    expect(() => json('x'.repeat(16385))).toThrow();
  });
  it('preserves bigint case revision and canonical calendar dates', () => {
    expect(
      parseCase({
        schemaVersion: 1,
        case: { revision: '9007199254740993', observedAt: T },
      }).case.revision,
    ).toBe('9007199254740993');
    for (const observedAt of [
      '2026-02-30T12:00:00.000Z',
      '2026-11-13T24:00:00.000Z',
      '2026-11-13T12:00:00Z',
    ])
      expect(() => parseCase({ schemaVersion: 1, case: { revision: '0', observedAt } })).toThrow();
  });
  it('distinguishes no_delivery/not_applicable timestamps from operational unavailable', () => {
    for (const state of ['no_delivery', 'not_applicable'])
      expect(
        parseFact({
          state,
          eligible: null,
          uncertainty: null,
          revision: null,
          asOf: T,
        }).asOf,
      ).toBe(T);
    expect(
      parseFact({
        state: 'unavailable',
        eligible: null,
        uncertainty: null,
        revision: null,
        asOf: null,
      }).asOf,
    ).toBeNull();
    expect(() =>
      parseFact({
        state: 'unavailable',
        eligible: null,
        uncertainty: null,
        revision: null,
        asOf: T,
      }),
    ).toThrow();
  });
  it('validates applicability conclusion and exact current binding', () => {
    const fact = {
      state: 'current',
      eligible: true,
      uncertainty: 'none',
      revision: '2',
      asOf: T,
    };
    expect(parseCurrent({ ...end, fact }, end).fact.state).toBe('current');
    expect(() => parseCurrent({ ...end, generation: '2', fact }, end)).toThrow();
    expect(() => parseFact({ ...fact, uncertainty: 'missing' })).toThrow();
    expect(policyCopy({ policy: parseFact(fact), policyHistorical: true }).heading).toBe(
      'Previous case observation',
    );
  });
  it('keeps P2 source/state count equality without labelling dispatch as execution completion', () => {
    expect(parseProgress({ schemaVersion: 1, asOf: T, counts: counts() }).counts.workKnown).toBe(1);
    for (const patch of [
      { native: 3 },
      { workKnown: 2 },
      { pending: -1 },
      { sms: 1.5 },
      { running: 17 },
    ])
      expect(() =>
        parseProgress({
          schemaVersion: 1,
          asOf: T,
          counts: { ...counts(), ...patch },
        }),
      ).toThrow();
  });
  it('freezes exact SMS body/time/key and verifies public receipt source IDs', () => {
    const command = smsCommand({
        schemaVersion: 1,
        commandId: C,
        occurredAt: T,
        body: 'Investigate',
      }),
      event = 'cp_sms_' + C.replaceAll('-', '');
    const value = {
      schemaVersion: 1,
      commandId: C,
      replayed: false,
      receipt: {
        receiptId: B,
        eventId: event,
        messageId: event,
        acceptanceSequence: '1',
        acceptedAt: T,
      },
    };
    expect(parseSms(value, command).receipt.eventId).toBe(event);
    expect(() => parseSms({ ...value, commandId: B }, command)).toThrow();
    expect(() =>
      parseSms({ ...value, receipt: { ...value.receipt, eventId: 'different' } }, command),
    ).toThrow();
    expect(() => smsCommand({ ...command, body: '\ud800' })).toThrow();
  });
  it('enforces seven closed request purposes and exact response error/status pairs', () => {
    expect(encodeRequest('status', { schemaVersion: 1 })).toBe('{"schemaVersion":1}');
    expect(() => encodeRequest('status', { schemaVersion: 1, scope: 'foreign' })).toThrow();
    expect(
      errorCode({ schemaVersion: 1, status: 'unavailable', code: 'outcome_unknown' }, 503),
    ).toBe('outcome_unknown');
    expect(() =>
      errorCode({ schemaVersion: 1, status: 'unavailable', code: 'outcome_unknown' }, 400),
    ).toThrow();
  });
  it('copies finite own error codes without reading getters or retaining private errors', () => {
    const raw = Object.assign(new Error('PRIVATE'), { code: 'unauthorized' });
    const safe = safeCode(raw);
    expect(safe).not.toBe(raw);
    expect(safe.message).toBe('denied');
    expect(
      safeCode(
        new Proxy(
          {},
          {
            getOwnPropertyDescriptor() {
              throw new Error('PRIVATE');
            },
          },
        ),
      ).code,
    ).toBe('unavailable');
    let reads = 0;
    expect(
      safeCode({
        get code() {
          reads++;
          throw new Error('PRIVATE');
        },
      }).code,
    ).toBe('unavailable');
    expect(reads).toBe(0);
  });
});
