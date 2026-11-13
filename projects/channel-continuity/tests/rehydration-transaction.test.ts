/** Actual shared inbox transaction/rollback/observer path. Metadata+driver are synthetic; no PG claim. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { randomUUID } from 'node:crypto';
import { produceTextEvent } from '../src/index.js';
import { ChannelInbox, SeededAccounts, type InboxEvent } from '../src/postgres.js';
import { createNativeIntegration } from '../src/native.js';
import { createFakeSmsIntegration, signFakeSms } from '../src/security.js';
import { ChannelRehydrator, DEFAULT_REHYDRATION_QUERY } from '../src/rehydration.js';
const driver = vi.hoisted(() => ({ query: vi.fn(), release: vi.fn(), end: vi.fn() }));
vi.mock('../src/database.js', async () => {
  const original = await vi.importActual<typeof import('../src/database.js')>('../src/database.js');
  return {
    ...original,
    validate: async () => ({
      maxInbox: 32,
      maxChallenges: 32,
      maxAssociations: 32,
      maxSenders: 32,
    }),
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
const scope = { tenantId: 'tenant', accountId: 'account' },
  provider = { tenantId: 'tenant', provider: 'fake_sms', providerAccountId: 'sms' },
  nativeProvider = { tenantId: 'tenant', provider: 'livekit', providerAccountId: 'rtc' };
const account = 'a'.repeat(43),
  publisher = 'b'.repeat(43),
  key = Buffer.alloc(32, 7);
let row: Record<string, unknown> | undefined,
  sqlFailure = false,
  rollback: Promise<void> = Promise.resolve();
const now = new Date();
function configured() {
  const events: InboxEvent[] = [];
  const i = new ChannelInbox(
    {
      host: '127.0.0.1',
      port: 1,
      database: 'livekit_lab',
      user: 'livekit_lab',
      password: 'p'.repeat(43),
      schema: 'p2_rehydration_unit',
    },
    createNativeIntegration(nativeProvider, [
      { token: publisher, scope, caseId: 'case', conversationId: 'conversation' },
    ]),
    new SeededAccounts([
      { token: account, ...scope, caseId: 'case', conversationId: 'conversation' },
    ]),
    {},
    (event) => {
      events.push(event);
    },
  );
  const cases = { inspect: vi.fn() };
  const r = new ChannelRehydrator(i, cases, createFakeSmsIntegration(provider, key), {
    observer: () => {},
    maxActive: 1,
    timeoutMs: 50,
  });
  const message = {
    schemaVersion: 1 as const,
    eventId: randomUUID(),
    messageId: randomUUID(),
    senderId: 'sender',
    body: 'Accepted earlier',
    occurredAt: '2030-01-01T00:00:00.000Z',
  };
  const signed = signFakeSms(message, key, Math.floor(Date.now() / 1000), provider);
  return { i, r, cases, message, signed, events };
}
beforeEach(() => {
  vi.clearAllMocks();
  row = undefined;
  sqlFailure = false;
  rollback = Promise.resolve();
  driver.query.mockImplementation(async (sql: string) => {
    if (sql === 'ROLLBACK') {
      await rollback;
      return { rows: [], rowCount: 0 };
    }
    if (sql.includes('clock_timestamp()') && sql.includes('AS now'))
      return { rows: [{ now: new Date() }], rowCount: 1 };
    if (sql.includes('SELECT i.*,p.operation_key')) {
      if (sqlFailure) throw Error('SENTINEL_PRIVATE_SQL_BODY');
      return { rows: row ? [row] : [], rowCount: row ? 1 : 0 };
    }
    return { rows: [], rowCount: 0 };
  });
});
describe('rehydration semantics through actual legacy normalization', () => {
  it('preserves known no-disclosure denial after actual rollback and reports AccessDenied, not a dependency outage', async () => {
    const x = configured();
    try {
      await expect(x.r.sms(x.signed.raw, x.signed.headers)).rejects.toMatchObject({
        code: 'access_denied',
      });
      expect(x.cases.inspect).not.toHaveBeenCalled();
      expect(driver.query.mock.calls.some(([sql]) => sql === 'ROLLBACK')).toBe(true);
      expect(driver.release).toHaveBeenCalledWith(true);
      expect(x.events.at(-1)).toEqual({
        event: 'rejected',
        operation: 'rehydration',
        code: 'AccessDenied',
      });
      expect(x.i.metrics().dependencyErrors).toBe(0);
      expect(x.r.metrics().active).toBe(0);
    } finally {
      await x.r.close();
      await x.i.close();
    }
  });
  it('preserves scope-cursor rejection without misreporting an SQL dependency failure', async () => {
    const x = configured();
    const normalized = produceTextEvent(
      {
        eventId: x.message.eventId,
        messageId: x.message.messageId,
        senderId: x.message.senderId,
        body: x.message.body,
        occurredAt: x.message.occurredAt,
        providerScope: provider,
        accountScope: scope,
        caseId: 'case',
        conversationId: 'conversation',
        receivedAt: now.toISOString(),
        channel: 'sms',
      },
      { providerScope: provider, accountScope: scope },
    );
    row = {
      receipt_id: randomUUID(),
      event_id: x.message.eventId,
      message_id: x.message.messageId,
      tenant_id: 'tenant',
      provider: 'fake_sms',
      provider_account_id: 'sms',
      account_id: 'account',
      conversation_id: 'conversation',
      canonical_payload: normalized.canonical,
      wire_json: normalized.wireJson,
      acceptance_sequence: '1',
      accepted_at: now,
      association_epoch: '1',
      operation_key: randomUUID(),
      state: 'pending',
      current_epoch: '1',
      current_account_id: 'account',
      current_conversation_id: 'conversation',
      current_case_id: 'case',
    };
    try {
      await expect(
        x.r.sms(x.signed.raw, x.signed.headers, {
          ...DEFAULT_REHYDRATION_QUERY,
          historyCursor: { kind: 'history', scopeDigest: 'f'.repeat(64), beforeSequence: '2' },
        }),
      ).rejects.toMatchObject({ code: 'invalid_query' });
      expect(x.cases.inspect).not.toHaveBeenCalled();
      expect(x.events.at(-1)?.code).toBe('InvalidConfiguration');
      expect(x.i.metrics().dependencyErrors).toBe(0);
    } finally {
      await x.r.close();
      await x.i.close();
    }
  });
  it('keeps unexpected SQL errors unavailable and never reflects their raw body', async () => {
    const x = configured();
    sqlFailure = true;
    try {
      await expect(x.r.sms(x.signed.raw, x.signed.headers)).rejects.toMatchObject({
        code: 'context_unavailable',
        message: 'context_unavailable',
      });
      expect(x.events.at(-1)?.code).toBe('StorageUnavailable');
      expect(x.i.metrics().dependencyErrors).toBe(1);
      expect(x.cases.inspect).not.toHaveBeenCalled();
    } finally {
      await x.r.close();
      await x.i.close();
    }
  });
  it('retains both actual transaction and facade slots until a held rollback really settles', async () => {
    let release!: () => void;
    rollback = new Promise<void>((resolve) => {
      release = resolve;
    });
    const x = configured();
    try {
      const waiting = x.r.sms(x.signed.raw, x.signed.headers);
      await expect(waiting).rejects.toMatchObject({ code: 'context_unavailable' });
      expect(x.r.metrics().active).toBe(1);
      expect(x.i.metrics().active).toBe(1);
      await expect(x.r.sms(x.signed.raw, x.signed.headers)).rejects.toMatchObject({
        code: 'overloaded',
      });
      release();
      await x.r.close();
      expect(x.r.metrics().active).toBe(0);
      expect(x.i.metrics().active).toBe(0);
      expect(driver.release).toHaveBeenCalledWith(true);
    } finally {
      release();
      await x.r.close();
      await x.i.close();
    }
  });
});
