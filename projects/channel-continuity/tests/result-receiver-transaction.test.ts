/** Real outbox transaction/error path with a synthetic PG driver; no database qualification. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { randomUUID } from 'node:crypto';
import { ChannelOutbox } from '../src/outbox.js';
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
