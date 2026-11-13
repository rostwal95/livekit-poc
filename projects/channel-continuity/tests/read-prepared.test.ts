/** Actual prepared-read transaction/owner paths over a synthetic PG driver; no SQL qualification. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash } from 'node:crypto';
import { produceTextEvent } from '../src/index.js';
import { SeededAccounts } from '../src/postgres.js';
import { createFakeSmsIntegration } from '../src/security.js';
import { createNativeIntegration } from '../src/native-types.js';
import { ChannelDispatcher, type DispatchPorts } from '../src/dispatch.js';
import { ChannelGateway } from '../src/gateway.js';
import { DispatchStore } from '../src/dispatch-store.js';
import { preparedSubmission } from '../src/dispatch-types.js';
const driver = vi.hoisted(() => ({
  query: vi.fn(),
  release: vi.fn(),
  connect: vi.fn(),
  end: vi.fn(),
  validate: vi.fn(),
}));
vi.mock('../src/database.js', async () => {
  const original = await vi.importActual<typeof import('../src/database.js')>('../src/database.js');
  return {
    ...original,
    validate: (...args: unknown[]) => driver.validate(...args),
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
const DB = {
  host: '127.0.0.1',
  port: 15432,
  database: 'livekit_lab',
  user: 'livekit_lab',
  password: 'synthetic'.repeat(5),
  schema: 'p2_read_prepared_unit',
};
const SCOPE = { tenantId: 'tenant', accountId: 'account' },
  REF = { ...SCOPE, caseId: 'case', conversationId: 'conversation' },
  ACCOUNT = 'a'.repeat(43),
  PUBLISHER = 'p'.repeat(43),
  RECEIPT = '11111111-1111-4111-8111-111111111111',
  OPERATION = '22222222-2222-4222-8222-222222222222',
  SENDER = '33333333-3333-4333-8333-333333333333';
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
const tick = () => new Promise<void>((done) => setImmediate(done));
function data(native = false) {
  const provider = {
      tenantId: SCOPE.tenantId,
      provider: native ? 'livekit' : 'fake_sms',
      providerAccountId: native ? 'rtc' : 'sms',
    },
    eventId = native ? RECEIPT : 'source_event',
    messageId = native ? RECEIPT : 'source_message',
    event = produceTextEvent(
      {
        eventId,
        messageId,
        providerScope: provider,
        accountScope: SCOPE,
        conversationId: REF.conversationId,
        caseId: REF.caseId,
        channel: native ? 'web_chat' : 'sms',
        senderId: SENDER,
        body: 'Review "policy" \\ safely — café 🧭',
        receivedAt: '2030-01-01T00:00:00.000Z',
      },
      { providerScope: provider, accountScope: SCOPE },
    ),
    prepared = preparedSubmission({
      schemaVersion: 1,
      kind: 'investigation',
      operationKey: OPERATION,
      scope: SCOPE,
      caseId: REF.caseId,
      caseRevision: '9223372036854775807',
      conversationId: REF.conversationId,
      message: {
        receiptId: RECEIPT,
        eventId,
        messageId,
        senderId: SENDER,
        body: event.event.type === 'text.received' ? event.event.body : '',
      },
    }),
    row = {
      receipt_id: RECEIPT,
      operation_key: OPERATION,
      tenant_id: SCOPE.tenantId,
      provider: provider.provider,
      provider_account_id: provider.providerAccountId,
      account_id: SCOPE.accountId,
      conversation_id: REF.conversationId,
      event_id: eventId,
      message_id: messageId,
      acceptance_sequence: '16',
      accepted_at: new Date('2030-01-01T00:00:00.000Z'),
      association_epoch: '1',
      wire_json: JSON.stringify(event.event),
      canonical_payload: event.canonical,
      state: 'dispatched',
      possible_external: true,
      attempt_count: 3,
      claim_epoch: '3',
    },
    state = {
      row,
      plan: { payload_json: prepared.canonicalPayload, payload_digest: prepared.payloadDigest },
      planCount: 1,
      version: 8,
      sourceRevoked: true,
      capacity: 16,
    };
  let hold: Promise<void> | undefined;
  driver.query.mockImplementation(async (text: string, parameters: unknown[] = []) => {
    if (text === 'BEGIN' || text === 'COMMIT' || text === 'ROLLBACK')
      return { rows: [], rowCount: 0 };
    if (text.includes('SELECT version FROM'))
      return { rows: [{ version: state.version }], rowCount: 1 };
    if (text.includes('SELECT max_active,max_attempts,lease_ms,retry_delay_ms'))
      return {
        rows: [{ max_active: 2, max_attempts: 3, lease_ms: 500, retry_delay_ms: 20 }],
        rowCount: 1,
      };
    if (text.includes('SELECT i.*,p.operation_key')) {
      if (hold) await hold;
      const expected = [
        state.row.receipt_id,
        state.row.tenant_id,
        state.row.provider,
        state.row.provider_account_id,
        state.row.account_id,
        state.row.conversation_id,
      ];
      return parameters.every((value, n) => value === expected[n])
        ? { rows: [state.row], rowCount: 1 }
        : { rows: [], rowCount: 0 };
    }
    if (text.includes('SELECT payload_json,payload_digest'))
      return {
        rows:
          state.planCount === 0 ? [] : Array.from({ length: state.planCount }, () => state.plan),
        rowCount: state.planCount,
      };
    throw Error('PRIVATE_UNEXPECTED_QUERY');
  });
  const seeds = [{ token: ACCOUNT, ...REF }],
    integration = native
      ? createNativeIntegration(provider, [
          {
            token: PUBLISHER,
            scope: SCOPE,
            caseId: REF.caseId,
            conversationId: REF.conversationId,
          },
        ])
      : createFakeSmsIntegration(provider, Buffer.alloc(32, 7)),
    accounts = new SeededAccounts(seeds),
    forbidden = vi.fn(async () => {
      throw Error('PRIVATE_AUTHORITY_CALL');
    }),
    ports = {
      cases: { inspect: forbidden },
      agent: { prepare: forbidden },
      operations: {
        capabilities: 'stable_idempotency_and_lookup',
        lookup: forbidden,
        accept: forbidden,
      },
    } as DispatchPorts;
  return {
    state,
    prepared,
    integration,
    accounts,
    seeds,
    ports,
    forbidden,
    hold(value: Promise<void>) {
      hold = value;
    },
  };
}
function sqls(): string[] {
  return driver.query.mock.calls.map(([text]) => text as string);
}
function assertReadOnly() {
  expect(sqls().every((sql) => /^(SELECT |BEGIN$|COMMIT$|ROLLBACK$)/.test(sql))).toBe(true);
  expect(
    sqls().some((sql) =>
      /FOR UPDATE|native_bindings|sender_heads|dispatch_attempts|admission/.test(sql),
    ),
  ).toBe(false);
}
beforeEach(() => {
  vi.clearAllMocks();
  driver.connect.mockImplementation(async () => ({ query: driver.query, release: driver.release }));
  driver.end.mockResolvedValue(undefined);
  driver.validate.mockResolvedValue({
    maxInbox: 16,
    maxChallenges: 16,
    maxAssociations: 16,
    maxSenders: 16,
  });
});
describe('read-only retained prepared dispatch', () => {
  it.each([false, true])(
    'returns exact immutable original plan at capacity after source revocation: native=%s',
    async (native) => {
      const f = data(native),
        d = new ChannelDispatcher(DB, f.integration, f.accounts, f.ports),
        before = JSON.stringify(f.state);
      try {
        const known = await d.readPrepared(ACCOUNT, RECEIPT);
        expect(known).toEqual(f.prepared);
        expect(known?.canonicalPayload).toBe(f.state.plan.payload_json);
        expect(known?.payloadDigest).toBe(
          createHash('sha256').update(known!.canonicalPayload).digest('hex'),
        );
        expect(Object.isFrozen(known)).toBe(true);
        expect(Object.isFrozen(known?.submission.message)).toBe(true);
        expect(known?.submission.caseRevision).toBe('9223372036854775807');
        expect(f.state.sourceRevoked).toBe(true);
        expect(f.state.capacity).toBe(16);
        expect(JSON.stringify(f.state)).toBe(before);
        expect(f.forbidden).not.toHaveBeenCalled();
        expect(await d.readPrepared(ACCOUNT, RECEIPT)).toEqual(known);
        expect(
          driver.query.mock.calls.find(([sql]) =>
            (sql as string).includes('SELECT i.*,p.operation_key'),
          )?.[1],
        ).toEqual([
          RECEIPT,
          SCOPE.tenantId,
          native ? 'livekit' : 'fake_sms',
          native ? 'rtc' : 'sms',
          SCOPE.accountId,
          REF.conversationId,
        ]);
        assertReadOnly();
      } finally {
        await d.close();
      }
    },
  );
  it('returns null only for a scoped known input with no original plan, without planning it', async () => {
    const f = data(),
      store = new DispatchStore(DB, f.integration, f.accounts);
    f.state.planCount = 0;
    f.state.row.state = 'pending';
    f.state.row.possible_external = false;
    const before = JSON.stringify(f.state);
    try {
      expect(await store.readPrepared(ACCOUNT, RECEIPT)).toBeNull();
      expect(JSON.stringify(f.state)).toBe(before);
      assertReadOnly();
    } finally {
      await store.close();
    }
  });
  it.each(['bad-token', 'bad-uuid'])('rejects %s before opening PG', async (kind) => {
    const f = data(),
      store = new DispatchStore(DB, f.integration, f.accounts);
    try {
      await expect(
        store.readPrepared(
          kind === 'bad-token' ? 'z'.repeat(43) : ACCOUNT,
          kind === 'bad-uuid' ? 'bad' : RECEIPT,
        ),
      ).rejects.toMatchObject({
        code: kind === 'bad-token' ? 'AccessDenied' : 'OperationConflict',
      });
      expect(driver.connect).not.toHaveBeenCalled();
    } finally {
      await store.close();
    }
  });
  it.each(['receipt', 'account', 'conversation', 'provider'])(
    'does not disclose a foreign %s input as null',
    async (kind) => {
      const f = data(),
        store = new DispatchStore(DB, f.integration, f.accounts);
      if (kind === 'account') f.state.row.account_id = 'other_account';
      if (kind === 'conversation') f.state.row.conversation_id = 'other_conversation';
      if (kind === 'provider') f.state.row.provider_account_id = 'other_provider';
      try {
        await expect(
          store.readPrepared(ACCOUNT, kind === 'receipt' ? SENDER : RECEIPT),
        ).rejects.toMatchObject({ code: 'NotFound' });
        expect(sqls().some((sql) => sql.includes('dispatch_plans'))).toBe(false);
        expect(sqls()).toContain('ROLLBACK');
      } finally {
        await store.close();
      }
    },
  );
  it.each(['digest', 'malformed', 'noncanonical', 'duplicate-plan', 'corrupt-input'])(
    'rejects stored %s corruption and rolls back without writes',
    async (kind) => {
      const f = data(),
        store = new DispatchStore(DB, f.integration, f.accounts);
      if (kind === 'digest') f.state.plan.payload_digest = '0'.repeat(64);
      if (kind === 'malformed') f.state.plan.payload_json = '{';
      if (kind === 'noncanonical') f.state.plan.payload_json += ' ';
      if (kind === 'duplicate-plan') f.state.planCount = 2;
      if (kind === 'corrupt-input') f.state.row.canonical_payload += ' ';
      try {
        await expect(store.readPrepared(ACCOUNT, RECEIPT)).rejects.toMatchObject({
          code: 'SchemaMismatch',
        });
        expect(sqls()).toContain('ROLLBACK');
        expect(sqls()).not.toContain('COMMIT');
        assertReadOnly();
      } finally {
        await store.close();
      }
    },
  );
  it('rejects a valid canonical plan for changed source bytes instead of returning it', async () => {
    const f = data(),
      store = new DispatchStore(DB, f.integration, f.accounts),
      changed = preparedSubmission({
        ...f.prepared.submission,
        message: { ...f.prepared.submission.message, body: 'changed' },
      });
    f.state.plan = {
      payload_json: changed.canonicalPayload,
      payload_digest: changed.payloadDigest,
    };
    try {
      await expect(store.readPrepared(ACCOUNT, RECEIPT)).rejects.toMatchObject({
        code: 'OperationConflict',
      });
      assertReadOnly();
    } finally {
      await store.close();
    }
  });
  it('preserves explicit schema upgrade rejection before loading source/plan', async () => {
    const f = data(),
      store = new DispatchStore(DB, f.integration, f.accounts);
    f.state.version = 1;
    try {
      await expect(store.readPrepared(ACCOUNT, RECEIPT)).rejects.toMatchObject({
        code: 'UpgradeRequired',
      });
      expect(sqls().some((sql) => sql.includes('SELECT i.*'))).toBe(false);
    } finally {
      await store.close();
    }
  });
  it.each(['read', 'commit'])(
    'normalizes private %s failures as StorageUnavailable and releases the connection',
    async (stage) => {
      const f = data(),
        store = new DispatchStore(DB, f.integration, f.accounts),
        original = driver.query.getMockImplementation()!;
      driver.query.mockImplementation((sql: string, parameters?: unknown[]) => {
        if (stage === 'read' ? sql.includes('SELECT payload_json') : sql === 'COMMIT')
          throw Error('PRIVATE_SENTINEL');
        return original(sql, parameters);
      });
      try {
        await expect(store.readPrepared(ACCOUNT, RECEIPT)).rejects.toMatchObject({
          code: 'StorageUnavailable',
          message: 'StorageUnavailable',
        });
        expect(driver.release).toHaveBeenCalledWith(true);
        expect(sqls()).toContain('ROLLBACK');
      } finally {
        await store.close();
      }
    },
  );
  it('retains the four existing actual SQL slots and makes useful progress after overload', async () => {
    const f = data(),
      store = new DispatchStore(DB, f.integration, f.accounts),
      held = deferred();
    f.hold(held.promise);
    const reads = Array.from({ length: 4 }, () => store.readPrepared(ACCOUNT, RECEIPT));
    const observed = Promise.all(reads);
    try {
      await tick();
      expect(driver.connect).toHaveBeenCalledTimes(4);
      expect(driver.release).not.toHaveBeenCalled();
      await expect(store.readPrepared(ACCOUNT, RECEIPT)).rejects.toMatchObject({
        code: 'Overloaded',
      });
      held.resolve();
      expect(await observed).toEqual(Array.from({ length: 4 }, () => f.prepared));
      expect(await store.readPrepared(ACCOUNT, RECEIPT)).toEqual(f.prepared);
    } finally {
      held.resolve();
      await observed;
      await store.close();
    }
  });
  it('store close cannot complete or admit a new read while original SQL remains held', async () => {
    const f = data(),
      store = new DispatchStore(DB, f.integration, f.accounts),
      held = deferred();
    f.hold(held.promise);
    const read = store.readPrepared(ACCOUNT, RECEIPT);
    await tick();
    let closed = false;
    const closing = store.close().then(() => {
      closed = true;
    });
    try {
      await tick();
      expect(closed).toBe(false);
      expect(driver.release).not.toHaveBeenCalled();
      await expect(store.readPrepared(ACCOUNT, RECEIPT)).rejects.toMatchObject({
        code: 'StorageUnavailable',
      });
      held.resolve();
      expect(await read).toEqual(f.prepared);
      await closing;
      expect(closed).toBe(true);
      expect(driver.release).toHaveBeenCalledTimes(1);
    } finally {
      held.resolve();
      await read;
      await closing;
    }
  });
  it.each([false, true])(
    'gateway delegates to its owned dispatcher without listening or creating authority: native=%s',
    async (native) => {
      const f = data(native),
        delegate = vi.spyOn(ChannelDispatcher.prototype, 'readPrepared'),
        gateway = new ChannelGateway({
          database: DB,
          integration: f.integration,
          accounts: f.seeds,
          ports: f.ports,
          ...(native ? { inputMode: 'native_livekit' as const } : {}),
          options: { observer: () => {} },
        });
      try {
        expect(await gateway.readPrepared(ACCOUNT, RECEIPT)).toEqual(f.prepared);
        expect(delegate).toHaveBeenCalledExactlyOnceWith(ACCOUNT, RECEIPT);
        expect(f.forbidden).not.toHaveBeenCalled();
        expect(gateway.metrics()).toMatchObject({ driver: 0, active: 0, handlers: 0, sockets: 0 });
        assertReadOnly();
      } finally {
        delegate.mockRestore();
        await gateway.close();
      }
    },
  );
  it('gateway close waits for its delegated actual prepared read and denies later admission', async () => {
    const f = data(),
      gateway = new ChannelGateway({
        database: DB,
        integration: f.integration,
        accounts: f.seeds,
        ports: f.ports,
        options: { observer: () => {} },
      }),
      held = deferred();
    f.hold(held.promise);
    const read = gateway.readPrepared(ACCOUNT, RECEIPT);
    await tick();
    let closed = false;
    const closing = gateway.close().then(() => {
      closed = true;
    });
    try {
      await tick();
      expect(closed).toBe(false);
      await expect(gateway.readPrepared(ACCOUNT, RECEIPT)).rejects.toMatchObject({
        code: 'StorageUnavailable',
      });
      expect(driver.release).not.toHaveBeenCalled();
      held.resolve();
      expect(await read).toEqual(f.prepared);
      await closing;
      expect(closed).toBe(true);
      expect(f.forbidden).not.toHaveBeenCalled();
    } finally {
      held.resolve();
      await read;
      await closing;
    }
  });
});
