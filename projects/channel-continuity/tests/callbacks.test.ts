import { afterEach, describe, it, expect, vi } from 'vitest';
import { randomUUID } from 'node:crypto';
import {
  CallbackInbox,
  CallbackError,
  reduceCallbackEvidence,
  createFakeSmsCallbackIntegration,
  signFakeSmsCallback,
  type CallbackObservation,
  type CallbackReceipt,
} from '../src/callbacks.js';
import { CallbackStore } from '../src/callback-store.js';
import { callbackLimits } from '../src/callback-types.js';
import { SeededAccounts } from '../src/postgres.js';
const scope = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' },
  key = Buffer.alloc(32, 9),
  db = {
    host: '127.0.0.1',
    port: 15432,
    database: 'livekit_lab',
    user: 'livekit_lab',
    password: 'x'.repeat(40),
    schema: 'p2_callback_unit',
  },
  observation: CallbackObservation = {
    schemaVersion: 1,
    eventId: 'event-a',
    attemptId: randomUUID(),
    providerOperationKey: randomUUID(),
    requestDigest: 'a'.repeat(64),
    providerMessageId: 'message-a',
    state: 'delivered',
    occurredAt: '2030-01-01T00:00:00.000Z',
  },
  receipt: CallbackReceipt = {
    receiptId: randomUUID(),
    eventId: 'event-a',
    attemptId: observation.attemptId,
    payloadDigest: 'b'.repeat(64),
    acceptedAt: observation.occurredAt,
  };
const accounts = () =>
  new SeededAccounts([
    {
      token: 'account_'.repeat(6),
      tenantId: 'tenant-a',
      accountId: 'account-a',
      conversationId: 'conversation-a',
      caseId: 'case-a',
    },
  ]);
const runtime = (options: ConstructorParameters<typeof CallbackInbox>[3] = {}) =>
  new CallbackInbox(db, createFakeSmsCallbackIntegration(scope, key), accounts(), {
    observer: () => {},
    ...options,
  });
const signed = () => signFakeSmsCallback(observation, key, Math.floor(Date.now() / 1000), scope);
const deferred = <T>() => {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};
afterEach(() => vi.restoreAllMocks());
describe('order-independent provider reports', () => {
  it('rejects hostile arrays without overridden map or element accessors executing', () => {
    let touched = 0;
    const a = [observation];
    Object.defineProperty(a, '0', {
      enumerable: true,
      get() {
        touched++;
        return observation;
      },
    });
    expect(() => reduceCallbackEvidence(a, null)).toThrow(CallbackError);
    const b = [observation];
    b.map = (() => {
      touched++;
      throw Error('sentinel');
    }) as typeof b.map;
    expect(() => reduceCallbackEvidence(b, null)).toThrow(CallbackError);
    class Hostile extends Array<CallbackObservation> {}
    expect(() => reduceCallbackEvidence(new Hostile(observation), null)).toThrow(CallbackError);
    expect(touched).toBe(0);
  });
  it('rejects unrelated attempt/result identities', () => {
    expect(() =>
      reduceCallbackEvidence([observation, { ...observation, attemptId: randomUUID() }], null),
    ).toThrow(CallbackError);
    expect(() =>
      reduceCallbackEvidence([observation], {
        schemaVersion: 1,
        attemptId: randomUUID(),
        requestDigest: observation.requestDigest,
        status: 'definitive_not_accepted',
      }),
    ).toThrow(CallbackError);
  });
  it('distinguishes no reports from a known send result', () => {
    expect(reduceCallbackEvidence([], null).assessment).toBe('none');
  });
  it('retains weaker reordered observations without regression', () => {
    const states = ['accepted_by_provider', 'delivered', 'unknown', 'read_reported'] as const;
    const data = states.map((state) => ({ ...observation, state }));
    expect(reduceCallbackEvidence(data, null)).toEqual(
      reduceCallbackEvidence([...data].reverse(), null),
    );
    expect(reduceCallbackEvidence(data, null)).toMatchObject({
      strongestReported: 'read_reported',
      assessment: 'reported',
      reportedUnknown: true,
    });
  });
  it('accepted then failed is compatible, delivered/read plus failed conflicts', () => {
    const failed = { ...observation, state: 'failed' as const };
    expect(
      reduceCallbackEvidence([{ ...observation, state: 'accepted_by_provider' }, failed], null)
        .conflicts,
    ).toEqual([]);
    for (const state of ['delivered', 'read_reported'] as const)
      expect(reduceCallbackEvidence([{ ...observation, state }, failed], null)).toMatchObject({
        assessment: 'conflicted',
        conflicts: ['terminal_reports'],
      });
  });
  it('preserves conflicting reported IDs and send result mismatch', () => {
    const result = {
      schemaVersion: 1 as const,
      attemptId: observation.attemptId,
      requestDigest: observation.requestDigest,
      status: 'accepted_by_provider' as const,
      providerMessageId: 'other',
    };
    expect(reduceCallbackEvidence([observation], result)).toMatchObject({
      assessment: 'conflicted',
      conflicts: ['provider_identity'],
      sendResult: result,
    });
    expect(
      reduceCallbackEvidence([observation, { ...observation, providerMessageId: 'other' }], null)
        .providerMessageIds,
    ).toEqual(['message-a', 'other']);
  });
  it('positive callbacks contradict definitive nonacceptance but failed/unknown never certify nonacceptance', () => {
    const result = {
      schemaVersion: 1 as const,
      attemptId: observation.attemptId,
      requestDigest: observation.requestDigest,
      status: 'definitive_not_accepted' as const,
    };
    expect(reduceCallbackEvidence([observation], result).conflicts).toEqual(['send_result']);
    for (const state of ['unknown', 'failed'] as const)
      expect(reduceCallbackEvidence([{ ...observation, state }], result).conflicts).toEqual([]);
  });
  it.each([
    { maxGlobal: 0, maxPerAttempt: 1 },
    { maxGlobal: 100001, maxPerAttempt: 1 },
    { maxGlobal: 1, maxPerAttempt: 33 },
    { maxGlobal: true, maxPerAttempt: 1 },
    { maxGlobal: 1, maxPerAttempt: NaN },
  ])('rejects invalid persisted bounds %j', (v) =>
    expect(() => callbackLimits(v)).toThrow(CallbackError),
  );
});
describe('actual work lifetime and truthful observations', () => {
  it('rejects inherited/accessor options before creating storage', () => {
    let touched = 0;
    const options = {
      get timeoutMs(): number {
        touched++;
        throw Error('sentinel');
      },
    };
    expect(
      () =>
        new CallbackInbox(db, createFakeSmsCallbackIntegration(scope, key), accounts(), options),
    ).toThrow(CallbackError);
    expect(
      () =>
        new CallbackInbox(
          db,
          createFakeSmsCallbackIntegration(scope, key),
          accounts(),
          Object.create({ timeoutMs: 20 }),
        ),
    ).toThrow(CallbackError);
    expect(touched).toBe(0);
  });
  it('rejects nonplain/nonenumerable headers and identifiers without laundering their shape', async () => {
    vi.spyOn(CallbackStore.prototype, 'close').mockResolvedValue();
    const accept = vi.spyOn(CallbackStore.prototype, 'accept'),
      inspect = vi.spyOn(CallbackStore.prototype, 'inspectAttempt'),
      c = runtime(),
      s = signed();
    await expect(c.accept(s.raw, Object.create(s.headers))).rejects.toThrow(CallbackError);
    const headers = { ...s.headers };
    Object.defineProperty(headers, 'timestamp', { value: s.headers.timestamp, enumerable: false });
    await expect(c.accept(s.raw, headers)).rejects.toThrow(CallbackError);
    expect(() =>
      c.inspectAttempt(
        'token',
        Object.create({ outboundId: randomUUID(), attemptId: randomUUID() }),
      ),
    ).toThrow(CallbackError);
    expect(accept).not.toHaveBeenCalled();
    expect(inspect).not.toHaveBeenCalled();
    await c.close();
  });
  it('returns historical original receipts on replay and emits fixed fields', async () => {
    const accept = vi
        .spyOn(CallbackStore.prototype, 'accept')
        .mockResolvedValue({ receipt, created: false }),
      events: unknown[] = [];
    vi.spyOn(CallbackStore.prototype, 'close').mockResolvedValue();
    const c = runtime({
        observer: (e) => {
          events.push(e);
        },
      }),
      s = signed();
    expect(await c.accept(s.raw, s.headers)).toEqual(receipt);
    expect(accept).toHaveBeenCalledTimes(1);
    expect(c.metrics()).toMatchObject({ replayed: 1, accepted: 0, active: 0 });
    expect(events).toEqual([{ event: 'replayed', code: 'ok' }]);
    await c.close();
  });
  it('snapshots raw bytes/headers before scheduled work', async () => {
    const observed: unknown[] = [];
    vi.spyOn(CallbackStore.prototype, 'accept').mockImplementation(async (raw, headers) => {
      observed.push(Buffer.from(raw).toString(), headers);
      return { receipt, created: true };
    });
    vi.spyOn(CallbackStore.prototype, 'close').mockResolvedValue();
    const c = runtime(),
      s = signed(),
      raw = Buffer.from(s.raw),
      headers = { ...s.headers },
      operation = c.accept(raw, headers);
    raw.fill(0);
    headers.signature = 'changed';
    await operation;
    expect(observed).toEqual([Buffer.from(s.raw).toString(), s.headers]);
    await c.close();
  });
  it('retains ignored actual I/O slots after all waiter deadlines and incomplete close', async () => {
    const work = deferred<{ receipt: CallbackReceipt; created: boolean }>();
    vi.spyOn(CallbackStore.prototype, 'accept').mockReturnValue(work.promise);
    vi.spyOn(CallbackStore.prototype, 'close').mockResolvedValue();
    const c = runtime({ timeoutMs: 20, cleanupMs: 20 }),
      s = signed();
    const calls = Array.from({ length: 4 }, () => c.accept(s.raw, s.headers));
    const results = await Promise.allSettled(calls);
    expect(
      results.every((x) => x.status === 'rejected' && x.reason.code === 'AcknowledgementUnknown'),
    ).toBe(true);
    expect(c.metrics().active).toBe(4);
    expect(() => c.accept(s.raw, s.headers)).toThrow('Overloaded');
    await expect(c.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
    expect(c.metrics().active).toBe(4);
    work.resolve({ receipt, created: true });
    await new Promise((r) => setImmediate(r));
    expect(c.metrics().active).toBe(0);
    await c.close();
  });
  it('validates AbortSignal before admission without executing fake methods', async () => {
    const invoke = vi.spyOn(CallbackStore.prototype, 'accept');
    vi.spyOn(CallbackStore.prototype, 'close').mockResolvedValue();
    const c = runtime(),
      s = signed();
    expect(() =>
      c.accept(s.raw, s.headers, {
        aborted: false,
        addEventListener() {
          throw Error();
        },
      } as unknown as AbortSignal),
    ).toThrow('InvalidCommand');
    expect(invoke).not.toHaveBeenCalled();
    expect(c.metrics().active).toBe(0);
    await c.close();
  });
  it('contains bounded async telemetry and slow synchronous observer cannot return overdue success', async () => {
    vi.spyOn(CallbackStore.prototype, 'accept').mockResolvedValue({ receipt, created: true });
    vi.spyOn(CallbackStore.prototype, 'close').mockResolvedValue();
    const c = runtime({
        timeoutMs: 20,
        observer: (e) => {
          if (e.event === 'accepted') {
            const end = performance.now() + 25;
            while (performance.now() < end) {
              /*controlled synchronous observer*/
            }
          }
        },
      }),
      s = signed();
    await expect(c.accept(s.raw, s.headers)).rejects.toMatchObject({
      code: 'AcknowledgementUnknown',
    });
    expect(c.metrics().accepted).toBe(1);
    await c.close();
  });
  it('sanitizes arbitrary adapter failure without payload logging', async () => {
    vi.spyOn(CallbackStore.prototype, 'accept').mockRejectedValue(new Error('secret-payload'));
    vi.spyOn(CallbackStore.prototype, 'close').mockResolvedValue();
    const events: unknown[] = [],
      c = runtime({
        observer: (e) => {
          events.push(e);
        },
      }),
      s = signed();
    await expect(c.accept(s.raw, s.headers)).rejects.toMatchObject({
      code: 'Unavailable',
      message: 'Unavailable',
    });
    expect(JSON.stringify(events)).not.toContain('secret');
    await c.close();
  });
});
