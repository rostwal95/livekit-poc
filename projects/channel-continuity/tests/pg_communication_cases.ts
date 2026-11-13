/** Owned local application fixture; product uses public SDK, SQL is explicitly owner-only. */
import assert from 'node:assert/strict';
import { AssertionError } from 'node:assert';
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync, renameSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';
import pg from 'pg';
import {
  ChannelInbox,
  ChannelError,
  SeededAccounts,
  type DatabaseSettings,
  type StoredMessage,
} from '@livekit-ecosystem/channel-continuity/postgres';
import {
  createFakeSmsIntegration,
  signFakeSms,
} from '@livekit-ecosystem/channel-continuity/security';
import {
  createNativeIntegration,
  NativeChannelInbox,
  NativeAgentHttpClient,
  type NativeAcceptance,
} from '@livekit-ecosystem/channel-continuity/native';
import { GatewayError } from '@livekit-ecosystem/channel-continuity/gateway';
import {
  CommunicationInbox,
  CommunicationGateway,
  createCommunicationIntegration,
  reduceCommunicationEvidence,
  type ResponseAnchor,
  type ResponseReceipt,
  type SdkObservation,
  type BrowserObservation,
  type ObservationReceipt,
} from '@livekit-ecosystem/channel-continuity/communication';
import {
  ChannelDispatcher,
  type DispatchPorts,
  type OperationReceipt,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  ChannelOutbox,
  type SendRequest,
  type CarrierSendPort,
} from '@livekit-ecosystem/channel-continuity/outbox';
import {
  CallbackInbox,
  createFakeSmsCallbackIntegration,
  signFakeSmsCallback,
} from '@livekit-ecosystem/channel-continuity/callbacks';
import {
  installChannelSchema,
  upgradeChannelSchemaV2,
  upgradeChannelSchemaV3,
  upgradeChannelSchemaV4,
  upgradeChannelSchemaV5,
  upgradeChannelSchemaV6,
  upgradeChannelSchemaV7,
} from '@livekit-ecosystem/channel-continuity/migrations';
const MODES = [
  'install',
  'legacy-seed',
  'upgrade-hold',
  'upgrade',
  'expiry',
  'exercise',
  'crash',
  'replay',
  'drift',
  'verify',
  'cleanup',
  'media-install',
  'media-seed',
  'media-serve',
  'media-verify',
  'media-cleanup',
];
const mode = process.argv[2];
assert.ok(process.argv.length === 3 && mode && MODES.includes(mode));
const owner = [
  'install',
  'upgrade-hold',
  'upgrade',
  'verify',
  'cleanup',
  'media-install',
  'media-verify',
  'media-cleanup',
].includes(mode);
function env(key: string) {
  const v = process.env[key];
  assert.ok(v && v.length <= 4096);
  return v;
}
const DIR = env('P2_COMM_DIRECTORY'),
  schema = env('P2_COMM_SCHEMA');
assert.match(schema, /^p2_playback_[a-f0-9]{32}(?![\s\S])/);
assert.equal(process.env[owner ? 'P2_COMM_RUNTIME_PASSWORD' : 'P2_COMM_OWNER_PASSWORD'], undefined);
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
const communication = JSON.parse(readFileSync(DIR + '/communication.json', 'utf8')) as {
  schemaVersion: 1;
  publisherToken: string;
  sdkToken: string;
  browserToken: string;
  inputIds: [string, string, string];
};
assert.equal(fixture.schemaVersion, 1);
assert.equal(communication.schemaVersion, 1);
assert.equal(
  new Set([
    fixture.accountToken,
    fixture.publisherToken,
    fixture.bindingToken,
    fixture.prepareToken,
    communication.publisherToken,
    communication.sdkToken,
    communication.browserToken,
  ]).size,
  7,
);
const sha = (v: string) => createHash('sha256').update(v).digest('hex');
function id(v: string) {
  const h = sha(fixture.bindingId + ':' + v);
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
}
function db(): DatabaseSettings {
  return {
    host: '127.0.0.1',
    port: Number(env('P2_COMM_PG_PORT')),
    database: 'livekit_lab',
    user: owner ? 'continuity_migrator' : 'livekit_lab',
    password: env(owner ? 'P2_COMM_OWNER_PASSWORD' : 'P2_COMM_RUNTIME_PASSWORD'),
    schema,
  };
}
function save(name: string, value: unknown) {
  const path = DIR + '/' + name,
    temp = path + '.pending';
  writeFileSync(temp, JSON.stringify(value) + '\n', { flag: 'wx', mode: 0o600 });
  renameSync(temp, path);
}
function load<T>(name: string): T {
  return JSON.parse(readFileSync(DIR + '/' + name, 'utf8')) as T;
}
function reached(name: string) {
  writeFileSync(DIR + '/' + name + '.reached', process.pid + '\n', { flag: 'wx', mode: 0o600 });
}
async function barrier(name: string, ms = 10000) {
  reached(name);
  const end = performance.now() + ms;
  while (!existsSync(DIR + '/' + name + '.released')) {
    assert.ok(performance.now() < end, 'communication_barrier_timeout');
    await delay(5);
  }
  assert.equal(readFileSync(DIR + '/' + name + '.released', 'utf8'), process.pid + '\n');
}
async function sql<T>(work: (client: pg.Client) => Promise<T>) {
  assert.ok(owner);
  const client = new pg.Client({
    ...db(),
    ssl: false,
    application_name: 'p2-communication-fixture-' + mode,
    connectionTimeoutMillis: 1000,
    query_timeout: 5000,
    options:
      '-c search_path=pg_catalog -c statement_timeout=4000 -c idle_in_transaction_session_timeout=5000',
  });
  try {
    await client.connect();
    return await work(client);
  } finally {
    await client.end();
  }
}
function captureBackends(phase: 'capacity' | 'expiry', maximum: number) {
  const original = pg.Pool.prototype.connect,
    backends = new Set<number>();
  let published = false;
  const wrapped = async function (this: pg.Pool) {
    const client = await (original as (this: pg.Pool) => Promise<pg.PoolClient>).call(this);
    try {
      const row = (await client.query('SELECT pg_backend_pid() AS pid')).rows;
      if (row.length !== 1 || !Number.isSafeInteger(row[0].pid) || row[0].pid < 1)
        throw Error('invalid_backend_identity');
      backends.add(row[0].pid);
      assert.ok(backends.size <= maximum, 'extra_backend_identity');
      if (backends.size === maximum && !published) {
        assert.equal(existsSync(DIR + '/communication-' + phase + '-backends.json'), false);
        save('communication-' + phase + '-backends.json', {
          schemaVersion: 1,
          phase,
          processId: process.pid,
          schema,
          backendIds: [...backends].sort((a, b) => a - b),
        });
        published = true;
      }
      return client;
    } catch (error) {
      client.release(true);
      throw error;
    }
  };
  pg.Pool.prototype.connect = wrapped as typeof original;
  return () => {
    assert.equal(pg.Pool.prototype.connect, wrapped);
    pg.Pool.prototype.connect = original;
  };
}

const q = (name: string) => '"' + schema + '"."' + name + '"';
const scopes = {
  scope: fixture.scope,
  caseId: fixture.caseId,
  conversationId: fixture.conversationId,
};
const evidence = {
  scope: { ...fixture.scope, accountId: fixture.scope.accountId + '-evidence' },
  caseId: fixture.caseId + '-evidence',
  conversationId: fixture.conversationId + '-evidence',
  accountToken: sha('evidence-account:' + fixture.accountToken),
  publisherToken: sha('evidence-publisher:' + fixture.publisherToken),
  bearer: sha('evidence-bearer:' + fixture.bindingToken),
  responsePublisher: sha('evidence-communication-publisher:' + communication.publisherToken),
  sdkToken: sha('evidence-sdk:' + communication.sdkToken),
  browserToken: sha('evidence-browser:' + communication.browserToken),
};
function accounts() {
  return new SeededAccounts([
    {
      ...fixture.scope,
      caseId: fixture.caseId,
      conversationId: fixture.conversationId,
      token: fixture.accountToken,
    },
    {
      ...evidence.scope,
      caseId: evidence.caseId,
      conversationId: evidence.conversationId,
      token: evidence.accountToken,
    },
  ]);
}
function native() {
  return createNativeIntegration(fixture.providerScope, [
    { ...scopes, token: fixture.publisherToken },
    {
      scope: evidence.scope,
      caseId: evidence.caseId,
      conversationId: evidence.conversationId,
      token: evidence.publisherToken,
    },
  ]);
}
function integration() {
  return createCommunicationIntegration(native(), [
    {
      ...scopes,
      publisherToken: communication.publisherToken,
      sdkToken: communication.sdkToken,
      browserToken: communication.browserToken,
    },
    {
      scope: evidence.scope,
      caseId: evidence.caseId,
      conversationId: evidence.conversationId,
      publisherToken: evidence.responsePublisher,
      sdkToken: evidence.sdkToken,
      browserToken: evidence.browserToken,
    },
  ]);
}
function inbox(
  hooks: ConstructorParameters<typeof CommunicationInbox>[3] = {},
  observer: ConstructorParameters<typeof CommunicationInbox>[4] = () => {},
) {
  return new CommunicationInbox(db(), integration(), accounts(), hooks, observer);
}
function publication(
  bindingId = fixture.bindingId,
  bearer = fixture.bindingToken,
  roomId = fixture.roomId,
  participantId = fixture.participantId,
  expiresAt = fixture.expiresAt,
) {
  return { bindingId, bearer, roomId, participantId, expiresAt };
}
function input(inputId: string, roomId = fixture.roomId, participantId = fixture.participantId) {
  return {
    schemaVersion: 1 as const,
    inputId,
    channel: 'web_chat' as const,
    body: 'INVESTIGATE',
    roomId,
    participantId,
  };
}
async function reject(work: () => unknown, code: string) {
  await assert.rejects(
    async () => work(),
    (error: unknown) =>
      error instanceof Error && Object.getOwnPropertyDescriptor(error, 'code')?.value === code,
  );
}
function ports(file = 'communication-operations.json'): DispatchPorts {
  const rows = () =>
    existsSync(DIR + '/' + file)
      ? load<
          Array<{
            canonicalPayload: string;
            payloadDigest: string;
            receipt: OperationReceipt;
            submission: unknown;
          }>
        >(file)
      : [];
  return {
    cases: {
      async inspect(v) {
        return { ...v, revision: '1', source: 'synthetic_read_only' };
      },
    },
    agent: {
      async prepare(v) {
        return { kind: 'investigation', source: 'scripted', caseRevision: v.currentCase.revision };
      },
    },
    operations: {
      capabilities: 'stable_idempotency_and_lookup',
      async lookup(v) {
        const row = rows().find((x) => x.receipt.operationKey === v.operationKey);
        if (!row) return { status: 'absent' };
        assert.deepEqual(row.receipt.scope, v.scope);
        assert.equal(row.payloadDigest, v.payloadDigest);
        return { status: 'accepted', receipt: row.receipt };
      },
      async accept(v) {
        const all = rows();
        let row = all.find((x) => x.receipt.operationKey === v.submission.operationKey);
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
          all.push(row);
          save(file, all);
        }
        return row.receipt;
      },
    },
  };
}
const policy = { maxResponses: 10, maxObservations: 32, maxObservationsPerResponse: 4 };
async function install(nativeBound = 4) {
  await installChannelSchema(db());
  await upgradeChannelSchemaV2(db());
  await upgradeChannelSchemaV3(db());
  await upgradeChannelSchemaV4(db());
  await upgradeChannelSchemaV5(db());
  await upgradeChannelSchemaV6(db(), { maxBindings: nativeBound });
}
function anchor(
  n: number,
  accepted: NativeAcceptance,
  bindingId = fixture.bindingId,
): ResponseAnchor {
  assert.ok(accepted.status === 'accepted' || accepted.status === 'replayed');
  assert.ok(accepted.receiptId && accepted.operationKey);
  return {
    schemaVersion: 1,
    responseId: id('response-' + n),
    generationId: id('generation-' + n),
    sdkSpeechId: 'speech_fixture_' + n,
    bindingId,
    inputId: accepted.inputId,
    receiptId: accepted.receiptId,
    operationKey: accepted.operationKey,
    caseRevision: '1',
  };
}
function sdk(a: ResponseAnchor, n: number, fact: SdkObservation['fact']): SdkObservation {
  return {
    schemaVersion: 1,
    eventId: id('sdk-' + a.responseId + '-' + n),
    responseId: a.responseId,
    generationId: a.generationId,
    sdkSpeechId: a.sdkSpeechId,
    fact,
  };
}
function browser(
  a: ResponseAnchor,
  n: number,
  state: BrowserObservation['state'],
): BrowserObservation {
  return {
    schemaVersion: 1,
    eventId: id('browser-' + a.responseId + '-' + n),
    responseId: a.responseId,
    state,
    observedAudioMs: 123,
  };
}
const CASES = [
  'v6_preservation_v7_repeat_older_upgrade',
  'interrupted_v7_ddl_rollback',
  'exact_response_input_operation_speech_binding',
  'concurrent_replay_and_changed_payload_conflict',
  'independent_source_capability_roles',
  'wrong_scope_response_generation_denied',
  'generated_and_sdk_partial_source_separation',
  'commutative_reordering_and_contradiction',
  'missing_client_completion_stays_unknown',
  'global_per_response_caps_original_replay',
  'expiry_revocation_original_evidence_only',
  'commit_before_ack_kill_fresh_replay',
  'counter_catalog_drift_no_growth',
  'retained_io_timeout_and_later_progress',
  'populated_v7_restore_original_receipts',
  'safe_telemetry_without_business_authority',
];
async function cleanup() {
  await sql(async (c) => {
    const row = (
      await c.query(
        "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=$1",
        [schema],
      )
    ).rows[0];
    if (row) {
      assert.equal(row.owner, 'continuity_migrator');
      assert.match(row.marker, /^p2-channel-schema-v[1-7]$/);
      await c.query('DROP SCHEMA "' + schema + '" CASCADE');
    }
    assert.equal(
      (await c.query('SELECT 1 FROM pg_namespace WHERE nspname=$1', [schema])).rowCount,
      0,
    );
  });
  return { storageVersion: 0, cleanupComplete: true, ownedSchemaAbsent: true };
}
async function mediaSeed() {
  const i = inbox();
  try {
    await i.bind(fixture.publisherToken, publication());
    assert.equal((await i.history(fixture.accountToken)).messages.length, 0);
    return { nativeBindings: 1, nativeInputs: 0 };
  } finally {
    await i.close();
  }
}
async function mediaServe() {
  const endpoint = load<{ host: '127.0.0.1'; port: number }>('python-endpoint.json'),
    client = new NativeAgentHttpClient(
      endpoint,
      'Bearer ' + fixture.prepareToken,
      [{ bindingId: fixture.bindingId, ...scopes }],
      { timeoutMs: 4500 },
    ),
    p = { ...ports(), agent: client.port };
  const gateway = new CommunicationGateway({
    database: db(),
    integration: integration(),
    accounts: [
      {
        ...fixture.scope,
        ...{
          caseId: fixture.caseId,
          conversationId: fixture.conversationId,
          token: fixture.accountToken,
        },
      },
    ],
    ports: p,
    options: { pollMs: 20, observer: () => {} },
  });
  let stopped = false;
  let stop!: () => void;
  const ending = new Promise<void>((resolve) => {
    stop = () => {
      stopped = true;
      resolve();
    };
  });
  process.once('SIGTERM', stop);
  process.once('SIGINT', stop);
  try {
    const address = await gateway.listen();
    if (!stopped) {
      save('node-endpoint.json', address);
      reached('node_ready');
    }
    await ending;
  } finally {
    await gateway.close();
    await client.close();
  }
  const all = gateway.metrics(),
    metrics: Record<string, number> = {};
  for (const key of [
    'accepted',
    'replayed',
    'dispatched',
    'active',
    'intakes',
    'sockets',
    'handlers',
    'driver',
    'observerPending',
  ]) {
    assert.ok(Object.hasOwn(all, key) && Number.isSafeInteger(all[key]));
    metrics[key] = all[key]!;
  }
  const report = {
    cleanupComplete: true,
    metrics,
    communicationMetrics: Object.fromEntries(
      [
        'responsesAccepted',
        'responsesReplayed',
        'observationsAccepted',
        'observationsReplayed',
        'identityConflicts',
        'rejected',
        'unknownAcknowledgements',
        'capacityRejected',
        'telemetryFailures',
      ].map((key) => {
        const all = gateway.communicationMetrics();
        assert.ok(Object.hasOwn(all, key) && Number.isSafeInteger(all[key]));
        return [key, all[key]];
      }),
    ),
  };
  save('communication-node-private-proof.json', {
    communicationMetrics: gateway.communicationMetrics(),
  });
  save('node-terminal.json', {
    schemaVersion: 1,
    status: 'passed',
    mode,
    nodeVersion: process.versions.node,
    storageVersion: 7,
    ...report,
  });
  return report;
}
async function mediaVerify() {
  return sql(async (c) => {
    const count = async (name: string) =>
      Number((await c.query(`SELECT count(*) AS n FROM ${q(name)}`)).rows[0].n);
    const counts = {
      nativeInputs: await count('inbox'),
      processingIntents: await count('processing_intents'),
      preparedPlans: await count('dispatch_plans'),
      responses: await count('native_responses'),
      totalObservations: await count('native_observations'),
    };
    assert.deepEqual(counts, {
      nativeInputs: 3,
      processingIntents: 3,
      preparedPlans: 3,
      responses: 3,
      totalObservations: 10,
    });
    const ledger = load<
      Array<{
        submission: { message: { eventId: string }; operationKey: string };
        canonicalPayload: string;
        payloadDigest: string;
        receipt: OperationReceipt;
      }>
    >('communication-operations.json');
    assert.equal(ledger.length, 3);
    const rows = (
      await c.query(
        `SELECT r.*,i.event_id,i.wire_json,i.canonical_payload,p.operation_key AS input_operation,p.payload_json,p.payload_digest FROM ${q('native_responses')} r JOIN ${q('inbox')} i ON i.receipt_id=r.input_receipt_id JOIN ${q('dispatch_plans')} p ON p.receipt_id=i.receipt_id ORDER BY r.response_sequence`,
      )
    ).rows;
    const sourceProof = load<{
      schemaVersion: number;
      source: string;
      anchors: Array<{ status: string; payload: ResponseAnchor; receipt: ResponseReceipt }>;
      sdkFacts: Array<{ status: string; payload: SdkObservation; receipt: ObservationReceipt }>;
    }>('communication-python-source-proof.json');
    assert.equal(sourceProof.schemaVersion, 1);
    assert.equal(sourceProof.source, 'native_sdk_public_nodes');
    assert.equal(sourceProof.anchors.length, 3);
    assert.equal(sourceProof.sdkFacts.length, 6);
    let sdkCompleted = 0,
      sdkInterrupted = 0,
      browserCompleted = 0,
      browserPartial = 0,
      browserUnknown = 0;
    const proof = [];
    for (const row of rows) {
      const a = JSON.parse(row.canonical_anchor),
        plan = JSON.parse(row.payload_json);
      const recordedAnchor = sourceProof.anchors.find((x) => x.payload.responseId === a.responseId);
      assert.ok(recordedAnchor);
      assert.equal(recordedAnchor.status, 'known');
      for (const [key, value] of Object.entries(recordedAnchor.payload))
        assert.deepEqual(a[key], value);
      assert.deepEqual(recordedAnchor.receipt, {
        responseId: a.responseId,
        receiptId: row.receipt_id,
        anchorDigest: row.anchor_digest,
        responseSequence: row.response_sequence,
        acceptedAt: row.accepted_at.toISOString(),
      });
      assert.equal(sha(row.canonical_anchor), row.anchor_digest);
      assert.equal(a.bindingId, fixture.bindingId);
      assert.equal(a.responseId, row.response_id);
      assert.equal(a.inputId, row.event_id);
      assert.equal(a.receiptId, row.input_receipt_id);
      assert.equal(a.operationKey, row.operation_key);
      assert.equal(a.operationKey, row.input_operation);
      assert.deepEqual(a.scope, fixture.scope);
      assert.deepEqual(a.providerScope, fixture.providerScope);
      assert.equal(a.caseId, fixture.caseId);
      assert.equal(a.conversationId, fixture.conversationId);
      assert.equal(a.roomId, fixture.roomId);
      assert.equal(a.participantId, fixture.participantId);
      assert.equal(a.generationId, row.generation_id);
      assert.equal(a.sdkSpeechId, row.sdk_speech_id);
      assert.equal(plan.operationKey, a.operationKey);
      assert.equal(plan.message.eventId, a.inputId);
      assert.equal(sha(row.payload_json), row.payload_digest);
      const operation = ledger.find((x) => x.receipt.operationKey === a.operationKey);
      assert.ok(operation);
      assert.equal(operation.payloadDigest, row.payload_digest);
      assert.equal(operation.canonicalPayload, row.payload_json);
      const observations = (
        await c.query(
          `SELECT * FROM ${q('native_observations')} WHERE response_id=$1 ORDER BY observation_sequence`,
          [a.responseId],
        )
      ).rows;
      const sdkRows = observations.filter((o) => o.source === 'agent_sdk'),
        browserRows = observations.filter((o) => o.source === 'browser_client');
      assert.equal(sdkRows.length, 2);
      for (const o of observations) {
        assert.equal(o.binding_id, a.bindingId);
        assert.equal(sha(o.canonical_payload), o.payload_digest);
        const data = JSON.parse(o.canonical_payload);
        assert.equal(data.responseId, a.responseId);
        assert.equal(data.eventId, o.event_id);
        if (o.source === 'agent_sdk') {
          assert.equal(data.generationId, a.generationId);
          assert.equal(data.sdkSpeechId, a.sdkSpeechId);
          const recorded = sourceProof.sdkFacts.find((x) => x.payload.eventId === data.eventId);
          assert.ok(recorded);
          assert.equal(recorded.status, 'known');
          assert.deepEqual(recorded.payload, data);
          assert.deepEqual(recorded.receipt, {
            responseId: a.responseId,
            eventId: o.event_id,
            receiptId: o.receipt_id,
            payloadDigest: o.payload_digest,
            observationSequence: o.observation_sequence,
            acceptedAt: o.accepted_at.toISOString(),
          });
        }
      }
      const generated = sdkRows
        .map((o) => JSON.parse(o.canonical_payload))
        .find((o) => o.fact.type === 'generated_complete');
      assert.ok(
        generated && typeof generated.fact.text === 'string' && generated.fact.text.length > 0,
      );
      const settled = sdkRows
        .map((o) => JSON.parse(o.canonical_payload))
        .find((o) => o.fact.type === 'speech_settled');
      assert.ok(settled);
      if (settled.fact.state === 'completed') sdkCompleted++;
      else {
        assert.equal(settled.fact.state, 'interrupted');
        sdkInterrupted++;
        assert.ok(settled.fact.sdkText === null || typeof settled.fact.sdkText === 'string');
      }
      const states = browserRows.map((o) => JSON.parse(o.canonical_payload).state);
      if (states.includes('completed')) {
        browserCompleted++;
        assert.deepEqual(states, ['started', 'completed']);
      } else if (states.includes('partial')) {
        browserPartial++;
        assert.deepEqual(states, ['started', 'partial']);
      } else {
        browserUnknown++;
        assert.equal(states.length, 0);
      }
      proof.push({
        anchor: a,
        responseReceipt: {
          responseId: a.responseId,
          receiptId: row.receipt_id,
          anchorDigest: row.anchor_digest,
          responseSequence: row.response_sequence,
          acceptedAt: row.accepted_at.toISOString(),
        },
        observationRows: observations.map((o) => ({
          source: o.source,
          eventId: o.event_id,
          receiptId: o.receipt_id,
          payloadDigest: o.payload_digest,
          payload: JSON.parse(o.canonical_payload),
        })),
      });
    }
    assert.deepEqual(
      [sdkCompleted, sdkInterrupted, browserCompleted, browserPartial, browserUnknown],
      [2, 1, 1, 1, 1],
    );
    save('communication-owner-proof.json', { counts, proof });
    return {
      ...counts,
      operationAcceptances: 3,
      sdkObservations: 6,
      browserObservations: 4,
      sdkCompleted: 2,
      sdkInterrupted: 1,
      browserCompletedReported: 1,
      browserPartial: 1,
      browserUnknown: 1,
      exactIdentityJoins: true,
      noAcknowledgements: true,
    };
  });
}
async function legacySeed() {
  const provider = { ...fixture.providerScope, provider: 'fake_sms' },
    key = Buffer.alloc(32, 0x61),
    callbackKey = Buffer.alloc(32, 0x71),
    smsIntegration = createFakeSmsIntegration(provider, key),
    smsInbox = new ChannelInbox(db(), smsIntegration, accounts(), {}, () => {}),
    nativeInbox = new NativeChannelInbox(db(), native(), accounts(), {}, () => {}),
    publisher = sha('legacy-outbox:' + fixture.publisherToken),
    controller = sha('legacy-control:' + fixture.publisherToken);
  const carrier: CarrierSendPort = {
    capabilities: 'ordinary_fake_sms_v1',
    async send(request) {
      return {
        schemaVersion: 1,
        attemptId: request.attemptId,
        requestDigest: sha(JSON.stringify(request)),
        status: 'accepted_by_provider',
        providerMessageId: 'legacy-' + request.providerOperationKey,
      };
    },
  };
  const box = new ChannelOutbox(
      db(),
      smsIntegration,
      accounts(),
      [{ ...scopes, token: publisher }],
      carrier,
      { observer: () => {}, recoveryControllers: [{ ...scopes, token: controller }] },
    ),
    callbacks = new CallbackInbox(
      db(),
      createFakeSmsCallbackIntegration(provider, callbackKey),
      accounts(),
      { observer: () => {} },
    ),
    dispatcher = new ChannelDispatcher(db(), native(), accounts(), ports(), { observer: () => {} });
  const sign = (body: string, eventId: string) =>
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
    const challenge = await smsInbox.createChallenge(fixture.accountToken, 'legacy-sender'),
      link = sign('LINK ' + challenge.challengeId + ' ' + challenge.secret, id('legacy-link')),
      association = await smsInbox.completeAssociation(link.raw, link.headers),
      message = sign('Legacy café 🧭\n"quoted"', id('legacy-sms')),
      smsAccepted = await smsInbox.acceptSms(message.raw, message.headers);
    await nativeInbox.bind(fixture.publisherToken, publication());
    const accepted = await nativeInbox.accept(fixture.bindingToken, input(id('legacy-native')));
    assert.equal(accepted.status, 'accepted');
    assert.ok(accepted.receiptId);
    const result = await dispatcher.step(fixture.accountToken, accepted.receiptId);
    assert.equal(result.status, 'dispatched');
    const route = await box.inspectRoute(fixture.accountToken);
    await box.selectRoute(fixture.accountToken, {
      expectedRouteVersion: route.version,
      senderId: 'legacy-sender',
      associationVersion: association.associationVersion,
    });
    const queued = await box.enqueue(publisher, {
      schemaVersion: 1,
      outboundId: id('legacy-outbound'),
      responseId: 'legacy-response',
      body: 'Legacy notification café 🧭\n"quoted"',
    });
    const sent = await box.send(fixture.accountToken, queued.outboundId);
    assert.equal(sent.status, 'accepted_by_provider');
    const outbound = await box.inspect(fixture.accountToken, queued.outboundId),
      request = outbound.attempts[0]!.request;
    const callback = signFakeSmsCallback(
        {
          schemaVersion: 1,
          eventId: id('legacy-callback'),
          attemptId: request.attemptId,
          providerOperationKey: request.providerOperationKey,
          requestDigest: sha(JSON.stringify(request)),
          providerMessageId: 'legacy-' + request.providerOperationKey,
          state: 'delivered',
          occurredAt: '2030-01-01T00:00:00.000Z',
        },
        callbackKey,
        Math.floor(Date.now() / 1000),
        provider,
      ),
      callbackReceipt = await callbacks.accept(callback.raw, callback.headers),
      recovery = await box.reconcile(controller, {
        commandId: id('legacy-recovery'),
        outboundId: request.outboundId,
        attemptId: request.attemptId,
      });
    assert.equal(recovery.receipt.decision, 'terminal');
    const original = {
      sms: await smsInbox.inspect(fixture.accountToken, smsAccepted.receipt.receiptId),
      native: await nativeInbox.inspect(fixture.accountToken, accepted.receiptId),
      nativeAcceptance: accepted,
      outbound: await box.inspect(fixture.accountToken, queued.outboundId),
      callbackReceipt,
      recovery,
    };
    save('communication-legacy-original.json', original);
    return {
      storageVersion: 6,
      legacySmsInputs: 1,
      legacyNativeInputs: 1,
      legacyReplyIntents: 1,
      legacySendAttempts: 1,
      legacySendResults: 1,
      legacyCallbacks: 1,
      legacyRecoveryCommands: 1,
      legacyOperationAcceptances: 1,
    };
  } finally {
    const closed = await Promise.allSettled([
      dispatcher.close(),
      callbacks.close(),
      box.close(),
      nativeInbox.close(),
      smsInbox.close(),
    ]);
    assert.ok(
      closed.every((x) => x.status === 'fulfilled'),
      'legacy_fixture_cleanup',
    );
  }
}
async function assertLegacy(client: pg.Client) {
  const original = load<{
    sms: StoredMessage;
    native: StoredMessage;
    outbound: {
      receipt: { outboundId: string; receiptId: string };
      reply: unknown;
      attempts: Array<{ request: SendRequest; result: unknown }>;
    };
    callbackReceipt: { receiptId: string };
    recovery: { receipt: { commandId: string; receiptId: string } };
  }>('communication-legacy-original.json');
  for (const item of [original.sms, original.native]) {
    const rows = (
      await client.query(
        `SELECT i.*,p.operation_key,p.state FROM ${q('inbox')} i JOIN ${q('processing_intents')} p USING(receipt_id) WHERE i.receipt_id=$1`,
        [item.receipt.receiptId],
      )
    ).rows;
    assert.equal(rows.length, 1);
    const row = rows[0];
    assert.deepEqual(JSON.parse(row.wire_json), item.event);
    assert.equal(row.operation_key, item.operationKey);
    assert.equal(row.state, item.processingState);
    assert.equal(row.acceptance_sequence, item.receipt.acceptanceSequence);
    assert.equal(row.accepted_at.toISOString(), item.receipt.acceptedAt);
    const wire = JSON.parse(row.wire_json);
    for (const key of ['receivedAt', 'retryCount', 'signature']) delete wire[key];
    assert.deepEqual(JSON.parse(row.canonical_payload), wire);
  }
  const out = (
    await client.query(`SELECT * FROM ${q('reply_intents')} WHERE outbound_id=$1`, [
      original.outbound.receipt.outboundId,
    ])
  ).rows[0];
  assert.ok(out);
  assert.deepEqual(JSON.parse(out.canonical_payload), original.outbound.reply);
  assert.equal(out.receipt_id, original.outbound.receipt.receiptId);
  const request = original.outbound.attempts[0]!,
    attempt = (
      await client.query(
        `SELECT a.*,r.canonical_result FROM ${q('send_attempts')} a JOIN ${q('send_results')} r USING(attempt_id) WHERE a.attempt_id=$1`,
        [request.request.attemptId],
      )
    ).rows[0];
  assert.ok(attempt);
  assert.deepEqual(JSON.parse(attempt.canonical_request), request.request);
  assert.deepEqual(JSON.parse(attempt.canonical_result), request.result);
  assert.equal(
    (
      await client.query(
        `SELECT count(*)::integer n FROM ${q('callback_observations')} WHERE receipt_id=$1`,
        [original.callbackReceipt.receiptId],
      )
    ).rows[0].n,
    1,
  );
  const recovery = (
    await client.query(
      `SELECT receipt_json FROM ${q('send_recovery_commands')} WHERE command_id=$1`,
      [original.recovery.receipt.commandId],
    )
  ).rows[0];
  assert.ok(recovery);
  assert.deepEqual(JSON.parse(recovery.receipt_json), original.recovery.receipt);
}
async function upgrade() {
  await sql(async (c) => {
    assert.equal(
      (await c.query(`SELECT version FROM ${q('schema_metadata')} WHERE singleton`)).rows[0]
        .version,
      6,
    );
    assert.equal(
      (
        await c.query(
          "SELECT count(*)::integer n FROM pg_tables WHERE schemaname=$1 AND tablename IN('communication_settings','native_responses','native_observations')",
          [schema],
        )
      ).rows[0].n,
      0,
    );
    await assertLegacy(c);
  });
  await upgradeChannelSchemaV7(db(), policy);
  await upgradeChannelSchemaV7(db(), policy);
  await installChannelSchema(db());
  await upgradeChannelSchemaV2(db());
  await upgradeChannelSchemaV3(db());
  await upgradeChannelSchemaV4(db());
  await upgradeChannelSchemaV5(db());
  await upgradeChannelSchemaV6(db(), { maxBindings: 4 });
  await sql(assertLegacy);
  return {
    legacyPreserved: true,
    rollbackTablesAbsent: true,
    repeatedUpgrade: true,
    olderUpgradesCompatible: true,
  };
}

async function expiry() {
  const i = inbox(),
    short = {
      bindingId: id('short-binding'),
      bearer: sha('short:' + fixture.bindingToken),
      roomId: fixture.roomId + '-short',
      participantId: fixture.participantId + '-short',
      expiresAt: new Date(Date.now() + 1400).toISOString(),
    },
    fresh = {
      bindingId: id('fresh-binding'),
      bearer: sha('fresh:' + fixture.bindingToken),
      roomId: fixture.roomId + '-fresh',
      participantId: fixture.participantId + '-fresh',
      expiresAt: fixture.expiresAt,
    };
  try {
    await i.bind(fixture.publisherToken, short);
    const accepted = await i.accept(
      short.bearer,
      input(id('short-input'), short.roomId, short.participantId),
    );
    const original = anchor(1, accepted, short.bindingId),
      receipt = await i.beginResponse(communication.publisherToken, original);
    save('communication-expiry-ready.json', {
      schemaVersion: 1,
      bindingId: short.bindingId,
      responseId: original.responseId,
      inputId: original.inputId,
      operationKey: original.operationKey,
      expiresAt: short.expiresAt,
    });
    await barrier('communication_expiry_ready');
    const restore = captureBackends('expiry', 1);
    try {
      const pending = i.beginResponse(communication.publisherToken, {
        ...anchor(80, accepted, short.bindingId),
      });
      reached('communication_expiry_waiting');
      await reject(() => pending, 'AccessDenied');
    } finally {
      restore();
    }
    const late = sdk(original, 0, {
        type: 'generated_complete',
        text: 'Late original source café 🧭\n"quoted"',
      }),
      lateReceipt = await i.observeSdk(communication.sdkToken, late);
    await i.revoke(fixture.publisherToken, short.bindingId);
    const lateBrowser = browser(original, 0, 'partial'),
      lateBrowserReceipt = await i.observeBrowser(communication.browserToken, lateBrowser);
    assert.deepEqual(await i.beginResponse(communication.publisherToken, original), receipt);
    await reject(
      () => i.beginResponse(communication.publisherToken, anchor(81, accepted, short.bindingId)),
      'AccessDenied',
    );
    await i.bind(fixture.publisherToken, fresh);
    const current = await i.accept(
        fresh.bearer,
        input(id('fresh-input'), fresh.roomId, fresh.participantId),
      ),
      currentAnchor = anchor(2, current, fresh.bindingId),
      currentReceipt = await i.beginResponse(communication.publisherToken, currentAnchor);
    assert.ok(current.receiptId);
    const dispatcher = new ChannelDispatcher(db(), native(), accounts(), ports(), {
      observer: () => {},
    });
    try {
      assert.equal(
        (await dispatcher.step(fixture.accountToken, current.receiptId)).status,
        'dispatched',
      );
    } finally {
      await dispatcher.close();
    }
    const state = {
      short,
      original,
      receipt,
      accepted,
      late,
      lateReceipt,
      lateBrowser,
      lateBrowserReceipt,
      fresh,
      current,
      currentAnchor,
      currentReceipt,
    };
    save('communication-expiry-state.json', state);
    save('communication-expiry-proof.json', {
      schemaVersion: 1,
      expiredNewResponseDenied: true,
      originalLateEvidenceAccepted: true,
      freshBindingProgress: true,
      originalReceiptPreserved: true,
    });
    return {
      completedGroups: [CASES[10]],
      expiredNewResponseDenied: true,
      originalLateEvidenceAccepted: true,
      freshBindingProgress: true,
    };
  } finally {
    await i.close();
  }
}

type SavedResponse = Readonly<{ anchor: ResponseAnchor; receipt: ResponseReceipt }>;
type SavedObservation = Readonly<{
  source: 'agent_sdk' | 'browser_client';
  payload: SdkObservation | BrowserObservation;
  receipt: ObservationReceipt;
}>;
type ExpiryState = Readonly<{
  original: ResponseAnchor;
  receipt: ResponseReceipt;
  accepted: NativeAcceptance;
  late: SdkObservation;
  lateReceipt: ObservationReceipt;
  lateBrowser: BrowserObservation;
  lateBrowserReceipt: ObservationReceipt;
  current: NativeAcceptance;
  currentAnchor: ResponseAnchor;
  currentReceipt: ResponseReceipt;
}>;
type ExerciseProof = Readonly<{
  schemaVersion: 1;
  responses: SavedResponse[];
  observations: SavedObservation[];
  metrics: Readonly<Record<string, number>>;
  reorderedProjectionEqual: boolean;
  operationAcceptances: number;
}>;
async function exercise() {
  const notifications: Array<Readonly<{ event: string; operation: string; code: string }>> = [];
  let observerMode: 'normal' | 'throw' | 'hold' = 'normal';
  let releaseObserver!: () => void;
  const heldObserver = new Promise<void>((resolve) => {
    releaseObserver = resolve;
  });
  const i = inbox({}, (event) => {
    if (event.operation !== 'communication') return;
    notifications.push(event);
    if (observerMode === 'throw') throw new Error('synthetic_observer_outage');
    if (observerMode === 'hold') return heldObserver;
  });
  const prior = load<{ nativeAcceptance: NativeAcceptance }>('communication-legacy-original.json'),
    exp = load<ExpiryState>('communication-expiry-state.json');
  const responses: SavedResponse[] = [
      { anchor: exp.original, receipt: exp.receipt },
      { anchor: exp.currentAnchor, receipt: exp.currentReceipt },
    ],
    observations: SavedObservation[] = [
      { source: 'agent_sdk', payload: exp.late, receipt: exp.lateReceipt },
      { source: 'browser_client', payload: exp.lateBrowser, receipt: exp.lateBrowserReceipt },
    ];
  const anchors = new Map<number, ResponseAnchor>([
    [1, exp.original],
    [2, exp.currentAnchor],
  ]);
  const putSdk = async (a: ResponseAnchor, n: number, fact: SdkObservation['fact']) => {
    const payload = sdk(a, n, fact),
      receipt = await i.observeSdk(communication.sdkToken, payload);
    observations.push({ source: 'agent_sdk', payload, receipt });
    return receipt;
  };
  const putBrowser = async (a: ResponseAnchor, n: number, state: BrowserObservation['state']) => {
    const payload = browser(a, n, state),
      receipt = await i.observeBrowser(communication.browserToken, payload);
    observations.push({ source: 'browser_client', payload, receipt });
    return receipt;
  };
  try {
    for (const n of [0, 3, 4, 5, 6, 7]) {
      const a = anchor(n, prior.nativeAcceptance);
      anchors.set(n, a);
      responses.push({
        anchor: a,
        receipt: await i.beginResponse(communication.publisherToken, a),
      });
    }
    await i.bind(
      evidence.publisherToken,
      publication(
        id('evidence-binding'),
        evidence.bearer,
        fixture.roomId + '-evidence',
        fixture.participantId + '-evidence',
      ),
    );
    const evidenceInput = await i.accept(
        evidence.bearer,
        input(
          id('evidence-input'),
          fixture.roomId + '-evidence',
          fixture.participantId + '-evidence',
        ),
      ),
      evidenceAnchor = anchor(8, evidenceInput, id('evidence-binding')),
      evidenceReceipt = await i.beginResponse(evidence.responsePublisher, evidenceAnchor);
    assert.equal(evidenceReceipt.responseSequence, '1');
    anchors.set(8, evidenceAnchor);
    responses.push({ anchor: evidenceAnchor, receipt: evidenceReceipt });
    await reject(
      () => i.inspectResponse(fixture.accountToken, evidenceAnchor.responseId),
      'AccessDenied',
    );
    await reject(
      () => i.inspectResponse(evidence.accountToken, exp.original.responseId),
      'AccessDenied',
    );
    await reject(
      () => i.beginResponse(communication.publisherToken, evidenceAnchor),
      'AccessDenied',
    );
    await reject(
      () =>
        i.observeSdk(
          communication.sdkToken,
          sdk(evidenceAnchor, 9, { type: 'speech_settled', state: 'unknown', sdkText: null }),
        ),
      'AccessDenied',
    );
    const evidenceList = await i.responses(evidence.accountToken, { limit: 32 });
    assert.equal(evidenceList.length, 1);
    assert.equal(evidenceList[0]!.receipt.responseSequence, '1');
    const a = anchors.get(0)!;
    const original = responses.find((x) => x.anchor.responseId === a.responseId)!.receipt;
    assert.deepEqual(
      await Promise.all([
        i.beginResponse(communication.publisherToken, a),
        i.beginResponse(communication.publisherToken, a),
      ]),
      [original, original],
    );
    await reject(
      () => i.beginResponse(communication.publisherToken, { ...a, caseRevision: '2' }),
      'IdentityConflict',
    );
    await reject(() => i.beginResponse(communication.sdkToken, a), 'AccessDenied');
    await reject(
      () =>
        i.observeSdk(
          communication.publisherToken,
          sdk(a, 90, { type: 'speech_settled', state: 'unknown', sdkText: null }),
        ),
      'AccessDenied',
    );
    await reject(
      () => i.observeBrowser(communication.sdkToken, browser(a, 90, 'completed')),
      'AccessDenied',
    );
    await reject(() => i.beginResponse(fixture.accountToken, a), 'AccessDenied');
    await reject(
      () =>
        i.beginResponse(communication.publisherToken, {
          ...anchor(77, prior.nativeAcceptance),
          operationKey: id('foreign-operation'),
        }),
      'AccessDenied',
    );
    await reject(
      () =>
        i.observeSdk(communication.sdkToken, {
          ...sdk(a, 91, { type: 'speech_settled', state: 'completed', sdkText: null }),
          generationId: id('wrong-generation'),
        }),
      'AccessDenied',
    );
    const full = 'Full generated café 🧭\n"quoted" response';
    await putSdk(a, 0, { type: 'generated_complete', text: full });
    await putSdk(a, 1, {
      type: 'speech_settled',
      state: 'interrupted',
      sdkText: 'Full generated café',
    });
    await putBrowser(a, 0, 'partial');
    await putSdk(a, 2, { type: 'speech_settled', state: 'unknown', sdkText: null });
    const view = await i.inspectResponse(fixture.accountToken, a.responseId);
    assert.equal(view.generatedText, full);
    assert.equal(view.sdkText, 'Full generated café');
    assert.equal(view.sdkState, 'interrupted');
    assert.equal(view.browserState, 'partial');
    const originalFact = observations.find((x) => x.payload.responseId === a.responseId)!;
    assert.equal(originalFact.source, 'agent_sdk');
    await reject(
      () =>
        i.observeSdk(communication.sdkToken, {
          ...(originalFact.payload as SdkObservation),
          fact: { type: 'generated_complete', text: 'different' },
        }),
      'IdentityConflict',
    );
    await reject(
      () =>
        i.observeSdk(
          communication.sdkToken,
          sdk(a, 3, { type: 'speech_settled', state: 'unknown', sdkText: null }),
        ),
      'Overloaded',
    );
    const replay = await i.observeSdk(
      communication.sdkToken,
      originalFact.payload as SdkObservation,
    );
    assert.deepEqual(replay, originalFact.receipt);
    for (let n = 0; n < 2; n++)
      await putSdk(exp.original, n + 1, {
        type: 'speech_settled',
        state: 'unknown',
        sdkText: null,
      });
    const b = exp.currentAnchor;
    await putSdk(b, 0, { type: 'generated_complete', text: 'Fresh current generated text' });
    await putSdk(b, 1, {
      type: 'speech_settled',
      state: 'completed',
      sdkText: 'Fresh current generated text',
    });
    await putBrowser(b, 0, 'started');
    await putBrowser(b, 1, 'completed');
    assert.equal(
      (await i.inspectResponse(fixture.accountToken, b.responseId)).browserState,
      'completed_reported',
    );
    const targets = [3, 4, 5, 6].map((n) =>
      sdk(anchors.get(n)!, 0, { type: 'speech_settled', state: 'unknown', sdkText: null }),
    );
    save('communication-capacity-ready.json', {
      schemaVersion: 1,
      responseIds: targets.map((x) => x.responseId),
      eventIds: targets.map((x) => x.eventId),
      maximumOperations: 4,
      maximumConnections: 2,
    });
    await barrier('communication_capacity_ready');
    const restore = captureBackends('capacity', 2);
    try {
      const pending = targets.map((payload) => i.observeSdk(communication.sdkToken, payload));
      const waiter = await Promise.race([
        Promise.all(pending).then(() => 'settled'),
        delay(20).then(() => 'abandoned'),
      ]);
      assert.equal(waiter, 'abandoned');
      assert.equal(i.metrics().active, 4);
      await reject(
        () =>
          i.observeSdk(
            communication.sdkToken,
            sdk(anchors.get(7)!, 0, { type: 'speech_settled', state: 'unknown', sdkText: null }),
          ),
        'Overloaded',
      );
      reached('communication_capacity_waiting');
      const receipts = await Promise.all(pending);
      receipts.forEach((receipt, n) =>
        observations.push({ source: 'agent_sdk', payload: targets[n]!, receipt }),
      );
      assert.equal(i.metrics().active, 0);
    } finally {
      restore();
    }
    await putSdk(anchors.get(3)!, 1, {
      type: 'speech_settled',
      state: 'completed',
      sdkText: 'One SDK text',
    });
    await putSdk(anchors.get(3)!, 2, {
      type: 'speech_settled',
      state: 'interrupted',
      sdkText: 'One SDK text',
    });
    await putBrowser(anchors.get(3)!, 0, 'completed');
    const contradictory = await i.observations(fixture.accountToken, anchors.get(3)!.responseId, {
      limit: 8,
    });
    const forward = reduceCommunicationEvidence(contradictory),
      backward = reduceCommunicationEvidence([...contradictory].reverse());
    assert.deepEqual(forward, backward);
    assert.equal(forward.conflicted, true);
    assert.equal(forward.sdkState, 'conflicted');
    await putSdk(anchors.get(4)!, 1, {
      type: 'generated_complete',
      text: 'Generated without browser completion',
    });
    await putSdk(anchors.get(4)!, 2, {
      type: 'speech_settled',
      state: 'completed',
      sdkText: 'Generated without browser completion',
    });
    await putSdk(anchors.get(4)!, 3, { type: 'speech_settled', state: 'unknown', sdkText: null });
    assert.equal(
      (await i.inspectResponse(fixture.accountToken, anchors.get(4)!.responseId)).browserState,
      'unknown',
    );
    observerMode = 'throw';
    for (let n = 1; n < 4; n++)
      await putSdk(anchors.get(5)!, n, { type: 'speech_settled', state: 'unknown', sdkText: null });
    observerMode = 'normal';
    assert.ok(i.communicationMetrics().telemetryFailures! >= 3);
    for (let n = 1; n < 4; n++)
      await putSdk(anchors.get(6)!, n, { type: 'speech_settled', state: 'unknown', sdkText: null });
    observerMode = 'hold';
    const first = observations[0]!;
    assert.equal(first.source, 'agent_sdk');
    for (let n = 0; n < 16; n++)
      assert.deepEqual(
        await i.observeSdk(communication.sdkToken, first.payload as SdkObservation),
        first.receipt,
      );
    assert.equal(i.communicationMetrics().observerPending, 8);
    assert.ok(i.communicationMetrics().observerDropped! >= 8);
    releaseObserver();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    observerMode = 'normal';
    assert.equal(i.communicationMetrics().observerPending, 0);
    for (const event of notifications) {
      assert.deepEqual(Object.keys(event).sort(), ['code', 'event', 'operation']);
      assert.equal(event.operation, 'communication');
    }
    // Bounded response/observation pagination is over immutable source identities.
    const page = await i.responses(fixture.accountToken, { limit: 2 });
    assert.equal(page.length, 2);
    const older = await i.responses(fixture.accountToken, {
      limit: 32,
      beforeSequence: page[1]!.receipt.responseSequence,
    });
    assert.equal(older.length, 6);
    const facts = await i.observations(fixture.accountToken, a.responseId, { limit: 2 });
    assert.equal(facts.length, 2);
    assert.deepEqual(
      facts.map((x) => x.receipt.observationSequence),
      ['1', '2'],
    );
    assert.equal(
      (await i.observations(fixture.accountToken, a.responseId, { limit: 8, afterSequence: '2' }))
        .length,
      2,
    );
    assert.equal(observations.length, 28);
    assert.equal(responses.length, 9);
    const all = await i.responses(fixture.accountToken, { limit: 32 });
    assert.equal(all.length, 8);
    assert.deepEqual(
      all.map((x) => x.receipt.responseSequence),
      ['8', '7', '6', '5', '4', '3', '2', '1'],
    );
    const proof: ExerciseProof = {
      schemaVersion: 1,
      responses,
      observations,
      metrics: i.communicationMetrics(),
      reorderedProjectionEqual: true,
      operationAcceptances: load<unknown[]>('communication-operations.json').length,
    };
    assert.equal(proof.operationAcceptances, 2);
    save('communication-exercise-proof.json', proof);
    save('communication-capacity-proof.json', {
      schemaVersion: 1,
      admittedOperations: 4,
      abandonedWaiters: 1,
      fifthRejected: 'Overloaded',
      settledOperations: 4,
      laterProgress: true,
    });
    return {
      completedGroups: [2, 3, 4, 5, 6, 7, 8, 13, 15].map((n) => CASES[n]),
      responses: 9,
      observations: 28,
      maximumOperations: 4,
      maximumConnections: 2,
    };
  } finally {
    releaseObserver();
    await i.close();
  }
}
async function crash(): Promise<never> {
  const prior = load<{ nativeAcceptance: NativeAcceptance }>('communication-legacy-original.json'),
    a = anchor(9, prior.nativeAcceptance);
  let hold = false;
  const i = inbox({
    afterCommunicationCommit: () =>
      hold ? barrier('communication_observation_committed') : undefined,
  });
  try {
    const receipt = await i.beginResponse(communication.publisherToken, a),
      payload = sdk(a, 0, {
        type: 'generated_complete',
        text: 'Committed before lost acknowledgement café 🧭\n"original"',
      });
    save('communication-crash-original.json', {
      schemaVersion: 1,
      anchor: a,
      responseReceipt: receipt,
      payload,
    });
    hold = true;
    await i.observeSdk(communication.sdkToken, payload);
    throw new Error('crash_barrier_returned');
  } finally {
    await i.close();
  }
}
async function replay() {
  const i = inbox(),
    original = load<{
      anchor: ResponseAnchor;
      responseReceipt: ResponseReceipt;
      payload: SdkObservation;
    }>('communication-crash-original.json'),
    proof = load<ExerciseProof>('communication-exercise-proof.json'),
    before = load<unknown[]>('communication-operations.json');
  try {
    assert.deepEqual(
      await i.beginResponse(communication.publisherToken, original.anchor),
      original.responseReceipt,
    );
    const receipt = await i.observeSdk(communication.sdkToken, original.payload);
    if (existsSync(DIR + '/communication-replay-proof.json')) {
      const p = load<{ originalObservation: ObservationReceipt }>(
        'communication-replay-proof.json',
      );
      assert.deepEqual(receipt, p.originalObservation);
    }
    assert.deepEqual(await i.observeSdk(communication.sdkToken, original.payload), receipt);
    const extras: SavedObservation[] = [];
    for (let n = 1; n < 4; n++) {
      const payload = sdk(original.anchor, n, {
        type: 'speech_settled',
        state: 'unknown',
        sdkText: null,
      });
      extras.push({
        source: 'agent_sdk',
        payload,
        receipt: await i.observeSdk(communication.sdkToken, payload),
      });
    }
    const empty = proof.responses.find((x) => x.anchor.responseId === id('response-7'))!;
    await reject(
      () =>
        i.observeSdk(
          communication.sdkToken,
          sdk(empty.anchor, 0, { type: 'speech_settled', state: 'unknown', sdkText: null }),
        ),
      'Overloaded',
    );
    await reject(
      () =>
        i.beginResponse(communication.publisherToken, {
          ...original.anchor,
          responseId: id('response-10'),
          generationId: id('generation-10'),
          sdkSpeechId: 'speech_fixture_10',
        }),
      'Overloaded',
    );
    for (const row of proof.responses)
      assert.deepEqual(
        await i.beginResponse(
          row.anchor.responseId === id('response-8')
            ? evidence.responsePublisher
            : communication.publisherToken,
          row.anchor,
        ),
        row.receipt,
      );
    for (const row of proof.observations) {
      const actual =
        row.source === 'agent_sdk'
          ? await i.observeSdk(communication.sdkToken, row.payload as SdkObservation)
          : await i.observeBrowser(communication.browserToken, row.payload as BrowserObservation);
      assert.deepEqual(actual, row.receipt);
    }
    const facts = await i.observations(fixture.accountToken, original.anchor.responseId, {
      limit: 8,
    });
    assert.equal(facts.length, 4);
    assert.deepEqual(
      facts.map((x) => x.receipt.observationSequence),
      ['1', '2', '3', '4'],
    );
    const responses = await i.responses(fixture.accountToken, { limit: 32 });
    assert.equal(responses.length, 9);
    assert.equal(
      responses.reduce((n, x) => n + x.observationCount, 0),
      32,
    );
    assert.equal((await i.responses(evidence.accountToken, { limit: 32 })).length, 1);
    assert.deepEqual(load('communication-operations.json'), before);
    assert.equal(before.length, 2);
    save('communication-replay-proof.json', {
      schemaVersion: 1,
      evidenceResponse: proof.responses.find((x) => x.anchor.responseId === id('response-8'))!
        .receipt,
      originalResponse: original.responseReceipt,
      originalObservation: receipt,
      extraObservations: extras,
      allResponses: responses.map((x) => x.receipt),
      operationAcceptances: before.length,
    });
    return {
      completedGroups: [CASES[9], CASES[11]],
      responses: 10,
      observations: 32,
      originalResponseReceiptPreserved: true,
      originalObservationReceiptPreserved: true,
      newGenerationCalls: 0,
      newOperationCalls: 0,
    };
  } finally {
    await i.close();
  }
}
async function drift() {
  const marker = load<{ schemaVersion: number; kind: string }>('communication-fault.json');
  assert.deepEqual(Object.keys(marker).sort(), ['kind', 'schemaVersion']);
  assert.equal(marker.schemaVersion, 1);
  assert.ok(marker.kind === 'count' || marker.kind === 'catalog');
  const i = inbox(),
    original = load<{ anchor: ResponseAnchor }>('communication-crash-original.json');
  try {
    await reject(
      () =>
        i.observeSdk(
          communication.sdkToken,
          sdk(original.anchor, 99, { type: 'speech_settled', state: 'unknown', sdkText: null }),
        ),
      'SchemaMismatch',
    );
    return {
      completedGroups: [CASES[12]],
      driftKind: marker.kind,
      errorCode: 'SchemaMismatch',
      newRows: 0,
    };
  } finally {
    await i.close();
  }
}
async function verify() {
  return sql(async (c) => {
    await assertLegacy(c);
    const settings = (await c.query(`SELECT * FROM ${q('communication_settings')} WHERE singleton`))
      .rows;
    assert.equal(settings.length, 1);
    assert.deepEqual(
      [
        settings[0].max_responses,
        settings[0].max_observations,
        settings[0].max_observations_per_response,
        settings[0].response_count,
        settings[0].observation_count,
      ],
      [10, 32, 4, 10, 32],
    );
    const rs = (await c.query(`SELECT * FROM ${q('native_responses')} ORDER BY response_sequence`))
        .rows,
      os = (
        await c.query(
          `SELECT * FROM ${q('native_observations')} ORDER BY response_id,observation_sequence`,
        )
      ).rows;
    assert.equal(rs.length, 10);
    assert.equal(os.length, 32);
    const proof = load<ExerciseProof>('communication-exercise-proof.json'),
      crash = load<{
        anchor: ResponseAnchor;
        responseReceipt: ResponseReceipt;
        payload: SdkObservation;
      }>('communication-crash-original.json'),
      replayed = load<{
        originalObservation: ObservationReceipt;
        extraObservations: SavedObservation[];
      }>('communication-replay-proof.json');
    const originals = [
        ...proof.responses,
        { anchor: crash.anchor, receipt: crash.responseReceipt },
      ],
      facts = [
        ...proof.observations,
        { source: 'agent_sdk', payload: crash.payload, receipt: replayed.originalObservation },
        ...replayed.extraObservations,
      ];
    const joins = [];
    for (const r of rs) {
      const a = JSON.parse(r.canonical_anchor),
        original = originals.find((x) => x.anchor.responseId === r.response_id);
      assert.ok(original);
      assert.equal(sha(r.canonical_anchor), r.anchor_digest);
      assert.equal(a.responseId, r.response_id);
      assert.equal(a.bindingId, r.binding_id);
      assert.equal(a.generationId, r.generation_id);
      assert.equal(a.sdkSpeechId, r.sdk_speech_id);
      assert.equal(a.receiptId, r.input_receipt_id);
      assert.equal(a.operationKey, r.operation_key);
      assert.equal(a.scope.tenantId, r.tenant_id);
      assert.equal(a.scope.accountId, r.account_id);
      assert.equal(a.caseId, r.case_id);
      assert.equal(a.conversationId, r.conversation_id);
      assert.deepEqual(a.providerScope, fixture.providerScope);
      for (const [key, value] of Object.entries(original.anchor)) assert.deepEqual(a[key], value);
      const inputs = (
        await c.query(
          `SELECT i.*,p.operation_key FROM ${q('inbox')} i JOIN ${q('processing_intents')} p USING(receipt_id) WHERE i.receipt_id=$1`,
          [a.receiptId],
        )
      ).rows;
      assert.equal(inputs.length, 1);
      const event = JSON.parse(inputs[0].wire_json);
      assert.equal(event.eventId, a.inputId);
      assert.equal(event.senderId, a.bindingId);
      assert.equal(event.caseId, a.caseId);
      assert.equal(event.conversationId, a.conversationId);
      assert.deepEqual(event.accountScope, a.scope);
      assert.equal(inputs[0].operation_key, a.operationKey);
      const actual = {
        responseId: r.response_id,
        receiptId: r.receipt_id,
        anchorDigest: r.anchor_digest,
        responseSequence: r.response_sequence,
        acceptedAt: r.accepted_at.toISOString(),
      };
      assert.deepEqual(actual, original.receipt);
      const observations = os.filter((x) => x.response_id === r.response_id);
      assert.ok(observations.length <= 4);
      assert.deepEqual(
        observations.map((x) => x.observation_sequence),
        observations.map((_, n) => String(n + 1)),
      );
      for (const o of observations) {
        const payload = JSON.parse(o.canonical_payload),
          expected = facts.find((x) => x.source === o.source && x.payload.eventId === o.event_id);
        assert.ok(expected);
        assert.equal(o.binding_id, r.binding_id);
        assert.equal(payload.responseId, r.response_id);
        assert.equal(payload.eventId, o.event_id);
        assert.equal(sha(o.canonical_payload), o.payload_digest);
        assert.deepEqual(payload, expected.payload);
        if (o.source === 'agent_sdk') {
          assert.equal((payload as SdkObservation).generationId, a.generationId);
          assert.equal((payload as SdkObservation).sdkSpeechId, a.sdkSpeechId);
        }
        const receipt = {
          responseId: r.response_id,
          eventId: o.event_id,
          receiptId: o.receipt_id,
          payloadDigest: o.payload_digest,
          observationSequence: o.observation_sequence,
          acceptedAt: o.accepted_at.toISOString(),
        };
        assert.deepEqual(receipt, expected.receipt);
      }
      joins.push({
        anchor: a,
        receipt: actual,
        observations: observations.map((o) => ({
          source: o.source,
          payload: JSON.parse(o.canonical_payload),
          receiptId: o.receipt_id,
          payloadDigest: o.payload_digest,
          observationSequence: o.observation_sequence,
          acceptedAt: o.accepted_at.toISOString(),
        })),
      });
    }
    assert.deepEqual(
      rs.filter((x) => x.account_id === fixture.scope.accountId).map((x) => x.response_sequence),
      ['1', '2', '3', '4', '5', '6', '7', '8', '9'],
    );
    assert.deepEqual(
      rs.filter((x) => x.account_id === evidence.scope.accountId).map((x) => x.response_sequence),
      ['1'],
    );
    assert.equal((await c.query(`SELECT count(*)::integer n FROM ${q('inbox')}`)).rows[0].n, 5);
    assert.equal(
      (await c.query(`SELECT count(*)::integer n FROM ${q('native_bindings')}`)).rows[0].n,
      4,
    );
    assert.equal(load<unknown[]>('communication-operations.json').length, 2);
    save('communication-owner-proof.json', {
      schemaVersion: 1,
      responses: 10,
      observations: 32,
      originalReceiptsStable: true,
      exactIdentityJoins: true,
      operationAcceptances: 2,
      joins,
    });
    return {
      responses: 10,
      observations: 32,
      exactIdentityJoins: true,
      originalReceiptsStable: true,
      legacyPreserved: true,
      noAcknowledgements: true,
    };
  });
}

let stage = 'initializing';
async function main(): Promise<Record<string, unknown>> {
  switch (mode) {
    case 'media-install':
      await install();
      await upgradeChannelSchemaV7(db());
      return {};
    case 'media-seed':
      return mediaSeed();
    case 'media-serve':
      return mediaServe();
    case 'media-verify':
      return mediaVerify();
    case 'cleanup':
    case 'media-cleanup':
      return cleanup();
    case 'install':
      await install();
      return { storageVersion: 6 };
    case 'legacy-seed':
      return legacySeed();
    case 'expiry':
      return expiry();
    case 'exercise':
      return exercise();
    case 'crash':
      return crash();
    case 'replay':
      return replay();
    case 'drift':
      return drift();
    case 'verify':
      return verify();
    case 'upgrade':
      return upgrade();
    case 'upgrade-hold':
      await upgradeChannelSchemaV7(db(), policy, {
        harnessAfterTables: () => barrier('communication_upgrade_ddl'),
      });
      throw Error('upgrade_barrier_returned');
    default:
      throw Error('fixture_mode_unimplemented');
  }
}
try {
  stage = mode;
  const result = await main();
  console.log(
    JSON.stringify({
      schemaVersion: 1,
      status: 'passed',
      mode,
      nodeVersion: process.versions.node,
      storageVersion: 7,
      ...result,
    }),
  );
} catch (error) {
  const channelCodes = new Set([
    'InvalidConfiguration',
    'InvalidEvent',
    'AccessDenied',
    'AssociationRequired',
    'AssociationRejected',
    'IdentityConflict',
    'Overloaded',
    'NotFound',
    'StorageUnavailable',
    'AcknowledgementUnknown',
    'SchemaMismatch',
    'CleanupIncomplete',
    'UpgradeRequired',
    'DispatchClaimLost',
    'DispatchUnavailable',
    'OperationConflict',
  ]);
  const gatewayCodes = new Set([
    'invalid_http',
    'body_limit',
    'body_timeout',
    'request_aborted',
    'capacity',
    'unauthorized',
    'not_found',
    'identity_conflict',
    'storage_unavailable',
    'acknowledgement_unknown',
    'closing',
    'cleanup_incomplete',
  ]);
  const knownChannel = error instanceof ChannelError,
    knownGateway = error instanceof GatewayError;
  const descriptor =
    knownChannel || knownGateway ? Object.getOwnPropertyDescriptor(error, 'code') : undefined;
  const value = descriptor && 'value' in descriptor ? descriptor.value : undefined;
  const code =
    typeof value === 'string' && (knownChannel ? channelCodes.has(value) : gatewayCodes.has(value))
      ? value
      : null;
  const errorType = knownChannel
    ? 'ChannelError'
    : knownGateway
      ? 'GatewayError'
      : error instanceof AssertionError
        ? 'AssertionError'
        : error instanceof Error
          ? 'Error'
          : 'DependencyError';
  const stackDescriptor =
    error && typeof error === 'object'
      ? Object.getOwnPropertyDescriptor(error, 'stack')
      : undefined;
  const stack =
    stackDescriptor && 'value' in stackDescriptor && typeof stackDescriptor.value === 'string'
      ? stackDescriptor.value
      : '';
  const frames = stack
    .split('\n')
    .flatMap((line: string) => {
      const match = /pg_communication_cases\.js:(\d+):\d+/.exec(line);
      return match ? [{ file: 'pg_communication_cases.js', line: Number(match[1]) }] : [];
    })
    .slice(0, 4);
  save('communication-failure-' + mode + '.json', {
    schemaVersion: 1,
    stage,
    errorType,
    code,
    frames,
  });
  console.log(
    JSON.stringify({
      schemaVersion: 1,
      status: 'failed',
      mode,
      code: 'communication_fixture_failed',
    }),
  );
  process.exitCode = 1;
}
