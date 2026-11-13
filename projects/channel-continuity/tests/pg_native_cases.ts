/** Owned application fixture; public SDK product, explicit owner SQL inquiry only. */
import assert from 'node:assert/strict';
import { randomUUID, createHash } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';
import pg from 'pg';
import {
  ChannelInbox,
  SeededAccounts,
  type DatabaseSettings,
} from '@livekit-ecosystem/channel-continuity/postgres';
import {
  createFakeSmsIntegration,
  signFakeSms,
} from '@livekit-ecosystem/channel-continuity/security';
import {
  NativeChannelInbox,
  NativeGateway,
  NativeAgentHttpClient,
  createNativeIntegration,
  type NativeAcceptance,
} from '@livekit-ecosystem/channel-continuity/native';
import {
  ChannelDispatcher,
  type DispatchPorts,
  type OperationReceipt,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  installChannelSchema,
  upgradeChannelSchemaV2,
  upgradeChannelSchemaV3,
  upgradeChannelSchemaV4,
  upgradeChannelSchemaV5,
  upgradeChannelSchemaV6,
} from '@livekit-ecosystem/channel-continuity/migrations';
const MODES = [
  'install',
  'legacy-seed',
  'upgrade',
  'upgrade-interrupt',
  'seed',
  'serve',
  'replay',
  'expiry',
  'verify',
  'cleanup',
];
const mode = process.argv[2];
assert.ok(mode && MODES.includes(mode));
const owner = ['install', 'upgrade', 'upgrade-interrupt', 'verify', 'cleanup'].includes(mode);
function env(k: string) {
  const v = process.env[k];
  assert.ok(v && v.length <= 4096);
  return v;
}
const DIR = env('P2_NATIVE_DIRECTORY'),
  schema = env('P2_NATIVE_SCHEMA');
assert.match(schema, /^p2_native_[a-f0-9]{32}(?![\s\S])/);
assert.equal(
  process.env[owner ? 'P2_NATIVE_RUNTIME_PASSWORD' : 'P2_NATIVE_OWNER_PASSWORD'],
  undefined,
);
const fixture = JSON.parse(readFileSync(DIR + '/fixture.json', 'utf8')) as {
  schemaVersion: 1;
  providerScope: { tenantId: string; provider: string; providerAccountId: string };
  scope: { tenantId: string; accountId: string };
  caseId: string;
  conversationId: string;
  bindingId: string;
  roomId: string;
  participantId: string;
  agentId: string;
  accountToken: string;
  publisherToken: string;
  bindingToken: string;
  prepareToken: string;
  expiresAt: string;
  ids: { text: string; voice: string };
};
assert.equal(fixture.schemaVersion, 1);
const sha = (s: string) => createHash('sha256').update(s).digest('hex');
const uuid = (s: string) => {
  const h = sha(s);
  return (
    h.slice(0, 8) +
    '-' +
    h.slice(8, 12) +
    '-4' +
    h.slice(13, 16) +
    '-a' +
    h.slice(17, 20) +
    '-' +
    h.slice(20, 32)
  );
};
const AUX = {
  scope: { ...fixture.scope, accountId: fixture.scope.accountId + '-aux' },
  caseId: fixture.caseId + '-aux',
  conversationId: fixture.conversationId + '-aux',
  bindingId: uuid(fixture.bindingId + ':aux'),
  expiryBindingId: uuid(fixture.bindingId + ':expiry'),
  inputId: uuid(fixture.bindingId + ':aux-input'),
  expiryInputId: uuid(fixture.bindingId + ':expiry-input'),
  reservedInputId: uuid(fixture.bindingId + ':reserved-input'),
  token: sha('aux-account:' + fixture.accountToken),
  publisher: sha('aux-publisher:' + fixture.publisherToken),
  bearer: sha('aux-binding:' + fixture.bindingToken),
  expiryBearer: sha('expiry-binding:' + fixture.bindingToken),
};
function db(): DatabaseSettings {
  return {
    host: '127.0.0.1',
    port: Number(env('P2_NATIVE_PG_PORT')),
    database: 'livekit_lab',
    user: owner ? 'continuity_migrator' : 'livekit_lab',
    password: env(owner ? 'P2_NATIVE_OWNER_PASSWORD' : 'P2_NATIVE_RUNTIME_PASSWORD'),
    schema,
  };
}
function save(name: string, value: unknown) {
  writeFileSync(DIR + '/' + name, JSON.stringify(value) + '\n', { mode: 0o600 });
}
function load<T>(name: string): T {
  return JSON.parse(readFileSync(DIR + '/' + name, 'utf8')) as T;
}
function reached(name: string) {
  writeFileSync(DIR + '/' + name + '.reached', process.pid + '\n', { flag: 'wx', mode: 0o600 });
}
async function waitReleased(name: string, seconds = 15) {
  reached(name);
  const end = performance.now() + seconds * 1000;
  while (!existsSync(DIR + '/' + name + '.released')) {
    assert.ok(performance.now() < end, 'native_fixture_barrier_timeout');
    await delay(10);
  }
  assert.equal(readFileSync(DIR + '/' + name + '.released', 'utf8'), process.pid + '\n');
}
async function sql<T>(work: (client: pg.Client) => Promise<T>) {
  const c = new pg.Client({
    ...db(),
    ssl: false,
    application_name: 'p2-native-fixture-' + mode,
    connectionTimeoutMillis: 1000,
    query_timeout: 5000,
    options:
      '-c search_path=pg_catalog -c statement_timeout=4000 -c idle_in_transaction_session_timeout=5000',
  });
  try {
    await c.connect();
    return await work(c);
  } finally {
    await c.end();
  }
}
const q = (name: string) => '"' + schema + '"."' + name + '"';
function accounts() {
  return new SeededAccounts([
    {
      ...fixture.scope,
      token: fixture.accountToken,
      caseId: fixture.caseId,
      conversationId: fixture.conversationId,
    },
    { ...AUX.scope, token: AUX.token, caseId: AUX.caseId, conversationId: AUX.conversationId },
  ]);
}
function integration() {
  return createNativeIntegration(fixture.providerScope, [
    {
      token: fixture.publisherToken,
      scope: fixture.scope,
      caseId: fixture.caseId,
      conversationId: fixture.conversationId,
    },
    {
      token: AUX.publisher,
      scope: AUX.scope,
      caseId: AUX.caseId,
      conversationId: AUX.conversationId,
    },
  ]);
}
function inbox(hooks = {}) {
  return new NativeChannelInbox(db(), integration(), accounts(), hooks, () => undefined);
}
function normalPublication() {
  return {
    bindingId: fixture.bindingId,
    bearer: fixture.bindingToken,
    roomId: fixture.roomId,
    participantId: fixture.participantId,
    expiresAt: fixture.expiresAt,
  };
}
const AUX_INPUT = {
  schemaVersion: 1 as const,
  inputId: AUX.inputId,
  channel: 'web_chat' as const,
  body: 'investigate',
  roomId: fixture.roomId + '-aux',
  participantId: fixture.participantId + '-aux',
};
async function reject(work: () => Promise<unknown>, code: string) {
  await assert.rejects(work, (e: unknown) =>
    Boolean(e && typeof e === 'object' && 'code' in e && e.code === code),
  );
}
function ports(file = 'native-operations.json'): DispatchPorts {
  const rows = () =>
    existsSync(DIR + '/' + file)
      ? load<
          Array<{
            submission: unknown;
            canonicalPayload: string;
            payloadDigest: string;
            receipt: OperationReceipt;
          }>
        >(file)
      : [];
  return {
    cases: {
      async inspect(reference) {
        return { ...reference, revision: '1', source: 'synthetic_read_only' };
      },
    },
    agent: {
      async prepare(input) {
        return {
          kind: 'investigation',
          source: 'scripted',
          caseRevision: input.currentCase.revision,
        };
      },
    },
    operations: {
      capabilities: 'stable_idempotency_and_lookup',
      async lookup(v) {
        const row = rows().find((x) => x.receipt.operationKey === v.operationKey);
        if (!row) return { status: 'absent' };
        assert.deepEqual(row.receipt.scope, v.scope);
        assert.equal(row.receipt.payloadDigest, v.payloadDigest);
        return { status: 'accepted', receipt: row.receipt };
      },
      async accept(v) {
        const current = rows();
        let row = current.find((x) => x.receipt.operationKey === v.submission.operationKey);
        if (row) {
          assert.equal(row.canonicalPayload, v.canonicalPayload);
          assert.equal(row.payloadDigest, v.payloadDigest);
        } else {
          row = {
            submission: v.submission,
            canonicalPayload: v.canonicalPayload,
            payloadDigest: v.payloadDigest,
            receipt: {
              scope: v.submission.scope,
              operationKey: v.submission.operationKey,
              payloadDigest: v.payloadDigest,
              receiptId: randomUUID(),
            },
          };
          current.push(row);
          save(file, current);
        }
        return row.receipt;
      },
    },
  };
}
async function legacy(replay = false) {
  const provider = {
      tenantId: fixture.scope.tenantId,
      provider: 'fake_sms',
      providerAccountId: 'native-legacy',
    },
    key = Buffer.alloc(32, 0x61),
    seed = {
      ...AUX.scope,
      token: AUX.token,
      caseId: AUX.caseId,
      conversationId: AUX.conversationId,
    };
  const box = new ChannelInbox(
    db(),
    createFakeSmsIntegration(provider, key),
    new SeededAccounts([seed]),
    {},
    () => undefined,
  );
  const signed = (body: string, eventId: string) =>
    signFakeSms(
      {
        schemaVersion: 1,
        eventId,
        messageId: eventId,
        senderId: 'legacy-sender',
        body,
        occurredAt: '2030-01-01T00:00:00.000Z',
      },
      key,
      Math.floor(Date.now() / 1000),
      provider,
    );
  try {
    if (replay) {
      const original = load<{ receipt: { receiptId: string } }>('native-legacy-original.json');
      const input = signed('investigate', 'native-legacy-input');
      const accepted = await box.acceptSms(input.raw, input.headers);
      assert.equal(accepted.replayed, true);
      assert.equal(accepted.receipt.receiptId, original.receipt.receiptId);
      assert.deepEqual(
        JSON.parse(JSON.stringify(await box.inspect(AUX.token, accepted.receipt.receiptId))),
        original,
      );
      return;
    }
    const challenge = await box.createChallenge(AUX.token, 'legacy-sender'),
      link = signed('LINK ' + challenge.challengeId + ' ' + challenge.secret, 'native-legacy-link');
    await box.completeAssociation(link.raw, link.headers);
    const input = signed('investigate', 'native-legacy-input'),
      accepted = await box.acceptSms(input.raw, input.headers);
    save('native-legacy-original.json', await box.inspect(AUX.token, accepted.receipt.receiptId));
  } finally {
    await box.close();
  }
}
async function seed() {
  await legacy(true);
  const box = inbox();
  try {
    await box.bind(fixture.publisherToken, normalPublication());
    const grant = {
      bindingId: AUX.bindingId,
      bearer: AUX.bearer,
      roomId: AUX_INPUT.roomId,
      participantId: AUX_INPUT.participantId,
      expiresAt: fixture.expiresAt,
    };
    const published = await box.bind(AUX.publisher, grant);
    assert.deepEqual(await box.bind(AUX.publisher, grant), published);
    await reject(() => box.bind(fixture.accountToken, grant), 'AccessDenied');
    await reject(() => box.accept(fixture.accountToken, AUX_INPUT), 'AccessDenied');
    await reject(
      () => box.accept(AUX.bearer, { ...AUX_INPUT, roomId: 'wrong-room' }),
      'AccessDenied',
    );
    await reject(
      () => box.accept(AUX.bearer, { ...AUX_INPUT, participantId: 'wrong-participant' }),
      'AccessDenied',
    );
  } finally {
    await box.close();
  }
  let committed = false;
  const lost = inbox({
    afterAcceptCommit() {
      committed = true;
      throw new Error('synthetic_lost_ack');
    },
  });
  try {
    await reject(() => lost.accept(AUX.bearer, AUX_INPUT), 'AcknowledgementUnknown');
    assert.equal(committed, true);
  } finally {
    await lost.close();
  }
  const fresh = inbox();
  try {
    const ack = await fresh.accept(AUX.bearer, AUX_INPUT);
    assert.equal(ack.status, 'replayed');
    await reject(
      () => fresh.accept(AUX.bearer, { ...AUX_INPUT, body: 'changed' }),
      'IdentityConflict',
    );
    const stored = await fresh.inspect(AUX.token, ack.receiptId);
    save('native-aux-original.json', { ack, stored });
  } finally {
    await fresh.close();
  }
}
async function expiry() {
  const box = inbox();
  let prepare = 0,
    operation = 0;
  let arrived!: () => void, release!: () => void;
  const entered = new Promise<void>((r) => {
      arrived = r;
    }),
    held = new Promise<void>((r) => {
      release = r;
    });
  const base = ports('native-expiry-operations.json');
  const d = new ChannelDispatcher(
    db(),
    integration(),
    accounts(),
    {
      ...base,
      agent: {
        async prepare(v, s) {
          prepare++;
          return base.agent.prepare(v, s);
        },
      },
      operations: {
        ...base.operations,
        async accept(v, s) {
          operation++;
          arrived();
          await held;
          return base.operations.accept(v, s);
        },
      },
    },
    { timeoutMs: 5000, cleanupTimeoutMs: 2000 },
  );
  let admitted: Promise<unknown> | undefined;
  try {
    const now = await sql(
      async (c) => (await c.query('SELECT clock_timestamp() AS now')).rows[0]!.now as Date,
    );
    const expiryAt = new Date(now.getTime() + 1100).toISOString();
    const grant = {
      bindingId: AUX.expiryBindingId,
      bearer: AUX.expiryBearer,
      roomId: AUX_INPUT.roomId + '-expiry',
      participantId: AUX_INPUT.participantId + '-expiry',
      expiresAt: expiryAt,
    };
    await box.bind(AUX.publisher, grant);
    const body = { ...AUX_INPUT, roomId: grant.roomId, participantId: grant.participantId };
    const ack = await box.accept(AUX.expiryBearer, { ...body, inputId: AUX.expiryInputId });
    const reverseAck = await box.accept(AUX.expiryBearer, {
      ...body,
      inputId: AUX.reservedInputId,
    });
    save('native-expiry-original.json', {
      ack,
      reverseAck,
      grant: {
        bindingId: grant.bindingId,
        roomId: grant.roomId,
        participantId: grant.participantId,
        expiresAt: grant.expiresAt,
      },
    });
    await reject(
      () => box.bind(AUX.publisher, { ...grant, bindingId: randomUUID(), bearer: sha('fourth') }),
      'Overloaded',
    );
    await box.bind(fixture.publisherToken, normalPublication());
    admitted = d.step(AUX.token, reverseAck.receiptId);
    let admissionTimer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        entered,
        admitted.then(
          async (value) => {
            if (operation > 0) return value;
            const result = value as { status: string };
            const current = await d.inspect(AUX.token, reverseAck.receiptId);
            const databaseNow = await sql(
              async (c) => (await c.query('SELECT clock_timestamp() AS now')).rows[0]!.now as Date,
            );
            save('native-expiry-admission-diagnostic.json', {
              schemaVersion: 1,
              stage: 'before_operation',
              resultStatus: result.status,
              prepareCalls: prepare,
              operationCalls: operation,
              expiryAt,
              databaseNow: databaseNow.toISOString(),
              observation: current,
            });
            throw Error('native_operation_not_entered');
          },
          async (error) => {
            if (operation > 0) throw error;
            const code =
              error &&
              typeof error === 'object' &&
              'code' in error &&
              typeof error.code === 'string'
                ? error.code
                : 'unknown';
            save('native-expiry-admission-diagnostic.json', {
              schemaVersion: 1,
              stage: 'admission_rejected',
              code,
              prepareCalls: prepare,
              operationCalls: operation,
            });
            throw Error('native_admission_rejected');
          },
        ),
        new Promise<never>((_, reject) => {
          admissionTimer = setTimeout(() => reject(Error('native_admission_deadline')), 4000);
        }),
      ]);
    } finally {
      if (admissionTimer) clearTimeout(admissionTimer);
    }
    // Actual call follows the persisted possible marker before the parent's owner lock.
    await waitReleased('expiry_ready');
    const promise = d.step(AUX.token, ack.receiptId);
    reached('expiry_waiting');
    const result = await promise;
    assert.equal(result.status, 'blocked');
    assert.equal(prepare, 1);
    assert.equal(operation, 1);
    const after = await sql(
      async (c) => (await c.query('SELECT clock_timestamp() AS now')).rows[0]!.now as Date,
    );
    assert.ok(after.getTime() >= Date.parse(expiryAt));
    release();
    const reservedResult = await admitted;
    assert.equal((reservedResult as { status: string }).status, 'dispatched');
    await reject(
      () => box.accept(AUX.expiryBearer, { ...body, inputId: AUX.expiryInputId }),
      'AccessDenied',
    );
    save('native-expiry-proof.json', {
      expiryAt,
      observedAfter: after.toISOString(),
      result,
      reservedResult,
      prepareCalls: prepare,
      operationCalls: operation,
      expiredNewPrepareCalls: 0,
      expiredNewOperationCalls: 0,
      blockedHistory: await box.inspect(AUX.token, ack.receiptId),
      admittedHistory: await box.inspect(AUX.token, reverseAck.receiptId),
    });
  } finally {
    release();
    if (admitted) await Promise.allSettled([admitted]);
    await d.close();
    await box.close();
  }
}

async function replay() {
  const box = inbox();
  try {
    const original = load<{ ack: NativeAcceptance; stored: unknown }>('native-aux-original.json'),
      next = await box.accept(AUX.bearer, AUX_INPUT);
    assert.equal(next.status, 'replayed');
    assert.deepEqual({ ...next, status: 'replayed' }, { ...original.ack, status: 'replayed' });
    assert.deepEqual(
      JSON.parse(JSON.stringify(await box.inspect(AUX.token, next.receiptId))),
      original.stored,
    );
    save('native-aux-replay.json', next);
  } finally {
    await box.close();
  }
}
async function serving() {
  const endpoint = load<{ host: '127.0.0.1'; port: number }>('python-endpoint.json'),
    client = new NativeAgentHttpClient(endpoint, 'Bearer ' + fixture.prepareToken, [
      {
        bindingId: fixture.bindingId,
        scope: fixture.scope,
        caseId: fixture.caseId,
        conversationId: fixture.conversationId,
      },
    ]);
  const base = ports(),
    gateway = new NativeGateway({
      database: db(),
      integration: integration(),
      accounts: [
        {
          ...fixture.scope,
          token: fixture.accountToken,
          caseId: fixture.caseId,
          conversationId: fixture.conversationId,
        },
      ],
      ports: { ...base, agent: client.port },
      options: { observer: () => undefined },
    });
  try {
    save('node-endpoint.json', await gateway.listen());
    reached('node_ready');
    await new Promise<void>((resolve) => {
      process.once('SIGTERM', resolve);
      process.once('SIGINT', resolve);
    });
  } finally {
    await gateway.close();
    await client.close();
  }
  const full = gateway.metrics(),
    keys = [
      'accepted',
      'replayed',
      'dispatched',
      'active',
      'intakes',
      'sockets',
      'handlers',
      'driver',
      'observerPending',
    ];
  for (const key of keys)
    assert.ok(Object.hasOwn(full, key) && Number.isSafeInteger(full[key]) && full[key]! >= 0);
  const selected = Object.fromEntries(keys.map((k) => [k, full[k]!]));
  save('node-private-proof.json', { gateway: full, agentClient: client.metrics() });
  const report = {
    schemaVersion: 1,
    status: 'passed',
    mode,
    cleanupComplete: Object.values(selected)
      .slice(3)
      .every((v) => v === 0),
    nodeVersion: process.versions.node,
    metrics: selected,
  };
  save('node-terminal.json', report);
  return report;
}
async function verify() {
  return sql(async (client) => {
    const metadata = (await client.query('SELECT * FROM ' + q('schema_metadata'))).rows;
    assert.equal(metadata[0]!.version, 6);
    const input = (
      await client.query(
        'SELECT i.*,p.operation_key,p.state FROM ' +
          q('inbox') +
          ' i JOIN ' +
          q('processing_intents') +
          ' p USING(receipt_id) ORDER BY i.receipt_id',
      )
    ).rows;
    assert.equal(input.length, 6);
    const native = input.filter(
        (r) => r.provider === 'livekit' && r.account_id === fixture.scope.accountId,
      ),
      aux = input.filter((r) => r.provider === 'livekit' && r.account_id === AUX.scope.accountId),
      legacy = input.filter((r) => r.provider === 'fake_sms');
    assert.equal(native.length, 2);
    assert.equal(aux.length, 3);
    assert.equal(legacy.length, 1);
    const plans = (
      await client.query('SELECT * FROM ' + q('dispatch_plans') + ' ORDER BY receipt_id')
    ).rows;
    assert.equal(plans.length, 3);
    const normalPlans = plans.filter((p) => native.some((r) => r.receipt_id === p.receipt_id));
    assert.equal(normalPlans.length, 2);
    const operations = load<
      Array<{
        submission: {
          operationKey: string;
          message: { receiptId: string; eventId: string; senderId: string; body: string };
          caseId: string;
          conversationId: string;
          scope: unknown;
        };
        canonicalPayload: string;
        payloadDigest: string;
        receipt: OperationReceipt;
      }>
    >('native-operations.json');
    assert.equal(operations.length, 2);
    for (const row of native) {
      assert.equal(row.state, 'dispatched');
      const e = JSON.parse(row.canonical_payload);
      assert.equal(e.senderId, fixture.bindingId);
      assert.equal(e.caseId, fixture.caseId);
      assert.equal(e.conversationId, fixture.conversationId);
      assert.equal(e.accountScope.accountId, fixture.scope.accountId);
      assert.equal(e.eventId, e.messageId);
      assert.ok([fixture.ids.text, fixture.ids.voice].includes(e.eventId));
      const plan = plans.find((p) => p.receipt_id === row.receipt_id);
      assert.ok(plan);
      const op = operations.find((p) => p.submission.operationKey === row.operation_key);
      assert.ok(op);
      assert.equal(op.submission.message.receiptId, row.receipt_id);
      assert.equal(op.submission.message.eventId, e.eventId);
      assert.equal(op.submission.message.body, e.body);
      assert.equal(op.payloadDigest, sha(op.canonicalPayload));
      assert.equal(op.canonicalPayload, plan.payload_json);
      assert.equal(op.payloadDigest, plan.payload_digest);
      assert.equal(op.receipt.operationKey, row.operation_key);
    }
    const old = load<{ receipt: { receiptId: string }; operationKey: string; event: unknown }>(
      'native-legacy-original.json',
    );
    assert.equal(legacy[0]!.receipt_id, old.receipt.receiptId);
    assert.equal(legacy[0]!.operation_key, old.operationKey);
    assert.deepEqual(JSON.parse(legacy[0]!.wire_json), old.event);
    const original = load<{ ack: NativeAcceptance; stored: { event: unknown } }>(
        'native-aux-original.json',
      ),
      a = aux.find((r) => r.event_id === AUX.inputId);
    assert.ok(a);
    assert.equal(a.receipt_id, original.ack.receiptId);
    assert.equal(a.operation_key, original.ack.operationKey);
    assert.deepEqual(JSON.parse(a.wire_json), original.stored.event);
    const expiry = load<{ ack: NativeAcceptance; reverseAck: NativeAcceptance; grant: unknown }>(
      'native-expiry-original.json',
    );
    const auxOps = load<
      Array<{
        submission: { operationKey: string; message: { receiptId: string } };
        canonicalPayload: string;
        payloadDigest: string;
        receipt: OperationReceipt;
      }>
    >('native-expiry-operations.json');
    assert.equal(auxOps.length, 1);
    const reserved = aux.find((r) => r.receipt_id === expiry.reverseAck.receiptId),
      blocked = aux.find((r) => r.receipt_id === expiry.ack.receiptId);
    assert.ok(reserved && blocked);
    assert.equal(reserved.state, 'dispatched');
    assert.equal(blocked.state, 'blocked');
    assert.equal(auxOps[0]!.receipt.operationKey, reserved.operation_key);
    assert.equal(auxOps[0]!.submission.message.receiptId, reserved.receipt_id);
    const auxPlan = plans.find((p) => p.receipt_id === reserved.receipt_id);
    assert.ok(auxPlan);
    assert.equal(auxPlan.payload_json, auxOps[0]!.canonicalPayload);
    assert.equal(auxPlan.payload_digest, auxOps[0]!.payloadDigest);
    const bindings = (
      await client.query('SELECT * FROM ' + q('native_bindings') + ' ORDER BY binding_id')
    ).rows;
    assert.equal(bindings.length, 3);
    const snapshot: Record<string, unknown> = {};
    const tables = (
      await client.query('SELECT tablename FROM pg_tables WHERE schemaname=$1 ORDER BY tablename', [
        schema,
      ])
    ).rows;
    for (const row of tables) {
      const name = row.tablename as string;
      assert.match(name, /^[a-z_]+$/);
      snapshot[name] = (
        await client.query(
          'SELECT to_jsonb(t) AS row FROM ' + q(name) + ' t ORDER BY to_jsonb(t)::text',
        )
      ).rows.map((r) => r.row);
    }
    save('native-owner-proof.json', {
      input,
      plans,
      operations,
      bindings,
      auxOriginal: original,
      auxOperations: auxOps,
      expiry,
      legacyOriginal: old,
      snapshot,
    });
    return {
      schemaVersionObserved: 6,
      nativeInputs: 2,
      auxInputs: 3,
      legacyInputs: 1,
      processingIntents: 6,
      normalPreparedPlans: 2,
      normalOperationAcceptances: 2,
      auxPreparedPlans: 1,
      auxOperationAcceptances: 1,
      nativeBindings: 3,
      exactIdentityJoins: true,
      legacyPreserved: true,
      auxReplayPreserved: true,
    };
  });
}
async function run() {
  if (mode === 'install') {
    await installChannelSchema(db());
    await upgradeChannelSchemaV2(db());
    await upgradeChannelSchemaV3(db());
    await upgradeChannelSchemaV4(db());
    await upgradeChannelSchemaV5(db());
  } else if (mode === 'legacy-seed') await legacy();
  else if (mode === 'upgrade-interrupt') {
    await upgradeChannelSchemaV6(
      db(),
      { maxBindings: 3 },
      { harnessAfterTables: () => waitReleased('upgrade_ddl') },
    );
    throw Error('expected_owned_interruption');
  } else if (mode === 'upgrade') {
    await sql(async (c) => {
      const row = (await c.query('SELECT version FROM ' + q('schema_metadata'))).rows[0];
      assert.equal(row.version, 5);
      assert.equal(
        (
          await c.query(
            "SELECT count(*)::integer AS count FROM pg_tables WHERE schemaname=$1 AND tablename IN ('native_settings','native_bindings')",
            [schema],
          )
        ).rows[0].count,
        0,
      );
      const old = load<{ receipt: { receiptId: string }; event: unknown }>(
        'native-legacy-original.json',
      );
      assert.deepEqual(
        JSON.parse(
          (
            await c.query('SELECT wire_json FROM ' + q('inbox') + ' WHERE receipt_id=$1', [
              old.receipt.receiptId,
            ])
          ).rows[0].wire_json,
        ),
        old.event,
      );
    });
    await upgradeChannelSchemaV6(db(), { maxBindings: 3 });
    await upgradeChannelSchemaV6(db(), { maxBindings: 3 });
    await installChannelSchema(db());
    await upgradeChannelSchemaV2(db());
    await upgradeChannelSchemaV3(db());
    await upgradeChannelSchemaV4(db());
    await upgradeChannelSchemaV5(db());
  } else if (mode === 'seed') await seed();
  else if (mode === 'expiry') await expiry();
  else if (mode === 'replay') await replay();
  else if (mode === 'serve') return serving();
  else if (mode === 'verify')
    return {
      schemaVersion: 1,
      status: 'passed',
      mode,
      cleanupComplete: true,
      nodeVersion: process.versions.node,
      ...(await verify()),
    };
  else if (mode === 'cleanup')
    await sql(async (c) => {
      const row = (
        await c.query(
          "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=$1",
          [schema],
        )
      ).rows[0];
      if (row) {
        assert.equal(row.owner, 'continuity_migrator');
        assert.match(row.marker, /^p2-channel-schema-v[1-6](?![\s\S])/);
        await c.query('DROP SCHEMA "' + schema + '" CASCADE');
      }
    });
  return {
    schemaVersion: 1,
    status: 'passed',
    mode,
    cleanupComplete: true,
    nodeVersion: process.versions.node,
  };
}
try {
  console.log(JSON.stringify(await run()));
} catch (error) {
  const e = error instanceof Error ? error : undefined;
  const state = e && Object.getOwnPropertyDescriptor(e, 'code');
  const code =
    state &&
    'value' in state &&
    typeof state.value === 'string' &&
    /^[A-Z0-9]{5}$/.test(state.value)
      ? state.value
      : null;
  const frames = (e?.stack ?? '')
    .split('\n')
    .flatMap((line) => {
      const m = /pg_native_cases\.js:(\d+):\d+/.exec(line);
      return m ? [{ file: 'pg_native_cases.js', line: Number(m[1]) }] : [];
    })
    .slice(0, 4);
  save('native-failure-' + mode + '.json', {
    type:
      e instanceof assert.AssertionError
        ? 'AssertionError'
        : e?.name === 'Error'
          ? 'Error'
          : 'DependencyError',
    sqlState: code,
    frames,
  });
  console.log(
    JSON.stringify({
      schemaVersion: 1,
      status: 'failed',
      mode,
      cleanupComplete: false,
      nodeVersion: process.versions.node,
      code: 'native_fixture_failed',
    }),
  );
  process.exitCode = 1;
}
