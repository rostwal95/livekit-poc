/** Explicit local PostgreSQL lane. This filename is outside ordinary Vitest discovery. */
import assert from 'node:assert/strict';
import { dispatchCases, childDispatch, cleanupDispatch } from './pg_dispatch_cases.js';
import { awaitFixtureEntry, fixtureResult, observeFixtureWork } from './fixture-work.js';
import { gatewayCases, childGateway } from './pg_gateway_cases.js';
import { agentCases, cleanupAgents } from './pg_agent_cases.js';
import { fork, spawn, type ChildProcess } from 'node:child_process';
import { resolve } from 'node:path';
import {
  createStandaloneExample,
  StandaloneError,
  type StandaloneBinding,
  type StandalonePorts,
} from '@livekit-ecosystem/channel-continuity/standalone';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import pg from 'pg';
import {
  ChannelInbox,
  SeededAccounts,
  ChannelError,
  type ChannelLimits,
  type DatabaseSettings,
  type InboxEvent,
} from '../src/postgres.js';
import { installChannelSchema } from '../src/migrations.js';
import {
  createFakeSmsIntegration,
  signFakeSms,
  type FakeSmsMessage,
  type FakeSmsIntegration,
  type SignedFakeSms,
} from '../src/security.js';
import type { ProviderScope } from '../src/index.js';

const MARKER = 'p2-channel-schema-v1';
const OWNER = 'continuity_migrator';
const RUNTIME = 'livekit_lab';
const DB = 'livekit_lab';
const HMAC_KEY = Buffer.alloc(32, 0x61); // Synthetic carrier fixture, never a provider credential.
const SCOPE: ProviderScope = Object.freeze({
  tenantId: 'tenant-a',
  provider: 'fake_sms',
  providerAccountId: 'carrier-a',
});
const TOKEN_A = 'synthetic-account-a-' + 'a'.repeat(40);
const TOKEN_B = 'synthetic-account-b-' + 'b'.repeat(40);
const TOKEN_C = 'synthetic-account-c-' + 'c'.repeat(40);
const SEEDS = Object.freeze([
  {
    token: TOKEN_A,
    tenantId: 'tenant-a',
    accountId: 'account-a',
    conversationId: 'conversation-a',
    caseId: 'case-a',
  },
  {
    token: TOKEN_B,
    tenantId: 'tenant-a',
    accountId: 'account-b',
    conversationId: 'conversation-b',
    caseId: 'case-b',
  },
  {
    token: TOKEN_C,
    tenantId: 'tenant-b',
    accountId: 'account-c',
    conversationId: 'conversation-c',
    caseId: 'case-c',
  },
]);
const DEFAULT_LIMITS: ChannelLimits = {
  maxInbox: 1000,
  maxChallenges: 512,
  maxAssociations: 256,
  maxSenders: 128,
};
const CHILD_EVENT = 'child-committed-event';
const CHILD_SENDER = 'child-owned-sender';
type Receipt = Awaited<ReturnType<ChannelInbox['acceptSms']>>['receipt'];
type Hooks = NonNullable<ConstructorParameters<typeof ChannelInbox>[3]>;
type CaseCode = 'ok' | 'assertion_failed' | 'test_timeout' | 'setup_failed';
type CaseResult = Readonly<{ name: string; status: 'passed' | 'failed'; code: CaseCode }>;

class TestFailure extends Error {
  constructor(readonly code: Exclude<CaseCode, 'ok'>) {
    super(code);
  }
}
function environment(name: string): string {
  const value = process.env[name];
  if (typeof value !== 'string' || !value) throw new TestFailure('setup_failed');
  return value;
}
function port(): number {
  const selected = Number(environment('P2_POSTGRES_PORT'));
  if (!Number.isSafeInteger(selected) || selected < 1 || selected > 65535)
    throw new TestFailure('setup_failed');
  return selected;
}
function connection(schema: string, owner = false): DatabaseSettings {
  if (!/^p2_inbox_[a-f0-9]{32}(?![\s\S])/.test(schema)) throw new TestFailure('setup_failed');
  return {
    host: '127.0.0.1',
    port: port(),
    database: DB,
    user: owner ? OWNER : RUNTIME,
    password: environment(owner ? 'P2_MIGRATION_PASSWORD' : 'P2_RUNTIME_PASSWORD'),
    schema,
  };
}
function identifier(schema: string): string {
  assert.match(schema, /^p2_inbox_[a-f0-9]{32}(?![\s\S])/);
  return '"' + schema + '"';
}
async function sql<T>(
  settings: DatabaseSettings,
  operation: (client: pg.Client) => Promise<T>,
): Promise<T> {
  const client = new pg.Client({
    host: settings.host,
    port: settings.port,
    database: settings.database,
    user: settings.user,
    password: settings.password,
    ssl: false,
    application_name: 'p2-inbox-fixture',
    connectionTimeoutMillis: 1500,
    query_timeout: 5000,
    options:
      '-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000',
  });
  try {
    await client.connect();
    return await operation(client);
  } finally {
    await client.end();
  }
}
function code(error: unknown): string | undefined {
  return error instanceof ChannelError ? error.code : undefined;
}
async function rejects(work: () => Promise<unknown>, expected: readonly string[]): Promise<void> {
  await assert.rejects(work, (failure: unknown) => expected.includes(code(failure) ?? ''));
}
async function bounded<T>(work: Promise<T>, milliseconds: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      work,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new TestFailure('test_timeout')), milliseconds);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
function signed(
  eventId: string,
  senderId: string,
  body = 'Review the synthetic policy',
  scope: ProviderScope = SCOPE,
  messageId = eventId,
  timestamp = Math.floor(Date.now() / 1000),
): SignedFakeSms {
  const message: FakeSmsMessage = {
    schemaVersion: 1,
    eventId,
    messageId,
    senderId,
    body,
    occurredAt: '2030-01-01T00:00:00.000Z',
  };
  return signFakeSms(message, HMAC_KEY, timestamp, scope);
}
async function accept(inbox: ChannelInbox, message: SignedFakeSms) {
  return await inbox.acceptSms(message.raw, message.headers);
}

const schemas = new Set<string>();
const inboxes = new Set<ChannelInbox>();
const children = new Set<ChildProcess>();
const observations: InboxEvent[] = [];
let observationOverflow = false;
function observe(event: InboxEvent): void {
  if (observations.length >= 512) {
    observationOverflow = true;
    return;
  }
  observations.push(event);
}
function verifyObservations(): void {
  assert.equal(observationOverflow, false);
  const encoded = JSON.stringify(observations);
  for (const privateValue of [TOKEN_A, TOKEN_B, TOKEN_C, 'SYNTHETIC_PRIVATE_FAILURE', 'LINK '])
    assert.equal(encoded.includes(privateValue), false);
  assert.ok(observations.some((event) => event.event === 'completed'));
  assert.ok(observations.some((event) => event.event === 'rejected'));
  for (const event of observations)
    assert.deepEqual(Object.keys(event).sort(), ['code', 'event', 'operation']);
}
let childTerminations = 0;
const demoObservations: Array<
  Readonly<{
    phase: 'accepted' | 'replayed';
    receipt_id: string;
    operation_key: string;
    acceptance_sequence: string;
    replayed: boolean;
    processing_state: 'pending';
    execution: 'not_executed';
  }>
> = [];
function inboxFor(schema: string, integration: FakeSmsIntegration, hooks?: Hooks): ChannelInbox {
  const inbox = new ChannelInbox(
    connection(schema),
    integration,
    new SeededAccounts(SEEDS),
    hooks,
    observe,
  );
  inboxes.add(inbox);
  return inbox;
}
async function fixture(
  limits: ChannelLimits = DEFAULT_LIMITS,
): Promise<{ schema: string; inbox: ChannelInbox; integration: FakeSmsIntegration }> {
  const schema = 'p2_inbox_' + randomUUID().replaceAll('-', '');
  schemas.add(schema); // Register before migration so even partial setup gets checked.
  await installChannelSchema(connection(schema, true), limits);
  const integration = createFakeSmsIntegration(SCOPE, HMAC_KEY);
  return { schema, integration, inbox: inboxFor(schema, integration) };
}
async function bind(
  inbox: ChannelInbox,
  token: string,
  sender: string,
  scope: ProviderScope = SCOPE,
): Promise<string> {
  const challenge = await inbox.createChallenge(token, sender);
  assert.match(challenge.challengeId, /^[a-f0-9-]{36}$/);
  assert.match(challenge.secret, /^[A-Za-z0-9_-]{43}$/);
  const link = signed(
    'link-' + randomUUID(),
    sender,
    `LINK ${challenge.challengeId} ${challenge.secret}`,
    scope,
  );
  const associated = await inbox.completeAssociation(link.raw, link.headers);
  assert.match(associated.associationVersion, /^[1-9][0-9]*$/);
  return associated.associationVersion;
}
async function rowCount(schema: string, table: 'inbox' | 'processing_intents'): Promise<number> {
  return await sql(connection(schema, true), async (client) => {
    const result = await client.query<{ count: string }>(
      `SELECT count(*)::text AS count FROM ${identifier(schema)}."${table}"`,
    );
    return Number(result.rows[0]!.count);
  });
}
async function dropOwnedSchema(schema: string): Promise<void> {
  await sql(connection(schema, true), async (client) => {
    const found = await client.query<{ marker: string | null; owner: string }>(
      "SELECT obj_description(oid,'pg_namespace') AS marker,pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=$1",
      [schema],
    );
    if (found.rows.length === 0) return;
    assert.equal(found.rows.length, 1);
    assert.ok([MARKER, 'p2-channel-schema-v2'].includes(found.rows[0]!.marker ?? ''));
    assert.equal(found.rows[0]!.owner, OWNER);
    await client.query(`DROP SCHEMA ${identifier(schema)} CASCADE`);
    const remaining = await client.query('SELECT 1 FROM pg_namespace WHERE nspname=$1', [schema]);
    assert.equal(remaining.rows.length, 0);
  });
}

async function migration_and_runtime_privileges(): Promise<void> {
  const f = await fixture();
  await installChannelSchema(connection(f.schema, true));
  await sql(connection(f.schema), async (client) => {
    const role = await client.query<{ owner: string; can_create: boolean; can_temp: boolean }>(
      `SELECT current_user AS owner,has_database_privilege(current_user,current_database(),'CREATE') AS can_create,has_database_privilege(current_user,current_database(),'TEMPORARY') AS can_temp`,
    );
    assert.deepEqual(role.rows[0], { owner: RUNTIME, can_create: false, can_temp: false });
    for (const statement of [
      `CREATE TABLE ${identifier(f.schema)}.forbidden_table(value text)`,
      `ALTER TABLE ${identifier(f.schema)}.inbox ADD COLUMN forbidden_column text`,
      `DELETE FROM ${identifier(f.schema)}.inbox`,
      `UPDATE ${identifier(f.schema)}.inbox SET canonical_payload='forbidden'`,
      `TRUNCATE ${identifier(f.schema)}.inbox`,
    ])
      await assert.rejects(
        () => client.query(statement),
        (failure: unknown) =>
          typeof failure === 'object' &&
          failure !== null &&
          'code' in failure &&
          failure.code === '42501',
      );
  });
  await sql(connection(f.schema, true), async (client) => {
    await client.query(`ALTER TABLE ${identifier(f.schema)}.inbox ADD COLUMN drift text`);
  });
  await rejects(() => installChannelSchema(connection(f.schema, true)), ['SchemaMismatch']);
  await rejects(() => f.inbox.createChallenge(TOKEN_A, 'drift-sender'), ['SchemaMismatch']);
  await sql(connection(f.schema, true), async (client) => {
    await client.query(`ALTER TABLE ${identifier(f.schema)}.inbox DROP COLUMN drift`);
  });
  await installChannelSchema(connection(f.schema, true));
  await bind(f.inbox, TOKEN_A, 'repaired-sender');
  type Admission = {
    inbox_count: number;
    challenge_count: number;
    association_count: number;
    sender_count: number;
  };
  const admission = await sql(connection(f.schema, true), async (client) => {
    const result = await client.query<Admission>(
      `SELECT * FROM ${identifier(f.schema)}.admission WHERE singleton`,
    );
    await client.query(`DELETE FROM ${identifier(f.schema)}.admission WHERE singleton`);
    return result.rows[0]!;
  });
  await rejects(() => f.inbox.createChallenge(TOKEN_A, 'missing-guard-sender'), ['SchemaMismatch']);
  await sql(connection(f.schema, true), async (client) => {
    await client.query(
      `INSERT INTO ${identifier(f.schema)}.admission(singleton,inbox_count,challenge_count,association_count,sender_count) VALUES(true,$1,$2,$3,$4)`,
      [
        admission.inbox_count,
        admission.challenge_count,
        admission.association_count,
        admission.sender_count,
      ],
    );
  });
  await bind(f.inbox, TOKEN_A, 'restored-guard-sender');

  // A failed transaction cannot hide nextval: sequence advancement survives rollback.
  await sql(connection(f.schema, true), async (client) => {
    await client.query(
      `ALTER TABLE ${identifier(f.schema)}.schema_metadata RENAME TO schema_metadata_original`,
    );
    await client.query(`CREATE SEQUENCE ${identifier(f.schema)}.metadata_read_probe START 1`);
    await client.query(
      `CREATE VIEW ${identifier(f.schema)}.schema_metadata AS SELECT singleton,nextval('${identifier(f.schema)}.metadata_read_probe'::regclass)::smallint AS version,runtime_role,definition_digest,catalog_snapshot,max_inbox,max_challenges,max_associations,max_senders FROM ${identifier(f.schema)}.schema_metadata_original`,
    );
    await client.query(
      `GRANT SELECT ON ${identifier(f.schema)}.schema_metadata TO livekit_lab; GRANT USAGE ON SEQUENCE ${identifier(f.schema)}.metadata_read_probe TO livekit_lab`,
    );
  });
  try {
    await rejects(
      () => f.inbox.createChallenge(TOKEN_A, 'metadata-view-sender'),
      ['SchemaMismatch'],
    );
    await rejects(() => installChannelSchema(connection(f.schema, true)), ['SchemaMismatch']);
    await sql(connection(f.schema, true), async (client) => {
      const probe = await client.query<{ is_called: boolean }>(
        `SELECT is_called FROM ${identifier(f.schema)}.metadata_read_probe`,
      );
      assert.equal(probe.rows[0]!.is_called, false);
    });
  } finally {
    await sql(connection(f.schema, true), async (client) => {
      await client.query(`DROP VIEW ${identifier(f.schema)}.schema_metadata`);
      await client.query(
        `ALTER TABLE ${identifier(f.schema)}.schema_metadata_original RENAME TO schema_metadata`,
      );
      await client.query(`DROP SEQUENCE ${identifier(f.schema)}.metadata_read_probe`);
    });
  }
  await installChannelSchema(connection(f.schema, true));

  for (const [change, repair, sender] of [
    [
      `ALTER TABLE ${identifier(f.schema)}.inbox ENABLE ROW LEVEL SECURITY`,
      `ALTER TABLE ${identifier(f.schema)}.inbox DISABLE ROW LEVEL SECURITY`,
      'rls-drift-sender',
    ],
    [
      `ALTER TABLE ${identifier(f.schema)}.inbox ALTER COLUMN canonical_payload TYPE text COLLATE \"pg_catalog\".\"C\"`,
      `ALTER TABLE ${identifier(f.schema)}.inbox ALTER COLUMN canonical_payload TYPE text COLLATE \"pg_catalog\".\"default\"`,
      'collation-drift-sender',
    ],
  ] as const) {
    const before = await sql(
      connection(f.schema, true),
      async (client) =>
        (await client.query(`SELECT * FROM ${identifier(f.schema)}.admission WHERE singleton`))
          .rows[0],
    );
    await sql(connection(f.schema, true), async (client) => {
      await client.query(change);
    });
    try {
      await rejects(() => f.inbox.createChallenge(TOKEN_A, sender), ['SchemaMismatch']);
      const after = await sql(
        connection(f.schema, true),
        async (client) =>
          (await client.query(`SELECT * FROM ${identifier(f.schema)}.admission WHERE singleton`))
            .rows[0],
      );
      assert.deepEqual(after, before);
    } finally {
      await sql(connection(f.schema, true), async (client) => {
        await client.query(repair);
      });
    }
    await installChannelSchema(connection(f.schema, true));
  }
  await bind(f.inbox, TOKEN_A, 'metadata-restored-sender');
  assert.equal(
    (await accept(f.inbox, signed('metadata-restored-progress', 'metadata-restored-sender')))
      .replayed,
    false,
  );
}
async function signed_possession_and_invalid_authority(): Promise<void> {
  const f = await fixture();
  await rejects(
    () => f.inbox.createChallenge('unknown-synthetic-token', 'sender-a'),
    ['AccessDenied'],
  );
  const challenge = await f.inbox.createChallenge(TOKEN_A, 'sender-a');
  const ordinary = signed('not-link', 'sender-a');
  await rejects(
    () => f.inbox.completeAssociation(ordinary.raw, ordinary.headers),
    ['AssociationRejected'],
  );
  const unsigned = signed(
    'invalid-signature',
    'sender-a',
    `LINK ${challenge.challengeId} ${challenge.secret}`,
  );
  await assert.rejects(() =>
    f.inbox.completeAssociation(unsigned.raw, { ...unsigned.headers, signature: '0'.repeat(64) }),
  );
  const wrongSender = signed(
    'wrong-sender',
    'sender-b',
    `LINK ${challenge.challengeId} ${challenge.secret}`,
  );
  await rejects(
    () => f.inbox.completeAssociation(wrongSender.raw, wrongSender.headers),
    ['AssociationRejected'],
  );
  const link = signed(
    'valid-link',
    'sender-a',
    `LINK ${challenge.challengeId} ${challenge.secret}`,
  );
  await f.inbox.completeAssociation(link.raw, link.headers);
  const result = await accept(f.inbox, signed('valid-message', 'sender-a'));
  const stored = await f.inbox.inspect(TOKEN_A, result.receipt.receiptId);
  assert.equal(stored.event.accountScope?.accountId, 'account-a');
  assert.equal(stored.event.conversationId, 'conversation-a');
  assert.equal(stored.event.caseId, 'case-a');
  assert.equal(stored.processingState, 'pending');
}
async function concurrent_exact_replay(): Promise<void> {
  const f = await fixture();
  await bind(f.inbox, TOKEN_A, 'sender-a');
  const message = signed('same-event', 'sender-a');
  const otherGateway = inboxFor(f.schema, f.integration);
  const results = await Promise.all(
    Array.from({ length: 6 }, (_, index) => accept(index < 3 ? f.inbox : otherGateway, message)),
  );
  assert.equal(new Set(results.map((item) => item.receipt.receiptId)).size, 1);
  assert.equal(results.filter((item) => !item.replayed).length, 1);
  for (const item of results) assert.deepEqual(item.receipt, results[0]!.receipt);
  assert.equal(await rowCount(f.schema, 'inbox'), 1);
  assert.equal(await rowCount(f.schema, 'processing_intents'), 1);
}
async function semantic_conflict_and_retry_metadata(): Promise<void> {
  const f = await fixture();
  await bind(f.inbox, TOKEN_A, 'sender-a');
  const original = await accept(
    f.inbox,
    signed('original-event', 'sender-a', 'same synthetic text'),
  );
  await rejects(
    () => accept(f.inbox, signed('original-event', 'sender-a', 'changed synthetic text')),
    ['IdentityConflict'],
  );
  await rejects(
    () =>
      accept(
        f.inbox,
        signed('original-event', 'sender-a', 'same synthetic text', SCOPE, 'changed-message'),
      ),
    ['IdentityConflict'],
  );
  const retried = await accept(
    f.inbox,
    signed(
      'original-event',
      'sender-a',
      'same synthetic text',
      SCOPE,
      'original-event',
      Math.floor(Date.now() / 1000) + 1,
    ),
  );
  assert.equal(retried.replayed, true);
  assert.deepEqual(retried.receipt, original.receipt);
  const distinct = await accept(
    f.inbox,
    signed('another-event', 'sender-a', 'same synthetic text'),
  );
  assert.equal(distinct.replayed, false);
  assert.notEqual(distinct.receipt.receiptId, original.receipt.receiptId);
  assert.equal(await rowCount(f.schema, 'inbox'), 2);
}
async function provider_and_tenant_identity_domains(): Promise<void> {
  const f = await fixture();
  const secondScope: ProviderScope = { ...SCOPE, providerAccountId: 'carrier-b' };
  const otherTenant: ProviderScope = {
    tenantId: 'tenant-b',
    provider: 'fake_sms',
    providerAccountId: 'carrier-a',
  };
  const second = inboxFor(f.schema, createFakeSmsIntegration(secondScope, HMAC_KEY));
  const third = inboxFor(f.schema, createFakeSmsIntegration(otherTenant, HMAC_KEY));
  await bind(f.inbox, TOKEN_A, 'shared-sender');
  await bind(second, TOKEN_A, 'shared-sender', secondScope);
  await bind(third, TOKEN_C, 'shared-sender', otherTenant);
  const receipts: Receipt[] = [];
  for (const [inbox, scope] of [
    [f.inbox, SCOPE],
    [second, secondScope],
    [third, otherTenant],
  ] as const)
    receipts.push(
      (
        await accept(
          inbox,
          signed('shared-provider-event', 'shared-sender', 'same synthetic text', scope),
        )
      ).receipt,
    );
  assert.equal(new Set(receipts.map((item) => item.receiptId)).size, 3);
  await rejects(
    () => f.inbox.inspect(TOKEN_A, receipts[2]!.receiptId),
    ['NotFound', 'AccessDenied'],
  );
  assert.equal(await rowCount(f.schema, 'inbox'), 3);
}
async function capacity_preserves_replay_and_reads(): Promise<void> {
  const f = await fixture({ ...DEFAULT_LIMITS, maxInbox: 2 });
  await bind(f.inbox, TOKEN_A, 'sender-a');
  const message = signed('capacity-original', 'sender-a');
  const first = await accept(f.inbox, message);
  await accept(f.inbox, signed('capacity-second', 'sender-a'));
  await rejects(() => accept(f.inbox, signed('capacity-overflow', 'sender-a')), ['Overloaded']);
  const replay = await accept(f.inbox, message);
  assert.equal(replay.replayed, true);
  assert.deepEqual(replay.receipt, first.receipt);
  assert.equal(
    (await f.inbox.inspect(TOKEN_A, first.receipt.receiptId)).receipt.receiptId,
    first.receipt.receiptId,
  );
  assert.equal((await f.inbox.history(TOKEN_A, { limit: 10 })).messages.length, 2);
  assert.equal(await rowCount(f.schema, 'inbox'), 2);
  let signalEntered!: () => void;
  let release!: () => void;
  const entered = new Promise<void>((resolve) => {
    signalEntered = resolve;
  });
  const released = new Promise<void>((resolve) => {
    release = resolve;
  });
  const held = inboxFor(f.schema, f.integration, {
    async beforeAcceptCommit() {
      signalEntered();
      await released;
    },
  });
  const callers = Array.from({ length: 4 }, () => observeFixtureWork(accept(held, message)));
  const pending = observeFixtureWork(Promise.all(callers.map(fixtureResult)));
  try {
    await awaitFixtureEntry(entered, pending, 5000, () => new TestFailure('test_timeout'));
    assert.equal(held.metrics().active, 4);
    await rejects(() => accept(held, signed('active-overflow', 'sender-a')), ['Overloaded']);
    assert.equal(held.metrics().active, 4);
    assert.equal(held.metrics().overloaded, 1);
  } finally {
    release();
    // Promise.all may reject before its other accepts settle. Join every
    // independently observed caller before fixture cleanup can reach its schema.
    await Promise.all(callers);
  }
  for (const result of await fixtureResult(pending)) {
    assert.equal(result.replayed, true);
    assert.deepEqual(result.receipt, first.receipt);
  }
  assert.equal(held.metrics().active, 0);
  assert.equal(
    (await f.inbox.inspect(TOKEN_A, first.receipt.receiptId)).receipt.receiptId,
    first.receipt.receiptId,
  );
}
async function challenge_expiry_attempts_and_single_use(): Promise<void> {
  const f = await fixture();
  const expired = await f.inbox.createChallenge(TOKEN_A, 'expired-sender');
  await sql(connection(f.schema, true), async (client) => {
    await client.query(
      `UPDATE ${identifier(f.schema)}.challenges SET issued_at=clock_timestamp()-interval '2 seconds',expires_at=clock_timestamp()-interval '1 second' WHERE challenge_id=$1`,
      [expired.challengeId],
    );
  });
  const expiredLink = signed(
    'expired-link',
    'expired-sender',
    `LINK ${expired.challengeId} ${expired.secret}`,
  );
  const expiredObservationStart = observations.length;
  await rejects(
    () => f.inbox.completeAssociation(expiredLink.raw, expiredLink.headers),
    ['AssociationRejected'],
  );
  assert.deepEqual(
    observations.slice(expiredObservationStart).filter((event) => event.operation === 'associate'),
    [{ event: 'rejected', operation: 'associate', code: 'AssociationRejected' }],
  );
  const exhausted = await f.inbox.createChallenge(TOKEN_A, 'attempt-sender');
  for (let index = 0; index < 3; index++) {
    const wrong = signed(
      'wrong-secret-' + index,
      'attempt-sender',
      `LINK ${exhausted.challengeId} ${'A'.repeat(43)}`,
    );
    const wrongObservationStart = observations.length;
    await rejects(
      () => f.inbox.completeAssociation(wrong.raw, wrong.headers),
      ['AssociationRejected'],
    );
    assert.deepEqual(
      observations.slice(wrongObservationStart).filter((event) => event.operation === 'associate'),
      [{ event: 'rejected', operation: 'associate', code: 'AssociationRejected' }],
    );
    await sql(connection(f.schema, true), async (client) => {
      const stored = await client.query<{ attempts: number; consumed_at: Date | null }>(
        `SELECT attempts,consumed_at FROM ${identifier(f.schema)}.challenges WHERE challenge_id=$1`,
        [exhausted.challengeId],
      );
      assert.equal(stored.rows[0]!.attempts, index + 1);
      assert.equal(stored.rows[0]!.consumed_at, null);
    });
  }
  const exhaustedLink = signed(
    'exhausted-link',
    'attempt-sender',
    `LINK ${exhausted.challengeId} ${exhausted.secret}`,
  );
  await rejects(
    () => f.inbox.completeAssociation(exhaustedLink.raw, exhaustedLink.headers),
    ['AssociationRejected'],
  );
  const current = await f.inbox.createChallenge(TOKEN_A, 'current-sender');
  const link = signed(
    'concurrent-link',
    'current-sender',
    `LINK ${current.challengeId} ${current.secret}`,
  );
  const raced = await Promise.allSettled(
    Array.from({ length: 2 }, () => f.inbox.completeAssociation(link.raw, link.headers)),
  );
  assert.equal(raced.filter((item) => item.status === 'fulfilled').length, 1);
  for (const item of raced)
    if (item.status === 'rejected') assert.equal(code(item.reason), 'AssociationRejected');
  await rejects(() => f.inbox.completeAssociation(link.raw, link.headers), ['AssociationRejected']);
  assert.equal(
    (await accept(f.inbox, signed('post-challenge-progress', 'current-sender'))).replayed,
    false,
  );
}
async function revocation_reassignment_and_private_history(): Promise<void> {
  const f = await fixture();
  await bind(f.inbox, TOKEN_A, 'sender-a');
  const old = await accept(f.inbox, signed('old-account-event', 'sender-a'));
  const oldChallenge = await f.inbox.createChallenge(TOKEN_A, 'sender-a');
  const revoked = await f.inbox.revokeAssociation(TOKEN_A, 'sender-a');
  assert.equal(revoked.revoked, true);
  const repeated = await f.inbox.revokeAssociation(TOKEN_A, 'sender-a');
  assert.equal(repeated.revoked, false);
  assert.equal(repeated.associationVersion, revoked.associationVersion);
  await rejects(
    () => accept(f.inbox, signed('revoked-event', 'sender-a')),
    ['AssociationRequired'],
  );
  const staleLink = signed(
    'old-link',
    'sender-a',
    `LINK ${oldChallenge.challengeId} ${oldChallenge.secret}`,
  );
  await rejects(
    () => f.inbox.completeAssociation(staleLink.raw, staleLink.headers),
    ['AssociationRejected'],
  );
  await bind(f.inbox, TOKEN_B, 'sender-a');
  const current = await accept(f.inbox, signed('new-account-event', 'sender-a'));
  await rejects(
    () => f.inbox.inspect(TOKEN_B, old.receipt.receiptId),
    ['NotFound', 'AccessDenied'],
  );
  await rejects(
    () => f.inbox.inspect(TOKEN_A, current.receipt.receiptId),
    ['NotFound', 'AccessDenied'],
  );
  assert.equal(
    (await f.inbox.inspect(TOKEN_A, old.receipt.receiptId)).receipt.receiptId,
    old.receipt.receiptId,
  );
  const currentHistory = await f.inbox.history(TOKEN_B, { limit: 10 });
  assert.deepEqual(
    currentHistory.messages.map((item) => item.receipt.receiptId),
    [current.receipt.receiptId],
  );
}
async function stable_sequence_and_history_paging(): Promise<void> {
  const f = await fixture();
  await bind(f.inbox, TOKEN_A, 'sender-a');
  const receipts: Receipt[] = [];
  for (let index = 0; index < 5; index++)
    receipts.push((await accept(f.inbox, signed('ordered-' + index, 'sender-a'))).receipt);
  for (let index = 0; index < receipts.length; index++) {
    const item = receipts[index]!;
    assert.match(item.acceptanceSequence, /^[1-9][0-9]*$/);
    assert.ok(Number.isFinite(Date.parse(item.acceptedAt)));
    if (index)
      assert.ok(BigInt(item.acceptanceSequence) > BigInt(receipts[index - 1]!.acceptanceSequence));
  }
  const pages: Receipt[] = [];
  let after: string | undefined;
  for (let index = 0; index < 3; index++) {
    const page = await f.inbox.history(
      TOKEN_A,
      after === undefined ? { limit: 2 } : { after, limit: 2 },
    );
    assert.equal(page.messages.length, index < 2 ? 2 : 1);
    pages.push(...page.messages.map((item) => item.receipt));
    after = page.nextCursor;
    assert.equal(after === undefined, index === 2);
  }
  assert.deepEqual(pages, receipts);
}
async function before_commit_rolls_back(): Promise<void> {
  const f = await fixture();
  await bind(f.inbox, TOKEN_A, 'sender-a');
  const faulty = inboxFor(f.schema, f.integration, {
    beforeAcceptCommit() {
      throw new Error('SYNTHETIC_PRIVATE_FAILURE');
    },
  });
  const message = signed('before-commit-event', 'sender-a');
  await rejects(() => accept(faulty, message), ['StorageUnavailable']);
  assert.equal(await rowCount(f.schema, 'inbox'), 0);
  assert.equal(await rowCount(f.schema, 'processing_intents'), 0);
  const recovered = await accept(f.inbox, message);
  assert.equal(recovered.replayed, false);
  assert.equal(await rowCount(f.schema, 'processing_intents'), 1);
}
async function after_commit_response_loss_reconciles(): Promise<void> {
  const f = await fixture();
  await bind(f.inbox, TOKEN_A, 'sender-a');
  const faulty = inboxFor(f.schema, f.integration, {
    afterAcceptCommit() {
      throw new Error('SYNTHETIC_PRIVATE_FAILURE');
    },
  });
  const message = signed('after-commit-event', 'sender-a');
  await rejects(() => accept(faulty, message), ['AcknowledgementUnknown']);
  const fresh = inboxFor(f.schema, f.integration);
  const recovered = await accept(fresh, message);
  assert.equal(recovered.replayed, true);
  assert.equal(
    (await fresh.inspect(TOKEN_A, recovered.receipt.receiptId)).receipt.receiptId,
    recovered.receipt.receiptId,
  );
  assert.equal(await rowCount(f.schema, 'inbox'), 1);
  assert.equal(await rowCount(f.schema, 'processing_intents'), 1);
  assert.ok(observations.some((event) => event.code === 'AcknowledgementUnknown'));
  assert.ok(observations.some((event) => event.code === 'StorageUnavailable'));

  const unhandled: unknown[] = [];
  const observeUnhandled = (reason: unknown): void => {
    unhandled.push(reason);
  };
  process.on('unhandledRejection', observeUnhandled);
  const asyncObserverInbox = new ChannelInbox(
    connection(f.schema),
    f.integration,
    new SeededAccounts(SEEDS),
    {},
    async (event) => {
      observe(event);
      throw new Error('SYNTHETIC_PRIVATE_FAILURE');
    },
  );
  inboxes.add(asyncObserverInbox);
  try {
    await bind(asyncObserverInbox, TOKEN_A, 'async-observer-sender');
    const progressed = await accept(
      asyncObserverInbox,
      signed('async-observer-progress', 'async-observer-sender'),
    );
    assert.equal(progressed.replayed, false);
    assert.equal(
      (await asyncObserverInbox.inspect(TOKEN_A, progressed.receipt.receiptId)).receipt.receiptId,
      progressed.receipt.receiptId,
    );
  } finally {
    await asyncObserverInbox.close();
    await new Promise<void>((resolve) => setImmediate(resolve));
    process.off('unhandledRejection', observeUnhandled);
  }
  assert.deepEqual(unhandled, []);
  assert.ok(asyncObserverInbox.metrics().telemetryFailures! > 0);
  assert.equal(asyncObserverInbox.metrics().active, 0);
  verifyObservations();
}
async function waitForExit(
  child: ChildProcess,
): Promise<Readonly<{ exit: number | null; signal: NodeJS.Signals | null }>> {
  if (child.exitCode !== null || child.signalCode !== null)
    return { exit: child.exitCode, signal: child.signalCode };
  return await new Promise((resolve, reject) => {
    child.once('error', () => reject(new TestFailure('assertion_failed')));
    child.once('exit', (exit, signal) => resolve({ exit, signal }));
  });
}
async function actual_process_exit_after_commit(): Promise<void> {
  const f = await fixture();
  await bind(f.inbox, TOKEN_A, CHILD_SENDER);
  const childEnv: NodeJS.ProcessEnv = {
    PATH: process.env.PATH,
    P2_POSTGRES_PORT: environment('P2_POSTGRES_PORT'),
    P2_RUNTIME_PASSWORD: environment('P2_RUNTIME_PASSWORD'),
    P2_CHILD_SCHEMA: f.schema,
  };
  const child = fork(fileURLToPath(import.meta.url), ['--child-after-commit'], {
    env: childEnv,
    stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
  });
  children.add(child);
  const reached = new Promise<void>((resolve, reject) => {
    child.once('message', (message: unknown) => {
      if (
        typeof message === 'object' &&
        message !== null &&
        'type' in message &&
        message.type === 'accept_committed'
      )
        resolve();
      else reject(new TestFailure('assertion_failed'));
    });
    child.once('exit', () => reject(new TestFailure('assertion_failed')));
    child.once('error', () => reject(new TestFailure('assertion_failed')));
  });
  await bounded(reached, 10000);
  assert.equal(await rowCount(f.schema, 'inbox'), 1);
  assert.ok(child.kill('SIGKILL'));
  const terminated = await bounded(waitForExit(child), 5000);
  assert.equal(terminated.signal, 'SIGKILL');
  children.delete(child);
  childTerminations++;
  const fresh = inboxFor(f.schema, f.integration);
  const recovered = await accept(fresh, signed(CHILD_EVENT, CHILD_SENDER));
  assert.equal(recovered.replayed, true);
  assert.equal(await rowCount(f.schema, 'inbox'), 1);
  assert.equal(await rowCount(f.schema, 'processing_intents'), 1);
}
async function childAfterCommit(): Promise<void> {
  assert.equal(process.env.P2_MIGRATION_PASSWORD, undefined);
  const inbox = new ChannelInbox(
    connection(environment('P2_CHILD_SCHEMA')),
    createFakeSmsIntegration(SCOPE, HMAC_KEY),
    new SeededAccounts(SEEDS),
    {
      async afterAcceptCommit() {
        if (!process.send) throw new TestFailure('setup_failed');
        await new Promise<void>((resolve, reject) =>
          process.send!({ type: 'accept_committed' }, (error) =>
            error ? reject(error) : resolve(),
          ),
        );
        await new Promise<never>(() => undefined);
      },
    },
    () => undefined,
  );
  try {
    await accept(inbox, signed(CHILD_EVENT, CHILD_SENDER));
  } finally {
    await inbox.close();
  }
}

async function standalone_example_public_ports(): Promise<void> {
  const f = await fixture();
  await bind(f.inbox, TOKEN_A, 'example-owned-sender');
  const binding: StandaloneBinding = {
    providerScope: SCOPE,
    accountScope: { tenantId: 'tenant-a', accountId: 'account-a' },
    conversationId: 'conversation-a',
    caseId: 'case-a',
  };
  let validCase = false;
  let operationInspections = 0;
  const ports: StandalonePorts = {
    inbox: f.inbox,
    cases: {
      async inspect(reference) {
        return {
          scope: validCase ? reference.scope : { ...reference.scope, accountId: 'other-account' },
          caseId: reference.caseId,
          revision: '1',
          source: 'synthetic_read_only',
        };
      },
    },
    agent: {
      async preview(input) {
        return {
          kind: 'investigation',
          source: 'scripted',
          caseRevision: input.currentCase.revision,
        };
      },
    },
    operations: {
      async inspectPending(input) {
        operationInspections++;
        return { operationKey: input.operationKey, state: 'not_executed', durable: false };
      },
    },
  };
  assert.throws(
    () =>
      createStandaloneExample(
        { ...ports, agent: undefined } as unknown as StandalonePorts,
        binding,
      ),
    (error: unknown) => error instanceof StandaloneError && error.code === 'MissingAdapter',
  );
  assert.equal(await rowCount(f.schema, 'inbox'), 0);
  const example = createStandaloneExample(ports, binding);
  try {
    const frame = signed('example-port-event', 'example-owned-sender');
    const accepted = await example.accept(frame.raw, frame.headers);
    assert.equal(accepted.replayed, false);
    await assert.rejects(
      () => example.preview(TOKEN_A, accepted.receipt.receiptId),
      (error: unknown) => error instanceof StandaloneError && error.code === 'InvalidAdapterResult',
    );
    assert.equal(operationInspections, 0);
    const stored = await f.inbox.inspect(TOKEN_A, accepted.receipt.receiptId);
    assert.equal(stored.processingState, 'pending');
    validCase = true;
    const preview = await example.preview(TOKEN_A, accepted.receipt.receiptId);
    assert.deepEqual(preview.receipt, accepted.receipt);
    assert.equal(preview.operationKey, stored.operationKey);
    assert.equal(preview.execution, 'not_executed');
    assert.deepEqual(preview.operation, {
      operationKey: stored.operationKey,
      state: 'not_executed',
      durable: false,
    });
    assert.equal(operationInspections, 1);
    assert.equal(await rowCount(f.schema, 'inbox'), 1);
    assert.equal(await rowCount(f.schema, 'processing_intents'), 1);
    const pending = await sql(
      connection(f.schema, true),
      async (client) =>
        (
          await client.query(
            `SELECT operation_key::text,state FROM ${identifier(f.schema)}.processing_intents`,
          )
        ).rows,
    );
    assert.deepEqual(pending, [{ operation_key: stored.operationKey, state: 'pending' }]);
  } finally {
    await example.close();
  }
}
async function runPublicExample(schema: string): Promise<Record<string, unknown>> {
  const examplePath = resolve(process.cwd(), 'dist/examples/fake-carrier.js');
  const child = spawn(process.execPath, [examplePath], {
    env: {
      PATH: process.env.PATH,
      P2_POSTGRES_PORT: environment('P2_POSTGRES_PORT'),
      P2_RUNTIME_PASSWORD: environment('P2_RUNTIME_PASSWORD'),
      P2_DEMO_SCHEMA: schema,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  children.add(child);
  const output: Buffer[] = [],
    errors: Buffer[] = [];
  let size = 0;
  const capture =
    (target: Buffer[]) =>
    (chunk: Buffer | string): void => {
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      size += bytes.length;
      if (size > 8192) {
        child.kill('SIGKILL');
        return;
      }
      target.push(bytes);
    };
  child.stdout!.on('data', capture(output));
  child.stderr!.on('data', capture(errors));
  const closed = await bounded(
    new Promise<Readonly<{ exit: number | null; signal: NodeJS.Signals | null }>>(
      (done, reject) => {
        child.once('error', () => reject(new TestFailure('assertion_failed')));
        child.once('close', (exit, signal) => done({ exit, signal }));
      },
    ),
    10000,
  );
  children.delete(child);
  assert.deepEqual(closed, { exit: 0, signal: null });
  assert.ok(size <= 8192);
  assert.equal(Buffer.concat(errors).length, 0);
  const report = JSON.parse(Buffer.concat(output).toString('utf8')) as Record<string, unknown>;
  assert.deepEqual(
    Object.keys(report).sort(),
    [
      'schema_version',
      'mode',
      'status',
      'code',
      'acceptance',
      'receipt',
      'replayed',
      'operationKey',
      'processingState',
      'execution',
      'cleanup_complete',
    ].sort(),
  );
  assert.equal(report.schema_version, 1);
  assert.equal(report.mode, 'standalone_input_preview');
  assert.equal(report.status, 'passed');
  assert.equal(report.code, 'ok');
  assert.equal(report.acceptance, 'observed');
  assert.equal(report.processingState, 'pending');
  assert.equal(report.execution, 'not_executed');
  assert.equal(report.cleanup_complete, true);
  assert.match(
    report.operationKey as string,
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
  assert.equal(typeof report.replayed, 'boolean');
  const receipt = report.receipt as Record<string, unknown>;
  assert.equal(typeof receipt, 'object');
  assert.notEqual(receipt, null);
  assert.deepEqual(
    Object.keys(receipt).sort(),
    ['receiptId', 'eventId', 'messageId', 'acceptanceSequence', 'acceptedAt'].sort(),
  );
  assert.match(
    receipt.receiptId as string,
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
  assert.match(receipt.acceptanceSequence as string, /^[1-9][0-9]{0,18}$/);
  assert.ok(BigInt(receipt.acceptanceSequence as string) <= 9223372036854775807n);
  assert.equal(receipt.eventId, 'example-owned-event');
  assert.equal(receipt.messageId, 'example-owned-message');
  assert.equal(typeof receipt.acceptedAt, 'string');
  const encoded = JSON.stringify(report);
  for (const secret of [
    TOKEN_A,
    environment('P2_RUNTIME_PASSWORD'),
    environment('P2_MIGRATION_PASSWORD'),
    'LINK ',
  ])
    assert.equal(encoded.includes(secret), false);
  return report;
}
async function standalone_example_fresh_process_replay(): Promise<void> {
  const f = await fixture();
  await bind(f.inbox, TOKEN_A, 'example-owned-sender');
  const accepted = await runPublicExample(f.schema);
  assert.equal(accepted.replayed, false);
  const original = accepted.receipt as Record<string, unknown>;
  demoObservations.push(
    Object.freeze({
      phase: 'accepted',
      receipt_id: original.receiptId as string,
      operation_key: accepted.operationKey as string,
      acceptance_sequence: original.acceptanceSequence as string,
      replayed: false,
      processing_state: 'pending',
      execution: 'not_executed',
    }),
  );
  const replayed = await runPublicExample(f.schema);
  assert.equal(replayed.replayed, true);
  assert.deepEqual(accepted.receipt, replayed.receipt);
  assert.equal(accepted.operationKey, replayed.operationKey);
  demoObservations.push(
    Object.freeze({
      phase: 'replayed',
      receipt_id: original.receiptId as string,
      operation_key: replayed.operationKey as string,
      acceptance_sequence: original.acceptanceSequence as string,
      replayed: true,
      processing_state: 'pending',
      execution: 'not_executed',
    }),
  );
  assert.equal(await rowCount(f.schema, 'inbox'), 1);
  assert.equal(await rowCount(f.schema, 'processing_intents'), 1);
  const pending = await sql(
    connection(f.schema, true),
    async (client) =>
      (
        await client.query(
          `SELECT operation_key::text,state FROM ${identifier(f.schema)}.processing_intents`,
        )
      ).rows,
  );
  assert.deepEqual(pending, [{ operation_key: accepted.operationKey, state: 'pending' }]);
}

const dispatchContext = {
  fixture,
  connection,
  sql,
  bind: async (inbox: unknown, token: string, sender: string) =>
    await bind(inbox as ChannelInbox, token, sender),
  signed,
  children,
  terminated: () => {
    childTerminations++;
  },
};
const DISPATCH_CASES = dispatchCases(dispatchContext);
const GATEWAY_CASES = gatewayCases(dispatchContext);
const AGENT_CASES = agentCases(dispatchContext);
const CASES: ReadonlyArray<readonly [string, () => Promise<void>]> = [
  ['migration_and_runtime_privileges', migration_and_runtime_privileges],
  ['signed_possession_and_invalid_authority', signed_possession_and_invalid_authority],
  ['concurrent_exact_replay', concurrent_exact_replay],
  ['semantic_conflict_and_retry_metadata', semantic_conflict_and_retry_metadata],
  ['provider_and_tenant_identity_domains', provider_and_tenant_identity_domains],
  ['capacity_preserves_replay_and_reads', capacity_preserves_replay_and_reads],
  ['challenge_expiry_attempts_and_single_use', challenge_expiry_attempts_and_single_use],
  ['revocation_reassignment_and_private_history', revocation_reassignment_and_private_history],
  ['stable_sequence_and_history_paging', stable_sequence_and_history_paging],
  ['before_commit_rolls_back', before_commit_rolls_back],
  ['after_commit_response_loss_reconciles', after_commit_response_loss_reconciles],
  ['actual_process_exit_after_commit', actual_process_exit_after_commit],
  ['standalone_example_public_ports', standalone_example_public_ports],
  ['standalone_example_fresh_process_replay', standalone_example_fresh_process_replay],
];
async function cleanup(): Promise<boolean> {
  let complete = true;
  for (const child of children) {
    try {
      child.kill('SIGKILL');
      await bounded(waitForExit(child), 3000);
    } catch {
      complete = false;
    }
  }
  children.clear();
  if (!(await cleanupAgents())) complete = false;
  if (!(await cleanupDispatch(dispatchContext))) complete = false;
  for (const inbox of inboxes) {
    try {
      await bounded(inbox.close(), 7000);
    } catch {
      complete = false;
    }
  }
  inboxes.clear();
  for (const schema of schemas) {
    try {
      await bounded(dropOwnedSchema(schema), 7000);
    } catch {
      complete = false;
    }
  }
  schemas.clear();
  return complete;
}
async function main(): Promise<void> {
  if (process.argv[2] === '--child-after-commit') {
    await childAfterCommit();
    return;
  }
  if (process.argv[2] === '--child-gateway') {
    await childGateway();
    return;
  }
  if (process.argv[2] === '--child-dispatch') {
    await childDispatch();
    return;
  }
  const exampleOnly = process.argv[2] === '--example';
  const dispatchOnly = process.argv[2] === '--dispatch';
  const gatewayOnly = process.argv[2] === '--gateway';
  const agentOnly = process.argv[2] === '--agent';
  if (
    process.argv.length > 3 ||
    (process.argv[2] !== undefined && !exampleOnly && !dispatchOnly && !gatewayOnly && !agentOnly)
  )
    throw new TestFailure('setup_failed');
  const selectedCases = exampleOnly
    ? CASES.slice(-2)
    : dispatchOnly
      ? DISPATCH_CASES
      : gatewayOnly
        ? GATEWAY_CASES
        : agentOnly
          ? AGENT_CASES
          : [...CASES, ...DISPATCH_CASES, ...GATEWAY_CASES, ...AGENT_CASES];
  const started = performance.now();
  const cases: CaseResult[] = [];
  let cleanupComplete = false;
  try {
    const [major, minor, patch] = process.versions.node.split('.').map(Number);
    if (!(
      (major === 24 && (minor! > 22 || (minor === 22 && patch! >= 2))) ||
      (major === 26 && minor! >= 13)
    ))
      throw new TestFailure('setup_failed');
    environment('P2_RUNTIME_PASSWORD');
    environment('P2_MIGRATION_PASSWORD');
    port();
    for (const [name, run] of selectedCases) {
      try {
        await bounded(run(), 20000);
        cases.push({ name, status: 'passed', code: 'ok' });
      } catch (error) {
        cases.push({
          name,
          status: 'failed',
          code: error instanceof TestFailure ? error.code : 'assertion_failed',
        });
        break;
      }
    }
  } catch {
    /* Missing setup is a failed zero-test gate, never a skip. */
  } finally {
    cleanupComplete = await cleanup();
  }
  const passed = cases.filter((item) => item.status === 'passed').length;
  const failures = cases.filter((item) => item.code === 'assertion_failed').length;
  const errors = cases.length - passed - failures;
  const status =
    cases.length === selectedCases.length &&
    passed === selectedCases.length &&
    cleanupComplete &&
    childTerminations === (exampleOnly ? 0 : dispatchOnly || gatewayOnly || agentOnly ? 1 : 4)
      ? 'passed'
      : 'failed';
  const report = {
    schema_version: 1,
    status,
    mode: exampleOnly
      ? 'local_synthetic_postgres_example'
      : dispatchOnly
        ? 'local_synthetic_postgres_dispatch'
        : gatewayOnly
          ? 'local_synthetic_postgres_gateway'
          : agentOnly
            ? 'local_synthetic_postgres_agent'
            : 'local_synthetic_postgres',
    tests: cases.length,
    passed,
    failures,
    errors,
    skipped: 0,
    duration_seconds: (performance.now() - started) / 1000,
    cleanup_complete: cleanupComplete,
    child_terminations: childTerminations,
    case_results: cases,
    ...(exampleOnly ? { demo_observations: demoObservations } : {}),
    node_version: process.versions.node,
  };
  process.stdout.write(JSON.stringify(report) + '\n');
  process.exitCode = status === 'passed' ? 0 : 1;
}
void main().catch(() => {
  process.exitCode = 1;
});
