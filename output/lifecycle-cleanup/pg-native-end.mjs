/** Explicit isolated PG fixture. Public P2 APIs + a durable cooperating file port;
 * no real P1/SFU/provider claim. Owner install/verify/cleanup run as separate roles. */
import assert from 'node:assert/strict';
import { randomUUID, randomBytes, createHash } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { request } from 'node:http';
import { createRequire } from 'node:module';
import { setTimeout as delay } from 'node:timers/promises';
import {
  NativeGateway, NativeChannelInbox, createNativeIntegration,
} from '../../projects/channel-continuity/dist/native.js';
import { SeededAccounts, ChannelError } from '../../projects/channel-continuity/dist/postgres.js';
import * as migration from '../../projects/channel-continuity/dist/migrations.js';
const require = createRequire(new URL('../../projects/channel-continuity/package.json', import.meta.url));
const { Client } = require('pg');
const mode = process.argv[2];
assert.ok(['install', 'run', 'verify', 'cleanup'].includes(mode));
const config = JSON.parse(readFileSync(process.env.P2_END_CONFIG, 'utf8'));
const db = config.database, dir = config.directory;
assert.match(db.schema, /^p2_lifecycle_[a-f0-9]{32}$/);
assert.equal(db.host, '127.0.0.1');
assert.equal(db.database, 'livekit_lab');
assert.equal(db.user, mode === 'run' ? 'livekit_lab' : 'continuity_migrator');
const q = (n) => '"' + db.schema + '"."' + n + '"';
const save = (name, value) => writeFileSync(dir + '/' + name, JSON.stringify(value) + '\n', { mode: 0o600 });
const load = (name) => JSON.parse(readFileSync(dir + '/' + name, 'utf8'));
async function sql(fn) {
  const c = new Client({ ...db, ssl: false, connectionTimeoutMillis: 1000, query_timeout: 5000,
    application_name: 'lifecycle-native-end', options: '-c statement_timeout=4000 -c idle_in_transaction_session_timeout=5000' });
  try { await c.connect(); return await fn(c); } finally { await c.end(); }
}
function gate() { let release; const promise = new Promise((r) => { release = r; }); return { promise, release }; }
async function until(fn, budget = 3000) {
  const end = performance.now() + budget;
  while (!(await fn())) { assert.ok(performance.now() < end, 'bounded_condition_timeout'); await delay(10); }
}
async function post(port, bearer, input) {
  const raw = Buffer.from(JSON.stringify(input));
  return await new Promise((resolve, reject) => {
    const r = request({ host: '127.0.0.1', port, method: 'POST', path: '/v1/native/accept',
      headers: { authorization: 'Bearer ' + bearer, 'content-type': 'application/json',
        'content-length': raw.length, connection: 'close' } }, (response) => {
      const chunks = []; response.on('data', (v) => chunks.push(v));
      response.on('end', () => resolve({ status: response.statusCode,
        body: JSON.parse(Buffer.concat(chunks).toString()) }));
    }); r.on('error', reject); r.end(raw);
  });
}
async function install() {
  assert.equal(existsSync(dir + '/fixture.json'), false, 'fresh_private_fixture_required');
  await migration.installChannelSchema(db, { maxInbox: 16, maxChallenges: 16, maxAssociations: 16, maxSenders: 16 });
  await migration.upgradeChannelSchemaV2(db, { maxActive: 2, maxAttempts: 2, leaseMs: 8000, retryDelayMs: 50 });
  for (const n of [3, 4, 5]) await migration['upgradeChannelSchemaV' + n](db);
  await migration.upgradeChannelSchemaV6(db, { maxBindings: 8 });
  save('fixture.json', { provider: { tenantId: 'lifecycle_tenant', provider: 'livekit', providerAccountId: 'native_end' },
    scope: { tenantId: 'lifecycle_tenant', accountId: 'lifecycle_account' }, caseId: 'case', conversationId: 'conversation',
    account: randomBytes(32).toString('base64url'), publisher: randomBytes(32).toString('base64url') });
}
async function run() {
  const f = load('fixture.json'), proofs = [], ledger = new Map();
  const integration = createNativeIntegration(f.provider, [{ token: f.publisher, scope: f.scope,
    caseId: f.caseId, conversationId: f.conversationId }]);
  const seeds = [{ token: f.account, ...f.scope, caseId: f.caseId, conversationId: f.conversationId }];
  const box = new NativeChannelInbox(db, integration, new SeededAccounts(seeds), {}, () => {});
  const end = performance.now() + 60000;
  try {
    for (const name of ['pending_sql_fence', 'held_possible_call', 'lost_operation_ack', 'revoked_pending', 'expired_pending', 'exhausted_initial']) {
      assert.ok(performance.now() < end, 'whole_fixture_deadline');
      const binding = randomUUID(), bearer = randomBytes(32).toString('base64url'), inputId = randomUUID();
      const expiresAt = new Date(Date.now() + (name === 'expired_pending' ? 2000 : 60000)).toISOString();
      const publication = { bindingId: binding, bearer, roomId: 'room_' + name, participantId: 'caller', expiresAt };
      await box.bind(f.publisher, publication);
      const input = { schemaVersion: 1, inputId, channel: 'web_chat', body: 'investigate ' + name,
        roomId: publication.roomId, participantId: 'caller' };
      const ackGate = gate(), callGate = gate();
      let ackSeen = false, calls = 0, lookups = 0, prepares = 0, entered = false;
      const ports = {
        cases: { async inspect(ref) { return { ...ref, revision: '1', source: 'synthetic_read_only' }; } },
        agent: { async prepare(value) { prepares++; if (name === 'exhausted_initial') throw new ChannelError('DispatchUnavailable');
          return { kind: 'investigation', source: 'scripted', caseRevision: value.currentCase.revision }; } },
        operations: { capabilities: 'stable_idempotency_and_lookup',
          async lookup(value) { lookups++; const stored = ledger.get(value.operationKey);
            if (!stored) return { status: 'absent' };
            assert.equal(stored.receipt.payloadDigest, value.payloadDigest);
            return { status: 'accepted', receipt: stored.receipt }; },
          async accept(value) { calls++; entered = true;
            const receipt = { scope: value.submission.scope, operationKey: value.submission.operationKey,
              payloadDigest: value.payloadDigest, receiptId: randomUUID() };
            assert.equal(ledger.has(receipt.operationKey), false, 'no_duplicate_external_accept');
            ledger.set(receipt.operationKey, { receipt, canonicalPayload: value.canonicalPayload });
            save('external-receipts.json', [...ledger.values()]);
            if (name === 'held_possible_call') await callGate.promise;
            if (name === 'lost_operation_ack') throw new ChannelError('DispatchUnavailable');
            return receipt;
          } },
      };
      const g = new NativeGateway({ database: db, integration, accounts: seeds, ports,
        options: { pollMs: 20, idlePollMs: 100, dispatchTimeoutMs: 1500, cleanupMs: 5000,
          observer: () => {}, harnessAfterAcknowledgement: async () => { ackSeen = true; await ackGate.promise; } } });
      let blocker;
      try {
        const endpoint = await g.listen();
        if (name === 'pending_sql_fence') {
          blocker = new Client({ ...db, ssl: false, connectionTimeoutMillis: 1000, query_timeout: 5000 });
          await blocker.connect(); await blocker.query('BEGIN');
          await blocker.query('SELECT singleton FROM ' + q('admission') + ' WHERE singleton FOR UPDATE');
        }
        const accepting = post(endpoint.port, bearer, input);
        let fence, fenceSettled = false;
        if (blocker) {
          await until(() => sql(async (c) => (await c.query("SELECT count(*)::int AS n FROM pg_stat_activity WHERE usename=current_user AND pid<>pg_backend_pid() AND wait_event_type='Lock' AND query LIKE '%admission%'" )).rows[0].n > 0));
          fence = g.fenceNativeInput(bearer).then(() => { fenceSettled = true; });
          await delay(20); assert.equal(fenceSettled, false, 'fence_waits_actual_sql_owner');
          assert.equal((await post(endpoint.port, bearer, input)).body.code, 'closed');
          await blocker.query('COMMIT'); await blocker.end(); blocker = undefined;
        }
        const ack = (await accepting).body;
        assert.equal(ack.status, 'accepted'); await until(() => ackSeen);
        const original = await box.inspect(f.account, ack.receiptId);
        assert.equal(original.processingState, 'pending'); assert.equal(prepares, 0);
        await (fence ?? g.fenceNativeInput(bearer));
        assert.equal((await post(endpoint.port, bearer, input)).body.code, 'closed');
        if (name === 'revoked_pending') await box.revoke(f.publisher, binding);
        if (name === 'expired_pending') await delay(Math.max(0, Date.parse(expiresAt) - Date.now() + 25));
        ackGate.release();
        if (name === 'held_possible_call') {
          await until(() => entered);
          const observed = await g.inspectDispatch(f.account, ack.receiptId);
          assert.equal(observed.possibleExternal, true); assert.notEqual(observed.state, 'dispatched');
          let drained = false;
          const draining = g.drainNativeInput(f.account, binding, bearer).then(() => { drained = true; });
          await delay(50); assert.equal(drained, false, 'possible_call_owner_still_active');
          callGate.release(); await draining;
        } else if (['revoked_pending', 'expired_pending', 'exhausted_initial'].includes(name)) {
          await until(async () => ['blocked', 'exhausted'].includes((await g.inspectDispatch(f.account, ack.receiptId)).state));
          await assert.rejects(() => g.drainNativeInput(f.account, binding, bearer), (e) => e.code === 'cleanup_incomplete');
          assert.equal(calls, 0);
        } else await g.drainNativeInput(f.account, binding, bearer);
        const observed = await g.inspectDispatch(f.account, ack.receiptId);
        const retained = await box.inspect(f.account, ack.receiptId);
        assert.deepEqual(retained.receipt, original.receipt);
        assert.equal(retained.operationKey, original.operationKey);
        assert.deepEqual(retained.event, original.event);
        if (!['revoked_pending', 'expired_pending', 'exhausted_initial'].includes(name)) {
          assert.equal(observed.state, 'dispatched'); assert.equal(calls, 1);
          assert.equal(observed.externalReceiptId, ledger.get(ack.operationKey).receipt.receiptId);
          await box.revoke(f.publisher, binding);
        }
        proofs.push({ name, inputId, bindingId: binding, receiptId: ack.receiptId,
          operationKey: ack.operationKey, state: observed.state, possibleExternal: observed.possibleExternal,
          externalReceiptId: observed.externalReceiptId, canonicalDigest: createHash('sha256').update(JSON.stringify(retained.event)).digest('hex'),
          calls, lookups, prepares, actualSqlWaiterObserved: name === 'pending_sql_fence' });
      } finally {
        ackGate.release(); callGate.release();
        if (blocker) { await blocker.query('ROLLBACK'); await blocker.end(); }
        await g.close();
      }
    }
  } finally { await box.close(); }
  save('proof.json', { schemaVersion: 1, scenarios: proofs, externalLogicalAcceptances: ledger.size,
    cleanupComplete: true, limits: 'Real P2 PostgreSQL/HTTP; cooperating durable file port, not real P1/RTC/provider.' });
  return { scenarios: proofs.length, externalLogicalAcceptances: ledger.size, cleanupComplete: true };
}
async function verify() {
  const p = load('proof.json'); assert.equal(p.scenarios.length, 6);
  await sql(async (c) => {
    const rows = (await c.query('SELECT i.receipt_id,i.event_id,i.wire_json,p.operation_key,p.state,p.possible_external,p.external_receipt_id FROM ' + q('inbox') + ' i JOIN ' + q('processing_intents') + ' p USING(receipt_id)')).rows;
    assert.equal(rows.length, 6);
    for (const proof of p.scenarios) {
      const row = rows.find((r) => r.receipt_id === proof.receiptId); assert.ok(row);
      assert.equal(row.event_id, proof.inputId); assert.equal(row.operation_key, proof.operationKey);
      assert.equal(row.state, proof.state); assert.equal(row.external_receipt_id, proof.externalReceiptId);
      assert.equal(createHash('sha256').update(JSON.stringify(JSON.parse(row.wire_json))).digest('hex'), proof.canonicalDigest);
    }
    assert.equal((await c.query('SELECT count(*)::int AS n FROM ' + q('processing_intents') + ' WHERE claim_owner IS NOT NULL')).rows[0].n, 0);
  });
  assert.equal(load('external-receipts.json').length, 3);
  return { reconciledOriginalInputs: 6, independentExternalReceipts: 3 };
}
try {
  const result = mode === 'install' ? await install() : mode === 'run' ? await run() : mode === 'verify' ? await verify() : await sql((c) => c.query('DROP SCHEMA "' + db.schema + '" CASCADE'));
  console.log(JSON.stringify({ schemaVersion: 1, mode, status: 'passed', ...(mode === 'cleanup' ? { cleanupComplete: true } : result) }));
} catch (error) {
  const frame = typeof error?.stack === 'string'
    ? error.stack.split('\n').find((line) => line.includes('/output/lifecycle-cleanup/pg-native-end.mjs:'))?.trim()
    : undefined;
  console.error(JSON.stringify({ schemaVersion: 1, mode, status: 'failed', code: 'lifecycle_assertion_failed', frame }));
  process.exitCode = 1;
}
