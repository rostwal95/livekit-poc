/** Real outbox transaction/error path with a synthetic PG driver; no database qualification. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { randomUUID } from 'node:crypto';
import { ChannelOutbox, type CarrierResult, type CarrierSendPort } from '../src/outbox.js';
import { OutboxStore } from '../src/outbox-store.js';
import { sendRequest, sha } from '../src/outbox-types.js';
import { SendPolicyStore } from '../src/send-policy-store.js';
import {
  lookup,
  operationDigest,
  operationFrom,
  recoveryObservation,
  recoveryReceipt,
} from '../src/send-policy-types.js';
import { ChannelInbox, SeededAccounts, ChannelError } from '../src/postgres.js';
import { createFakeSmsIntegration } from '../src/security.js';
import { ChannelResultReader } from '../src/result-receiver.js';
import {
  registerRehydrationInbox,
  type RehydrationInboxAccess,
} from '../src/rehydration-access.js';
const driver = vi.hoisted(() => ({ query: vi.fn(), release: vi.fn(), end: vi.fn() }));
vi.mock('../src/database.js', async () => {
  const original = await vi.importActual<typeof import('../src/database.js')>('../src/database.js');
  return {
    ...original,
    validate: async () => ({ maxInbox: 8, maxChallenges: 8, maxAssociations: 8, maxSenders: 8 }),
    PgPool: class {
      on() {}
      async connect() {
        return { query: driver.query, release: driver.release };
      }
      async end() {
        driver.end();
      }
    },
  };
});
const receiverId = randomUUID(),
  bindingId = randomUUID(),
  deliveryId = randomUUID();
const DB = {
  host: '127.0.0.1',
  port: 15432,
  database: 'livekit_lab',
  user: 'livekit_lab',
  password: 'synthetic'.repeat(5),
  schema: 'p2_result_transaction_unit',
};
const scope = { tenantId: 'tenant', accountId: 'account' },
  ref = { scope, caseId: 'case', conversationId: 'conversation' };
const route = { ...ref, recipientId: 'recipient' },
  bearer = 'b'.repeat(43),
  account = 'a'.repeat(43),
  publisher = 'p'.repeat(43);
const grant = {
  ...ref,
  bindingId,
  roomId: 'room',
  participantId: 'participant',
  admittedAt: '2030-01-01T00:00:00.000Z',
};
const observedCase = {
  schemaVersion: 1,
  source: 'p1_public_v4',
  ...ref,
  revision: '2',
  request: {
    schemaVersion: 1,
    kind: 'booking_investigation',
    bookingReference: 'DEMO-BK-001',
    newCheckIn: '2030-12-12',
    investigationConsent: true,
  },
  workflow: { taskId: randomUUID(), state: 'ready', version: '0' },
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
};
beforeEach(() => {
  vi.clearAllMocks();
  driver.query.mockImplementation(async (text: string) => {
    if (text.includes('SELECT version FROM')) return { rows: [{ version: 8 }], rowCount: 1 };
    if (text.includes('SELECT * FROM') && text.includes('outbox_settings'))
      return {
        rows: [{ receiver_id: receiverId, max_replies: 8, max_routes: 8, max_attempts: 3 }],
        rowCount: 1,
      };
    if (text.includes('SELECT singleton FROM') && text.includes('admission'))
      return { rows: [{ singleton: true }], rowCount: 1 };
    if (text.includes('clock_timestamp()'))
      return { rows: [{ now: new Date('2030-01-01T00:00:00.000Z') }], rowCount: 1 };
    return { rows: [], rowCount: 0 };
  });
});
function configured(final: boolean, error: unknown) {
  const box = new ChannelOutbox(
    DB,
    createFakeSmsIntegration(
      { tenantId: scope.tenantId, provider: 'fake_sms', providerAccountId: 'sms' },
      Buffer.alloc(32, 7),
    ),
    new SeededAccounts([
      { token: account, ...scope, caseId: ref.caseId, conversationId: ref.conversationId },
    ]),
    [{ token: publisher, ...ref }],
    {
      capabilities: 'ordinary_fake_sms_v1',
      send: vi.fn(async () => {
        throw Error('must_not_send');
      }),
    },
    { observer: () => {} },
  );
  const inbox = {} as ChannelInbox,
    currentBearer = vi.fn(async (_client: unknown, _bearer: string, lock: boolean) => {
      if (lock === final) throw error;
      return grant;
    });
  registerRehydrationInbox(inbox, {
    schema: DB.schema,
    databaseIdentity: JSON.stringify([DB.host, DB.port, DB.database, DB.schema]),
    native: { currentBearer } as unknown as RehydrationInboxAccess['native'],
    communication: {} as RehydrationInboxAccess['communication'],
    transaction: async () => {
      throw Error('must_use_existing_outbox_pool');
    },
  });
  const cases = { inspect: vi.fn(async () => observedCase) };
  const reader = new ChannelResultReader(
    box,
    inbox,
    cases as unknown as ConstructorParameters<typeof ChannelResultReader>[2],
    { receiverId, bindings: [route] },
    { observer: () => {} },
  );
  return { box, reader, currentBearer, cases };
}
describe('native denial semantics before the existing outbox safe boundary', () => {
  it.each([false, true])(
    'preserves genuine ChannelError AccessDenied at protected=%s through actual rollback',
    async (final) => {
      const x = configured(final, new ChannelError('AccessDenied'));
      try {
        await expect(x.reader.native(bearer, deliveryId)).rejects.toMatchObject({
          code: 'AccessDenied',
          message: 'AccessDenied',
        });
        expect(x.currentBearer).toHaveBeenCalledTimes(final ? 2 : 1);
        expect(x.currentBearer.mock.calls.at(-1)?.[2]).toBe(final);
        expect(x.cases.inspect).toHaveBeenCalledTimes(final ? 1 : 0);
        expect(driver.query.mock.calls.filter(([text]) => text === 'ROLLBACK')).toHaveLength(1);
        expect(driver.query.mock.calls.filter(([text]) => text === 'COMMIT')).toHaveLength(
          final ? 1 : 0,
        );
        expect(
          driver.query.mock.calls.some(([text]) => /^INSERT|^UPDATE/.test(text as string)),
        ).toBe(false);
      } finally {
        await x.reader.close();
        await x.box.close();
      }
    },
  );
  it.each([false, true])(
    'keeps genuine storage failures and spoofed codes unavailable at protected=%s without sentinel text',
    async (final) => {
      const storage = new ChannelError('StorageUnavailable');
      storage.message = 'PRIVATE_STORAGE_SENTINEL';
      for (const error of [
        storage,
        { code: 'AccessDenied', message: 'PRIVATE_SPOOF_SENTINEL' },
        Error('PRIVATE_NATIVE_SENTINEL'),
      ]) {
        const x = configured(final, error);
        try {
          await expect(x.reader.native(bearer, deliveryId)).rejects.toMatchObject({
            code: 'Unavailable',
            message: 'Unavailable',
          });
        } finally {
          await x.reader.close();
          await x.box.close();
        }
      }
    },
  );
  it('allows a later useful read after a first genuine permission denial without leaking earlier state', async () => {
    const x = configured(false, new ChannelError('AccessDenied'));
    try {
      await expect(x.reader.native(bearer, deliveryId)).rejects.toMatchObject({
        code: 'AccessDenied',
      });
      x.currentBearer.mockImplementation(async () => grant);
      await expect(x.reader.native(bearer, deliveryId)).resolves.toBeNull();
      expect(x.cases.inspect).toHaveBeenCalledTimes(1);
      expect(x.reader.metrics().active).toBe(0);
      expect(x.box.metrics().storageActive).toBe(0);
    } finally {
      await x.reader.close();
      await x.box.close();
    }
  });
});
describe('known carrier results while ordinary calls hold every store slot', () => {
  const controller = 'c'.repeat(43),
    providerScope = { tenantId: scope.tenantId, provider: 'fake_sms', providerAccountId: 'sms' },
    request = sendRequest({
      schemaVersion: 1,
      outboundId: randomUUID(),
      responseId: 'response',
      body: 'Notice',
      ...ref,
      attemptId: randomUUID(),
      providerOperationKey: randomUUID(),
      providerScope,
      senderId: 'sender',
      associationVersion: '1',
      routeVersion: '1',
    }),
    op = operationFrom(request, 'idempotent_fake_sms_v1');
  afterEach(() => vi.restoreAllMocks());
  function loaded(carrier: CarrierSendPort) {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const original = driver.query.getMockImplementation()!;
    driver.query.mockImplementation(async (text: string, values?: unknown[]) => {
      if (text.startsWith('SELECT i.outbound_id')) await held;
      if (text.startsWith('SELECT canonical_request FROM'))
        return { rows: [{ canonical_request: JSON.stringify(request) }], rowCount: 1 };
      return original(text, values);
    });
    const box = new ChannelOutbox(
      DB,
      createFakeSmsIntegration(providerScope, Buffer.alloc(32, 7)),
      new SeededAccounts([
        { token: account, ...scope, caseId: ref.caseId, conversationId: ref.conversationId },
      ]),
      [{ token: publisher, ...ref }],
      carrier,
      { observer: () => {}, recoveryControllers: [{ token: controller, ...ref }] },
    );
    const reads = Array.from({ length: 4 }, () => box.pending(account));
    return { box, reads, release };
  }
  it.each(['accepted_by_provider', 'definitive_not_accepted'] as const)(
    'records a %s send result instead of reporting unknown',
    async (status) => {
      const digest = sha(JSON.stringify(request)),
        result: CarrierResult =
          status === 'accepted_by_provider'
            ? {
                schemaVersion: 1,
                attemptId: request.attemptId,
                requestDigest: digest,
                status,
                providerMessageId: 'provider-message',
              }
            : { schemaVersion: 1, attemptId: request.attemptId, requestDigest: digest, status };
      vi.spyOn(OutboxStore.prototype, 'reserve').mockResolvedValue({ request });
      const x = loaded({ capabilities: 'ordinary_fake_sms_v1', send: async () => result });
      try {
        expect(x.box.metrics().storageActive).toBe(4);
        await expect(x.box.pending(account)).rejects.toMatchObject({ code: 'Overloaded' });
        expect(await x.box.send(account, request.outboundId)).toEqual({
          status,
          outboundId: request.outboundId,
          attemptId: request.attemptId,
        });
        expect(
          driver.query.mock.calls
            .filter(([text]) => /^INSERT INTO \S+send_results"/.test(text as string))
            .map(([, values]) => values),
        ).toEqual([[request.attemptId, JSON.stringify(result)]]);
        expect(x.box.metrics()).toMatchObject({ unknown: 0, storageActive: 4 });
      } finally {
        x.release();
        await Promise.all(x.reads);
        await x.box.close();
      }
    },
  );
  it('records a known recovery lookup instead of rejecting it as overloaded', async () => {
    const receipt = recoveryReceipt({
        schemaVersion: 1,
        receiptId: randomUUID(),
        commandId: randomUUID(),
        kind: 'reconcile',
        outboundId: request.outboundId,
        sourceAttemptId: request.attemptId,
        providerOperationKey: op.providerOperationKey,
        operationDigest: operationDigest(op),
        decision: 'lookup_authorized',
        code: 'lookup',
        newAttemptId: null,
        acceptedAt: '2030-01-01T00:00:00.000Z',
      }),
      found = lookup(
        {
          schemaVersion: 1,
          providerScope,
          providerOperationKey: op.providerOperationKey,
          operationDigest: operationDigest(op),
          state: 'accepted_by_provider',
          providerMessageId: 'provider-message',
        },
        op,
      ),
      observation = recoveryObservation(
        {
          schemaVersion: 1,
          commandId: receipt.commandId,
          providerOperationKey: op.providerOperationKey,
          operationDigest: operationDigest(op),
          source: 'lookup',
          state: 'accepted_by_provider',
          assessment: 'reported',
          providerMessageId: 'provider-message',
          observedAt: '2030-01-01T00:00:00.000Z',
        },
        receipt,
      );
    vi.spyOn(OutboxStore.prototype, 'reserveRecovery').mockResolvedValue({
      view: { receipt, observation: null },
      created: true,
      action: 'lookup',
      operation: op,
      request: null,
    });
    vi.spyOn(SendPolicyStore.prototype, 'command').mockResolvedValue({
      receipt,
      observation: null,
    });
    const observe = vi
      .spyOn(SendPolicyStore.prototype, 'observe')
      .mockImplementation(async (_client, saved) => ({ receipt: saved, observation }));
    const x = loaded({
      capabilities: 'idempotent_fake_sms_v1',
      async send() {
        throw Error('unused');
      },
      lookup: async () => found,
    });
    try {
      await expect(x.box.pending(account)).rejects.toMatchObject({ code: 'Overloaded' });
      expect(
        await x.box.reconcile(controller, {
          commandId: receipt.commandId,
          outboundId: request.outboundId,
          attemptId: request.attemptId,
        }),
      ).toEqual({ receipt, observation });
      expect(observe).toHaveBeenCalledTimes(1);
      expect(observe.mock.calls[0]![3]).toEqual(found);
      expect(x.box.metrics()).toMatchObject({ recoveryKnown: 1, recoveryCapacityRejected: 0 });
    } finally {
      x.release();
      await Promise.all(x.reads);
      await x.box.close();
    }
  });
});
