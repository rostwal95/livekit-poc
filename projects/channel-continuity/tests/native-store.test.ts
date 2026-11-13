/** Narrow storage authority/temporal invariants; actual SQL joins live in pg_native_cases. */
import assert from 'node:assert/strict';
import { test } from 'vitest';
import { randomUUID, createHash } from 'node:crypto';
import type { PoolClient } from 'pg';
import { NativeStore } from '../src/native-store.js';
import { createNativeIntegration } from '../src/native.js';
import { upgradeChannelSchemaV6 } from '../src/migrations.js';
import type { StoredMessage } from '../src/postgres.js';
const sha = (s: string) => createHash('sha256').update(s).digest('hex');
const providerScope = { tenantId: 'tenant', provider: 'livekit', providerAccountId: 'local' },
  scope = { tenantId: 'tenant', accountId: 'account' };
function fixture() {
  const bindingId = randomUUID(),
    published = new Date('2030-01-01T00:00:00.000Z'),
    expires = new Date(published.getTime() + 1000),
    store = new NativeStore(
      'p2_native_test',
      createNativeIntegration(providerScope, [
        { token: 'p'.repeat(43), scope, caseId: 'case', conversationId: 'conversation' },
      ]),
    );
  const raw = {
    schemaVersion: 1,
    bindingId,
    providerScope,
    scope,
    caseId: 'case',
    conversationId: 'conversation',
    roomId: 'room',
    participantId: 'browser',
    expiresAt: expires.toISOString(),
  };
  const row = {
    binding_id: bindingId,
    tenant_id: 'tenant',
    provider: 'livekit',
    provider_account_id: 'local',
    account_id: 'account',
    case_id: 'case',
    conversation_id: 'conversation',
    room_id: 'room',
    participant_id: 'browser',
    bearer_digest: sha('b'.repeat(43)),
    canonical_binding: JSON.stringify(raw),
    binding_digest: sha(JSON.stringify(raw)),
    published_at: published,
    expires_at: expires,
    revoked_at: null as Date | null,
  };
  const message = {
    event: {
      schemaVersion: 1,
      type: 'text.received',
      eventId: randomUUID(),
      messageId: randomUUID(),
      providerScope,
      accountScope: scope,
      caseId: 'case',
      conversationId: 'conversation',
      senderId: bindingId,
      channel: 'web_chat',
      body: 'investigate',
      receivedAt: published.toISOString(),
    },
    associationVersion: '1',
  } as unknown as StoredMessage;
  let now = new Date(published.getTime() + 100),
    settings = { singleton: true, max_bindings: 3, binding_count: 1, actual: 1 };
  const calls: string[] = [];
  let held: Promise<void> | undefined;
  const client = {
    async query(sql: string) {
      calls.push(sql);
      if (sql.includes('native_bindings') && !sql.includes('native_settings')) {
        if (held) await held;
        return { rows: [row] };
      }
      if (sql.includes('native_settings')) return { rows: [settings] };
      if (sql.includes('clock_timestamp()')) return { rows: [{ now }] };
      throw Error('unexpected_query');
    },
  } as unknown as PoolClient;
  return {
    store,
    row,
    message,
    client,
    calls,
    settings,
    setNow: (v: Date) => {
      now = v;
    },
    hold: (v: Promise<void>) => {
      held = v;
    },
    expires,
  };
}
for (const kind of [
  'expired',
  'revoked',
  'wrong-account',
  'wrong-case',
  'wrong-provider',
  'wrong-epoch',
] as const)
  test('new native binding authority rejects ' + kind, async () => {
    const f = fixture();
    if (kind === 'expired') f.setNow(f.expires);
    if (kind === 'revoked') f.row.revoked_at = new Date();
    if (kind === 'wrong-account')
      f.message = {
        ...f.message,
        event: { ...f.message.event, accountScope: { ...scope, accountId: 'other' } },
      };
    if (kind === 'wrong-case')
      f.message = { ...f.message, event: { ...f.message.event, caseId: 'other' } };
    if (kind === 'wrong-provider')
      f.message = {
        ...f.message,
        event: {
          ...f.message.event,
          providerScope: { ...providerScope, providerAccountId: 'other' },
        },
      };
    if (kind === 'wrong-epoch') f.message = { ...f.message, associationVersion: '2' };
    assert.equal(await f.store.binding(f.client, f.message), null);
  });
test('fresh clock after binding lock expiry then independent eligible progress', async () => {
  const f = fixture();
  let release!: () => void;
  f.hold(
    new Promise<void>((r) => {
      release = r;
    }),
  );
  const pending = f.store.binding(f.client, f.message);
  assert.equal(f.calls.length, 1);
  f.setNow(f.expires);
  release();
  assert.equal(await pending, null);
  assert.match(f.calls[0]!, /FOR UPDATE/);
  assert.match(f.calls.at(-1)!, /clock_timestamp/);
  const valid = fixture();
  assert.equal(await valid.store.binding(valid.client, valid.message), '1');
});
test('canonical stored binding extra fields cannot be laundered with recomputed digest', async () => {
  const f = fixture();
  f.row.canonical_binding = f.row.canonical_binding.slice(0, -1) + ',"extra":true}';
  f.row.binding_digest = sha(f.row.canonical_binding);
  await assert.rejects(() => f.store.binding(f.client, f.message), { code: 'SchemaMismatch' });
});
test('corrupt native counter prevents new authority', async () => {
  const f = fixture();
  f.settings.binding_count = 2;
  await assert.rejects(() => f.store.binding(f.client, f.message), { code: 'SchemaMismatch' });
  assert.equal(
    f.calls.some((c) => c.includes('clock_timestamp')),
    false,
  );
});
test('invalid trusted owner hook is rejected before any PostgreSQL connection', async () => {
  const db = {
    host: '127.0.0.1' as const,
    port: 1,
    database: 'livekit_lab',
    user: 'continuity_migrator',
    password: 'a'.repeat(43),
    schema: 'p2_native_test',
  };
  let read = false;
  for (const hooks of [
    null,
    { unknown: true },
    Object.defineProperty({}, 'harnessAfterTables', {
      enumerable: true,
      get() {
        read = true;
        throw Error('sensitive');
      },
    }),
  ])
    await assert.rejects(() => upgradeChannelSchemaV6(db, { maxBindings: 3 }, hooks as never), {
      code: 'InvalidConfiguration',
    });
  assert.equal(read, false);
});
