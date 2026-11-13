import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import {
  ChannelResultReceiver,
  ChannelResultReader,
  parseResultIntent,
  resultReceipt,
} from '../src/result-receiver.js';
import { registerResultOutbox } from '../src/result-receiver-access.js';
import {
  registerRehydrationInbox,
  type RehydrationInboxAccess,
} from '../src/rehydration-access.js';
import type { ChannelOutbox } from '../src/outbox.js';
import type { OutboxStore } from '../src/outbox-store.js';
import type { ChannelInbox } from '../src/postgres.js';
const fixture = JSON.parse(
  readFileSync(
    new URL('../../../contracts/delegation/result-receiver-v1.json', import.meta.url),
    'utf8',
  ),
) as { intent_canonical: string; receipt: unknown };
const intent = parseResultIntent(fixture.intent_canonical),
  receipt = resultReceipt(fixture.receipt);
const route = {
  scope: { tenantId: intent.scope.tenant_id, accountId: intent.scope.account_id },
  caseId: 'case_fixed',
  conversationId: 'conversation_fixed',
  recipientId: intent.recipient_id,
};
const token = 'p'.repeat(43),
  identity = JSON.stringify(['127.0.0.1', 1, 'livekit_lab', 'unit']);
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function setup(accept = vi.fn(async () => receipt)) {
  const outbox = {} as ChannelOutbox;
  const store = {
    databaseIdentity: identity,
    acceptResult: accept,
    findResult: vi.fn(async () => receipt),
    readNativeResult: vi.fn(async () => null),
  } as unknown as OutboxStore;
  registerResultOutbox(outbox, store);
  const config = {
    receiverId: intent.receiver_id,
    bindings: [{ ...route, publisherToken: token }],
  };
  return {
    outbox,
    store,
    config,
    receiver: new ChannelResultReceiver(outbox, config, { observer: () => {} }),
  };
}
describe('receiver facade actual ownership and bounded safe boundaries', () => {
  it('uses one snapshotted original binding and never closes application-owned outbox', async () => {
    const x = setup();
    expect(await x.receiver.accept(token, intent)).toEqual(receipt);
    expect(await x.receiver.find(token, intent)).toEqual(receipt);
    expect(x.store.acceptResult).toHaveBeenCalledTimes(1);
    expect(x.receiver.receiverId).toBe(intent.receiver_id);
    await x.receiver.close();
    await expect(x.receiver.find(token, intent)).rejects.toMatchObject({ code: 'Closed' });
  });
  it('retains an actual ignored operation through caller timeout and incomplete close, then permits cleanup retry', async () => {
    const hold = deferred<typeof receipt>();
    const x = setup(vi.fn(() => hold.promise));
    const r = new ChannelResultReceiver(x.outbox, x.config, {
      maxActive: 1,
      timeoutMs: 20,
      cleanupMs: 20,
    });
    const result = r.accept(token, intent);
    await expect(result).rejects.toMatchObject({ code: 'AcknowledgementUnknown' });
    expect(r.metrics().active).toBe(1);
    await expect(r.find(token, intent)).rejects.toMatchObject({ code: 'Overloaded' });
    await expect(r.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
    expect(r.metrics().active).toBe(1);
    hold.resolve(receipt);
    await vi.waitFor(() => expect(r.metrics().active).toBe(0));
    await r.close();
    await x.receiver.close();
  });
  it('retains an entered reader operation after explicit caller abort until its actual work settles', async () => {
    const x = setup(),
      inbox = {} as ChannelInbox,
      entered = deferred<void>(),
      held = deferred<null>();
    registerRehydrationInbox(inbox, {
      schema: 'unit',
      databaseIdentity: identity,
      native: {} as RehydrationInboxAccess['native'],
      communication: {} as RehydrationInboxAccess['communication'],
      transaction: async () => {
        throw Error('not called');
      },
    });
    vi.spyOn(x.store, 'readNativeResult').mockImplementation(async () => {
      entered.resolve();
      return held.promise;
    });
    const reader = new ChannelResultReader(
      x.outbox,
      inbox,
      { inspect: vi.fn() },
      { receiverId: intent.receiver_id, bindings: [route] },
      { timeoutMs: 3000, cleanupMs: 20 },
    );
    const caller = new AbortController();
    const result = reader.native('b'.repeat(43), intent.delivery_id, caller.signal);
    try {
      await entered.promise;
      caller.abort();
      await expect(result).rejects.toMatchObject({ code: 'Unavailable' });
      expect(reader.metrics().waiterRejected).toBe(1);
      expect(reader.metrics().active).toBe(1);
      await expect(reader.native('b'.repeat(43), intent.delivery_id)).rejects.toMatchObject({
        code: 'Overloaded',
      });
      await expect(reader.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
      expect(reader.metrics().active).toBe(1);
      held.resolve(null);
      await vi.waitFor(() => expect(reader.metrics().active).toBe(0));
      await reader.close();
    } finally {
      held.resolve(null);
      await reader.close();
      await x.receiver.close();
    }
  });
  it('rejects foreign tokens and malformed inputs before store entry without exception sentinel disclosure', async () => {
    const x = setup();
    expect(() => x.receiver.accept('f'.repeat(43), intent)).toThrowError('AccessDenied');
    expect(() =>
      x.receiver.accept(token, { ...intent, prepared_at_ms: true } as never),
    ).toThrowError('InvalidCommand');
    expect(x.store.acceptResult).not.toHaveBeenCalled();
    await x.receiver.close();
  });
  it('contains observer failure and retains asynchronous observers until actual close', async () => {
    const x = setup(),
      hold = deferred<void>();
    const r = new ChannelResultReceiver(x.outbox, x.config, {
      cleanupMs: 20,
      observer: () => hold.promise,
    });
    expect(await r.accept(token, intent)).toEqual(receipt);
    await expect(r.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
    hold.resolve();
    await vi.waitFor(() => expect(r.metrics().observerPending).toBe(0));
    await r.close();
    const throwing = new ChannelResultReceiver(x.outbox, x.config, {
      observer: () => {
        throw Error('PRIVATE_SENTINEL');
      },
    });
    expect(await throwing.accept(token, intent)).toEqual(receipt);
    expect(throwing.metrics().observerFailures).toBe(1);
    await throwing.close();
    await x.receiver.close();
  });
  it('keeps reader route bindings secret-free and rejects mismatched database identity before any reader', async () => {
    const x = setup(),
      inbox = {} as ChannelInbox;
    registerRehydrationInbox(inbox, {
      schema: 'unit',
      databaseIdentity: identity,
      native: {} as RehydrationInboxAccess['native'],
      communication: {} as RehydrationInboxAccess['communication'],
      transaction: async () => {
        throw Error('not called');
      },
    });
    const cases = { inspect: vi.fn() };
    const reader = new ChannelResultReader(x.outbox, inbox, cases, {
      receiverId: intent.receiver_id,
      bindings: [route],
    });
    expect(await reader.native('b'.repeat(43), intent.delivery_id)).toBeNull();
    expect(x.store.readNativeResult).toHaveBeenCalledTimes(1);
    expect(cases.inspect).not.toHaveBeenCalled();
    expect(
      () =>
        new ChannelResultReader(x.outbox, inbox, cases, {
          receiverId: intent.receiver_id,
          bindings: [{ ...route, publisherToken: token }],
        } as never),
    ).toThrow();
    registerRehydrationInbox(inbox, {
      schema: 'unit',
      databaseIdentity: 'other',
      native: {} as RehydrationInboxAccess['native'],
      communication: {} as RehydrationInboxAccess['communication'],
      transaction: async () => {
        throw Error('not called');
      },
    });
    expect(
      () =>
        new ChannelResultReader(x.outbox, inbox, cases, {
          receiverId: intent.receiver_id,
          bindings: [route],
        }),
    ).toThrow();
    await reader.close();
    await x.receiver.close();
  });
});
