/** Actual gateway/dispatcher reads over a fake PG driver; no SQL qualification. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { produceTextEvent } from '../src/index.js';
import { ChannelGateway } from '../src/gateway.js';
import { NativeGateway, createNativeIntegration } from '../src/native.js';
import { createFakeSmsIntegration } from '../src/security.js';
import type { DispatchPorts } from '../src/dispatch.js';
const driver = vi.hoisted(() => ({ query: vi.fn(), connect: vi.fn(), end: vi.fn() }));
vi.mock('../src/database.js', async () => {
  const original = await vi.importActual<typeof import('../src/database.js')>('../src/database.js');
  return {
    ...original,
    validate: async () => {},
    PgPool: class {
      on() {}
      connect() {
        return driver.connect();
      }
      end() {
        return driver.end();
      }
    },
  };
});
const account = 'a'.repeat(43),
  publisher = 'p'.repeat(43);
const scope = { tenantId: 'tenant', accountId: 'account' };
const route = { ...scope, caseId: 'case', conversationId: 'conversation' };
const id = '11111111-1111-4111-8111-111111111111';
const op = '22222222-2222-4222-8222-222222222222';
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function fixture(native: boolean) {
  const providerScope = {
    tenantId: 'tenant',
    provider: native ? 'livekit' : 'fake_sms',
    providerAccountId: native ? 'rtc' : 'sms',
  };
  const event = produceTextEvent(
    {
      eventId: id,
      messageId: id,
      providerScope,
      accountScope: scope,
      caseId: 'case',
      conversationId: 'conversation',
      channel: native ? 'web_chat' : 'sms',
      senderId: 'sender',
      body: 'Read café 🧭.',
      receivedAt: '2030-01-01T00:00:00.000Z',
    },
    { providerScope, accountScope: scope },
  );
  const row = {
    receipt_id: id,
    event_id: id,
    message_id: id,
    operation_key: op,
    tenant_id: 'tenant',
    provider: providerScope.provider,
    provider_account_id: providerScope.providerAccountId,
    account_id: 'account',
    conversation_id: 'conversation',
    acceptance_sequence: '16',
    accepted_at: new Date('2030-01-01T00:00:00Z'),
    association_epoch: '1',
    wire_json: JSON.stringify(event.event),
    canonical_payload: event.canonical,
    state: 'uncertain',
    claim_epoch: '2',
    attempt_count: 2,
    possible_external: true,
    external_receipt_id: null,
    next_attempt_at: null,
    last_code: 'AcknowledgementUnknown',
  };
  let hold: Promise<void> | undefined,
    missing = false;
  driver.query.mockImplementation(async (sql: string) => {
    if (sql === 'BEGIN' || sql === 'COMMIT' || sql === 'ROLLBACK') return { rows: [], rowCount: 0 };
    if (sql.includes('SELECT version FROM')) return { rows: [{ version: 8 }], rowCount: 1 };
    if (sql.includes('SELECT max_active,max_attempts'))
      return {
        rows: [{ max_active: 4, max_attempts: 3, lease_ms: 5000, retry_delay_ms: 100 }],
        rowCount: 1,
      };
    if (sql.startsWith('SELECT i.*')) {
      if (hold) await hold;
      return { rows: missing ? [] : [row], rowCount: missing ? 0 : 1 };
    }
    if (sql.includes('SELECT epoch::text,started_at')) return { rows: [], rowCount: 0 };
    throw new Error('PRIVATE_UNEXPECTED_SQL');
  });
  const forbidden = vi.fn(async () => {
    throw new Error('PRIVATE_AUTHORITY_CALL');
  });
  const ports = {
    cases: { inspect: forbidden },
    agent: { prepare: forbidden },
    operations: {
      capabilities: 'stable_idempotency_and_lookup',
      lookup: forbidden,
      accept: forbidden,
    },
  } as DispatchPorts;
  const database = {
    host: '127.0.0.1',
    port: 15432,
    database: 'livekit_lab',
    user: 'livekit_lab',
    password: 'synthetic'.repeat(5),
    schema: 'p2_gateway_dispatch_read',
  };
  const accounts = [{ token: account, ...route }];
  const integration = native
    ? createNativeIntegration(providerScope, [
        { token: publisher, scope, caseId: 'case', conversationId: 'conversation' },
      ])
    : createFakeSmsIntegration(providerScope, Buffer.alloc(32, 7));
  const configuration = {
    database,
    accounts,
    ports,
    options: { cleanupMs: 30, observer: () => {} },
  };
  const gateway = native
    ? new NativeGateway({
        ...configuration,
        integration: integration as ReturnType<typeof createNativeIntegration>,
      })
    : new ChannelGateway({ ...configuration, integration });
  return {
    gateway,
    forbidden,
    row,
    hold(value: Promise<void>) {
      hold = value;
    },
    missing() {
      missing = true;
    },
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  driver.connect.mockResolvedValue({ query: driver.query, release: vi.fn() });
  driver.end.mockResolvedValue(undefined);
});
describe('public gateway integration-scoped dispatch read', () => {
  for (const native of [false, true])
    it(`reads ${native ? 'native' : 'SMS'} retained uncertainty without dispatch or writes`, async () => {
      const x = fixture(native);
      try {
        expect(driver.connect).not.toHaveBeenCalled();
        const observed = await x.gateway.inspectDispatch(account, id);
        expect(observed).toMatchObject({
          receiptId: id,
          operationKey: op,
          state: 'uncertain',
          possibleExternal: true,
          externalReceiptId: null,
          epoch: '2',
          attempts: 2,
        });
        const sql = driver.query.mock.calls.map(([q]) => String(q));
        expect(sql.filter((q) => /INSERT|UPDATE|DELETE|CREATE|DROP|FOR UPDATE/.test(q))).toEqual(
          [],
        );
        expect(
          driver.query.mock.calls.find(([q]) => String(q).startsWith('SELECT i.*'))?.[1],
        ).toEqual([
          id,
          'tenant',
          native ? 'livekit' : 'fake_sms',
          native ? 'rtc' : 'sms',
          'account',
          'conversation',
        ]);
        expect(x.forbidden).not.toHaveBeenCalled();
      } finally {
        await x.gateway.close();
      }
    });
  it('preserves authentication, unknown receipt and corrupt stored-state codes', async () => {
    const x = fixture(false);
    try {
      await expect(x.gateway.inspectDispatch('z'.repeat(43), id)).rejects.toMatchObject({
        code: 'AccessDenied',
      });
      expect(driver.connect).not.toHaveBeenCalled();
      x.row.state = 'forged';
      await expect(x.gateway.inspectDispatch(account, id)).rejects.toMatchObject({
        code: 'SchemaMismatch',
      });
      x.missing();
      await expect(x.gateway.inspectDispatch(account, id)).rejects.toMatchObject({
        code: 'NotFound',
      });
      expect(x.forbidden).not.toHaveBeenCalled();
    } finally {
      await x.gateway.close();
    }
  });
  it('retains an actual store read through close and denies new reads until it settles', async () => {
    const x = fixture(false),
      held = deferred();
    x.hold(held.promise);
    const reading = x.gateway.inspectDispatch(account, id);
    let readSettled = false;
    void reading.then(() => {
      readSettled = true;
    });
    await vi.waitFor(() =>
      expect(driver.query.mock.calls.some(([q]) => String(q).startsWith('SELECT i.*'))).toBe(true),
    );
    await expect(x.gateway.close()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    await expect(x.gateway.inspectDispatch(account, id)).rejects.toMatchObject({
      code: 'StorageUnavailable',
    });
    expect(readSettled).toBe(false); // requesting pool.end is separate from actual read/close settlement
    held.resolve();
    await reading;
    await x.gateway.close();
    expect(driver.end).toHaveBeenCalledTimes(2);
    expect(x.forbidden).not.toHaveBeenCalled();
  });
});
