/** Real inbox transaction code over a synthetic driver/catalog; no PG evidence. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChannelInbox, SeededAccounts } from '../src/postgres.js';
import { createFakeSmsIntegration, signFakeSms, WebhookError } from '../src/security.js';
const driver = vi.hoisted(() => ({ query: vi.fn(), release: vi.fn(), connect: vi.fn() }));
vi.mock('../src/database.js', async () => {
  const original = await vi.importActual<typeof import('../src/database.js')>('../src/database.js');
  return {
    ...original,
    validate: async () => ({
      maxInbox: 1000,
      maxChallenges: 512,
      maxAssociations: 256,
      maxSenders: 128,
    }),
    PgPool: class {
      on() {}
      async connect() {
        driver.connect();
        return { query: driver.query, release: driver.release };
      }
      async end() {}
    },
  };
});
const NOW = 1893456000;
const KEY = Buffer.alloc(32, 7);
const SCOPE = { tenantId: 'tenant', provider: 'fake_sms', providerAccountId: 'carrier' };
const ACCOUNT = 'a'.repeat(43);
const MESSAGE = {
  schemaVersion: 1 as const,
  eventId: 'event-demo',
  messageId: 'message-demo',
  senderId: 'sender-demo',
  body: 'Please inspect DEMO',
  occurredAt: '2030-01-01T00:00:00.000Z',
};
const state = { rollbackFails: false, commitFails: false, heads: [] as object[] };
function inbox() {
  return new ChannelInbox(
    {
      host: '127.0.0.1',
      port: 1,
      database: 'livekit_lab',
      user: 'livekit_lab',
      password: 'p'.repeat(43),
      schema: 'p2_admission_unit',
    },
    createFakeSmsIntegration(SCOPE, KEY),
    new SeededAccounts([
      {
        token: ACCOUNT,
        tenantId: 'tenant',
        accountId: 'account',
        conversationId: 'conversation',
        caseId: 'case',
      },
    ]),
    {},
    () => undefined,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(state, { rollbackFails: false, commitFails: false, heads: [] });
  driver.query.mockImplementation(async (text: string) => {
    if (text === 'ROLLBACK' && state.rollbackFails) throw new Error('connection lost');
    if (text === 'COMMIT' && state.commitFails) throw new Error('connection lost');
    if (text.includes('clock_timestamp()'))
      return { rows: [{ now: new Date(NOW * 1000) }], rowCount: 1 };
    if (text.includes('admission') && text.includes('FOR UPDATE'))
      return {
        rows: [{ inbox_count: 0, challenge_count: 0, association_count: 0, sender_count: 0 }],
        rowCount: 1,
      };
    if (text.startsWith('SELECT h.epoch'))
      return { rows: state.heads, rowCount: state.heads.length };
    return { rows: [], rowCount: 0 };
  });
});
describe('webhook authentication before admission', () => {
  it('rejects forged SMS and association bytes before taking a connection', async () => {
    const store = inbox();
    const signed = signFakeSms(MESSAGE, KEY, NOW, SCOPE);
    const forged = Buffer.from(signed.raw);
    forged.writeUInt8(forged.readUInt8(forged.length - 3) ^ 1, forged.length - 3);
    await expect(store.acceptSms(forged, signed.headers)).rejects.toBeInstanceOf(WebhookError);
    await expect(
      store.acceptSms(signed.raw, { ...signed.headers, signature: '0'.repeat(64) }),
    ).rejects.toBeInstanceOf(WebhookError);
    await expect(store.completeAssociation(forged, signed.headers)).rejects.toBeInstanceOf(
      WebhookError,
    );
    expect(driver.connect).not.toHaveBeenCalled();
    expect(store.metrics()).toMatchObject({ rejected: 3, active: 0 });
    await store.close();
  });
  it('still enforces the freshness window with database time inside the transaction', async () => {
    const store = inbox();
    const stale = signFakeSms(MESSAGE, KEY, NOW - 120, SCOPE);
    await expect(store.acceptSms(stale.raw, stale.headers)).rejects.toBeInstanceOf(WebhookError);
    expect(driver.connect).toHaveBeenCalledTimes(1);
    expect(driver.release).toHaveBeenCalledWith(false);
    await store.close();
  });
});
describe('pooled connection reuse', () => {
  it('keeps a connection after a clean rollback and discards it otherwise', async () => {
    const store = inbox();
    const signed = signFakeSms(MESSAGE, KEY, NOW, SCOPE);
    await expect(store.acceptSms(signed.raw, signed.headers)).rejects.toMatchObject({
      code: 'AssociationRequired',
    });
    expect(driver.release).toHaveBeenLastCalledWith(false);
    state.rollbackFails = true;
    await expect(store.acceptSms(signed.raw, signed.headers)).rejects.toMatchObject({
      code: 'AssociationRequired',
    });
    expect(driver.release).toHaveBeenLastCalledWith(true);
    Object.assign(state, {
      rollbackFails: false,
      commitFails: true,
      heads: [
        { epoch: '1', active_epoch: '1', account_id: 'account', conversation_id: 'conversation' },
      ],
    });
    await expect(store.revokeAssociation(ACCOUNT, 'sender-demo')).rejects.toMatchObject({
      code: 'AcknowledgementUnknown',
    });
    expect(driver.release).toHaveBeenLastCalledWith(true);
    await store.close();
  });
});
