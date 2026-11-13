/** Actual pure fixture ownership helper; no PG or synthetic cleanup claim. */
import { describe, it, expect } from 'vitest';
import {
  cleanupOperationsOwners,
  inspectOperationsOriginals,
  normalizeOperationsOriginal,
} from './operations-fixture-work.js';
import { produceTextEvent, parseEventJson } from '../src/index.js';
import { rehydrationContext, RehydrationError } from '../src/rehydration-types.js';
describe('operations fixture dependent closure', () => {
  it('attempts independent peers but withholds shared owners on failed close', async () => {
    const seen: string[] = [],
      failure = Error('fixed');
    await expect(
      cleanupOperationsOwners([
        [
          async () => {
            seen.push('reader');
            throw failure;
          },
          async () => {
            seen.push('observer');
          },
        ],
        [
          async () => {
            seen.push('inbox');
          },
          async () => {
            seen.push('case');
          },
        ],
      ]),
    ).rejects.toBe(failure);
    expect(seen).toEqual(['reader', 'observer']);
  });
  it('preserves original failure while attempting every safe independent owner', async () => {
    const primary = Error('primary'),
      secondary = Error('secondary');
    let other = 0,
      dependent = 0;
    await expect(
      cleanupOperationsOwners(
        [
          [
            () => Promise.reject(secondary),
            () => {
              other++;
            },
          ],
          [
            () => {
              dependent++;
            },
          ],
        ],
        primary,
      ),
    ).rejects.toBe(primary);
    expect(other).toBe(1);
    expect(dependent).toBe(0);
  });
  it('does not advance to shared owners until actual asynchronous closure settles', async () => {
    let release: () => void = () => {},
      dependent = 0,
      settled = false;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const work = cleanupOperationsOwners([
      [() => held],
      [
        () => {
          dependent++;
        },
      ],
    ]).then(() => {
      settled = true;
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(dependent).toBe(0);
    expect(settled).toBe(false);
    release();
    await work;
    expect(dependent).toBe(1);
    expect(settled).toBe(true);
  });
  it('successful closure preserves an earlier business assertion error', async () => {
    const primary = Error('primary');
    let count = 0;
    await expect(
      cleanupOperationsOwners(
        [
          [
            () => {
              count++;
            },
          ],
          [
            () => {
              count++;
            },
          ],
        ],
        primary,
      ),
    ).rejects.toBe(primary);
    expect(count).toBe(2);
  });
});

describe('fixed original inspection evidence schedule', () => {
  it('reproduces old10-request overload and collects the same originals within the public4-call budget', async () => {
    const values = Array.from({ length: 10 }, (_, n) => n);
    const probe = () => {
      let active = 0,
        maximum = 0;
      return {
        get active() {
          return active;
        },
        get maximum() {
          return maximum;
        },
        async inspect(value: number) {
          if (active >= 4) throw Error('Overloaded');
          active++;
          maximum = Math.max(maximum, active);
          try {
            await Promise.resolve();
            return { original: value };
          } finally {
            active--;
          }
        },
      };
    };
    const old = probe();
    await expect(Promise.all(values.map((v) => old.inspect(v)))).rejects.toThrow('Overloaded');
    expect(old.maximum).toBe(4);
    expect(old.active).toBe(0);
    const current = probe();
    expect(await inspectOperationsOriginals(values, (v) => current.inspect(v))).toEqual(
      values.map((original) => ({ original })),
    );
    expect(current.maximum).toBe(1);
    expect(current.active).toBe(0);
  });
  it('does not launch later inspection after an actual evidence read failure', async () => {
    const called: number[] = [],
      failure = Error('fixed');
    await expect(
      inspectOperationsOriginals(
        Array.from({ length: 10 }, (_, n) => n),
        async (n) => {
          called.push(n);
          if (n === 3) throw failure;
          return n;
        },
      ),
    ).rejects.toBe(failure);
    expect(called).toEqual([0, 1, 2, 3]);
  });
});

describe('retained full DTO identity across canonical wire and JSON proof', () => {
  it('rejects order-only JSON comparison while preserving every normalized original field', () => {
    const scope = { tenantId: 'ops-paging', accountId: 'account' },
      ref = { scope, caseId: 'case', conversationId: 'conversation' },
      providerScope = {
        tenantId: scope.tenantId,
        provider: 'livekit',
        providerAccountId: 'native',
      },
      stamp = '2030-01-01T00:00:00.000Z',
      id = '11111111-1111-4111-8111-111111111111',
      receiptId = '22222222-2222-4222-8222-222222222222',
      operationKey = '33333333-3333-4333-8333-333333333333';
    const produced = produceTextEvent(
      {
        eventId: id,
        messageId: id,
        providerScope,
        accountScope: scope,
        caseId: ref.caseId,
        conversationId: ref.conversationId,
        receivedAt: stamp,
        channel: 'web_chat',
        senderId: id,
        body: 'Canonical retained observation Ω',
      },
      { providerScope, accountScope: scope },
    );
    // Actual decodeStoredMessage uses the canonical wire JSON before the proof's JSON round trip.
    const original = JSON.parse(
      JSON.stringify({
        receipt: {
          receiptId,
          eventId: id,
          messageId: id,
          acceptanceSequence: '1',
          acceptedAt: stamp,
        },
        event: parseEventJson(produced.wireJson, { providerScope, accountScope: scope }).event,
        operationKey,
        processingState: 'pending',
        associationVersion: '1',
      }),
    ) as Record<string, unknown>;
    const context = rehydrationContext(
      {
        schemaVersion: 1,
        contextId: id,
        access: { kind: 'native', bindingId: id, roomId: 'room', participantId: 'browser' },
        case: {
          schemaVersion: 1,
          source: 'standalone_reference_v1',
          ...ref,
          revision: '1',
          request: {
            schemaVersion: 1,
            kind: 'booking_investigation',
            bookingReference: 'BK-001',
            newCheckIn: '2030-12-10',
            investigationConsent: true,
          },
          workflow: null,
          intent: { state: 'not_committed', intentId: null },
          mutation: {
            state: 'not_observed',
            outcome: 'not_observed',
            cancellation: 'not_observed',
            effectId: null,
            outcomeEventId: null,
          },
          supplierResult: null,
          sourceRevision: 'a'.repeat(64),
        },
        history: { messages: [original], nextCursor: null, hasMore: false },
        work: { items: [], nextCursor: null, hasMore: false },
        responses: { items: [], nextCursor: null, hasMore: false },
        replies: { items: [], nextCursor: null, hasMore: false },
        observed: {
          p2ObservedAt: stamp,
          caseObservedAt: stamp,
          disclosureAdmittedAt: stamp,
          atomic: false,
        },
      },
      ref,
    );
    const returned = context.history.messages[0]!;
    expect(JSON.stringify(returned)).not.toBe(JSON.stringify(original));
    expect(normalizeOperationsOriginal(context, original)).toEqual(returned);
    expect(
      normalizeOperationsOriginal(context, Object.fromEntries(Object.entries(original).reverse())),
    ).toEqual(returned);
    const event = original.event as Record<string, unknown>,
      receipt = original.receipt as Record<string, unknown>;
    expect(
      normalizeOperationsOriginal(context, {
        ...original,
        event: { ...event, body: 'Changed retained observation' },
      }),
    ).not.toEqual(returned);
    expect(
      normalizeOperationsOriginal(context, {
        ...original,
        receipt: { ...receipt, acceptedAt: '2030-01-02T00:00:00.000Z' },
      }),
    ).not.toEqual(returned);
    expect(() =>
      normalizeOperationsOriginal(context, {
        ...original,
        receipt: { ...receipt, eventId: 'wrong-original-event' },
      }),
    ).toThrow(RehydrationError);
    expect(
      parseEventJson(produced.wireJson, { providerScope, accountScope: scope }).canonical,
    ).toBe(produced.canonical);
  });
});
