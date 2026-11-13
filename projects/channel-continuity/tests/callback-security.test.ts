import { describe, it, expect } from 'vitest';
import { randomUUID, createHmac } from 'node:crypto';
import {
  createFakeSmsCallbackIntegration,
  signFakeSmsCallback,
  authenticateFakeSmsCallback,
} from '../src/callback-security.js';
import { signFakeSms, createFakeSmsIntegration } from '../src/security.js';
import {
  CallbackError,
  callbackObservation,
  type CallbackObservation,
} from '../src/callback-types.js';
const scope = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' },
  key = Buffer.alloc(32, 9),
  now = 1800000000;
const observation: CallbackObservation = {
  schemaVersion: 1,
  eventId: 'event-a',
  attemptId: randomUUID(),
  providerOperationKey: randomUUID(),
  requestDigest: 'a'.repeat(64),
  providerMessageId: 'message-a',
  state: 'delivered',
  occurredAt: '2030-01-01T00:00:00.000Z',
};
function signedRaw(raw: string) {
  const timestamp = String(now);
  return {
    raw: Buffer.from(raw),
    headers: {
      timestamp,
      signature: createHmac('sha256', key)
        .update(
          'p2.fake_sms_callback.v1\n' +
            scope.tenantId +
            '\n' +
            scope.provider +
            '\n' +
            scope.providerAccountId +
            '\n' +
            timestamp +
            '\n',
        )
        .update(raw)
        .digest('hex'),
    },
  };
}
function authenticate(raw = JSON.stringify(observation)) {
  const s = signedRaw(raw);
  return authenticateFakeSmsCallback(
    s.raw,
    s.headers,
    createFakeSmsCallbackIntegration(scope, key),
    now,
  );
}
describe('callback-specific raw authentication', () => {
  it('copies key and scope, preserves raw signed evidence and normalized exact eight fields', () => {
    const bytes = Buffer.from(key),
      input = { ...scope },
      integration = createFakeSmsCallbackIntegration(input, bytes);
    input.providerAccountId = 'changed';
    bytes.fill(0);
    const signed = signFakeSmsCallback(observation, key, now, scope),
      v = authenticateFakeSmsCallback(signed.raw, signed.headers, integration, now);
    expect(v.observation).toEqual(observation);
    expect(v.raw).toBe(JSON.stringify(observation));
    expect(Object.keys(v.observation)).toHaveLength(8);
    expect(Object.isFrozen(v.providerScope)).toBe(true);
    signed.raw.fill(0);
    expect(v.observation).toEqual(observation);
  });
  it('fresh retry timestamp is transport only; key order/whitespace/escaped values normalize', () => {
    const entries = Object.entries(observation).reverse();
    const raw =
      '{ ' +
      entries.map(([k, v]) => JSON.stringify(k) + ' : ' + JSON.stringify(v)).join(', ') +
      ' }';
    expect(authenticate(raw).observation).toEqual(observation);
    const s = signFakeSmsCallback(observation, key, now + 30, scope);
    expect(
      authenticateFakeSmsCallback(
        s.raw,
        s.headers,
        createFakeSmsCallbackIntegration(scope, key),
        now,
      ).observation,
    ).toEqual(observation);
  });
  it.each([-61, 61])('rejects stale or future envelope %d', (offset) => {
    const s = signFakeSmsCallback(observation, key, now + offset, scope);
    expect(() =>
      authenticateFakeSmsCallback(
        s.raw,
        s.headers,
        createFakeSmsCallbackIntegration(scope, key),
        now,
      ),
    ).toThrow(CallbackError);
  });
  it.each([-60, 60])('accepts boundary envelope %d', (offset) => {
    const s = signFakeSmsCallback(observation, key, now + offset, scope);
    expect(
      authenticateFakeSmsCallback(
        s.raw,
        s.headers,
        createFakeSmsCallbackIntegration(scope, key),
        now,
      ).observation,
    ).toEqual(observation);
  });
  it('rejects inbound SMS domain and inbound integration object', () => {
    const s = signFakeSms(
      {
        schemaVersion: 1,
        eventId: 'x',
        messageId: 'x',
        senderId: 'x',
        body: 'hello',
        occurredAt: observation.occurredAt,
      },
      key,
      now,
      scope,
    );
    expect(() =>
      authenticateFakeSmsCallback(
        s.raw,
        s.headers,
        createFakeSmsCallbackIntegration(scope, key),
        now,
      ),
    ).toThrow(CallbackError);
    const cb = signFakeSmsCallback(observation, key, now, scope);
    expect(() =>
      authenticateFakeSmsCallback(cb.raw, cb.headers, createFakeSmsIntegration(scope, key), now),
    ).toThrow(CallbackError);
  });
  it.each([
    { ...scope, tenantId: 'other' },
    { ...scope, providerAccountId: 'other' },
  ])('binds exact configured provider scope %j', (other) => {
    const s = signFakeSmsCallback(observation, key, now, scope);
    expect(() =>
      authenticateFakeSmsCallback(
        s.raw,
        s.headers,
        createFakeSmsCallbackIntegration(other, key),
        now,
      ),
    ).toThrow(CallbackError);
  });
  it('rejects altered raw bytes and wrong key', () => {
    const s = signFakeSmsCallback(observation, key, now, scope);
    s.raw[s.raw.length - 1] = 32;
    expect(() =>
      authenticateFakeSmsCallback(
        s.raw,
        s.headers,
        createFakeSmsCallbackIntegration(scope, key),
        now,
      ),
    ).toThrow(CallbackError);
    const t = signFakeSmsCallback(observation, key, now, scope);
    expect(() =>
      authenticateFakeSmsCallback(
        t.raw,
        t.headers,
        createFakeSmsCallbackIntegration(scope, Buffer.alloc(32, 8)),
        now,
      ),
    ).toThrow(CallbackError);
  });
  it.each([0, 31, 65])('rejects key bytes %d', (n) =>
    expect(() => createFakeSmsCallbackIntegration(scope, Buffer.alloc(n))).toThrow(CallbackError),
  );
  it.each([
    '',
    '{}',
    '[]',
    'null',
    '{' + JSON.stringify(observation).slice(1, -1) + ',"state":"failed"}',
    '{' + JSON.stringify(observation).slice(1, -1) + ',"extra":"x"}',
    JSON.stringify(observation) + 'x',
    JSON.stringify({ ...observation, schemaVersion: '1' }),
    JSON.stringify({ ...observation, state: [] }),
    JSON.stringify({ ...observation, eventId: 'é' }),
    JSON.stringify({ ...observation, occurredAt: '2030-02-30T00:00:00.000Z' }),
    JSON.stringify({ ...observation, occurredAt: '2030-01-01T00:00:00Z' }),
    JSON.stringify({ ...observation, requestDigest: 'A'.repeat(64) }),
    JSON.stringify({ ...observation, providerMessageId: '\ud800' }),
  ])('rejects invalid signed JSON %s', (raw) =>
    expect(() => authenticate(raw)).toThrow(CallbackError),
  );
  it('rejects invalid UTF8 and size before parsing', () => {
    const s = signedRaw(' '.repeat(4097));
    expect(() =>
      authenticateFakeSmsCallback(
        s.raw,
        s.headers,
        createFakeSmsCallbackIntegration(scope, key),
        now,
      ),
    ).toThrow(CallbackError);
    expect(() =>
      authenticateFakeSmsCallback(
        Buffer.from([255]),
        s.headers,
        createFakeSmsCallbackIntegration(scope, key),
        now,
      ),
    ).toThrow(CallbackError);
  });
  it('never executes accessor or coercion', () => {
    let touched = 0;
    const input = { ...observation };
    Object.defineProperty(input, 'state', {
      enumerable: true,
      get() {
        touched++;
        return 'delivered';
      },
    });
    expect(() => callbackObservation(input)).toThrow(CallbackError);
    const headers = {
      timestamp: String(now),
      get signature() {
        touched++;
        return 'a'.repeat(64);
      },
    };
    expect(() =>
      authenticateFakeSmsCallback(
        Buffer.from('{}'),
        headers,
        createFakeSmsCallbackIntegration(scope, key),
        now,
      ),
    ).toThrow(CallbackError);
    expect(touched).toBe(0);
  });
});
