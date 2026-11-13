import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  ContractError,
  parseEventJson,
  produceTextEvent,
  type TextEventInput,
  type TrustedPrincipal,
} from '../src/index.js';
const fixture = JSON.parse(
  readFileSync(
    fileURLToPath(new URL('../../../contracts/channel/v1.json', import.meta.url)),
    'utf8',
  ),
) as {
  producerInput: TextEventInput;
  valid: {
    name: string;
    principal: TrustedPrincipal;
    event: Record<string, unknown>;
    canonical: string;
    identity: string;
  }[];
  invalid: { name: string; principal: TrustedPrincipal; raw: string; code: string }[];
};
const original = fixture.valid[0]!;
const clone = (): Record<string, unknown> => structuredClone(original.event);
function decode(event: Record<string, unknown>) {
  return parseEventJson(JSON.stringify(event), original.principal);
}
function code(action: () => unknown): string {
  try {
    action();
    throw new Error('Expected rejection');
  } catch (error) {
    expect(error).toBeInstanceOf(ContractError);
    return (error as ContractError).code;
  }
}
describe('versioned channel contract', () => {
  it('actual text producer matches the frozen complete wire fixture', () => {
    const result = produceTextEvent(fixture.producerInput, original.principal);
    expect(JSON.parse(result.wireJson)).toEqual(original.event);
    expect(result.canonical).toBe(original.canonical);
    expect(result.identity).toBe(original.identity);
  });
  it.each(fixture.valid)('accepts $name with exact cross-language canonical bytes', (test) => {
    const result = parseEventJson(JSON.stringify(test.event), test.principal);
    expect(JSON.parse(result.wireJson)).toEqual(test.event);
    expect(result.canonical).toBe(test.canonical);
    expect(result.identity).toBe(test.identity);
  });
  it.each(fixture.invalid)('rejects $name with a payload-free code', (test) => {
    expect(code(() => parseEventJson(test.raw, test.principal))).toBe(test.code);
    try {
      parseEventJson(test.raw, test.principal);
    } catch (error) {
      expect((error as Error).message).toBe(test.code);
    }
  });
  it('retains identity and canonical payload after retry metadata changes', () => {
    const initial = decode(clone());
    const event = clone();
    Object.assign(event, {
      receivedAt: '2030-12-02T12:00:00.000Z',
      signature: 'different',
      retryCount: 2,
    });
    const repeated = decode(event);
    expect(repeated.identity).toBe(initial.identity);
    expect(repeated.canonical).toBe(initial.canonical);
    expect(repeated.wireJson).not.toBe(initial.wireJson);
  });
  it.each([
    ['body', 'different'],
    ['conversationId', 'other-conversation'],
    ['caseId', 'other-case'],
    ['occurredAt', '2030-12-01T09:00:00.000Z'],
    ['expectedCaseRevision', 1],
  ])('preserves event key but changes semantics for %s', (key, value) => {
    const event = clone();
    event[key as string] = value;
    const result = decode(event);
    expect(result.identity).toBe(original.identity);
    expect(result.canonical).not.toBe(original.canonical);
  });
  it('keeps identical text under distinct event IDs distinct', () => {
    const event = clone();
    event.eventId = 'event-new';
    expect(decode(event).identity).not.toBe(original.identity);
  });
  it('counts UTF-8 bytes and allows useful valid progress after rejection', () => {
    const event = clone();
    event.body = '🧭'.repeat(1024);
    expect(decode(event).event.type).toBe('text.received');
    event.body += 'x';
    expect(code(() => decode(event))).toBe('InvalidEvent');
    event.body = 'valid follow-up';
    expect(decode(event).event.type).toBe('text.received');
  });
  it('deep freezes output and does not retain the mutable producer input', () => {
    const fields = structuredClone(fixture.producerInput);
    const result = produceTextEvent(fields, original.principal);
    expect(Object.isFrozen(result)).toBe(true);
    expect(Object.isFrozen(result.event)).toBe(true);
    expect(Object.isFrozen(result.event.providerScope)).toBe(true);
    expect(() => {
      (result.event.providerScope as { tenantId: string }).tenantId = 'changed';
    }).toThrow(TypeError);
    (fields as { body: string }).body = 'changed';
    expect(result.canonical).toBe(original.canonical);
  });
  it('does not derive account or case authority from provider identity', () => {
    const providerOnly = { providerScope: original.principal.providerScope };
    const event = clone();
    expect(code(() => parseEventJson(JSON.stringify(event), providerOnly))).toBe('AccessDenied');
    delete event.accountScope;
    expect(code(() => parseEventJson(JSON.stringify(event), providerOnly))).toBe(
      'AssociationRequired',
    );
    delete event.caseId;
    expect(parseEventJson(JSON.stringify(event), providerOnly).event.type).toBe('text.received');
  });
  it('rejects malformed producer objects safely including unsupported values and cycles', () => {
    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;
    const getter = Object.defineProperty({}, 'body', {
      get() {
        throw new Error('SENTINEL_SECRET');
      },
      enumerable: true,
    });
    for (const value of [
      null,
      [],
      'secret',
      cyclic,
      getter,
      { body: '\ud800' },
      { body: BigInt(2) },
      { body: NaN },
      { body: 1.5 },
      { extra: undefined },
    ]) {
      expect(code(() => produceTextEvent(value as TextEventInput, original.principal))).toBe(
        'InvalidEvent',
      );
    }
  });
  it('rejects arrays before invoking a custom serialization hook', () => {
    let invoked = false;
    const array: unknown[] & { toJSON?: () => unknown } = [];
    array.toJSON = () => {
      invoked = true;
      return 'forged';
    };
    const fields = { ...fixture.producerInput, body: array };
    expect(
      code(() => produceTextEvent(fields as unknown as TextEventInput, original.principal)),
    ).toBe('InvalidEvent');
    expect(invoked).toBe(false);
  });
  it('bounds shared-child amplification and aggregate text before serialization', () => {
    let shared: Record<string, unknown> = { text: 'bounded' };
    for (let depth = 0; depth < 6; depth++)
      shared = Object.fromEntries(
        Array.from({ length: 64 }, (_, index) => [`child${index}`, shared]),
      );
    for (const fields of [
      shared,
      Object.fromEntries(
        Array.from({ length: 9 }, (_, index) => [`part${index}`, 'a'.repeat(4096)]),
      ),
      { body: 'a'.repeat(1000000) },
    ]) {
      expect(code(() => produceTextEvent(fields as TextEventInput, original.principal))).toBe(
        'InvalidEvent',
      );
    }
    expect(produceTextEvent(fixture.producerInput, original.principal).canonical).toBe(
      original.canonical,
    );
  });
  it('accepts the exact raw UTF-8 byte limit and rejects one extra byte', () => {
    const wire = decode(clone()).wireJson;
    const bounded = wire + ' '.repeat(32768 - new TextEncoder().encode(wire).length);
    expect(parseEventJson(bounded, original.principal).canonical).toBe(original.canonical);
    expect(code(() => parseEventJson(bounded + ' ', original.principal))).toBe('InvalidEvent');
  });
  it('rejects oversized wire and excessive depth before useful parsing', () => {
    for (const raw of [' '.repeat(32769), '['.repeat(5000) + ']'.repeat(5000)])
      expect(code(() => parseEventJson(raw, original.principal))).toBe('InvalidEvent');
  });
  it.each(['\n', '\r', '\u2028', '\u2029'])(
    'rejects trailing terminator in trusted provider scope',
    (suffix) => {
      const principal = {
        ...original.principal,
        providerScope: {
          ...original.principal.providerScope,
          providerAccountId: 'provider-demo' + suffix,
        },
      };
      expect(code(() => parseEventJson(JSON.stringify(original.event), principal))).toBe(
        'InvalidEvent',
      );
    },
  );
});
