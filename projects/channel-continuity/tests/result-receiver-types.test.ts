import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import {
  parseResultIntent,
  encodeResultIntent,
  resultIntent,
  resultReceipt,
  matchResultReceipt,
  resultRoute,
} from '../src/result-receiver-codec.js';
import { RESULT_NOTICE, ResultReceiverError } from '../src/result-receiver-types.js';
const shared = JSON.parse(
  readFileSync(
    new URL('../../../contracts/delegation/result-receiver-v1.json', import.meta.url),
    'utf8',
  ),
) as {
  schema_version: 1;
  intent_canonical: string;
  receipt: unknown;
  notice: string;
  negative_intents: { name: string; canonical: string }[];
};
const original = parseResultIntent(shared.intent_canonical);
describe('exact P1 receiver wire and immutable bindings', () => {
  it('executes the shared Python-produced canonical intent/receipt without replacing the result SHA with notice SHA', () => {
    expect(encodeResultIntent(original)).toBe(shared.intent_canonical);
    expect(shared.notice).toBe(RESULT_NOTICE);
    const receipt = resultReceipt(shared.receipt);
    expect(() => matchResultReceipt(original, receipt)).not.toThrow();
    expect(createHash('sha256').update(Buffer.from(original.body, 'base64')).digest('hex')).toBe(
      original.result_sha256,
    );
    expect(createHash('sha256').update(RESULT_NOTICE).digest('hex')).not.toBe(
      original.result_sha256,
    );
    expect(Object.isFrozen(original)).toBe(true);
    expect(Object.isFrozen(original.scope)).toBe(true);
  });
  it.each(shared.negative_intents)(
    'rejects shared raw canonical control $name',
    ({ canonical }) => {
      expect(() => parseResultIntent(canonical)).toThrow(ResultReceiverError);
    },
  );
  it('rejects all changed receipt identity fields and retains accepted time as a distinct actual observation', () => {
    const receipt = resultReceipt(shared.receipt);
    for (const changed of [
      { delivery_id: randomUUID() },
      { receiver_id: randomUUID() },
      { recipient_id: 'foreign' },
      { result_sha256: 'f'.repeat(64) },
    ])
      expect(() => matchResultReceipt(original, { ...receipt, ...changed })).toThrow();
    expect(() => resultReceipt({ ...receipt, accepted_at_ms: true })).toThrow();
    expect(() => resultReceipt({ ...receipt, extra: 1 })).toThrow();
  });
  it('does not execute getters, toJSON or coercion while snapshotting incoming fields', () => {
    let touched = 0;
    const value = { ...original };
    Object.defineProperty(value, 'body', {
      enumerable: true,
      get() {
        touched++;
        return original.body;
      },
    });
    expect(() => resultIntent(value)).toThrow();
    expect(touched).toBe(0);
    const badScope = { ...original.scope };
    Object.defineProperty(badScope, 'tenant_id', {
      enumerable: true,
      get() {
        touched++;
        return 'tenant';
      },
    });
    expect(() => resultIntent({ ...original, scope: badScope })).toThrow();
    expect(touched).toBe(0);
  });
  it('accepts exact8192 bytes and rejects next byte, noncanonical padding and timestamps outside P1 range', () => {
    const body = Buffer.alloc(8192, 0x61),
      full = {
        ...original,
        body: body.toString('base64'),
        result_sha256: createHash('sha256').update(body).digest('hex'),
      };
    expect(Buffer.from(parseResultIntent(encodeResultIntent(full)).body, 'base64').length).toBe(
      8192,
    );
    const over = Buffer.alloc(8193);
    expect(() =>
      resultIntent({
        ...full,
        body: over.toString('base64'),
        result_sha256: createHash('sha256').update(over).digest('hex'),
      }),
    ).toThrow();
    for (const time of [-1, true, NaN, 1.5, 4102444800001])
      expect(() => resultIntent({ ...original, prepared_at_ms: time })).toThrow();
    for (const body of ['YQ', 'YR==', 'YQ===', 'YQ==\n', 'YQ-_'])
      expect(() => resultIntent({ ...original, body })).toThrow();
  });
  it('keeps the P1 integration vocabulary explicit instead of accepting broad P2 IDs or reader publisher secrets', () => {
    const route = {
      scope: { tenantId: 'tenant', accountId: 'account' },
      caseId: 'case',
      conversationId: 'conversation',
      recipientId: 'recipient',
    };
    expect(resultRoute(route)).toEqual(route);
    expect(() => resultRoute({ ...route, publisherToken: 'x'.repeat(43) })).toThrow();
    for (const caseId of ['UPPER', 'a'.repeat(65), 'with.dot', 'bad\n'])
      expect(() => resultRoute({ ...route, caseId })).toThrow();
  });
});
