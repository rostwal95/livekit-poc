/** Real public Dispatcher/DispatchStore/validate path over a closed synthetic pg boundary.
 * No pg socket or real schema qualification; catalog rows are explicit unit fixtures.
 */
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { beforeEach, test, vi } from 'vitest';
import { produceTextEvent } from '../src/index.js';
import { SeededAccounts } from '../src/postgres.js';
import { ChannelDispatcher, type DispatchPorts } from '../src/dispatch.js';
import { createFakeSmsIntegration } from '../src/security.js';
import { createNativeIntegration } from '../src/native.js';
import { createCommunicationIntegration } from '../src/communication.js';
import { DEFINITION_DIGEST } from '../src/database.js';
import { CHANNEL_SCHEMA_MARKER, CHANNEL_SCHEMA_VERSION } from '../src/channel-schema.js';

const pgBoundary = vi.hoisted(() => ({
  query: vi.fn(),
  release: vi.fn(),
  end: vi.fn(),
  connect: vi.fn(),
}));
// Only the driver is mocked. database.validate, NativeStore, DispatchStore and
// ChannelDispatcher all execute their actual implementations.
vi.mock('pg', () => ({
  default: {
    Pool: class {
      on() {}
      async connect() {
        pgBoundary.connect();
        return { query: pgBoundary.query, release: pgBoundary.release };
      }
      end = pgBoundary.end;
    },
    Client: class {},
  },
}));
const scope = { tenantId: 'native-tenant', accountId: 'native-account' };
const token = 'a'.repeat(43);
const now = new Date('2030-01-01T00:00:00.000Z');
const sha = (value: string) => createHash('sha256').update(value).digest('hex');
function fixture(mode: 'sms' | 'native' | 'communication' = 'native') {
  const native = mode !== 'sms';
  const provider = {
    tenantId: scope.tenantId,
    provider: native ? 'livekit' : 'fake_sms',
    providerAccountId: 'local-account',
  };
  const receiptId = randomUUID(),
    operationKey = randomUUID(),
    bindingId = randomUUID();
  const produced = produceTextEvent(
    {
      eventId: randomUUID(),
      messageId: randomUUID(),
      providerScope: provider,
      accountScope: scope,
      caseId: 'case',
      conversationId: 'conversation',
      channel: native ? 'web_chat' : 'sms',
      senderId: native ? bindingId : 'sender',
      body: 'investigate',
      receivedAt: now.toISOString(),
    },
    { providerScope: provider, accountScope: scope },
  );
  assert.equal(produced.event.type, 'text.received');
  const state = {
    version: CHANNEL_SCHEMA_VERSION as unknown,
    marker: CHANNEL_SCHEMA_MARKER,
    definition: DEFINITION_DIGEST,
    unsafeAcl: false,
    maxInbox: 16,
    metadataRows: 1,
    catalog: { unit_catalog_identity: 'fixed-synthetic-catalog' },
    savedCatalog: { unit_catalog_identity: 'fixed-synthetic-catalog' },
  };
  const row: Record<string, unknown> = {
    receipt_id: receiptId,
    operation_key: operationKey,
    tenant_id: scope.tenantId,
    provider: provider.provider,
    provider_account_id: provider.providerAccountId,
    account_id: scope.accountId,
    conversation_id: 'conversation',
    event_id: produced.event.eventId,
    message_id: produced.event.messageId,
    canonical_payload: produced.canonical,
    wire_json: produced.wireJson,
    acceptance_sequence: '1',
    accepted_at: now,
    association_epoch: '1',
    state: 'pending',
    claim_epoch: '0',
    claim_owner: null,
    claim_until: null,
    claim_kind: null,
    attempt_count: 0,
    next_attempt_at: null,
    possible_external: false,
    external_receipt_id: null,
    last_code: 'none',
  };
  const binding: Record<string, unknown> = {
    binding_id: bindingId,
    tenant_id: scope.tenantId,
    provider: 'livekit',
    provider_account_id: provider.providerAccountId,
    account_id: scope.accountId,
    case_id: 'case',
    conversation_id: 'conversation',
    room_id: 'room',
    participant_id: 'browser',
    bearer_digest: sha('b'.repeat(43)),
    published_at: now,
    expires_at: new Date(now.getTime() + 60000),
    revoked_at: null,
    canonical_binding: '',
    binding_digest: '',
  };
  function canonicalBinding() {
    binding.canonical_binding = JSON.stringify({
      schemaVersion: 1,
      bindingId,
      providerScope: provider,
      scope,
      caseId: 'case',
      conversationId: 'conversation',
      roomId: 'room',
      participantId: 'browser',
      expiresAt: (binding.expires_at as Date).toISOString(),
    });
    binding.binding_digest = sha(binding.canonical_binding as string);
  }
  canonicalBinding();
  let plan: { payload_json: string; payload_digest: string } | null = null;
  const calls: string[] = [];
  const result = (rows: Record<string, unknown>[] = []) => ({ rows, rowCount: rows.length });
  pgBoundary.query.mockImplementation(async (sql: string, values: unknown[] = []) => {
    calls.push(sql);
    if (['BEGIN', 'COMMIT', 'ROLLBACK'].includes(sql)) return result();
    if (sql.includes('SELECT current_user AS name'))
      return result([
        {
          name: 'livekit_lab',
          rolsuper: false,
          rolcreatedb: false,
          rolcreaterole: false,
          rolreplication: false,
          rolbypassrls: false,
          member: false,
          can_create: false,
          can_temp: false,
          schema_admin: false,
          object_owner: false,
        },
      ]);
    if (sql.includes("c.relname='schema_metadata'"))
      return result([
        {
          relkind: 'r',
          owner: 'continuity_migrator',
          schema_owner: 'continuity_migrator',
          relrowsecurity: false,
          relforcerowsecurity: false,
          user_triggers: false,
          rules: false,
          unsafe_acl: state.unsafeAcl,
          unsafe_index: false,
          unsafe_constraint: false,
          columns: [
            ['singleton', 'boolean'],
            ['version', 'smallint'],
            ['runtime_role', 'text'],
            ['definition_digest', 'text'],
            ['catalog_snapshot', 'jsonb'],
            ['max_inbox', 'integer'],
            ['max_challenges', 'integer'],
            ['max_associations', 'integer'],
            ['max_senders', 'integer'],
          ].map(([n, t]) => [n, t, true, '', '', null, null]),
        },
      ]);
    if (sql.includes('SELECT jsonb_build_object(')) return result([{ snapshot: state.catalog }]);
    if (sql.includes('SELECT m.singleton,m.version'))
      return result(
        Array.from({ length: state.metadataRows }, () => ({
          singleton: true,
          version: state.version,
          runtime_role: 'livekit_lab',
          definition_digest: state.definition,
          catalog_snapshot: state.savedCatalog,
          max_inbox: state.maxInbox,
          max_challenges: 16,
          max_associations: 16,
          max_senders: 16,
          marker: state.marker,
        })),
      );
    if (sql.includes('SELECT singleton FROM')) return result([{ singleton: true }]);
    if (sql.includes('SELECT max_active,max_attempts'))
      return result([{ max_active: 2, max_attempts: 3, lease_ms: 5000, retry_delay_ms: 20 }]);
    if (sql.includes('clock_timestamp() AS now')) return result([{ now }]);
    if (sql.includes('SELECT i.receipt_id::text')) return result([{ receipt_id: receiptId }]);
    if (sql.includes('SELECT i.*,p.operation_key')) return result([{ ...row }]);
    if (sql.includes('SELECT * FROM') && sql.includes('native_bindings'))
      return result([{ ...binding }]);
    if (sql.includes('native_settings'))
      return result([{ singleton: true, max_bindings: 3, binding_count: 1, actual: 1 }]);
    if (sql.includes('SELECT epoch,active_epoch'))
      return result([{ epoch: '1', active_epoch: '1' }]);
    if (sql.includes('SELECT epoch::text,account_id'))
      return result([
        {
          epoch: '1',
          account_id: scope.accountId,
          conversation_id: 'conversation',
          case_id: 'case',
        },
      ]);
    if (sql.includes('SELECT count(*)::integer AS active')) return result([{ active: 0 }]);
    if (sql.includes('SELECT payload_json,payload_digest')) return result(plan ? [plan] : []);
    if (sql.includes('SET state=$2,claim_epoch=$3')) {
      Object.assign(row, {
        state: values[1],
        claim_epoch: values[2],
        claim_owner: values[3],
        claim_until: values[4],
        claim_kind: values[5],
        attempt_count: Number(row.attempt_count) + Number(values[6]),
      });
      return result();
    }
    if (sql.includes('INSERT INTO') && sql.includes('dispatch_plans')) {
      plan = { payload_json: values[2] as string, payload_digest: values[3] as string };
      return result();
    }
    if (sql.includes("SET possible_external=true,state='uncertain'")) {
      Object.assign(row, { possible_external: true, state: 'uncertain' });
      return result();
    }
    if (sql.includes("SET state='dispatched',possible_external=true")) {
      Object.assign(row, {
        state: 'dispatched',
        possible_external: true,
        external_receipt_id: values[1],
        claim_owner: null,
        claim_until: null,
        claim_kind: null,
        next_attempt_at: null,
      });
      return result();
    }
    if (sql.includes("SET state=$2,last_code='association_required'")) {
      Object.assign(row, { state: values[1], last_code: 'association_required' });
      return result();
    }
    if (sql.includes('dispatch_attempts') && (sql.startsWith('INSERT') || sql.startsWith('UPDATE')))
      return result();
    throw new Error('Unexpected synthetic driver query');
  });
  const observed = { agent: 0, accept: 0, lookup: 0 };
  const externalId = randomUUID();
  const adapters: DispatchPorts = {
    cases: {
      async inspect(reference) {
        return { ...reference, revision: '1', source: 'synthetic_read_only' };
      },
    },
    agent: {
      async prepare(input) {
        observed.agent++;
        return {
          kind: 'investigation',
          source: 'scripted',
          caseRevision: input.currentCase.revision,
        };
      },
    },
    operations: {
      capabilities: 'stable_idempotency_and_lookup',
      async lookup() {
        observed.lookup++;
        return { status: 'absent' };
      },
      async accept(prepared) {
        observed.accept++;
        assert.equal(prepared.submission.operationKey, operationKey);
        assert.deepEqual(prepared.submission.scope, scope);
        return {
          operationKey,
          scope,
          payloadDigest: prepared.payloadDigest,
          receiptId: externalId,
        };
      },
    },
  };
  const integration = native
    ? createNativeIntegration(provider, [
        { token: 'p'.repeat(43), scope, caseId: 'case', conversationId: 'conversation' },
      ])
    : createFakeSmsIntegration(provider, Buffer.alloc(32, 1));
  const configured =
    mode === 'communication'
      ? createCommunicationIntegration(integration as ReturnType<typeof createNativeIntegration>, [
          {
            scope,
            caseId: 'case',
            conversationId: 'conversation',
            publisherToken: 'r'.repeat(43),
            sdkToken: 's'.repeat(43),
            browserToken: 'z'.repeat(43),
          },
        ])
      : integration;
  const dispatcher = new ChannelDispatcher(
    {
      host: '127.0.0.1',
      port: 1,
      database: 'livekit_lab',
      user: 'livekit_lab',
      password: 'x'.repeat(43),
      schema: 'p2_native_unit',
    },
    configured,
    new SeededAccounts([{ ...scope, token, caseId: 'case', conversationId: 'conversation' }]),
    adapters,
    { timeoutMs: 1000, cleanupTimeoutMs: 1000 },
  );
  return {
    dispatcher,
    state,
    calls,
    observed,
    receiptId,
    operationKey,
    externalId,
    row,
    binding,
    canonicalBinding,
  };
}
beforeEach(() => {
  for (const fn of Object.values(pgBoundary)) fn.mockReset();
  pgBoundary.end.mockResolvedValue(undefined);
});
for (const mode of ['sms', 'native', 'communication'] as const) {
  test(mode + ' dispatcher validates the baseline and reads persisted eligibility', async () => {
    const f = fixture(mode);
    try {
      assert.deepEqual(await f.dispatcher.eligible(token, 1), [f.receiptId]);
      assert.ok(
        f.calls.findIndex((q) => q.includes("c.relname='schema_metadata'")) <
          f.calls.findIndex((q) => q.includes('SELECT m.singleton,m.version')),
      );
      assert.ok(f.calls.some((q) => q.includes('SELECT jsonb_build_object(')));
      assert.equal(f.observed.accept, 0);
    } finally {
      await f.dispatcher.close();
    }
    assert.equal(pgBoundary.end.mock.calls.length, 1);
  });
  test(
    mode + ' dispatch commits one original operation and replays without new generation',
    async () => {
      const f = fixture(mode);
      try {
        assert.deepEqual(await f.dispatcher.step(token, f.receiptId), {
          status: 'dispatched',
          receiptId: f.receiptId,
          operationKey: f.operationKey,
          externalReceiptId: f.externalId,
          reconciled: false,
        });
        assert.equal((await f.dispatcher.step(token, f.receiptId)).status, 'dispatched');
        assert.deepEqual(f.observed, { agent: 1, accept: 1, lookup: 1 });
        assert.equal(f.row.state, 'dispatched');
        assert.ok(f.calls.includes('COMMIT'));
      } finally {
        await f.dispatcher.close();
      }
    },
  );
}
for (const change of [
  'string_version',
  'future_version',
  'wrong_digest',
  'wrong_marker',
  'catalog_drift',
  'unsafe_metadata_acl',
  'invalid_limit',
  'duplicate_metadata',
] as const) {
  test('channel baseline rejects ' + change + ' before dispatch or external ports', async () => {
    const f = fixture();
    if (change === 'string_version') f.state.version = '1';
    if (change === 'future_version') f.state.version = 2;
    if (change === 'wrong_digest') f.state.definition = '0'.repeat(64);
    if (change === 'wrong_marker') f.state.marker = 'p2-channel-schema-v5';
    if (change === 'catalog_drift') f.state.savedCatalog = { unit_catalog_identity: 'different' };
    if (change === 'unsafe_metadata_acl') f.state.unsafeAcl = true;
    if (change === 'invalid_limit') f.state.maxInbox = 0;
    if (change === 'duplicate_metadata') f.state.metadataRows = 2;
    try {
      await assert.rejects(() => f.dispatcher.eligible(token, 1), { code: 'SchemaMismatch' });
      assert.deepEqual(f.observed, { agent: 0, accept: 0, lookup: 0 });
      assert.ok(f.calls.includes('ROLLBACK'));
      assert.deepEqual(pgBoundary.release.mock.calls.at(-1), [false]);
      if (change === 'unsafe_metadata_acl')
        assert.equal(
          f.calls.some((q) => q.includes('SELECT m.singleton,m.version')),
          false,
        );
    } finally {
      await f.dispatcher.close();
    }
  });
}
for (const kind of ['expired', 'revoked'] as const)
  test(kind + ' binding blocks a new dispatch through the real native guard', async () => {
    const f = fixture();
    if (kind === 'expired') {
      f.binding.expires_at = now;
      f.canonicalBinding();
    } else f.binding.revoked_at = now;
    try {
      assert.equal((await f.dispatcher.step(token, f.receiptId)).status, 'blocked');
      assert.deepEqual(f.observed, { agent: 0, accept: 0, lookup: 0 });
    } finally {
      await f.dispatcher.close();
    }
  });
test('revoked binding parks possible external input outside automatic eligibility', async () => {
  const f = fixture();
  Object.assign(f.row, {
    state: 'uncertain',
    possible_external: true,
    attempt_count: 1,
    last_code: 'adapter_unavailable',
  });
  f.binding.revoked_at = now;
  try {
    assert.equal((await f.dispatcher.step(token, f.receiptId)).status, 'uncertain');
    assert.deepEqual(f.observed, { agent: 0, accept: 0, lookup: 0 });
    assert.equal(f.row.state, 'uncertain');
    assert.equal(f.row.last_code, 'association_required');
    assert.equal(f.row.attempt_count, 1);
    await f.dispatcher.eligible(token, 4);
    const due = f.calls.filter((q) => q.includes('SELECT i.receipt_id::text'));
    assert.equal(due.length, 1);
    assert.ok(due[0]!.includes("NOT (d.state='uncertain' AND d.last_code='association_required')"));
    assert.ok(due[0]!.includes("d.state IN ('pending','running','uncertain')"));
  } finally {
    await f.dispatcher.close();
  }
});
