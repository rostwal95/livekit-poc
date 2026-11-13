import { createHmac } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import type { ProviderScope } from '../src/index.js';
import {
  authenticateFakeSms,
  createFakeSmsIntegration,
  signFakeSms,
  WebhookError,
  type FakeSmsIntegration,
  type FakeSmsMessage,
  type SignedFakeSms,
  type WebhookHeaders,
} from '../src/security.js';

const NOW = 1893456000;
const KEY = Buffer.from('synthetic-test-key-00000000000000000001', 'utf8');
const SCOPE: ProviderScope = Object.freeze({
  tenantId: 'tenant-demo',
  provider: 'fake_sms',
  providerAccountId: 'carrier-demo',
});
const MESSAGE: FakeSmsMessage = Object.freeze({
  schemaVersion: 1,
  eventId: 'event-demo',
  messageId: 'message-demo',
  senderId: 'sender-demo',
  body: 'Please inspect DEMO',
  occurredAt: '2030-01-01T00:00:00.000Z',
});
const RAW =
  '{"schemaVersion":1,"eventId":"event-demo","messageId":"message-demo","senderId":"sender-demo","body":"Please inspect DEMO","occurredAt":"2030-01-01T00:00:00.000Z"}';
const EXPECTED_MAC = 'ae2e87c5aa1852087db962b436ed60ffbb8b4910f648d5d174303f340b90480c';
const INTEGRATION = createFakeSmsIntegration(SCOPE, KEY);
function signed(message = MESSAGE, seconds = NOW): SignedFakeSms {
  return signFakeSms(message, KEY, seconds, SCOPE);
}
/** Independent transport oracle, including valid signatures on deliberately invalid bodies. */
function rawSigned(raw: Uint8Array, timestamp = String(NOW), scope = SCOPE): SignedFakeSms {
  const preamble = `p2.fake_sms.v1\n${scope.tenantId}\n${scope.provider}\n${scope.providerAccountId}\n${timestamp}\n`;
  const signature = createHmac('sha256', KEY).update(preamble, 'utf8').update(raw).digest('hex');
  return { raw, headers: { timestamp, signature } };
}
function rejected(action: () => unknown): void {
  try {
    action();
    throw new Error('Expected WebhookRejected');
  } catch (error) {
    expect(error).toBeInstanceOf(WebhookError);
    expect((error as WebhookError).code).toBe('WebhookRejected');
    expect((error as Error).message).toBe('WebhookRejected');
    expect(String(error)).not.toContain(KEY.toString('utf8'));
    expect(String(error)).not.toContain(MESSAGE.body);
    expect(String(error)).not.toContain(EXPECTED_MAC);
  }
}
function authenticate(frame: SignedFakeSms, integration = INTEGRATION, now = NOW) {
  return authenticateFakeSms(frame.raw, frame.headers, integration, now);
}

describe('synthetic carrier authentication', () => {
  it('matches a separately computed fixed HMAC vector and actual signer wire bytes', () => {
    const frame = signed();
    expect(Buffer.from(frame.raw).toString('utf8')).toBe(RAW);
    expect(frame.headers).toEqual({ timestamp: '1893456000', signature: EXPECTED_MAC });
    expect(authenticate(frame)).toEqual({
      ...MESSAGE,
      providerScope: SCOPE,
      authenticatedAtSeconds: NOW,
    });
  });
  it('authenticates actual non-ASCII UTF-8 bytes rather than a normalized reconstruction', () => {
    const frame = signed({ ...MESSAGE, body: 'Café 🧭\nexact bytes' });
    expect(frame.headers.signature).toBe(rawSigned(frame.raw).headers.signature);
    expect(authenticate(frame).body).toBe('Café 🧭\nexact bytes');
  });
  it('accepts duplicate provider observations in-window without inventing DB dedupe', () => {
    const frame = signed();
    expect(authenticate(frame)).toEqual(authenticate(frame));
    const reSigned = signed(MESSAGE, NOW + 10);
    expect(authenticate(reSigned, INTEGRATION, NOW + 10).eventId).toBe(MESSAGE.eventId);
  });
  it.each([-60, -59, 0, 59, 60])(
    'accepts the inclusive signed timestamp window offset %i',
    (offset) => {
      expect(authenticate(signed(MESSAGE, NOW + offset)).senderId).toBe(MESSAGE.senderId);
    },
  );
  it.each([-61, 61, -600, 600])(
    'rejects an expired/future signed timestamp offset %i',
    (offset) => {
      rejected(() => authenticate(signed(MESSAGE, NOW + offset)));
    },
  );
  it('rejects signature tampering, wrong key and timestamp mutation', () => {
    const frame = signed();
    rejected(() =>
      authenticate({ ...frame, headers: { ...frame.headers, signature: '0'.repeat(64) } }),
    );
    rejected(() => authenticate(frame, createFakeSmsIntegration(SCOPE, Buffer.alloc(32, 7))));
    rejected(() =>
      authenticate({ ...frame, headers: { ...frame.headers, timestamp: String(NOW + 1) } }),
    );
  });
  it.each([
    { ...SCOPE, tenantId: 'other-tenant' },
    { ...SCOPE, providerAccountId: 'other-carrier' },
  ])('binds reused keys to the exact configured scope $tenantId/$providerAccountId', (scope) => {
    const other = createFakeSmsIntegration(scope, KEY);
    rejected(() => authenticate(signed(), other));
    const otherFrame = signFakeSms(MESSAGE, KEY, NOW, scope);
    expect(authenticate(otherFrame, other).providerScope).toEqual(scope);
    rejected(() => authenticate(otherFrame));
  });
  it('rejects a forged integration object despite matching visible scope', () => {
    rejected(() => authenticate(signed(), { providerScope: SCOPE } as FakeSmsIntegration));
  });
  it('rejects changed raw whitespace/content without a new exact-byte signature', () => {
    const frame = signed();
    rejected(() => authenticate({ ...frame, raw: Buffer.from(RAW + ' ') }));
    rejected(() => authenticate({ ...frame, raw: Buffer.from(RAW.replace('DEMO', 'OTHER')) }));
    const spaced = rawSigned(Buffer.from(' \n' + RAW + '\t '));
    expect(authenticate(spaced).eventId).toBe(MESSAGE.eventId);
  });
  it.each([
    '',
    'A'.repeat(64),
    'g'.repeat(64),
    'a'.repeat(63),
    'a'.repeat(65),
    EXPECTED_MAC + '\n',
    EXPECTED_MAC + '\r',
    EXPECTED_MAC + '\u2028',
  ])('rejects malformed MAC encoding without leaking details', (signature) => {
    const frame = signed();
    rejected(() => authenticate({ ...frame, headers: { ...frame.headers, signature } }));
  });
  it.each([
    '01893456000',
    '1893456000\n',
    '1893456000\r',
    '1893456000\u2028',
    '1.893456e9',
    '1893456000.0',
    '-1893456000',
    '18934560000',
  ])('rejects noncanonical header timestamp %s', (timestamp) => {
    const frame = signed();
    rejected(() => authenticate({ ...frame, headers: { ...frame.headers, timestamp } }));
  });
  it.each([NaN, Infinity, NOW + 0.5, 0, 10000000000])(
    'rejects invalid verifier clock %s',
    (now) => {
      rejected(() => authenticate(signed(), INTEGRATION, now));
    },
  );
  it.each([
    RAW.replace('"eventId":"event-demo"', '"eventId":"event-demo","eventId":"other"'),
    RAW.replace('"eventId":"event-demo"', '"eventId":"event-demo","event\\u0049d":"other"'),
    RAW.replace('"schemaVersion":1', '"schemaVersion":1.0'),
    RAW.replace('"schemaVersion":1', '"schemaVersion":1e0'),
    RAW.replace('"schemaVersion":1', '"schemaVersion":true'),
    RAW.replace('"schemaVersion":1', '"schemaVersion":2'),
    RAW.replace('"body":"Please inspect DEMO"', '"body":null'),
    RAW.replace('"senderId":"sender-demo"', '"senderId":"sender-demo\\n"'),
    RAW.replace('"body":"Please inspect DEMO"', '"body":"\\ud800"'),
    RAW.slice(0, -1) + ',}',
    RAW + ' null',
    '[]',
    '{}',
  ])('rejects authenticated malformed flat JSON %#', (raw) => {
    rejected(() => authenticate(rawSigned(Buffer.from(raw))));
  });
  it.each(['tenantId', 'accountScope', 'conversationId', 'caseId', 'providerScope'])(
    'rejects a signed body attempting to attach %s authority',
    (field) => {
      const raw = Buffer.from(JSON.stringify({ ...MESSAGE, [field]: 'forged-scope' }));
      rejected(() => authenticate(rawSigned(raw)));
    },
  );
  it('rejects authenticated nested objects and wrong message/sender types', () => {
    for (const value of [
      { ...MESSAGE, senderId: { accountId: 'forged' } },
      { ...MESSAGE, senderId: 4 },
      { ...MESSAGE, messageId: [] },
      { ...MESSAGE, occurredAt: '2030-02-30T00:00:00.000Z' },
    ]) {
      rejected(() => authenticate(rawSigned(Buffer.from(JSON.stringify(value)))));
    }
  });
  it('validates strict UTF-8 after checking the exact signed bytes', () => {
    rejected(() => authenticate(rawSigned(Buffer.from([0xff, 0xfe, 0xfd]))));
  });
  it('accepts the exact wire byte bound and rejects an extra byte', () => {
    const bounded = Buffer.from(RAW + ' '.repeat(32768 - Buffer.byteLength(RAW)));
    expect(authenticate(rawSigned(bounded)).body).toBe(MESSAGE.body);
    rejected(() => authenticate(rawSigned(Buffer.concat([bounded, Buffer.from(' ')]))));
    rejected(() => authenticate(rawSigned(Buffer.alloc(0))));
  });
  it('uses the existing UTF-8 text bound and still permits valid progress', () => {
    const message = { ...MESSAGE, body: '🧭'.repeat(1024) };
    expect(authenticate(signed(message)).body).toBe(message.body);
    const raw = Buffer.from(JSON.stringify({ ...message, body: message.body + 'x' }));
    rejected(() => authenticate(rawSigned(raw)));
    expect(authenticate(signed()).eventId).toBe(MESSAGE.eventId);
  });
  it('copies configured key/scope and exposes no key through serialization', () => {
    const key = Buffer.from(KEY);
    const scope = { ...SCOPE };
    const integration = createFakeSmsIntegration(scope, key);
    key.fill(0);
    scope.providerAccountId = 'mutated';
    expect(authenticate(signed(), integration).providerScope).toEqual(SCOPE);
    expect(JSON.stringify(integration)).toBe(JSON.stringify({ providerScope: SCOPE }));
    expect(Object.keys(integration)).toEqual(['providerScope']);
    expect(JSON.stringify(integration)).not.toContain(KEY.toString('utf8'));
  });
  it('returns an immutable observation detached from later transport mutation', () => {
    const frame = signed();
    const result = authenticate(frame);
    frame.raw.fill(0);
    expect(result.body).toBe(MESSAGE.body);
    expect(Object.isFrozen(result)).toBe(true);
    expect(Object.isFrozen(result.providerScope)).toBe(true);
    expect(() => {
      (result.providerScope as { tenantId: string }).tenantId = 'other';
    }).toThrow(TypeError);
    expect(Object.keys(result)).not.toContain('accountScope');
    expect(Object.keys(result)).not.toContain('conversationId');
    expect(Object.keys(result)).not.toContain('caseId');
  });
  it('rejects accessor/header or signer serialization hooks without invoking them', () => {
    let invoked = false;
    const headers = Object.defineProperty({ signature: EXPECTED_MAC }, 'timestamp', {
      enumerable: true,
      get() {
        invoked = true;
        throw new Error('SECRET_SENTINEL');
      },
    });
    rejected(() => authenticate({ raw: Buffer.from(RAW), headers: headers as WebhookHeaders }));
    const message = Object.defineProperty({ ...MESSAGE }, 'body', {
      enumerable: true,
      get() {
        invoked = true;
        throw new Error('SECRET_SENTINEL');
      },
    });
    rejected(() => signFakeSms(message as FakeSmsMessage, KEY, NOW, SCOPE));
    expect(invoked).toBe(false);
  });
  it('rejects malformed key/configuration without dumping raw diagnostics', () => {
    for (const key of [
      Buffer.alloc(0),
      Buffer.alloc(31),
      Buffer.alloc(65),
      'PRIVATE_KEY_SENTINEL' as unknown as Uint8Array,
    ])
      rejected(() => createFakeSmsIntegration(SCOPE, key));
    rejected(() => createFakeSmsIntegration({ ...SCOPE, tenantId: 'tenant-demo\n' }, KEY));
    rejected(() => createFakeSmsIntegration({ ...SCOPE, provider: 'livekit' }, KEY));
  });
});
