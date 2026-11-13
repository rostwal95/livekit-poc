/** Offline adapter/lifetime tests. Persistence and process recovery live in the explicit PG lane. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { produceTextEvent } from '../src/index.js';
import { ChannelError, SeededAccounts, type StoredMessage } from '../src/postgres.js';
import { createFakeSmsIntegration } from '../src/security.js';
import { ChannelDispatcher, type DispatchPorts } from '../src/dispatch.js';
import {
  operationLookup,
  parsePreparedDispatch,
  prepareDispatch,
  preparedSubmission,
  type PreparedDispatch,
} from '../src/dispatch-types.js';
const calls = vi.hoisted(() => ({
  claim: vi.fn(),
  prepare: vi.fn(),
  reserve: vi.fn(),
  finish: vi.fn(),
  fail: vi.fn(),
  inspect: vi.fn(),
  close: vi.fn(),
}));
vi.mock('../src/dispatch-store.js', () => ({
  DispatchStore: class {
    claim = calls.claim;
    prepare = calls.prepare;
    reserve = calls.reserve;
    finish = calls.finish;
    fail = calls.fail;
    inspect = calls.inspect;
    close = calls.close;
  },
}));
const PROVIDER = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' };
const SCOPE = { tenantId: 'tenant-a', accountId: 'account-a' };
const RECEIPT = '12345678-1234-4234-8234-123456789abc',
  KEY = '22345678-1234-4234-8234-123456789abc',
  EXTERNAL = '32345678-1234-4234-8234-123456789abc';
const MESSAGE: StoredMessage = {
  receipt: {
    receiptId: RECEIPT,
    eventId: 'event-a',
    messageId: 'message-a',
    acceptanceSequence: '1',
    acceptedAt: '2030-01-01T00:00:00.000Z',
  },
  event: produceTextEvent(
    {
      eventId: 'event-a',
      providerScope: PROVIDER,
      accountScope: SCOPE,
      conversationId: 'conversation-a',
      caseId: 'case-a',
      receivedAt: '2030-01-01T00:00:00.000Z',
      channel: 'sms',
      messageId: 'message-a',
      senderId: 'sender-a',
      body: 'Read only investigation',
    },
    { providerScope: PROVIDER, accountScope: SCOPE },
  ).event,
  operationKey: KEY,
  processingState: 'pending',
  associationVersion: '1',
};
const CURRENT = {
  scope: SCOPE,
  caseId: 'case-a',
  revision: '1',
  source: 'synthetic_read_only' as const,
};
const PLAN = prepareDispatch(MESSAGE, CURRENT, {
  kind: 'investigation',
  source: 'scripted',
  caseRevision: '1',
});
const CLAIM = {
  receiptId: RECEIPT,
  operationKey: KEY,
  ownerId: EXTERNAL,
  epoch: '1',
  kind: 'dispatch',
  message: MESSAGE,
  prepared: null,
  possibleExternal: false,
};
function fixture(overrides: Partial<DispatchPorts> = {}) {
  const order: string[] = [];
  const ports: DispatchPorts = {
    cases: {
      async inspect() {
        order.push('case');
        return CURRENT;
      },
    },
    agent: {
      async prepare() {
        order.push('agent');
        return { kind: 'investigation', source: 'scripted', caseRevision: '1' };
      },
    },
    operations: {
      capabilities: 'stable_idempotency_and_lookup',
      async lookup() {
        order.push('lookup');
        return { status: 'absent' };
      },
      async accept(p) {
        order.push('accept');
        return { ...operationLookup(p), receiptId: EXTERNAL };
      },
    },
    ...overrides,
  };
  return { ports, order };
}
function make(ports: DispatchPorts, options = {}) {
  return new ChannelDispatcher(
    {
      host: '127.0.0.1',
      port: 5432,
      database: 'livekit_lab',
      user: 'livekit_lab',
      password: 'synthetic',
      schema: 'p2_inbox_' + 'a'.repeat(32),
    },
    createFakeSmsIntegration(PROVIDER, Buffer.alloc(32, 1)),
    new SeededAccounts([
      {
        token: 'synthetic-' + 'a'.repeat(40),
        tenantId: 'tenant-a',
        accountId: 'account-a',
        conversationId: 'conversation-a',
        caseId: 'case-a',
      },
    ]),
    ports,
    options,
  );
}
function deferred<T>() {
  let resolve!: (v: T) => void;
  return {
    promise: new Promise<T>((done) => {
      resolve = done;
    }),
    resolve: (v: T) => resolve(v),
  };
}
const tick = () => new Promise<void>((resolve) => setImmediate(resolve));
async function rejects(work: Promise<unknown>, code: string) {
  await expect(work).rejects.toMatchObject({ name: 'ChannelError', code, message: code });
}
beforeEach(() => {
  for (const call of Object.values(calls)) call.mockReset();
  calls.claim.mockResolvedValue({ claim: CLAIM });
  calls.prepare.mockImplementation(async (_t, _c, p: PreparedDispatch) => p);
  calls.reserve.mockResolvedValue(true);
  calls.finish.mockResolvedValue(undefined);
  calls.fail.mockResolvedValue(undefined);
  calls.close.mockResolvedValue(undefined);
});
describe('bounded persisted dispatch adapter orchestration', () => {
  it('requires declared cooperating ports before claiming any work', async () => {
    const f = fixture();
    for (const key of ['cases', 'agent', 'operations'])
      expect(() => make({ ...f.ports, [key]: undefined } as unknown as DispatchPorts)).toThrowError(
        'InvalidConfiguration',
      );
    expect(() => make(f.ports, { timeoutMs: Infinity })).toThrowError('InvalidConfiguration');
    expect(calls.claim).not.toHaveBeenCalled();
    const d = make(f.ports);
    expect(await d.step('token', RECEIPT)).toEqual({
      status: 'dispatched',
      receiptId: RECEIPT,
      operationKey: KEY,
      externalReceiptId: EXTERNAL,
      reconciled: false,
    });
    expect(f.order).toEqual(['case', 'agent', 'lookup', 'accept']);
    expect(calls.reserve.mock.invocationCallOrder[0]).toBeLessThan(
      calls.finish.mock.invocationCallOrder[0]!,
    );
    await d.close();
  });
  it('freezes a prepared plan and skips changed case/agent computation on retry', async () => {
    calls.claim.mockResolvedValue({ claim: { ...CLAIM, prepared: PLAN, possibleExternal: true } });
    const f = fixture(),
      d = make(f.ports);
    await d.step('token', RECEIPT);
    expect(f.order).toEqual(['lookup', 'accept']);
    expect(calls.prepare).not.toHaveBeenCalled();
    await d.close();
  });
  it('lookup-only reconciliation never calls case agent reservation or acceptance', async () => {
    calls.claim.mockResolvedValue({
      claim: { ...CLAIM, kind: 'reconcile', prepared: PLAN, possibleExternal: true },
    });
    const f = fixture(),
      d = make(f.ports);
    expect(await d.reconcile('token', RECEIPT)).toEqual({
      status: 'uncertain',
      receiptId: RECEIPT,
      operationKey: KEY,
    });
    expect(f.order).toEqual(['lookup']);
    expect(calls.reserve).not.toHaveBeenCalled();
    expect(calls.fail).toHaveBeenCalledWith('token', expect.anything(), 'lookup_absent');
    await d.close();
  });
  it('reconciles a correct durable receipt without resending and rejects forged scope or digest', async () => {
    let valid = false;
    const f = fixture({
        operations: {
          capabilities: 'stable_idempotency_and_lookup',
          async lookup() {
            return {
              status: 'accepted',
              receipt: {
                ...operationLookup(PLAN),
                scope: valid ? SCOPE : { ...SCOPE, accountId: 'other' },
                receiptId: EXTERNAL,
              },
            };
          },
          async accept() {
            throw new Error('PRIVATE_UNEXPECTED_ACCEPT');
          },
        },
      }),
      d = make(f.ports);
    await rejects(d.step('token', RECEIPT), 'OperationConflict');
    expect(calls.finish).not.toHaveBeenCalled();
    valid = true;
    expect((await d.step('token', RECEIPT)).status).toBe('dispatched');
    expect(calls.reserve).not.toHaveBeenCalled();
    await d.close();
  });
  it('persists a possible call before unlocked acceptance and preserves unknown acknowledgement', async () => {
    const f = fixture({
        operations: {
          capabilities: 'stable_idempotency_and_lookup',
          async lookup() {
            return { status: 'absent' };
          },
          async accept() {
            expect(calls.reserve).toHaveBeenCalledTimes(1);
            throw new Error('PRIVATE_PROVIDER_DIAGNOSTIC');
          },
        },
      }),
      d = make(f.ports);
    await rejects(d.step('token', RECEIPT), 'DispatchUnavailable');
    expect(calls.fail).toHaveBeenCalledWith('token', expect.anything(), 'adapter_unavailable');
    expect(calls.finish).not.toHaveBeenCalled();
    expect(JSON.stringify(d.counters())).not.toContain('PRIVATE');
    await d.close();
  });
  it('blocks external calls if the original current association disappeared', async () => {
    calls.reserve.mockResolvedValue(false);
    const f = fixture(),
      d = make(f.ports);
    expect((await d.step('token', RECEIPT)).status).toBe('blocked');
    expect(f.order).toEqual(['case', 'agent', 'lookup']);
    await d.close();
  });
  it('does not turn a delayed timer into successful work or execute a later stage', async () => {
    const f = fixture({
        cases: {
          async inspect() {
            const end = performance.now() + 35;
            while (performance.now() < end) {}
            return CURRENT;
          },
        },
      }),
      d = make(f.ports, { timeoutMs: 20 });
    await rejects(d.step('token', RECEIPT), 'DispatchUnavailable');
    expect(f.order).toEqual([]);
    expect(calls.prepare).not.toHaveBeenCalled();
    expect(calls.fail).toHaveBeenCalledWith('token', expect.anything(), 'timeout');
    await d.close();
  });
  it('retains timed-out adapter ownership until actual settlement and makes progress after release', async () => {
    const held = deferred<typeof CURRENT>();
    const f = fixture({ cases: { inspect: () => held.promise } }),
      d = make(f.ports, { timeoutMs: 20 });
    const a = d.step('token', RECEIPT),
      b = d.step('token', RECEIPT);
    await Promise.all([rejects(a, 'DispatchUnavailable'), rejects(b, 'DispatchUnavailable')]);
    await rejects(d.step('token', RECEIPT), 'Overloaded');
    held.resolve(CURRENT);
    await tick();
    expect(calls.fail).toHaveBeenCalledTimes(2);
    const fresh = make(fixture().ports);
    expect((await fresh.step('token', RECEIPT)).status).toBe('dispatched');
    await Promise.all([d.close(), fresh.close()]);
  });
  it('records a late known durable receipt while returning an expired caller deadline', async () => {
    const f = fixture({
        operations: {
          capabilities: 'stable_idempotency_and_lookup',
          async lookup() {
            return { status: 'absent' };
          },
          async accept(p) {
            const end = performance.now() + 35;
            while (performance.now() < end) {}
            return { ...operationLookup(p), receiptId: EXTERNAL };
          },
        },
      }),
      d = make(f.ports, { timeoutMs: 20 });
    await rejects(d.step('token', RECEIPT), 'DispatchUnavailable');
    expect(calls.finish).toHaveBeenCalledTimes(1);
    expect(calls.fail).not.toHaveBeenCalled();
    await d.close();
  });
  it('rejects stale claimant publication without overwriting a new owner', async () => {
    calls.finish.mockRejectedValue(new ChannelError('DispatchClaimLost'));
    calls.fail.mockRejectedValue(new ChannelError('DispatchClaimLost'));
    const d = make(fixture().ports);
    await rejects(d.step('token', RECEIPT), 'DispatchClaimLost');
    await d.close();
  });
  it('bounds cleanup, reports ignored work, eventually closes its store and does not accept new work', async () => {
    const held = deferred<typeof CURRENT>(),
      d = make(fixture({ cases: { inspect: () => held.promise } }).ports, {
        timeoutMs: 20,
        cleanupTimeoutMs: 20,
      });
    const work = d.step('token', RECEIPT);
    await tick();
    const close = d.close();
    expect(d.close()).toBe(close);
    await Promise.all([rejects(work, 'DispatchUnavailable'), rejects(close, 'CleanupIncomplete')]);
    await rejects(d.step('token', RECEIPT), 'StorageUnavailable');
    expect(calls.close).not.toHaveBeenCalled();
    held.resolve(CURRENT);
    await tick();
    await tick();
    expect(calls.close).toHaveBeenCalledTimes(1);
  });
  it('includes synchronous abort listeners in the total cleanup deadline', async () => {
    const held = deferred<typeof CURRENT>();
    let seen: AbortSignal | undefined;
    const d = make(
      fixture({
        cases: {
          inspect(_r, signal) {
            seen = signal;
            return held.promise;
          },
        },
      }).ports,
      { timeoutMs: 200, cleanupTimeoutMs: 20 },
    );
    const work = d.step('token', RECEIPT);
    await tick();
    seen!.addEventListener('abort', () => {
      const end = performance.now() + 35;
      while (performance.now() < end) {}
      held.resolve(CURRENT);
    });
    const closing = d.close();
    await rejects(closing, 'CleanupIncomplete');
    await rejects(work, 'DispatchUnavailable');
    await tick();
    expect(calls.close).toHaveBeenCalledTimes(1);
  });
  it('rejects delayed synchronous observers at the final deadline while preserving durable truth', async () => {
    const d = make(fixture().ports, {
      timeoutMs: 20,
      observer() {
        const end = performance.now() + 35;
        while (performance.now() < end) {}
      },
    });
    await rejects(d.step('token', RECEIPT), 'DispatchUnavailable');
    expect(calls.finish).toHaveBeenCalledTimes(1);
    expect(calls.fail).not.toHaveBeenCalled();
    await d.close();
  });
  it('sanitizes a forged ChannelError code before counters or observers and permits later work', async () => {
    let valid = false;
    const events: unknown[] = [];
    const d = make(
      fixture({
        cases: {
          async inspect() {
            if (!valid) throw new ChannelError('PRIVATE_PAYLOAD' as ChannelError['code']);
            return CURRENT;
          },
        },
      }).ports,
      {
        observer(event: Readonly<{ event: string; code: string }>) {
          events.push(event);
        },
      },
    );
    await rejects(d.step('token', RECEIPT), 'DispatchUnavailable');
    expect(JSON.stringify(events)).not.toContain('PRIVATE');
    expect(JSON.stringify(d.counters())).not.toContain('PRIVATE');
    valid = true;
    expect((await d.step('token', RECEIPT)).status).toBe('dispatched');
    await d.close();
  });
  it('consumes rejected async telemetry and bounds pending notifications', async () => {
    const d = make(fixture().ports, {
      observer: async () => {
        throw new Error('PRIVATE_OBSERVER');
      },
    });
    await d.step('token', RECEIPT);
    await tick();
    expect(Object.keys(d.counters())).toEqual(['dispatch:dispatched']);
    await d.close();
  });
});
describe('immutable investigation payload', () => {
  it('has deterministic digest and roundtrip for Unicode and maximum escaped text', () => {
    for (const body of ['हैलो 🎧', '\u0000'.repeat(4096)]) {
      const p = preparedSubmission({
        ...PLAN.submission,
        message: { ...PLAN.submission.message, body },
      });
      expect(Buffer.byteLength(p.canonicalPayload)).toBeLessThanOrEqual(32768);
      expect(parsePreparedDispatch(p.canonicalPayload, p.payloadDigest)).toEqual(p);
      expect(Object.isFrozen(p.submission.message)).toBe(true);
    }
  });
  it('rejects wrong revision, prototype hooks, unknown fields and noncanonical storage without invoking hooks', () => {
    const hook = vi.fn();
    expect(() =>
      preparedSubmission({
        ...PLAN.submission,
        message: { ...PLAN.submission.message, body: 'x'.repeat(4097) },
      }),
    ).toThrowError('OperationConflict');
    expect(() =>
      preparedSubmission({
        ...PLAN.submission,
        message: { ...PLAN.submission.message, body: '\ud800' },
      }),
    ).toThrowError('OperationConflict');
    expect(() =>
      preparedSubmission({
        ...PLAN.submission,
        message: { ...PLAN.submission.message, toJSON: hook },
      }),
    ).toThrowError('OperationConflict');
    expect(() =>
      prepareDispatch(MESSAGE, CURRENT, {
        kind: 'investigation',
        source: 'scripted',
        caseRevision: '2',
      }),
    ).toThrowError('OperationConflict');
    expect(() =>
      parsePreparedDispatch(' ' + PLAN.canonicalPayload, PLAN.payloadDigest),
    ).toThrowError('SchemaMismatch');
    expect(hook).not.toHaveBeenCalled();
  });
});
