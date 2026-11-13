import { afterEach, describe, expect, it, vi } from 'vitest';
import { randomUUID } from 'node:crypto';
import {
  ChannelOutbox,
  OutboxError,
  type CarrierSendPort,
  type SendRequest,
  type CarrierResult,
} from '../src/outbox.js';
import { OutboxStore } from '../src/outbox-store.js';
import {
  draft,
  envelope,
  sendRequest,
  carrierResult,
  sha,
  outboxLimits,
  uuid,
} from '../src/outbox-types.js';
import { SeededAccounts } from '../src/postgres.js';
import { createFakeSmsIntegration } from '../src/security.js';
import { LocalCaseHttpTransport } from '../src/local-case-http.js';
import { PgPool } from '../src/database.js';
const DB = {
  host: '127.0.0.1',
  port: 15432,
  database: 'livekit_lab',
  user: 'livekit_lab',
  password: 'x'.repeat(40),
  schema: 'p2_outbox_fixture',
};
const PROVIDER = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' },
  ACCOUNT = { tenantId: 'tenant-a', accountId: 'account-a' },
  TOKEN = 'account_'.repeat(6),
  PUBLISH = 'publisher_'.repeat(5);
const directory = () =>
  new SeededAccounts([
    { token: TOKEN, ...ACCOUNT, caseId: 'case-a', conversationId: 'conversation-a' },
  ]);
const integration = () => createFakeSmsIntegration(PROVIDER, Buffer.alloc(32, 7));
const publishers = () => [
  { token: PUBLISH, scope: ACCOUNT, caseId: 'case-a', conversationId: 'conversation-a' },
];
const DRAFT = {
  schemaVersion: 1 as const,
  outboundId: randomUUID(),
  responseId: 'response-a',
  body: 'Hello🙂\n',
};
const REQUEST: SendRequest = sendRequest({
  ...DRAFT,
  scope: ACCOUNT,
  caseId: 'case-a',
  conversationId: 'conversation-a',
  attemptId: randomUUID(),
  providerOperationKey: randomUUID(),
  providerScope: PROVIDER,
  senderId: 'sender-a',
  associationVersion: '2',
  routeVersion: '3',
});
const accepted = (r: SendRequest): CarrierResult => ({
  schemaVersion: 1,
  attemptId: r.attemptId,
  requestDigest: sha(JSON.stringify(r)),
  status: 'accepted_by_provider',
  providerMessageId: 'provider-message-a',
});
afterEach(() => vi.restoreAllMocks());
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function runtime(
  port: CarrierSendPort,
  options: ConstructorParameters<typeof ChannelOutbox>[5] = {},
) {
  return new ChannelOutbox(DB, integration(), directory(), publishers(), port, {
    observer: () => {},
    ...options,
  });
}
describe('strict independent outbox contracts', () => {
  it('preserves exact Unicode/control bytes and freezes all trusted recipient fields', () => {
    const e = envelope({
      ...DRAFT,
      scope: ACCOUNT,
      caseId: 'case-a',
      conversationId: 'conversation-a',
    });
    expect(e.body).toBe(DRAFT.body);
    expect(Object.isFrozen(e.scope)).toBe(true);
  });
  it.each([0, true, {}, null, '', 'x'.repeat(4097), '🙂'.repeat(1025), '\ud800'])(
    'rejects invalid text without coercion: %j',
    (body) => {
      expect(() => draft({ ...DRAFT, body })).toThrow(OutboxError);
    },
  );
  it('does not execute getters or toString during validation', () => {
    let touched = 0;
    const x = { ...DRAFT };
    Object.defineProperty(x, 'body', {
      enumerable: true,
      get() {
        touched++;
        return 'bad';
      },
    });
    expect(() => draft(x)).toThrow(OutboxError);
    expect(() =>
      draft({
        ...DRAFT,
        responseId: {
          toString() {
            touched++;
            return 'x';
          },
        },
      }),
    ).toThrow(OutboxError);
    expect(touched).toBe(0);
  });
  it.each(['0', '01', '1\n', '9223372036854775808'])(
    'rejects invalid positive route epoch %s',
    (associationVersion) => {
      expect(() => sendRequest({ ...REQUEST, associationVersion })).toThrow(OutboxError);
    },
  );
  it('retains decimal int64 epochs, distinct stable and attempt identities', () => {
    const r = sendRequest({
      ...REQUEST,
      associationVersion: '9223372036854775807',
      routeVersion: '9223372036854775807',
    });
    expect(r.associationVersion).toBe('9223372036854775807');
    expect(Object.isFrozen(r.scope)).toBe(true);
    expect(Object.isFrozen(r.providerScope)).toBe(true);
    expect(draft(DRAFT).body).toBe(DRAFT.body);
    expect(sha('é')).not.toBe(sha('e\u0301'));
  });
  it.each([true, 0, 6, 1.5, NaN])('rejects invalid persisted attempt cap %s', (maxAttempts) => {
    expect(() => outboxLimits({ maxReplies: 1, maxRoutes: 1, maxAttempts })).toThrow(OutboxError);
  });
  it('rejects trailing newline and changed recipient/digest/provider result', () => {
    expect(() => uuid(DRAFT.outboundId + '\n')).toThrow();
    expect(() =>
      sendRequest({ ...REQUEST, providerScope: { ...PROVIDER, tenantId: 'other' } }),
    ).toThrow();
    for (const changed of [
      { attemptId: randomUUID() },
      { requestDigest: 'f'.repeat(64) },
      { providerMessageId: 'bad\n' },
      { status: 'delivered' },
    ])
      expect(() => carrierResult({ ...accepted(REQUEST), ...changed }, REQUEST)).toThrow();
  });
  it('requires distinct publisher/account capability and no SQL for invalid configuration', () => {
    const connect = vi.spyOn(PgPool.prototype, 'connect');
    expect(
      () =>
        new OutboxStore(DB, integration(), directory(), [{ ...publishers()[0]!, token: TOKEN }]),
    ).toThrow(OutboxError);
    expect(connect).not.toHaveBeenCalled();
  });
  it('rejects malformed signals and publisher/account input before SQL', async () => {
    const connect = vi
      .spyOn(PgPool.prototype, 'connect')
      .mockRejectedValue(new Error('FORBIDDEN_SENTINEL'));
    const store = new OutboxStore(DB, integration(), directory(), publishers());
    try {
      expect(() => store.enqueue(TOKEN, DRAFT, new AbortController().signal)).toThrow(
        'AccessDenied',
      );
      expect(() => store.inspect('bad', DRAFT.outboundId, new AbortController().signal)).toThrow(
        'AccessDenied',
      );
      expect(() => store.enqueue(PUBLISH, DRAFT, {} as AbortSignal)).toThrow('InvalidCommand');
      expect(connect).not.toHaveBeenCalled();
    } finally {
      await store.close();
    }
  });
});
describe('bounded explicit send lifetime', () => {
  function setup() {
    const reserve = vi
        .spyOn(OutboxStore.prototype, 'reserve')
        .mockResolvedValue({ request: REQUEST }),
      record = vi
        .spyOn(OutboxStore.prototype, 'recordResult')
        .mockImplementation(async (_r, v) => v);
    return { reserve, record };
  }
  it('reserves immutable possible send before one carrier call and records known result', async () => {
    const { reserve, record } = setup(),
      send = vi.fn(async (r: SendRequest) => {
        expect(reserve).toHaveBeenCalledTimes(1);
        expect(Object.isFrozen(r)).toBe(true);
        return accepted(r);
      }),
      box = runtime({ capabilities: 'ordinary_fake_sms_v1', send });
    try {
      expect((await box.send(TOKEN, DRAFT.outboundId)).status).toBe('accepted_by_provider');
      expect(record).toHaveBeenCalledWith(REQUEST, accepted(REQUEST));
      expect(box.metrics().accepted).toBe(1);
    } finally {
      await box.close();
    }
  });
  it('known unknown/held/exhausted observations never invoke the carrier', async () => {
    const { reserve } = setup(),
      send = vi.fn(),
      box = runtime({ capabilities: 'ordinary_fake_sms_v1', send });
    try {
      for (const result of [
        { status: 'unknown' as const, outboundId: DRAFT.outboundId, attemptId: REQUEST.attemptId },
        { status: 'held' as const, reason: 'suppressed' as const, outboundId: DRAFT.outboundId },
        {
          status: 'exhausted' as const,
          outboundId: DRAFT.outboundId,
          attemptId: REQUEST.attemptId,
        },
      ]) {
        reserve.mockResolvedValueOnce({ result });
        expect(await box.send(TOKEN, DRAFT.outboundId)).toEqual(result);
      }
      expect(send).not.toHaveBeenCalled();
    } finally {
      await box.close();
    }
  });
  it('malformed and pre-aborted signals do not allocate work', async () => {
    const { reserve } = setup(),
      box = runtime({ capabilities: 'ordinary_fake_sms_v1', send: vi.fn() });
    try {
      expect(() =>
        box.send(TOKEN, DRAFT.outboundId, {
          addEventListener() {
            throw new Error('PRIVATE');
          },
        } as unknown as AbortSignal),
      ).toThrow('InvalidCommand');
      const a = new AbortController();
      a.abort();
      await expect(box.send(TOKEN, DRAFT.outboundId, a.signal)).rejects.toThrow('Unavailable');
      expect(reserve).not.toHaveBeenCalled();
    } finally {
      await box.close();
    }
  });
  it('timeout retains actual ignored calls and late known truth until settlement', async () => {
    const { record } = setup(),
      held = deferred<CarrierResult>(),
      started = deferred<void>(),
      box = runtime(
        {
          capabilities: 'ordinary_fake_sms_v1',
          send: () => {
            started.resolve();
            return held.promise;
          },
        },
        { timeoutMs: 20, maxActive: 1, cleanupMs: 20 },
      );
    const call = box.send(TOKEN, DRAFT.outboundId);
    await started.promise;
    expect((await call).status).toBe('unknown');
    expect(box.metrics().active).toBe(1);
    await expect(box.send(TOKEN, randomUUID())).rejects.toThrow('Overloaded');
    await expect(box.close()).rejects.toThrow('CleanupIncomplete');
    expect(box.metrics().active).toBe(1);
    held.resolve(accepted(REQUEST));
    await new Promise<void>((resolve) => setImmediate(resolve));
    await box.close();
    expect(record).toHaveBeenCalledTimes(1);
    expect(box.metrics().active).toBe(0);
  });
  it('provider error and malformed result are unknown without hidden retry or leak', async () => {
    setup();
    for (const send of [
      vi.fn(async () => {
        throw new Error('PRIVATE_SENTINEL');
      }),
      vi.fn(async () => ({ ...accepted(REQUEST), attemptId: randomUUID() })),
    ]) {
      const box = runtime({ capabilities: 'ordinary_fake_sms_v1', send });
      try {
        expect((await box.send(TOKEN, DRAFT.outboundId)).status).toBe('unknown');
        expect(send).toHaveBeenCalledTimes(1);
        expect(JSON.stringify(box.metrics())).not.toContain('PRIVATE_SENTINEL');
      } finally {
        await box.close();
      }
    }
  });
  it('blocking completion observer cannot produce overdue success or erase known receipt', async () => {
    setup();
    const events: unknown[] = [],
      box = runtime(
        { capabilities: 'ordinary_fake_sms_v1', send: async () => accepted(REQUEST) },
        {
          timeoutMs: 20,
          observer: (e) => {
            events.push(e);
            if (e.event === 'completed') {
              const until = performance.now() + 30;
              while (performance.now() < until) {
                /* controlled trusted observer */
              }
            }
          },
        },
      );
    try {
      expect((await box.send(TOKEN, DRAFT.outboundId)).status).toBe('unknown');
      expect(box.metrics().accepted).toBe(1);
      expect(events).toEqual([{ event: 'completed', code: 'accepted_by_provider' }]);
    } finally {
      await box.close();
    }
  });
  it('telemetry rejection and stuck promises remain finite and cannot alter carrier truth', async () => {
    setup();
    let n = 0;
    const box = runtime(
      { capabilities: 'ordinary_fake_sms_v1', send: async () => accepted(REQUEST) },
      {
        observer: () => {
          n++;
          if (n === 1) throw new Error('PRIVATE');
          return new Promise<void>(() => {});
        },
      },
    );
    try {
      for (let i = 0; i < 12; i++)
        expect((await box.send(TOKEN, DRAFT.outboundId)).status).toBe('accepted_by_provider');
      expect(box.metrics().observerPending).toBe(8);
      expect(box.metrics().observerDropped).toBeGreaterThan(0);
      expect(box.metrics().telemetryFailures).toBe(1);
    } finally {
      await box.close();
    }
  });
});

describe('durable producer observations and trusted snapshots', () => {
  it('counts committed enqueue facts and exact replay independently from send state', async () => {
    const receipt = {
        receiverId: randomUUID(),
        receiptId: randomUUID(),
        outboundId: DRAFT.outboundId,
        intentDigest: 'a'.repeat(64),
        bodyDigest: 'b'.repeat(64),
        acceptedAt: '2030-01-01T00:00:00.000Z',
      },
      enqueue = vi
        .spyOn(OutboxStore.prototype, 'enqueue')
        .mockResolvedValueOnce({ receipt, created: true })
        .mockResolvedValueOnce({ receipt, created: false })
        .mockRejectedValueOnce(new OutboxError('IdentityConflict')),
      events: unknown[] = [],
      box = runtime(
        { capabilities: 'ordinary_fake_sms_v1', send: vi.fn() },
        {
          observer: (e) => {
            events.push(e);
          },
        },
      );
    try {
      expect(await box.enqueue(PUBLISH, DRAFT)).toEqual(receipt);
      expect(await box.enqueue(PUBLISH, DRAFT)).toEqual(receipt);
      await expect(box.enqueue(PUBLISH, DRAFT)).rejects.toThrow('IdentityConflict');
      expect(enqueue).toHaveBeenCalledTimes(3);
      expect(box.metrics()).toMatchObject({ enqueued: 1, enqueueReplayed: 1, enqueueConflicts: 1 });
      expect(events).toEqual([
        { event: 'completed', code: 'queued' },
        { event: 'completed', code: 'replayed' },
        { event: 'rejected', code: 'identity_conflict' },
      ]);
    } finally {
      await box.close();
    }
  });
  it('observes suppression/route facts without implying provider calls', async () => {
    const route = { version: '1', senderId: 'sender-a', associationVersion: '1', suppressed: true };
    vi.spyOn(OutboxStore.prototype, 'selectRoute').mockResolvedValue(route);
    vi.spyOn(OutboxStore.prototype, 'setSuppressed').mockResolvedValue(route);
    const send = vi.fn(),
      events: unknown[] = [],
      box = runtime(
        { capabilities: 'ordinary_fake_sms_v1', send },
        {
          observer: (e) => {
            events.push(e);
          },
        },
      );
    try {
      await box.selectRoute(TOKEN, {
        senderId: 'sender-a',
        associationVersion: '1',
        expectedRouteVersion: '0',
      });
      await box.setSuppressed(TOKEN, { suppressed: true, expectedRouteVersion: '1' });
      expect(events).toEqual([
        { event: 'completed', code: 'route_selected' },
        { event: 'completed', code: 'suppressed' },
      ]);
      expect(send).not.toHaveBeenCalled();
    } finally {
      await box.close();
    }
  });
  it('provider scope is copied before a caller mutates trusted configuration', async () => {
    const provider = { ...PROVIDER },
      integration = { providerScope: provider },
      connect = vi.spyOn(PgPool.prototype, 'connect').mockRejectedValue(new Error('PRIVATE')),
      store = new OutboxStore(DB, integration, directory(), publishers());
    provider.tenantId = 'other';
    try {
      await expect(
        store.inspect(TOKEN, DRAFT.outboundId, new AbortController().signal),
      ).rejects.toThrow('Unavailable');
      expect(connect).toHaveBeenCalledTimes(1);
    } finally {
      await store.close();
    }
  });
  it('freezes the selected carrier method before an awaited reservation', async () => {
    const wait = deferred<{ request: SendRequest }>();
    vi.spyOn(OutboxStore.prototype, 'reserve').mockReturnValue(wait.promise);
    vi.spyOn(OutboxStore.prototype, 'recordResult').mockImplementation(
      async (_r, result) => result,
    );
    const original = vi.fn(async () => accepted(REQUEST)),
      replacement = vi.fn(),
      port = { capabilities: 'ordinary_fake_sms_v1' as const, send: original },
      box = runtime(port);
    try {
      const call = box.send(TOKEN, DRAFT.outboundId);
      port.send = replacement;
      wait.resolve({ request: REQUEST });
      expect((await call).status).toBe('accepted_by_provider');
      expect(original).toHaveBeenCalledTimes(1);
      expect(replacement).not.toHaveBeenCalled();
    } finally {
      await box.close();
    }
  });
  it.each([NaN, Infinity, 0, 32769])(
    'private transport cannot accept an unbounded request cap %s',
    (maximum) => {
      expect(
        () =>
          new LocalCaseHttpTransport(
            { host: '127.0.0.1', port: 1 },
            'Bearer ' + 'a'.repeat(43),
            {},
            maximum as 8192,
          ),
      ).toThrow('InvalidCommand');
    },
  );
});
