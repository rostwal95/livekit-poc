/** Selected v8 receiver fixtures. Public P2 APIs own behavior; SQL observes isolated test state. */
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';
import pg from 'pg';
import { ChannelOutbox, type CarrierSendPort } from '@livekit-ecosystem/channel-continuity/outbox';
import {
  NativeChannelInbox,
  createNativeIntegration,
} from '@livekit-ecosystem/channel-continuity/native';
import {
  SeededAccounts,
  type DatabaseSettings,
} from '@livekit-ecosystem/channel-continuity/postgres';
import { createFakeSmsIntegration } from '@livekit-ecosystem/channel-continuity/security';
import {
  CurrentCaseHttpClient,
  type CurrentCasePort,
} from '@livekit-ecosystem/channel-continuity/rehydration';
import {
  installChannelSchema,
  upgradeChannelSchemaV2,
  upgradeChannelSchemaV3,
  upgradeChannelSchemaV4,
  upgradeChannelSchemaV5,
  upgradeChannelSchemaV6,
  upgradeChannelSchemaV7,
  upgradeChannelSchemaV8,
} from '@livekit-ecosystem/channel-continuity/migrations';
import {
  ChannelResultReceiver,
  ChannelResultReader,
  parseResultIntent,
  encodeResultIntent,
  ResultReceiverError,
  RESULT_NOTICE,
  type P1ResultIntent,
} from '@livekit-ecosystem/channel-continuity/result-receiver';
import { observeFixtureWork, awaitFixtureEntry } from './fixture-work.js';
function env(name: string): string {
  const value = process.env['P2_RESULT_' + name];
  assert.ok(value);
  return value;
}
const directory = env('DIRECTORY');
type Fixture = {
  schema_version: 1;
  scope: { tenantId: string; accountId: string };
  case_id: string;
  conversation_id: string;
  recipient_id: string;
  legacy_outbound_id: string;
  delivery_ids: string[];
  work_ids: string[];
  attempt_ids: string[];
  native_binding_ids: Record<'a' | 'b' | 'revoke' | 'expire', string>;
  case_endpoint: { host: '127.0.0.1'; port: number };
};
const fixture = JSON.parse(readFileSync(directory + '/fixture.json', 'utf8')) as Fixture;
assert.equal(fixture.schema_version, 1);
assert.equal(fixture.delivery_ids.length, 8);
assert.equal(fixture.work_ids.length, 8);
assert.equal(fixture.attempt_ids.length, 8);
const schema = env('SCHEMA');
assert.match(schema, /^p2_result_[a-f0-9]{32}(?![\s\S])/u);
const q = (name: string) => `"${schema}"."${name}"`;
function db(owner = false): DatabaseSettings {
  return {
    host: '127.0.0.1',
    port: Number(env('PG_PORT')),
    database: 'livekit_lab',
    user: owner ? 'continuity_migrator' : 'livekit_lab',
    password: env(owner ? 'OWNER_PASSWORD' : 'RUNTIME_PASSWORD'),
    schema,
  };
}
async function sql<T>(owner: boolean, work: (client: pg.Client) => Promise<T>): Promise<T> {
  const d = db(owner),
    client = new pg.Client({
      ...d,
      ssl: false,
      connectionTimeoutMillis: 1500,
      query_timeout: 5000,
      application_name: 'p2-result-fixture-observer',
      options: '-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1500',
    });
  await client.connect();
  try {
    return await work(client);
  } finally {
    await client.end();
  }
}
function save(name: string, value: unknown): void {
  const text = JSON.stringify(value) + '\n';
  assert.ok(Buffer.byteLength(text) <= 262144);
  writeFileSync(directory + '/' + name, text, { flag: 'wx', mode: 0o600 });
}
function read<T>(name: string): T {
  return JSON.parse(readFileSync(directory + '/' + name, 'utf8')) as T;
}
const route = () => ({
  scope: fixture.scope,
  caseId: fixture.case_id,
  conversationId: fixture.conversation_id,
  recipientId: fixture.recipient_id,
});
const provider = () => ({
  tenantId: fixture.scope.tenantId,
  provider: 'fake_sms',
  providerAccountId: 'result_fixture_sms',
});
const accounts = () =>
  new SeededAccounts([
    {
      token: env('ACCOUNT_TOKEN'),
      ...fixture.scope,
      caseId: fixture.case_id,
      conversationId: fixture.conversation_id,
    },
  ]);
const publisher = () => ({
  token: env('PUBLISHER_TOKEN'),
  scope: fixture.scope,
  caseId: fixture.case_id,
  conversationId: fixture.conversation_id,
});
const setupRecord = () => read<{ receiver_id: string }>('result-setup.json');
const shared = JSON.parse(readFileSync(env('SHARED_FIXTURE'), 'utf8')) as {
  intent_canonical: string;
};
const baseIntent = parseResultIntent(shared.intent_canonical);
function intent(n: number, body?: Buffer): P1ResultIntent {
  return parseResultIntent(
    encodeResultIntent({
      ...baseIntent,
      delivery_id: fixture.delivery_ids[n]!,
      work_id: fixture.work_ids[n]!,
      attempt_id: fixture.attempt_ids[n]!,
      receiver_id: setupRecord().receiver_id,
      recipient_id: fixture.recipient_id,
      scope: { tenant_id: fixture.scope.tenantId, account_id: fixture.scope.accountId },
      ...(body
        ? {
            body: body.toString('base64'),
            result_sha256: createHash('sha256').update(body).digest('hex'),
          }
        : {}),
    }),
  );
}
const FAILURE_STAGES = [
  'configuration',
  'setup',
  'upgrade',
  'exercise_atomic_acceptance',
  'exercise_exact_replay',
  'exercise_identity_denials',
  'exercise_maximum_body',
  'exercise_native_first_denial',
  'exercise_native_current_read',
  'exercise_native_final_denial',
  'exercise_protected_expiry',
  'exercise_retained_read',
  'commit_before_ack',
  'recover',
  'serve',
  'restore_check',
  'cleanup_guard',
] as const;
type FailureStage = (typeof FAILURE_STAGES)[number];
let failureStage: FailureStage = 'configuration';
const SAFE_CODES = [
  'InvalidCommand',
  'AccessDenied',
  'NotFound',
  'IdentityConflict',
  'Overloaded',
  'UpgradeRequired',
  'Unavailable',
  'AcknowledgementUnknown',
  'CleanupIncomplete',
  'Closed',
] as const;
let expectedCode: string | null = null;
let actualCode: string | null = null;
function diagnosticCode(error: unknown): string {
  if (error && typeof error === 'object') {
    const d = Object.getOwnPropertyDescriptor(error, 'code');
    if (
      d &&
      'value' in d &&
      typeof d.value === 'string' &&
      SAFE_CODES.includes(d.value as (typeof SAFE_CODES)[number])
    )
      return d.value;
  }
  return 'unclassified';
}
let carrierCalls = 0;
function composition() {
  const integration = createFakeSmsIntegration(provider(), Buffer.alloc(32, 0x53));
  const native = createNativeIntegration(
    {
      tenantId: fixture.scope.tenantId,
      provider: 'livekit',
      providerAccountId: 'result_fixture_rtc',
    },
    [
      {
        token: env('NATIVE_PUBLISHER_TOKEN'),
        scope: fixture.scope,
        caseId: fixture.case_id,
        conversationId: fixture.conversation_id,
      },
    ],
  );
  const inbox = new NativeChannelInbox(db(), native, accounts(), {}, () => {});
  const carrier: CarrierSendPort = {
    capabilities: 'ordinary_fake_sms_v1',
    async send() {
      carrierCalls++;
      throw new Error('fixture_carrier_must_not_run');
    },
  };
  const outbox = new ChannelOutbox(db(), integration, accounts(), [publisher()], carrier, {
    observer: () => {},
  });
  const receiver = new ChannelResultReceiver(
    outbox,
    {
      receiverId: setupRecord().receiver_id,
      bindings: [{ ...route(), publisherToken: env('PUBLISHER_TOKEN') }],
    },
    { observer: () => {} },
  );
  const cases = new CurrentCaseHttpClient(
    fixture.case_endpoint,
    env('CASE_AUTHORIZATION'),
    [{ scope: fixture.scope, caseId: fixture.case_id, conversationId: fixture.conversation_id }],
    { timeoutMs: 1000, cleanupMs: 1000, maxActive: 2 },
  );
  const readers: ChannelResultReader[] = [];
  const reader = (port: CurrentCasePort = cases, options = { timeoutMs: 3000, cleanupMs: 100 }) => {
    const r = new ChannelResultReader(
      outbox,
      inbox,
      port,
      { receiverId: setupRecord().receiver_id, bindings: [route()] },
      { observer: () => {}, ...options },
    );
    readers.push(r);
    return r;
  };
  return {
    inbox,
    outbox,
    receiver,
    cases,
    reader,
    async close() {
      const first = await Promise.allSettled([...readers.map((r) => r.close()), receiver.close()]);
      assert.ok(first.every((x) => x.status === 'fulfilled'));
      await Promise.all([outbox.close(), inbox.close(), cases.close()]);
      assert.equal(carrierCalls, 0);
      save('result-ownership-' + mode + '.json', {
        schema_version: 1,
        receiver: receiver.metrics(),
        readers: readers.map((r) => r.metrics()),
        outbox: outbox.metrics(),
        inbox: inbox.metrics(),
        caseClient: cases.metrics(),
        carrier_calls: carrierCalls,
        cleanup_complete: true,
      });
    },
  };
}
async function snapshot(owner = false) {
  return sql(owner, async (c) => {
    const meta = (
      await c.query(`SELECT version,definition_digest FROM ${q('schema_metadata')} WHERE singleton`)
    ).rows[0];
    const settings = (
      await c.query(
        `SELECT receiver_id::text,max_replies FROM ${q('outbox_settings')} WHERE singleton`,
      )
    ).rows[0];
    const replyRows = (await c.query(`SELECT * FROM ${q('reply_intents')} ORDER BY outbound_id`))
      .rows;
    const resultRows =
      meta.version === 8
        ? (await c.query(`SELECT * FROM ${q('result_receipts')} ORDER BY delivery_id`)).rows
        : [];
    const counts = (
      await c.query(`SELECT reply_count,route_count FROM ${q('outbox_admission')} WHERE singleton`)
    ).rows[0];
    return { meta, settings, counts, replyRows, resultRows };
  });
}
async function reject(work: () => Promise<unknown>, code: string) {
  assert.ok(SAFE_CODES.includes(code as (typeof SAFE_CODES)[number]));
  expectedCode = code;
  actualCode = 'not_rejected';
  try {
    await work();
  } catch (error) {
    actualCode = diagnosticCode(error);
  }
  if (actualCode !== expectedCode) throw new Error('fixture_fixed_code_mismatch');
  expectedCode = actualCode = null;
}
async function bind(
  x: ReturnType<typeof composition>,
  label: 'a' | 'b' | 'revoke' | 'expire',
  duration = 280000,
) {
  const now = await sql(
    false,
    async (c) =>
      (await c.query("SELECT date_trunc('milliseconds',clock_timestamp()) AS now")).rows[0]
        ?.now as Date,
  );
  const expiresAt = new Date(now.getTime() + duration).toISOString();
  const result = await x.inbox.bind(env('NATIVE_PUBLISHER_TOKEN'), {
    bindingId: fixture.native_binding_ids[label],
    bearer: env('NATIVE_' + label.toUpperCase() + '_BEARER'),
    roomId: 'result_room_' + label,
    participantId: 'result_person_' + label,
    expiresAt,
  });
  return { ...result, label };
}
async function setup() {
  failureStage = 'setup';
  await installChannelSchema(db(true));
  await upgradeChannelSchemaV2(db(true));
  await upgradeChannelSchemaV3(db(true), { maxReplies: 8, maxRoutes: 8, maxAttempts: 3 });
  await upgradeChannelSchemaV4(db(true));
  await upgradeChannelSchemaV5(db(true));
  await upgradeChannelSchemaV6(db(true));
  await upgradeChannelSchemaV7(db(true));
  const receiverId = await sql(
    true,
    async (c) =>
      (await c.query(`SELECT receiver_id::text FROM ${q('outbox_settings')} WHERE singleton`))
        .rows[0]?.receiver_id as string,
  );
  // Establish this historical ordinary reply only through the existing public API.
  const box = new ChannelOutbox(
    db(),
    createFakeSmsIntegration(provider(), Buffer.alloc(32, 0x53)),
    accounts(),
    [publisher()],
    {
      capabilities: 'ordinary_fake_sms_v1',
      async send() {
        throw Error('unused');
      },
    },
    { observer: () => {} },
  );
  try {
    await box.enqueue(env('PUBLISHER_TOKEN'), {
      schemaVersion: 1,
      outboundId: fixture.legacy_outbound_id,
      responseId: 'legacy_result_fixture',
      body: 'Original ordinary reply retained.',
    });
    const old = await box.inspect(env('ACCOUNT_TOKEN'), fixture.legacy_outbound_id);
    save('result-setup.json', {
      schema_version: 1,
      receiver_id: receiverId,
      legacy_reply: old,
      schema_version_before: 7,
    });
  } finally {
    await box.close();
  }
  save('result-setup-snapshot.json', await snapshot(true));
}
async function upgrade() {
  failureStage = 'upgrade';
  const before = await snapshot(true);
  let caught = false;
  try {
    await upgradeChannelSchemaV8(db(true), {
      harnessAfterTables() {
        throw Error('synthetic_upgrade_interruption');
      },
    });
  } catch {
    caught = true;
  }
  assert.equal(caught, true);
  const rolledBack = await snapshot(true);
  assert.deepEqual(rolledBack, before);
  const receiverId = await upgradeChannelSchemaV8(db(true));
  assert.equal(receiverId, before.settings.receiver_id);
  const again = await upgradeChannelSchemaV8(db(true));
  assert.equal(again, receiverId);
  await installChannelSchema(db(true));
  await upgradeChannelSchemaV2(db(true));
  await upgradeChannelSchemaV3(db(true), { maxReplies: 8, maxRoutes: 8, maxAttempts: 3 });
  await upgradeChannelSchemaV4(db(true));
  await upgradeChannelSchemaV5(db(true));
  await upgradeChannelSchemaV6(db(true));
  await upgradeChannelSchemaV7(db(true));
  const after = await snapshot(true);
  assert.equal(after.meta.version, 8);
  assert.deepEqual(after.replyRows, before.replyRows);
  assert.deepEqual(after.counts, before.counts);
  save('result-upgrade.json', {
    schema_version: 1,
    before,
    rolled_back: rolledBack,
    after,
    receiver_id: receiverId,
  });
}
async function exercise() {
  failureStage = 'exercise_atomic_acceptance';
  const x = composition();
  const controls: Record<string, unknown>[] = [];
  try {
    const original = intent(0),
      before = await snapshot();
    const receipt = await x.receiver.accept(env('PUBLISHER_TOKEN'), original);
    const after = await snapshot();
    const reply = await x.outbox.inspect(env('ACCOUNT_TOKEN'), original.delivery_id);
    assert.equal(after.resultRows.length - before.resultRows.length, 1);
    assert.equal(after.replyRows.length - before.replyRows.length, 1);
    assert.equal(reply.reply.body, RESULT_NOTICE);
    assert.equal(reply.receipt.receiptId, receipt.receipt_id);
    assert.equal(reply.receipt.receiverId, receipt.receiver_id);
    assert.notEqual(reply.receipt.bodyDigest, receipt.result_sha256);
    assert.equal(Date.parse(reply.receipt.acceptedAt), receipt.accepted_at_ms);
    assert.equal(reply.attempts.length, 0);
    controls.push({
      name: 'atomic_original_acceptance',
      intent_canonical: encodeResultIntent(original),
      receipt,
      reply,
      before,
      after,
    });
    failureStage = 'exercise_exact_replay';
    const same = await Promise.all([
      x.receiver.accept(env('PUBLISHER_TOKEN'), original),
      x.receiver.accept(env('PUBLISHER_TOKEN'), original),
    ]);
    assert.deepEqual(same, [receipt, receipt]);
    const replay = await snapshot();
    assert.deepEqual(replay, after);
    controls.push({ name: 'concurrent_original_replay', receipts: same, snapshot: replay });
    failureStage = 'exercise_identity_denials';
    const changed = parseResultIntent(
      encodeResultIntent({ ...original, prepared_at_ms: original.prepared_at_ms + 1 }),
    );
    await reject(() => x.receiver.accept(env('PUBLISHER_TOKEN'), changed), 'IdentityConflict');
    await reject(() => x.receiver.find(env('PUBLISHER_TOKEN'), changed), 'IdentityConflict');
    await reject(
      () =>
        x.receiver.accept(env('PUBLISHER_TOKEN'), {
          ...original,
          scope: { ...original.scope, account_id: 'foreign_account' },
        }),
      'AccessDenied',
    );
    const collision = { ...original, delivery_id: fixture.legacy_outbound_id };
    await reject(() => x.receiver.accept(env('PUBLISHER_TOKEN'), collision), 'IdentityConflict');
    assert.deepEqual(await snapshot(), after);
    controls.push({
      name: 'changed_foreign_and_ordinary_collision_denial',
      changed_canonical: encodeResultIntent(changed),
      snapshot: after,
    });
    failureStage = 'exercise_maximum_body';
    const full = intent(1, Buffer.alloc(8192, 0x61));
    const fullReceipt = await x.receiver.accept(env('PUBLISHER_TOKEN'), full);
    const fullReply = await x.outbox.inspect(env('ACCOUNT_TOKEN'), full.delivery_id);
    assert.equal(Buffer.from(full.body, 'base64').length, 8192);
    assert.ok(Buffer.byteLength(fullReply.reply.body) <= 4096);
    controls.push({
      name: 'full_opaque_body_notice_separation',
      intent_canonical: encodeResultIntent(full),
      receipt: fullReceipt,
      reply: fullReply,
    });
    const a = await bind(x, 'a'),
      b = await bind(x, 'b');
    await x.inbox.revoke(env('NATIVE_PUBLISHER_TOKEN'), a.bindingId);
    const reader = x.reader();
    failureStage = 'exercise_native_first_denial';
    await reject(() => reader.native(env('NATIVE_A_BEARER'), original.delivery_id), 'AccessDenied');
    failureStage = 'exercise_native_current_read';
    const current = await reader.native(env('NATIVE_B_BEARER'), original.delivery_id);
    assert.ok(current);
    assert.equal(current.case.source, 'p1_public_v4');
    assert.deepEqual(current.receipt, receipt);
    assert.equal(current.observed.atomic, false);
    controls.push({ name: 'fresh_b_scoped_public_case_read', a, b, view: current });
    failureStage = 'exercise_native_final_denial';
    const revocable = await bind(x, 'revoke');
    let publicCase: unknown, revoke: unknown;
    const revoking = x.reader({
      async inspect(ref, signal) {
        const result = await x.cases.inspect(ref, signal);
        publicCase = result;
        revoke = await x.inbox.revoke(env('NATIVE_PUBLISHER_TOKEN'), revocable.bindingId);
        return result;
      },
    });
    await reject(
      () => revoking.native(env('NATIVE_REVOKE_BEARER'), original.delivery_id),
      'AccessDenied',
    );
    assert.deepEqual(await x.receiver.find(env('PUBLISHER_TOKEN'), original), receipt);
    controls.push({
      name: 'revocation_after_public_read_and_receiver_history',
      grant: revocable,
      public_case: publicCase,
      revoke,
      original_receipt: receipt,
    });
    failureStage = 'exercise_protected_expiry';
    const expiring = await bind(x, 'expire', 1000);
    let expiryClock: string | null = null,
      blockingGraph: unknown = null;
    let expiryEntered!: () => void;
    const expiryEntry = new Promise<void>((resolve) => {
      expiryEntered = resolve;
    });
    const expiry = x.reader({
      async inspect(ref, signal) {
        const result = await x.cases.inspect(ref, signal);
        expiryEntered();
        return result;
      },
    });
    await sql(false, async (lock) => {
      await lock.query('BEGIN');
      let released = false;
      const blockingPid = (await lock.query('SELECT pg_backend_pid() AS pid')).rows[0]
        ?.pid as number;
      await lock.query(`SELECT singleton FROM ${q('admission')} WHERE singleton FOR UPDATE`);
      const observed = observeFixtureWork(
        expiry.native(env('NATIVE_EXPIRE_BEARER'), original.delivery_id),
      );
      try {
        await awaitFixtureEntry(
          expiryEntry,
          observed,
          1000,
          () => new Error('expiry_entry_timeout'),
        );
        const deadline = performance.now() + 2000;
        while (true) {
          await lock.query('SELECT pg_stat_clear_snapshot()');
          const rows = (
            await lock.query(
              "SELECT pid,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE usename=current_user AND application_name='channel-continuity' AND query LIKE $1",
              ['%' + schema + '%'],
            )
          ).rows;
          const blocked = rows.find(
            (row) => Array.isArray(row.blockers) && row.blockers.includes(blockingPid),
          );
          if (blocked) {
            blockingGraph = {
              blocking_pid: blockingPid,
              blocked_pid: blocked.pid,
              blockers: blocked.blockers,
            };
            break;
          }
          const result = await Promise.race([
            observed.then(() => true),
            delay(5).then(() => false),
          ]);
          assert.equal(result, false);
          assert.ok(performance.now() < deadline);
        }
        while (true) {
          const now = (await lock.query('SELECT clock_timestamp() AS now')).rows[0]?.now as Date;
          if (now.getTime() >= Date.parse(expiring.expiresAt)) {
            expiryClock = now.toISOString();
            break;
          }
          assert.ok(performance.now() < deadline);
          await delay(5);
        }
        await lock.query('COMMIT');
        released = true;
        const result = await observed;
        assert.equal(result.status, 'rejected');
        if (result.status === 'rejected')
          assert.ok(
            result.reason instanceof ResultReceiverError && result.reason.code === 'AccessDenied',
          );
      } finally {
        if (!released) await lock.query('ROLLBACK');
      }
    });
    controls.push({
      name: 'expiry_after_protected_admission_wait',
      grant: expiring,
      blocking_graph: blockingGraph,
      db_expiry_witness: expiryClock,
    });
    failureStage = 'exercise_retained_read';
    let entered!: () => void, release!: () => void;
    const entry = new Promise<void>((r) => {
        entered = r;
      }),
      held = new Promise<void>((r) => {
        release = r;
      });
    const retained = x.reader(
      {
        async inspect(ref, signal) {
          const result = await x.cases.inspect(ref, signal);
          entered();
          await held;
          return result;
        },
      },
      { timeoutMs: 3000, cleanupMs: 30 },
    );
    const caller = new AbortController();
    const abandoned = observeFixtureWork(
      retained.native(env('NATIVE_B_BEARER'), original.delivery_id, caller.signal),
    );
    let pending: unknown, retainedPrimary: unknown;
    try {
      await awaitFixtureEntry(entry, abandoned, 3000, () => new Error('retained_entry_timeout'));
      caller.abort();
      const outcome = await abandoned;
      assert.equal(outcome.status, 'rejected');
      if (outcome.status === 'rejected')
        assert.ok(
          outcome.reason instanceof ResultReceiverError && outcome.reason.code === 'Unavailable',
        );
      assert.equal(retained.metrics().waiterRejected, 1);
      assert.equal(retained.metrics().active, 1);
      assert.equal(x.outbox.metrics().storageActive, 1);
      await reject(
        () => retained.native(env('NATIVE_B_BEARER'), original.delivery_id),
        'Overloaded',
      );
      await reject(() => retained.close(), 'CleanupIncomplete');
      const dbHeld = await sql(
        false,
        async (c) =>
          (
            await c.query(
              "SELECT state,query FROM pg_stat_activity WHERE usename=current_user AND application_name='channel-continuity' AND state LIKE 'idle in transaction%' AND query LIKE $1",
              ['%' + schema + '%'],
            )
          ).rows,
      );
      assert.equal(dbHeld.length, 0);
      assert.deepEqual(await x.receiver.find(env('PUBLISHER_TOKEN'), original), receipt);
      pending = {
        reader: retained.metrics(),
        outbox: x.outbox.metrics(),
        idle_transactions: dbHeld,
      };
      release();
      const settleDeadline = performance.now() + 1000;
      while (retained.metrics().active) {
        assert.ok(performance.now() < settleDeadline);
        await delay(5);
      }
      await retained.close();
    } catch (error) {
      retainedPrimary = error;
      throw error;
    } finally {
      release();
      try {
        await retained.close();
      } catch (error) {
        if (retainedPrimary === undefined) throw error;
      }
    }
    const useful = await reader.native(env('NATIVE_B_BEARER'), original.delivery_id);
    assert.ok(useful);
    controls.push({
      name: 'retained_waiter_sql_release_close_retry_and_progress',
      fault_kind: 'explicit_caller_abort_after_public_p1_read',
      read_completed: true,
      caller_aborted: caller.signal.aborted,
      pending,
      settled: retained.metrics(),
      useful_receipt: useful.receipt,
    });
    save('result-exercise.json', {
      schema_version: 1,
      controls,
      final_snapshot: await snapshot(),
      carrier_calls: carrierCalls,
    });
  } finally {
    await x.close();
  }
}
async function commitBeforeAck() {
  failureStage = 'commit_before_ack';
  const x = composition();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const original = intent(2),
      receipt = await x.receiver.accept(env('PUBLISHER_TOKEN'), original),
      retained = await snapshot();
    // A pending promise alone does not keep Node alive for the owned parent kill.
    const held = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error('parent_kill_missing')), 15000);
    });
    void held.catch(() => {});
    save('commit-before-ack.reached', {
      schema_version: 1,
      pid: process.pid,
      intent_canonical: encodeResultIntent(original),
      receipt,
      snapshot: retained,
    });
    await held;
  } finally {
    if (timer) clearTimeout(timer);
    await x.close();
  }
}
async function recover() {
  failureStage = 'recover';
  const x = composition();
  try {
    const original = intent(2),
      before = await snapshot(),
      found = await x.receiver.find(env('PUBLISHER_TOKEN'), original);
    assert.ok(found);
    const replay = await x.receiver.accept(env('PUBLISHER_TOKEN'), original);
    assert.deepEqual(replay, found);
    const after = await snapshot();
    assert.deepEqual(after, before);
    const crash = read<{ receipt: unknown }>('commit-before-ack.reached');
    assert.deepEqual(found, crash.receipt);
    save('result-recover.json', {
      schema_version: 1,
      before,
      after,
      receipt: found,
      intent_canonical: encodeResultIntent(original),
      carrier_calls: carrierCalls,
    });
  } finally {
    await x.close();
  }
}
async function restoreCheck() {
  failureStage = 'restore_check';
  const x = composition();
  try {
    const original = intent(0),
      known = await x.receiver.find(env('PUBLISHER_TOKEN'), original);
    assert.ok(known);
    const before = await snapshot();
    for (let n = 3; n < 8; n++) {
      const s = await snapshot();
      if (s.counts.reply_count === 8) break;
      await x.receiver.accept(env('PUBLISHER_TOKEN'), intent(n));
    }
    const full = await snapshot();
    assert.equal(full.counts.reply_count, 8);
    assert.equal(full.resultRows.length, 7);
    const denied = parseResultIntent(
      encodeResultIntent({
        ...original,
        delivery_id: randomUUID(),
        work_id: randomUUID(),
        attempt_id: randomUUID(),
      }),
    );
    await reject(() => x.receiver.accept(env('PUBLISHER_TOKEN'), denied), 'Overloaded');
    assert.deepEqual(await snapshot(), full);
    assert.deepEqual(await x.receiver.accept(env('PUBLISHER_TOKEN'), original), known);
    const reader = x.reader();
    const view = await reader.native(env('NATIVE_B_BEARER'), original.delivery_id);
    assert.ok(view);
    assert.deepEqual(view.receipt, known);
    assert.deepEqual(await snapshot(), full);
    save('result-restore-check.json', {
      schema_version: 1,
      restored_snapshot: before,
      at_capacity_snapshot: full,
      capacity_denial: { intent_canonical: encodeResultIntent(denied), code: 'Overloaded' },
      receipt: known,
      view,
      carrier_calls: carrierCalls,
    });
  } finally {
    await x.close();
  }
}
function send(response: ServerResponse, status: number, value: unknown, maximum = 2048) {
  const bytes = Buffer.from(JSON.stringify(value));
  assert.ok(bytes.length <= maximum);
  response.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': String(bytes.length),
    'Cache-Control': 'no-store',
    Connection: 'close',
  });
  response.end(bytes);
}
async function body(request: IncomingMessage, maximum: number) {
  assert.equal(request.headers['content-type'], 'application/json');
  assert.equal(request.headers['content-encoding'], undefined);
  assert.equal(request.headers['transfer-encoding'], undefined);
  const length = request.headers['content-length'];
  assert.ok(typeof length === 'string' && /^[1-9][0-9]{0,4}$/.test(length));
  assert.ok(Number(length) <= maximum);
  const chunks: Buffer[] = [];
  let count = 0;
  for await (const raw of request) {
    const chunk = Buffer.from(raw as Uint8Array);
    count += chunk.length;
    assert.ok(count <= maximum);
    chunks.push(chunk);
  }
  assert.equal(count, Number(length));
  return new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks));
}
async function serve() {
  failureStage = 'serve';
  const x = composition(),
    reader = x.reader();
  let handlers = 0;
  const tasks = new Set<Promise<void>>();
  let server: Server;
  const handle = async (request: IncomingMessage, response: ServerResponse) => {
    if (handlers >= 4) {
      send(response, 429, { schemaVersion: 1, status: 'error', error: 'Overloaded' });
      return;
    }
    handlers++;
    try {
      if (request.method !== 'POST') throw new ResultReceiverError('InvalidCommand');
      if (request.url === '/v1/p2-result-receiver/native-read') {
        if (request.headers.authorization !== 'Bearer ' + env('NATIVE_B_BEARER'))
          throw new ResultReceiverError('AccessDenied');
        const text = await body(request, 256),
          query = JSON.parse(text) as { schemaVersion: number; deliveryId: string };
        assert.deepEqual(Object.keys(query).sort(), ['deliveryId', 'schemaVersion']);
        assert.equal(query.schemaVersion, 1);
        const view = await reader.native(env('NATIVE_B_BEARER'), query.deliveryId);
        send(response, 200, { schemaVersion: 1, status: view ? 'known' : 'missing', view }, 32768);
        return;
      }
      if (request.headers.authorization !== 'Bearer ' + env('PUBLISHER_TOKEN'))
        throw new ResultReceiverError('AccessDenied');
      const intent = parseResultIntent(await body(request, 16384));
      const receipt =
        request.url === '/v1/p2-result-receiver/accept'
          ? await x.receiver.accept(env('PUBLISHER_TOKEN'), intent)
          : request.url === '/v1/p2-result-receiver/find'
            ? await x.receiver.find(env('PUBLISHER_TOKEN'), intent)
            : null;
      if (
        !['/v1/p2-result-receiver/accept', '/v1/p2-result-receiver/find'].includes(
          request.url ?? '',
        )
      )
        throw new ResultReceiverError('InvalidCommand');
      send(response, 200, { schemaVersion: 1, status: receipt ? 'accepted' : 'missing', receipt });
    } catch (error) {
      const code = error instanceof ResultReceiverError ? error.code : 'InvalidCommand';
      const status =
        code === 'AccessDenied'
          ? 403
          : code === 'IdentityConflict'
            ? 409
            : code === 'Overloaded'
              ? 429
              : code === 'InvalidCommand'
                ? 400
                : 503;
      send(response, status, { schemaVersion: 1, status: 'error', error: code });
    } finally {
      handlers--;
    }
  };
  server = createServer(
    { maxHeaderSize: 4096, requestTimeout: 2000, headersTimeout: 1000 },
    (req, res) => {
      const task = handle(req, res);
      tasks.add(task);
      void task.then(
        () => tasks.delete(task),
        () => tasks.delete(task),
      );
    },
  );
  server.maxHeadersCount = 32;
  server.maxConnections = 8;
  server.keepAliveTimeout = 1;
  server.on('clientError', (_error, socket) => {
    socket.end('HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n');
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  save('serve-ready.json', {
    schema_version: 1,
    host: '127.0.0.1',
    port: address.port,
    receiver_id: setupRecord().receiver_id,
  });
  try {
    await new Promise<void>((resolve) => {
      process.once('SIGTERM', resolve);
      process.once('SIGINT', resolve);
    });
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
    await Promise.all([...tasks]);
    save('result-serve-final.json', {
      schema_version: 1,
      handlers,
      pending_tasks: tasks.size,
      snapshot: await snapshot(),
      carrier_calls: carrierCalls,
    });
    await x.close();
  }
}
async function cleanup() {
  failureStage = 'cleanup_guard';
  const original = setupRecord();
  const guard = await sql(true, async (c) => {
    const row = (
      await c.query(
        "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=$1",
        [schema],
      )
    ).rows[0];
    assert.ok(row);
    assert.equal(row.owner, 'continuity_migrator');
    assert.equal(row.marker, 'p2-channel-schema-v8');
    return row;
  });
  // Validation-only repeated upgrade proves the whole v8 catalog before its protected test teardown.
  assert.equal(await upgradeChannelSchemaV8(db(true)), original.receiver_id);
  const before = await snapshot(true);
  assert.equal(before.settings.receiver_id, original.receiver_id);
  await sql(true, async (c) => {
    await c.query(`DROP SCHEMA "${schema}" CASCADE`);
    assert.equal(
      (await c.query('SELECT 1 FROM pg_namespace WHERE nspname=$1', [schema])).rowCount,
      0,
    );
  });
  save('result-cleanup.json', {
    schema_version: 1,
    guard,
    original_receiver_id: original.receiver_id,
    before,
    namespace_absent: true,
  });
}
const mode = process.argv[2];
const safeMode = [
  'setup',
  'upgrade',
  'exercise',
  'commit-before-ack',
  'recover',
  'restore-check',
  'serve',
  'cleanup',
].includes(mode ?? '')
  ? mode!
  : 'invalid';
try {
  if (mode === 'setup') await setup();
  else if (mode === 'upgrade') await upgrade();
  else if (mode === 'exercise') await exercise();
  else if (mode === 'commit-before-ack') await commitBeforeAck();
  else if (mode === 'recover') await recover();
  else if (mode === 'restore-check') await restoreCheck();
  else if (mode === 'serve') await serve();
  else if (mode === 'cleanup') await cleanup();
  else throw new Error('invalid_fixture_mode');
  process.stdout.write(
    JSON.stringify({ schema_version: 1, mode, status: 'passed', carrier_calls: carrierCalls }) +
      '\n',
  );
} catch (error) {
  save('result-failure-' + safeMode + '.json', {
    schema_version: 1,
    mode: safeMode,
    stage: failureStage,
    expected_code: expectedCode,
    actual_code: actualCode,
    error_type: error instanceof ResultReceiverError ? 'ResultReceiverError' : 'FixtureError',
    code: error instanceof ResultReceiverError ? error.code : null,
    carrier_calls: carrierCalls,
  });
  process.exitCode = 1;
}
