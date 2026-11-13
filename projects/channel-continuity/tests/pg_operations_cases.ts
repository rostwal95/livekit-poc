/** Role-separated local application fixture. Scripted ports are not RTC or carrier qualification. */
import assert from 'node:assert/strict';
import { createHash, createHmac, randomUUID } from 'node:crypto';
import { readFileSync, writeFileSync, linkSync, unlinkSync, existsSync, lstatSync } from 'node:fs';
import { request as httpRequest } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';
import pg from 'pg';
import { parseEventJson, type ProviderScope } from '@livekit-ecosystem/channel-continuity';
import {
  ChannelInbox,
  SeededAccounts,
  ChannelError,
  type DatabaseSettings,
  type StoredMessage,
  type InboxObserver,
} from '@livekit-ecosystem/channel-continuity/postgres';
import {
  createFakeSmsIntegration,
  signFakeSms,
} from '@livekit-ecosystem/channel-continuity/security';
import {
  createNativeIntegration,
  type NativeAcceptance,
} from '@livekit-ecosystem/channel-continuity/native';
import {
  CommunicationInbox,
  createCommunicationIntegration,
  type ResponseAnchor,
  type SdkObservation,
} from '@livekit-ecosystem/channel-continuity/communication';
import {
  ChannelDispatcher,
  type DispatchPorts,
  type OperationReceipt,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import { ChannelOutbox, type SendRequest } from '@livekit-ecosystem/channel-continuity/outbox';
import {
  CallbackInbox,
  createFakeSmsCallbackIntegration,
  signFakeSmsCallback,
  type CallbackObservation,
} from '@livekit-ecosystem/channel-continuity/callbacks';
import {
  ReferenceCaseAuthority,
  installReferenceCaseSchema,
} from '@livekit-ecosystem/channel-continuity/reference-case';
import {
  referenceCurrentCase,
  rehydrationContext,
  RehydrationError,
  type CurrentCasePort,
} from '@livekit-ecosystem/channel-continuity/rehydration';
import {
  OperationsReader,
  OperationsTelemetry,
  OperationsReadServer,
  OperationsHttpClient,
  OperationsError,
  operationsRecord,
  type OperationsProfile,
  type OperationsContext,
} from '@livekit-ecosystem/channel-continuity/operations';
import type { InvestigationRequest } from '@livekit-ecosystem/channel-continuity/routing';
import {
  installChannelSchema,
  upgradeChannelSchemaV2,
  upgradeChannelSchemaV3,
  upgradeChannelSchemaV4,
  upgradeChannelSchemaV5,
  upgradeChannelSchemaV6,
  upgradeChannelSchemaV7,
} from '@livekit-ecosystem/channel-continuity/migrations';
import { startOperationsLab } from '../examples/operations-lab.js';
import {
  cleanupOperationsOwners as cleanupTiers,
  inspectOperationsOriginals,
  normalizeOperationsOriginal,
} from './operations-fixture-work.js';
const MODES = [
  'install',
  'seed',
  'exercise',
  'serve',
  'advance-dispatch',
  'advance-reconcile',
  'advance-callback',
  'verify',
  'reopen',
  'cleanup',
] as const;
type Mode = (typeof MODES)[number];
const mode = process.argv[2] as Mode;
let substage: string = mode;
assert.ok(process.argv.length === 3 && MODES.includes(mode));
const owner = ['install', 'verify', 'cleanup'].includes(mode);
function env(name: string) {
  const value = process.env[name];
  assert.ok(value && value.length <= 4096);
  return value;
}
const DIR = env('P2_OPERATIONS_DIRECTORY'),
  schema = env('P2_OPERATIONS_SCHEMA');
assert.match(schema, /^p2_operations_[0-9a-f]{32}(?![\s\S])/);
const caseSchema = 'p2_case_operations_' + schema.slice(-32);
assert.equal(
  process.env[owner ? 'P2_OPERATIONS_RUNTIME_PASSWORD' : 'P2_OPERATIONS_OWNER_PASSWORD'],
  undefined,
);
type Fixture = {
  schemaVersion: 1;
  owner: string;
  profileId: string;
  sourceId: string;
  scope: { tenantId: string; accountId: string };
  caseId: string;
  conversationId: string;
  providerScope: ProviderScope;
  accountToken: string;
  publisherToken: string;
  nativeToken: string;
  bindingId: string;
  operatorAuthorization: string;
  cursorKeyBase64: string;
  expiresAt: string;
  request: InvestigationRequest;
  ids: {
    main: string;
    history: string[];
    sms: string;
    outbound: string;
    response: string;
    generation: string;
    callback: string;
    revisionCommand: string;
  };
  sms: {
    providerScope: ProviderScope;
    senderId: string;
    hmacKeyBase64: string;
    callbackKeyBase64: string;
  };
  communication: { publisherToken: string; sdkToken: string; browserToken: string };
};
function load<T>(file: string): T {
  const path = DIR + '/' + file,
    st = lstatSync(path);
  assert.ok(
    st.isFile() &&
      !st.isSymbolicLink() &&
      st.uid === process.getuid?.() &&
      (st.mode & 0o077) === 0 &&
      st.size <= 1048576,
  );
  return JSON.parse(readFileSync(path, 'utf8')) as T;
}
function publish(file: string, raw: string) {
  const path = DIR + '/' + file,
    temp = path + '.' + process.pid + '.' + randomUUID() + '.pending';
  writeFileSync(temp, raw, { flag: 'wx', mode: 0o600 });
  try {
    linkSync(temp, path);
  } finally {
    unlinkSync(temp);
  }
}
function save(file: string, value: unknown) {
  publish(file, JSON.stringify(value) + '\n');
}
const f = load<Fixture>('fixture.json');
assert.equal(f.schemaVersion, 1);
assert.match(f.owner, /^[0-9a-f]{32}(?![\s\S])/);
assert.equal(schema.slice(-32), f.owner);
assert.equal(f.ids.history.length, 9);
const sha = (s: string) => createHash('sha256').update(s).digest('hex');
function token(label: string) {
  return createHmac('sha256', f.accountToken)
    .update('p2.ops.fixture.v1:' + label)
    .digest('base64url');
}
function id(label: string) {
  const h = sha(f.profileId + ':' + label);
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
const REF = { scope: f.scope, caseId: f.caseId, conversationId: f.conversationId };
const ZERO = { scope: f.scope, caseId: 'case-zero', conversationId: 'conversation-zero' },
  FOREIGN = {
    scope: { tenantId: f.scope.tenantId, accountId: 'account-foreign' },
    caseId: 'case-foreign',
    conversationId: 'conversation-foreign',
  };
const binding = (name: string) =>
  name === 'main'
    ? {
        bindingId: f.bindingId,
        nativeToken: f.nativeToken,
        roomId: 'operations-main',
        participantId: 'operator-main',
      }
    : {
        bindingId: id(name + '-binding'),
        nativeToken: token(name + '-binding'),
        roomId: 'operations-' + name,
        participantId: 'operator-' + name,
      };
function db(target = schema): DatabaseSettings {
  return {
    host: '127.0.0.1',
    port: Number(env('P2_OPERATIONS_PG_PORT')),
    database: 'livekit_lab',
    user: owner ? 'continuity_migrator' : 'livekit_lab',
    password: env(owner ? 'P2_OPERATIONS_OWNER_PASSWORD' : 'P2_OPERATIONS_RUNTIME_PASSWORD'),
    schema: target,
  };
}
function accounts() {
  return new SeededAccounts([
    { ...f.scope, token: f.accountToken, caseId: f.caseId, conversationId: f.conversationId },
    {
      ...f.scope,
      token: token('zero-account'),
      caseId: ZERO.caseId,
      conversationId: ZERO.conversationId,
    },
    {
      ...FOREIGN.scope,
      token: token('foreign-account'),
      caseId: FOREIGN.caseId,
      conversationId: FOREIGN.conversationId,
    },
  ]);
}
const sms = () =>
  createFakeSmsIntegration(f.sms.providerScope, Buffer.from(f.sms.hmacKeyBase64, 'base64'));
function integration() {
  return createCommunicationIntegration(
    createNativeIntegration(f.providerScope, [
      { ...REF, token: f.publisherToken },
      { ...ZERO, token: token('zero-publisher') },
      { ...FOREIGN, token: token('foreign-publisher') },
    ]),
    [
      { ...REF, ...f.communication },
      {
        ...ZERO,
        publisherToken: token('zero-response'),
        sdkToken: token('zero-sdk'),
        browserToken: token('zero-browser'),
      },
      {
        ...FOREIGN,
        publisherToken: token('foreign-response'),
        sdkToken: token('foreign-sdk'),
        browserToken: token('foreign-browser'),
      },
    ],
  );
}
function inbox(observer: InboxObserver = () => {}) {
  return new CommunicationInbox(db(), integration(), accounts(), {}, observer);
}
function profile(name = 'main'): OperationsProfile {
  const b = binding(name);
  return {
    profileId: name === 'main' ? f.profileId : id(name + '-profile'),
    sourceId: f.sourceId,
    reference: name === 'zero' ? ZERO : name === 'foreign' ? FOREIGN : REF,
    bindingId: b.bindingId,
    nativeToken: b.nativeToken,
    cursorKey: Buffer.from(f.cursorKeyBase64, 'base64'),
  };
}
function authority() {
  return new ReferenceCaseAuthority(
    db(caseSchema),
    [REF, ZERO, FOREIGN].map((r) => ({ scope: r.scope, caseId: r.caseId })),
  );
}
const publication = (name: string, expiresAt = f.expiresAt) => {
  const b = binding(name);
  return {
    bindingId: b.bindingId,
    bearer: b.nativeToken,
    roomId: b.roomId,
    participantId: b.participantId,
    expiresAt,
  };
};
const input = (inputId: string) => ({
  schemaVersion: 1 as const,
  inputId,
  channel: 'web_chat' as const,
  body: 'INVESTIGATE ' + inputId,
  roomId: binding('main').roomId,
  participantId: binding('main').participantId,
});
const signed = (eventId: string, body: string) =>
  signFakeSms(
    {
      schemaVersion: 1,
      eventId,
      messageId: eventId,
      senderId: f.sms.senderId,
      body,
      occurredAt: '2030-01-01T00:00:00.000Z',
    },
    Buffer.from(f.sms.hmacKeyBase64, 'base64'),
    Math.floor(Date.now() / 1000),
    f.sms.providerScope,
  );
async function closeAll(actions: readonly (() => Promise<unknown>)[]) {
  let failure: unknown;
  for (const action of actions)
    try {
      await action();
    } catch (error) {
      failure ??= error;
    }
  if (failure) throw failure;
}

function reached(stem: string) {
  publish(stem + '.reached', String(process.pid) + '\n');
}
async function barrier(stem: string, maximum = 4000) {
  reached(stem);
  const end = performance.now() + maximum;
  while (!existsSync(DIR + '/' + stem + '.released')) {
    if (performance.now() >= end) throw new OperationsError('unavailable');
    await delay(5);
  }
  assert.equal(readFileSync(DIR + '/' + stem + '.released', 'utf8'), String(process.pid) + '\n');
}
const completed = new Set<string>();
const CASES = [
  'fixed_operator_capability_and_current_grant',
  'request_body_and_scope_selector_denied',
  'source_scope_section_cursor_binding',
  'ahead_missing_anchor_and_stale_case_cursor_denied',
  'bounded_get_header_host_body_and_client_framing',
  'durable_accepted_pending_running_projection',
  'uncertain_then_known_after_explicit_observation',
  'ordinary_send_unknown_and_callback_separate',
  'bounded_paging_and_canonical_identity_preserved',
  'read_only_zero_revision_and_non_atomic_as_of',
  'safe_read_error_and_same_read_retry',
  'late_read_fenced_and_close_retains_owner',
  'read_admission_overload_and_later_progress',
  'held_throwing_exporter_isolated_and_bounded',
  'real_safe_span_and_finite_metric_labels',
  'fresh_process_original_projection_and_zero_read_writes',
] as const;
const TABLES = [
  'admission',
  'associations',
  'callback_admission',
  'callback_observations',
  'callback_settings',
  'challenges',
  'communication_settings',
  'conversations',
  'dispatch_attempts',
  'dispatch_plans',
  'dispatch_settings',
  'inbox',
  'native_bindings',
  'native_observations',
  'native_responses',
  'native_settings',
  'outbound_routes',
  'outbox_admission',
  'outbox_settings',
  'processing_intents',
  'reply_intents',
  'schema_metadata',
  'send_attempts',
  'send_operations',
  'send_policy_settings',
  'send_recovery_commands',
  'send_recovery_observations',
  'send_results',
  'sender_heads',
];
type Snapshot = {
  schema: string;
  caseSchema: string;
  tables: Record<string, unknown[]>;
  caseTables: Record<string, unknown[]>;
};
async function sql<T>(action: (client: pg.Client) => Promise<T>) {
  const c = new pg.Client({
    ...db(),
    ssl: false,
    application_name: 'p2-operations-' + mode,
    connectionTimeoutMillis: 1000,
    statement_timeout: 2000,
  });
  await c.connect();
  try {
    return await action(c);
  } finally {
    await c.end();
  }
}
async function snapshot(): Promise<Snapshot> {
  return sql(async (c) => {
    const names = (
      await c.query('SELECT tablename FROM pg_tables WHERE schemaname=$1 ORDER BY tablename', [
        schema,
      ])
    ).rows.map((r) => r.tablename);
    assert.deepEqual(names, TABLES);
    const tables: Record<string, unknown[]> = {},
      caseTables: Record<string, unknown[]> = {};
    for (const name of TABLES)
      tables[name] = (
        await c.query(
          `SELECT to_jsonb(t) AS row FROM "${schema}"."${name}" t ORDER BY to_jsonb(t)::text`,
        )
      ).rows.map((r) => r.row);
    for (const name of ['case_metadata', 'cases'])
      caseTables[name] = (
        await c.query(
          `SELECT to_jsonb(t) AS row FROM "${caseSchema}"."${name}" t ORDER BY to_jsonb(t)::text`,
        )
      ).rows.map((r) => r.row);
    return { schema, caseSchema, tables, caseTables };
  });
}
async function install() {
  await installChannelSchema(db(), {
    maxInbox: 64,
    maxAssociations: 16,
    maxSenders: 8,
    maxChallenges: 16,
  });
  await upgradeChannelSchemaV2(db());
  await upgradeChannelSchemaV3(db(), { maxReplies: 8, maxRoutes: 4, maxAttempts: 5 });
  await upgradeChannelSchemaV4(db(), { maxGlobal: 16, maxPerAttempt: 8 });
  await upgradeChannelSchemaV5(db());
  await upgradeChannelSchemaV6(db(), { maxBindings: 8 });
  await upgradeChannelSchemaV7(db(), {
    maxResponses: 16,
    maxObservations: 64,
    maxObservationsPerResponse: 8,
  });
  await installReferenceCaseSchema(
    db(caseSchema),
    [REF, ZERO, FOREIGN].map((ref) => ({
      scope: ref.scope,
      caseId: ref.caseId,
      revision: ref === ZERO ? '0' : '1',
      request: f.request,
      cancelled: false,
      committed: false,
    })),
  );
  return { installed: true, currentCaseSource: 'standalone_reference_v1' };
}
async function cleanup() {
  assert.ok(owner);
  await sql(async (c) => {
    for (const [name, marker] of [
      [schema, 'p2-channel-schema-v7'],
      [caseSchema, 'p2-reference-case-v1'],
    ]) {
      const rows = (
        await c.query(
          "SELECT pg_get_userbyid(nspowner) owner,obj_description(oid,'pg_namespace') marker FROM pg_namespace WHERE nspname=$1",
          [name],
        )
      ).rows;
      if (rows.length) {
        assert.equal(rows.length, 1);
        assert.equal(rows[0].owner, 'continuity_migrator');
        assert.equal(rows[0].marker, marker);
        await c.query('DROP SCHEMA "' + name + '" CASCADE');
      }
      assert.equal(
        (
          await c.query(
            'SELECT1 FROM pg_namespace WHERE nspname=$1'.replace('SELECT1', 'SELECT 1'),
            [name],
          )
        ).rowCount,
        0,
      );
    }
  });
  return { ownedSchemasAbsent: true };
}
type SeedProof = {
  accepted: NativeAcceptance[];
  sms: { signed: { rawBase64: string; headers: unknown }; stored: StoredMessage };
  reply: unknown;
  sendRequest: SendRequest;
  sendOutcome: unknown;
  stored: StoredMessage[];
};
async function seed() {
  const i = inbox(),
    s = new ChannelInbox(db(), sms(), accounts(), {}, () => {});
  let sendRequest: SendRequest | undefined;
  const box = new ChannelOutbox(
    db(),
    sms(),
    accounts(),
    [{ ...REF, token: token('outbox-publisher') }],
    {
      capabilities: 'ordinary_fake_sms_v1',
      async send(request) {
        sendRequest = request;
        throw new Error('scripted_lost_response');
      },
    },
    { observer: () => {} },
  );
  let originalFailure: unknown;
  try {
    substage = 'seed_bindings';
    for (const name of ['main', 'zero', 'foreign', 'revoked'])
      await i.bind(
        name === 'zero'
          ? token('zero-publisher')
          : name === 'foreign'
            ? token('foreign-publisher')
            : f.publisherToken,
        publication(name),
      );
    substage = 'seed_native_inputs';
    const accepted: NativeAcceptance[] = [];
    for (const inputId of f.ids.history)
      accepted.push(await i.accept(f.nativeToken, input(inputId)));
    accepted.unshift(await i.accept(f.nativeToken, input(f.ids.main)));
    substage = 'seed_sms_association';
    const challenge = await s.createChallenge(f.accountToken, f.sms.senderId),
      link = signed(id('association'), 'LINK ' + challenge.challengeId + ' ' + challenge.secret);
    const associated = await s.completeAssociation(link.raw, link.headers);
    substage = 'seed_sms_accept';
    const message = signed(f.ids.sms, 'Retained fake SMS observation'),
      smsAccepted = await s.acceptSms(message.raw, message.headers);
    substage = 'seed_outbound_route';
    await box.selectRoute(f.accountToken, {
      senderId: f.sms.senderId,
      associationVersion: associated.associationVersion,
      expectedRouteVersion: '0',
    });
    substage = 'seed_outbound_enqueue_send';
    const reply = await box.enqueue(token('outbox-publisher'), {
        schemaVersion: 1,
        outboundId: f.ids.outbound,
        responseId: f.ids.response,
        body: 'Scripted read-only operations notice',
      }),
      outcome = await box.send(f.accountToken, f.ids.outbound);
    assert.equal(outcome.status, 'unknown');
    assert.ok(sendRequest);
    substage = 'seed_collect_originals';
    const stored = await inspectOperationsOriginals(accepted, (a) =>
      i.inspect(f.accountToken, a.receiptId),
    );
    const proof: SeedProof = {
      accepted,
      sms: {
        signed: {
          rawBase64: Buffer.from(message.raw).toString('base64'),
          headers: message.headers,
        },
        stored: await s.inspect(f.accountToken, smsAccepted.receipt.receiptId),
      },
      reply,
      sendRequest,
      sendOutcome: outcome,
      stored: [...stored],
    };
    substage = 'seed_save_originals';
    save('operations-seed-proof.json', proof);
    return {
      nativeInputs: 10,
      smsInputs: 1,
      nativeBindings: 4,
      outboundReplies: 1,
      ordinaryProviderCalls: 1,
      ordinarySendResult: 'unknown',
    };
  } catch (error) {
    originalFailure = error;
    throw error;
  } finally {
    await cleanupTiers([[() => box.close(), () => i.close(), () => s.close()]], originalFailure);
  }
}

type Ledger = {
  submission: unknown;
  canonicalPayload: string;
  payloadDigest: string;
  receipt: OperationReceipt;
};
function dispatchPorts(a: ReferenceCaseAuthority, wait = false): DispatchPorts {
  return {
    cases: {
      async inspect(ref, signal) {
        const c = await a.inspect(ref, signal);
        return {
          scope: c.scope,
          caseId: c.caseId,
          revision: c.revision,
          source: 'synthetic_read_only',
        };
      },
    },
    agent: {
      async prepare(v) {
        if (wait) await barrier('operations_dispatch_entered');
        return { kind: 'investigation', source: 'scripted', caseRevision: v.currentCase.revision };
      },
    },
    operations: {
      capabilities: 'stable_idempotency_and_lookup',
      async lookup(v) {
        if (!existsSync(DIR + '/operations-provider-ledger.json')) return { status: 'absent' };
        const rows = load<Ledger[]>('operations-provider-ledger.json'),
          r = rows.find((r) => r.receipt.operationKey === v.operationKey);
        if (!r) return { status: 'absent' };
        assert.equal(r.payloadDigest, v.payloadDigest);
        assert.deepEqual(r.receipt.scope, v.scope);
        return { status: 'accepted', receipt: r.receipt };
      },
      async accept(v) {
        assert.equal(existsSync(DIR + '/operations-provider-ledger.json'), false);
        const receipt = {
          scope: v.submission.scope,
          operationKey: v.submission.operationKey,
          payloadDigest: v.payloadDigest,
          receiptId: randomUUID(),
        };
        save('operations-provider-ledger.json', [
          {
            submission: v.submission,
            canonicalPayload: v.canonicalPayload,
            payloadDigest: v.payloadDigest,
            receipt,
          },
        ]);
        throw new ChannelError('AcknowledgementUnknown');
      },
    },
  };
}
async function advanceDispatch() {
  const seed = load<SeedProof>('operations-seed-proof.json'),
    a = authority(),
    d = new ChannelDispatcher(db(), integration(), accounts(), dispatchPorts(a, true), {
      timeoutMs: 5000,
      observer: () => {},
    });
  let originalFailure: unknown;
  try {
    const before = await d.inspect(f.accountToken, seed.accepted[0]!.receiptId);
    assert.equal(before.state, 'pending');
    await assert.rejects(
      () => d.step(f.accountToken, before.receiptId),
      (error: unknown) => error instanceof ChannelError && error.code === 'AcknowledgementUnknown',
    );
    const after = await d.inspect(f.accountToken, before.receiptId);
    assert.equal(after.state, 'uncertain');
    const ledger = load<Ledger[]>('operations-provider-ledger.json');
    assert.equal(ledger.length, 1);
    assert.equal(ledger[0]!.receipt.operationKey, before.operationKey);
    save('operations-dispatch-proof.json', {
      schemaVersion: 1,
      before,
      after,
      callerCode: 'AcknowledgementUnknown',
      logicalOperationAcceptances: 1,
      possibleProviderCalls: 1,
    });
    return {
      processingState: 'uncertain',
      logicalOperationAcceptances: 1,
      possibleProviderCalls: 1,
    };
  } catch (error) {
    originalFailure = error;
    throw error;
  } finally {
    await cleanupTiers([[() => d.close()], [() => a.close()]], originalFailure);
  }
}
async function advanceReconcile() {
  const seed = load<SeedProof>('operations-seed-proof.json'),
    i = inbox(),
    a = authority(),
    d = new ChannelDispatcher(db(), integration(), accounts(), dispatchPorts(a), {
      timeoutMs: 5000,
      observer: () => {},
    });
  let originalFailure: unknown;
  try {
    const receiptId = seed.accepted[0]!.receiptId;
    const end = performance.now() + 3000;
    await sql(async (c) => {
      while (true) {
        const row = (
          await c.query(
            `SELECT next_attempt_at<=clock_timestamp() eligible FROM "${schema}".processing_intents WHERE receipt_id=$1`,
            [receiptId],
          )
        ).rows[0];
        if (row?.eligible === true) return;
        assert.ok(performance.now() < end);
        await delay(5);
      }
    });
    const result = await d.step(f.accountToken, receiptId);
    assert.equal(result.status, 'dispatched');
    // Actual phase boundary: retire dispatcher/case connections before response publication.
    await d.close();
    await a.close();
    if (result.status === 'dispatched') assert.equal(result.reconciled, true);
    const original = load<Ledger[]>('operations-provider-ledger.json');
    assert.equal(original.length, 1);
    const accepted = seed.accepted[0]!;
    const anchor: ResponseAnchor = {
      schemaVersion: 1,
      responseId: f.ids.response,
      generationId: f.ids.generation,
      sdkSpeechId: 'scripted-operations-speech',
      bindingId: f.bindingId,
      inputId: f.ids.main,
      receiptId: accepted.receiptId,
      operationKey: accepted.operationKey,
      caseRevision: '2',
    };
    const response = await i.beginResponse(f.communication.publisherToken, anchor);
    const facts: SdkObservation[] = [
      {
        schemaVersion: 1,
        eventId: id('generated-fact'),
        responseId: anchor.responseId,
        generationId: anchor.generationId,
        sdkSpeechId: anchor.sdkSpeechId,
        fact: {
          type: 'generated_complete',
          text: 'Synthetic fixture publication, not actual SDK generation.',
        },
      },
      {
        schemaVersion: 1,
        eventId: id('sdk-fact'),
        responseId: anchor.responseId,
        generationId: anchor.generationId,
        sdkSpeechId: anchor.sdkSpeechId,
        fact: {
          type: 'speech_settled',
          state: 'completed',
          sdkText: 'Synthetic fixture publication, not actual SDK generation.',
        },
      },
    ];
    const observations = [];
    for (const fact of facts) observations.push(await i.observeSdk(f.communication.sdkToken, fact));
    save('operations-reconcile-proof.json', {
      schemaVersion: 1,
      result,
      anchor,
      response,
      facts,
      observations,
      ledger: original,
      operationLookups: 1,
      newOperationAcceptances: 0,
    });
    return {
      processingState: 'dispatched',
      logicalOperationAcceptances: 1,
      operationLookups: 1,
      newOperationAcceptances: 0,
      nativeResponses: 1,
      sdkFacts: 2,
    };
  } catch (error) {
    originalFailure = error;
    throw error;
  } finally {
    await cleanupTiers([[() => d.close()], [() => i.close(), () => a.close()]], originalFailure);
  }
}
async function advanceCallback() {
  const seed = load<SeedProof>('operations-seed-proof.json'),
    r = seed.sendRequest,
    key = Buffer.from(f.sms.callbackKeyBase64, 'base64');
  const cb = new CallbackInbox(
    db(),
    createFakeSmsCallbackIntegration(f.sms.providerScope, key),
    accounts(),
    { observer: () => {} },
  );
  let originalFailure: unknown;
  try {
    const observation: CallbackObservation = {
      schemaVersion: 1,
      eventId: f.ids.callback,
      attemptId: r.attemptId,
      providerOperationKey: r.providerOperationKey,
      requestDigest: sha(JSON.stringify(r)),
      state: 'delivered',
      occurredAt: '2030-01-01T00:00:01.000Z',
      providerMessageId: 'scripted-provider-message',
    };
    const signed = signFakeSmsCallback(
        observation,
        key,
        Math.floor(Date.now() / 1000),
        f.sms.providerScope,
      ),
      receipt = await cb.accept(signed.raw, signed.headers),
      view = await cb.inspectAttempt(f.accountToken, {
        outboundId: r.outboundId,
        attemptId: r.attemptId,
      });
    assert.equal(view.evidence.strongestReported, 'delivered');
    assert.equal(view.evidence.sendResult, null);
    save('operations-callback-proof.json', {
      schemaVersion: 1,
      observation,
      rawBase64: Buffer.from(signed.raw).toString('base64'),
      headers: signed.headers,
      receipt,
      view,
      newSendCalls: 0,
    });
    return {
      callbackObservations: 1,
      strongestReported: 'delivered',
      ordinarySendResult: 'unknown',
      newSendCalls: 0,
    };
  } catch (error) {
    originalFailure = error;
    throw error;
  } finally {
    await cleanupTiers([[() => cb.close()]], originalFailure);
  }
}
function testMarker(name: string) {
  const file = DIR + '/operations-' + name + '.json';
  if (!existsSync(file)) return false;
  const raw = load<unknown>('operations-' + name + '.json'),
    r = operationsRecord(raw, ['schemaVersion', 'owner', 'stage']);
  assert.equal(r.schemaVersion, 1);
  assert.equal(r.owner, f.owner);
  assert.equal(r.stage, name);
  return true;
}
async function serve() {
  let stopping = false;
  const stop = () => {
    stopping = true;
  };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
  let producerLog: (value: unknown) => void = () => {};
  const i = inbox((value) => producerLog(value)),
    a = authority(),
    base = referenceCurrentCase(a);
  let failRead = false,
    failedOnce = false,
    heldRead = false,
    releasedRead = false;
  let releaseRead: () => void = () => {};
  const heldReadWork = new Promise<void>((resolve) => {
    releaseRead = resolve;
  });
  const cases: CurrentCasePort = {
    async inspect(ref, signal) {
      if (!failedOnce && testMarker('read-failure')) {
        failedOnce = true;
        failRead = true;
      }
      if (!heldRead && testMarker('hold-read')) {
        heldRead = true;
        save('operations-read-held.json', {
          schemaVersion: 1,
          owner: f.owner,
          stage: 'read-held',
          pid: process.pid,
          readerActive: app.reader.metrics().active,
        });
        await heldReadWork;
      }
      if (failRead) {
        failRead = false;
        throw new RehydrationError('context_unavailable');
      }
      return base.inspect(ref, signal);
    },
  };
  let release: () => void = () => {};
  const exportHeld = new Promise<void>((_resolve, reject) => {
    release = () => reject(new Error('scripted_exporter_failure'));
  });
  void exportHeld.catch(() => {});
  const app = await startOperationsLab({
    inbox: i,
    cases,
    sms: sms(),
    profile: profile(),
    authorization: f.operatorAuthorization,
    observer: () => exportHeld,
  });
  producerLog = app.telemetry.observer('inbox');
  let failure: unknown;
  let released = false;
  let finalContext: OperationsContext | undefined;
  let finalTelemetry: unknown;
  let preflightIntakeReplay: NativeAcceptance | undefined;
  try {
    const preflight = new OperationsHttpClient(app.endpoint, f.operatorAuthorization, {
      reference: REF,
      bindingId: f.bindingId,
    });
    try {
      for (let n = 0; n < 12; n++) await preflight.context();
    } finally {
      await preflight.close();
    }
    assert.equal(app.telemetry.metrics().observerPending, 8);
    assert.ok(app.telemetry.metrics().observerDropped! >= 4);
    preflightIntakeReplay = await i.accept(f.nativeToken, input(f.ids.main));
    assert.equal(preflightIntakeReplay.status, 'replayed');
    assert.equal(
      preflightIntakeReplay.receiptId,
      load<SeedProof>('operations-seed-proof.json').accepted[0]!.receiptId,
    );
    save('operations-endpoint.json', { schemaVersion: 1, ...app.endpoint, pid: process.pid });
    reached('operations_ready');
    const end = performance.now() + 180000;
    while (!stopping) {
      assert.ok(performance.now() < end);
      if (heldRead && !releasedRead && testMarker('release-read')) {
        releasedRead = true;
        const afterForget = { readerActive: app.reader.metrics().active };
        assert.equal(afterForget.readerActive, 1);
        releaseRead();
        const until = performance.now() + 2000;
        while (app.reader.metrics().active !== 0) {
          assert.ok(performance.now() < until);
          await delay(2);
        }
        save('operations-late-read-proof.json', {
          schemaVersion: 1,
          owner: f.owner,
          pid: process.pid,
          afterForget,
          afterRelease: { readerActive: app.reader.metrics().active },
        });
      }
      if (!released && testMarker('release-exporter')) {
        released = true;
        release();
      }
      if (testMarker('browser-finished')) break;
      await delay(5);
    }
    assert.equal(testMarker('browser-finished'), true);
    assert.equal(failedOnce, true);
    assert.equal(released, true);
    assert.equal(heldRead, true);
    assert.equal(releasedRead, true);
    finalContext = await app.reader.read(randomUUID());
    save('operations-original-context.json', finalContext);
    const lastClient = new OperationsHttpClient(app.endpoint, f.operatorAuthorization, {
      reference: REF,
      bindingId: f.bindingId,
    });
    try {
      finalTelemetry = await lastClient.telemetry();
    } finally {
      await lastClient.close();
    }
  } catch (error) {
    failure = error;
  } finally {
    releaseRead();
    release();
    let appClosed = false;
    try {
      await app.close();
      appClosed = true;
    } catch (error) {
      failure ??= error;
    }
    const metrics = {
      http: app.server.metrics(),
      reader: app.reader.metrics(),
      telemetry: app.telemetry.metrics(),
      inbox: i.metrics(),
      inboxTelemetry: i.telemetryMetrics(),
    };
    if (appClosed)
      try {
        await closeAll([() => i.close(), () => a.close()]);
      } catch (error) {
        failure ??= error;
      }
    process.off('SIGTERM', stop);
    process.off('SIGINT', stop);
    if (!failure) {
      save('operations-server-proof.json', {
        schemaVersion: 1,
        metrics,
        diagnostics: finalTelemetry,
        preflightReads: 12,
        preflightIntakeReplay,
        failedReadRequested: failedOnce,
        exporterReleased: released,
        lateReadHeld: heldRead,
        lateReadReleased: releasedRead,
        finalContextId: finalContext!.context.contextId,
      });
    }
  }
  if (failure) throw failure;
  const t = app.telemetry.metrics();
  assert.equal(t.observerPending, 0);
  assert.equal(t.getterPending, 0);
  assert.ok(t.observerFailures! >= 1);
  assert.ok(t.observerDropped! >= 1);
  return {
    httpClosed: true,
    readerClosed: true,
    telemetryClosed: true,
    inboxClosed: true,
    casePortClosed: true,
    readerActive: 0,
    httpHandlers: 0,
    httpSockets: 0,
    observerPending: 0,
    getterPending: 0,
    exporterFailures: t.observerFailures,
    exporterDropped: t.observerDropped,
  };
}
function facts(v: OperationsContext) {
  const context = rehydrationContext(v.context, REF);
  return {
    access: context.access,
    case: context.case,
    history: context.history,
    work: context.work,
    responses: context.responses,
    replies: context.replies,
  };
}
async function reopen() {
  const before = await snapshot(),
    original = load<OperationsContext>('operations-original-context.json'),
    i = inbox(),
    a = authority(),
    reader = new OperationsReader(i, referenceCurrentCase(a), sms(), profile());
  let originalFailure: unknown;
  try {
    const fresh = await reader.read(randomUUID());
    assert.deepEqual(facts(fresh), facts(original));
    const cursor = load<{ cursor: string }>('operations-exercise-proof.json').cursor;
    const page = await reader.read(randomUUID(), { section: 'history', cursor });
    assert.ok(page.context.history.messages.length >= 1);
    const after = await snapshot();
    assert.deepEqual(after, before);
    save('operations-reopen-proof.json', {
      schemaVersion: 1,
      original: original.context.contextId,
      fresh,
      page,
      before,
      after,
      newPrepareCalls: 0,
      newOperationCalls: 0,
      newSendCalls: 0,
    });
    return {
      completedGroups: [CASES[15]],
      sameOriginalFacts: true,
      sameSignedCursor: true,
      newPrepareCalls: 0,
      newOperationCalls: 0,
      newSendCalls: 0,
      readWrites: 0,
    };
  } catch (error) {
    originalFailure = error;
    throw error;
  } finally {
    await cleanupTiers(
      [[() => reader.close()], [() => i.close(), () => a.close()]],
      originalFailure,
    );
  }
}
async function verify() {
  assert.ok(owner);
  const value = await snapshot(),
    rows = value.tables;
  assert.equal(rows.inbox!.length, 11);
  assert.equal(rows.processing_intents!.length, 11);
  assert.equal(rows.native_bindings!.length, 5);
  assert.equal(rows.dispatch_plans!.length, 1);
  assert.equal(rows.native_responses!.length, 1);
  assert.equal(rows.native_observations!.length, 2);
  assert.equal(rows.reply_intents!.length, 1);
  assert.equal(rows.send_attempts!.length, 1);
  assert.equal(rows.send_results!.length, 0);
  assert.equal(rows.callback_observations!.length, 1);
  const seed = load<SeedProof>('operations-seed-proof.json'),
    ledger = load<Ledger[]>('operations-provider-ledger.json');
  assert.equal(ledger.length, 1);
  for (const original of [...seed.stored, seed.sms.stored]) {
    const matching = (rows.inbox! as Array<Record<string, unknown>>).filter(
      (r) => r.receipt_id === original.receipt.receiptId,
    );
    assert.equal(matching.length, 1);
    const decoded = parseEventJson(matching[0]!.wire_json as string, {
      providerScope: original.event.providerScope,
      accountScope: original.event.accountScope!,
    });
    assert.equal(decoded.canonical, matching[0]!.canonical_payload);
    assert.equal(JSON.stringify(decoded.event), JSON.stringify(original.event));
    assert.equal(matching[0]!.event_id, original.event.eventId);
    const intent = (rows.processing_intents! as Array<Record<string, unknown>>).find(
      (r) => r.receipt_id === original.receipt.receiptId,
    );
    assert.equal(intent!.operation_key, original.operationKey);
  }
  const l = ledger[0]!;
  assert.equal(sha(l.canonicalPayload), l.payloadDigest);
  assert.deepEqual(JSON.parse(l.canonicalPayload), l.submission);
  assert.equal(l.receipt.operationKey, seed.accepted[0]!.operationKey);
  save('operations-owner-proof.json', value);
  return {
    completedGroups: CASES.slice(0, 15),
    nativeInputs: 10,
    smsInputs: 1,
    processingIntents: 11,
    nativeBindings: 5,
    preparedPlans: 1,
    operationAcceptances: 1,
    nativeResponses: 1,
    sdkFacts: 2,
    outboundReplies: 1,
    sendAttempts: 1,
    sendResults: 0,
    callbackObservations: 1,
    readWrites: 0,
    exactIdentityJoins: true,
  };
}

async function expectCode(work: Promise<unknown>, code: string) {
  await assert.rejects(
    () => work,
    (error: unknown) => error instanceof OperationsError && error.code === code,
  );
}
async function enteredOrSettled(entry: Promise<void>, work: Promise<unknown>) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const result = await Promise.race([
      entry.then(() => true),
      work.then(
        () => false,
        () => false,
      ),
      new Promise<false>((resolve) => {
        timer = setTimeout(() => resolve(false), 2000);
      }),
    ]);
    assert.equal(result, true);
  } finally {
    clearTimeout(timer);
  }
}
async function raw(
  endpoint: { port: number },
  path: string,
  headers: Record<string, string> = {},
  method = 'GET',
) {
  return new Promise<{ status: number; value: unknown }>((resolve, reject) => {
    const req = httpRequest(
      {
        host: '127.0.0.1',
        port: endpoint.port,
        path,
        method,
        agent: false,
        headers: {
          Host: `127.0.0.1:${endpoint.port}`,
          Connection: 'close',
          Authorization: f.operatorAuthorization,
          'x-p2-request-id': randomUUID(),
          ...headers,
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        let bytes = 0;
        res.on('data', (b: Buffer) => {
          bytes += b.length;
          if (bytes > 73728) {
            req.destroy();
            reject(new OperationsError());
          } else chunks.push(Buffer.from(b));
        });
        res.once('end', () => {
          try {
            resolve({
              status: res.statusCode!,
              value: JSON.parse(Buffer.concat(chunks).toString()) as unknown,
            });
          } catch {
            reject(new OperationsError());
          }
        });
        res.once('error', () => reject(new OperationsError()));
      },
    );
    req.once('error', () => reject(new OperationsError()));
    req.end();
  });
}
async function exercise() {
  let producerLog: (value: unknown) => void = () => {};
  const i = inbox((value) => producerLog(value)),
    a = authority(),
    base = referenceCurrentCase(a),
    reader = new OperationsReader(i, base, sms(), profile());
  const ownedReaders: OperationsReader[] = [reader];
  let releaseExpiry = () => {},
    releaseRevoke = () => {},
    releaseIgnored = () => {},
    releaseExport = () => {};
  let server: OperationsReadServer | undefined,
    client: OperationsHttpClient | undefined,
    telemetry: OperationsTelemetry | undefined;
  const setupMutations: unknown[] = [];
  let originalFailure: unknown;
  try {
    substage = 'exercise_initial_context';
    const first = await reader.read(randomUUID());
    assert.equal(first.context.case.revision, '1');
    assert.equal(first.context.history.messages.length, 8);
    assert.equal(first.context.history.hasMore, true);
    assert.ok(first.cursors.history);
    const oldCursor = first.cursors.history;
    substage = 'exercise_case_revision_cursor';
    const revision = await a.revise(
      {
        scope: REF.scope,
        caseId: REF.caseId,
        expectedRevision: '1',
        request: { ...f.request, newCheckIn: '2030-12-11' },
      },
      new AbortController().signal,
    );
    assert.equal(revision.revision, '2');
    setupMutations.push({ kind: 'case_revision', revision });
    await expectCode(
      reader.read(randomUUID(), { section: 'history', cursor: oldCursor }),
      'cursor_stale',
    );
    const current = await reader.read(randomUUID()),
      cursor = current.cursors.history;
    assert.ok(cursor);
    substage = 'exercise_expiry_final_grant';
    const expiryAt = new Date(Date.now() + 1500).toISOString(),
      expiredPublished = await i.bind(f.publisherToken, publication('expired', expiryAt));
    setupMutations.push({ kind: 'native_binding_publish', receipt: expiredPublished });
    let expireEntered = () => {};
    const expiryEntry = new Promise<void>((resolve) => {
      expireEntered = resolve;
    });
    const expiryHeld = new Promise<void>((resolve) => {
      releaseExpiry = resolve;
    });
    const expired = new OperationsReader(
      i,
      {
        async inspect(ref, signal) {
          expireEntered();
          await expiryHeld;
          return base.inspect(ref, signal);
        },
      },
      sms(),
      profile('expired'),
    );
    ownedReaders.push(expired);
    const expiryWork = expired.read(randomUUID());
    void expiryWork.catch(() => {});
    await enteredOrSettled(expiryEntry, expiryWork);
    let caseEnteredAt = '';
    let dbExpiredAt = '';
    await sql(async (c) => {
      const end = performance.now() + 2000;
      while (true) {
        const now = (await c.query("SELECT date_trunc('milliseconds',clock_timestamp()) AS now"))
          .rows[0]?.now;
        assert.ok(now instanceof Date);
        if (!caseEnteredAt) {
          caseEnteredAt = now.toISOString();
          assert.ok(now.getTime() < Date.parse(expiryAt));
        }
        if (now.getTime() >= Date.parse(expiryAt)) {
          dbExpiredAt = now.toISOString();
          return;
        }
        assert.ok(performance.now() < end);
        await delay(5);
      }
    });
    releaseExpiry();
    await expectCode(expiryWork, 'access_denied');
    await expired.close();
    substage = 'exercise_revocation_final_grant';
    let revokeEntered = () => {};
    const revokeEntry = new Promise<void>((resolve) => {
        revokeEntered = resolve;
      }),
      revokeHeld = new Promise<void>((resolve) => {
        releaseRevoke = resolve;
      });
    const revoked = new OperationsReader(
      i,
      {
        async inspect(ref, signal) {
          revokeEntered();
          await revokeHeld;
          return base.inspect(ref, signal);
        },
      },
      sms(),
      profile('revoked'),
    );
    ownedReaders.push(revoked);
    const revokeWork = revoked.read(randomUUID());
    void revokeWork.catch(() => {});
    await enteredOrSettled(revokeEntry, revokeWork);
    const revocation = await i.revoke(f.publisherToken, binding('revoked').bindingId);
    setupMutations.push({ kind: 'native_binding_revoke', receipt: revocation });
    releaseRevoke();
    await expectCode(revokeWork, 'access_denied');
    await revoked.close();
    substage = 'exercise_cursor_scope_section';
    const beforeRead = await snapshot();
    for (const section of ['work', 'responses', 'replies'] as const)
      await expectCode(reader.read(randomUUID(), { section, cursor }), 'invalid_query');
    const differentSource = new OperationsReader(i, base, sms(), {
        ...profile(),
        sourceId: 'different-trusted-source',
      }),
      foreign = new OperationsReader(i, base, sms(), profile('foreign')),
      zero = new OperationsReader(i, base, sms(), profile('zero'));
    ownedReaders.push(differentSource, foreign, zero);
    await expectCode(
      differentSource.read(randomUUID(), { section: 'history', cursor }),
      'invalid_query',
    );
    await expectCode(foreign.read(randomUUID(), { section: 'history', cursor }), 'invalid_query');
    const foreignContext = await foreign.read(randomUUID());
    assert.equal(foreignContext.context.case.scope.accountId, FOREIGN.scope.accountId);
    assert.equal(foreignContext.context.history.messages.length, 0);
    substage = 'exercise_cursor_anchor';
    const payload = JSON.parse(Buffer.from(cursor.split('.')[0]!, 'base64url').toString()) as {
      anchor: { id: string; position: string };
      cursor: { beforeSequence: string };
      scopeDigest: string;
    };
    function signedCursor(value: unknown) {
      const bytes = Buffer.from(JSON.stringify(value));
      return (
        bytes.toString('base64url') +
        '.' +
        createHmac('sha256', Buffer.from(f.cursorKeyBase64, 'base64'))
          .update(bytes)
          .digest('base64url')
      );
    }
    for (const changed of [
      { ...payload, anchor: { ...payload.anchor, id: id('missing-anchor') } },
      {
        ...payload,
        anchor: { ...payload.anchor, position: '9223372036854775807' },
        cursor: { ...payload.cursor, beforeSequence: '9223372036854775807' },
      },
      { ...payload, scopeDigest: 'c'.repeat(64) },
    ])
      await expectCode(
        reader.read(randomUUID(), { section: 'history', cursor: signedCursor(changed) }),
        'invalid_query',
      );
    substage = 'exercise_canonical_paging';
    const page = await reader.read(randomUUID(), { section: 'history', cursor });
    assert.equal(page.context.history.messages.length, 3);
    assert.equal(page.context.history.hasMore, false);
    const all = [...current.context.history.messages, ...page.context.history.messages];
    assert.equal(new Set(all.map((m) => m.receipt.receiptId)).size, 11);
    const originals = load<SeedProof>('operations-seed-proof.json');
    for (const original of [...originals.stored, originals.sms.stored]) {
      const result = all.find((m) => m.receipt.receiptId === original.receipt.receiptId);
      assert.ok(result);
      assert.deepEqual(result, normalizeOperationsOriginal(page.context, original));
    }
    substage = 'exercise_zero_revision';
    const zeroContext = await zero.read(randomUUID());
    assert.equal(zeroContext.context.case.revision, '0');
    assert.equal(zeroContext.context.observed.atomic, false);
    substage = 'exercise_read_retry';
    let failOnce = true;
    const retryReader = new OperationsReader(
      i,
      {
        async inspect(ref, signal) {
          if (failOnce) {
            failOnce = false;
            throw new RehydrationError();
          }
          return base.inspect(ref, signal);
        },
      },
      sms(),
      profile(),
    );
    ownedReaders.push(retryReader);
    await expectCode(retryReader.read(randomUUID()), 'unavailable');
    assert.equal((await retryReader.read(randomUUID())).status, 'known');
    substage = 'exercise_ignored_ownership';
    let actualEntries = 0,
      entered = () => {};
    const bothEntered = new Promise<void>((resolve) => {
        entered = resolve;
      }),
      ignoredHeld = new Promise<void>((resolve) => {
        releaseIgnored = resolve;
      });
    const ignored = new OperationsReader(
      i,
      {
        async inspect(ref, signal) {
          if (++actualEntries === 2) entered();
          await ignoredHeld;
          return base.inspect(ref, signal);
        },
      },
      sms(),
      profile(),
    );
    ownedReaders.push(ignored);
    const abortA = new AbortController(),
      abortB = new AbortController(),
      one = ignored.read(randomUUID(), undefined, abortA.signal),
      two = ignored.read(randomUUID(), undefined, abortB.signal);
    void one.catch(() => {});
    void two.catch(() => {});
    await enteredOrSettled(bothEntered, Promise.all([one, two]));
    abortA.abort();
    abortB.abort();
    await Promise.all([expectCode(one, 'unavailable'), expectCode(two, 'unavailable')]);
    const afterAbort = ignored.metrics();
    assert.equal(afterAbort.active, 2);
    await expectCode(ignored.read(randomUUID()), 'overloaded');
    await expectCode(ignored.close(), 'unavailable');
    const afterCloseTimeout = ignored.metrics();
    assert.equal(afterCloseTimeout.active, 2);
    releaseIgnored();
    await ignored.close();
    const afterRelease = ignored.metrics();
    assert.equal(afterRelease.active, 0);
    const useful = await reader.read(randomUUID());
    assert.equal(useful.status, 'known');
    const held = new Promise<void>((_resolve, reject) => {
      releaseExport = () => reject(new Error('scripted_sink_failure'));
    });
    void held.catch(() => {});
    telemetry = new OperationsTelemetry(
      [
        {
          source: 'inbox',
          read: () => {
            const m = i.metrics();
            return { accepted: m.accepted, replayed: m.replayed, active: m.active };
          },
        },
        { source: 'inbox_telemetry', read: () => i.telemetryMetrics() },
        {
          source: 'operations',
          read: () => {
            const t = telemetry!.metrics(),
              r = reader.metrics();
            return {
              ...t,
              readerActive: r.active,
              readerStarted: r.started,
              readerKnown: r.known,
              readerWaiterRejected: r.waiterRejected,
            };
          },
        },
      ],
      () => held,
    );
    producerLog = telemetry.observer('inbox');
    server = new OperationsReadServer(reader, telemetry, f.operatorAuthorization);
    const endpoint = await server.start();
    client = new OperationsHttpClient(endpoint, f.operatorAuthorization, {
      reference: REF,
      bindingId: f.bindingId,
    });
    substage = 'exercise_http_boundary';
    for (const [path, headers, method, status] of [
      ['/v1/operations/context?accountId=foreign', {}, 'GET', 400],
      ['/v1/operations/context?section=history&section=work', {}, 'GET', 400],
      ['/v1/operations/telemetry?section=work', {}, 'GET', 400],
      ['/v1/operations/context', { Host: '127.0.0.1:1' }, 'GET', 400],
      ['/v1/operations/context', { 'Content-Length': '1' }, 'GET', 400],
      ['/v1/operations/context', {}, 'POST', 400],
      [
        '/v1/operations/context',
        { Authorization: 'Bearer ' + token('wrong-operator') },
        'GET',
        403,
      ],
    ] as const) {
      const response = await raw(endpoint, path, headers, method);
      assert.equal(response.status, status);
      assert.equal((response.value as { status: string }).status, 'unavailable');
    }
    substage = 'exercise_exporter_observations';
    for (let n = 0; n < 12; n++) assert.equal((await client.context()).status, 'known');
    const diagnostics = await client.telemetry();
    assert.equal(diagnostics.scope, 'process');
    assert.ok(diagnostics.sources.every((s) => s.state === 'observed'));
    assert.ok(
      diagnostics.observations.some(
        (o) => o.kind === 'read_span' && o.operation === 'context' && o.code === 'known',
      ),
    );
    assert.ok(
      diagnostics.observations.some(
        (o) => o.kind === 'producer_log' && o.source === 'inbox' && o.operation === 'producer',
      ),
    );
    const beforeExportRelease = telemetry.metrics();
    assert.equal(beforeExportRelease.observerPending, 8);
    assert.ok(beforeExportRelease.observerDropped! >= 4);
    const intakeReplay = await i.accept(f.nativeToken, input(f.ids.main));
    assert.equal(intakeReplay.status, 'replayed');
    assert.equal(intakeReplay.receiptId, originals.accepted[0]!.receiptId);
    assert.equal(intakeReplay.operationKey, originals.accepted[0]!.operationKey);
    await client.close();
    client = undefined;
    await server.close();
    server = undefined;
    await expectCode(telemetry.close(), 'unavailable');
    releaseExport();
    await telemetry.close();
    const afterExportRelease = telemetry.metrics();
    assert.equal(afterExportRelease.observerPending, 0);
    assert.equal(afterExportRelease.observerFailures, 8);
    const afterRead = await snapshot();
    assert.deepEqual(afterRead, beforeRead);
    for (const n of [0, 1, 2, 3, 4, 8, 9, 10, 11, 12, 13, 14]) completed.add(CASES[n]!);
    const proof = {
      schemaVersion: 1,
      completedGroups: CASES.filter((c) => completed.has(c)),
      cursor,
      setupMutations,
      beforeRead,
      afterRead,
      cursorTests: {
        wrongSectionDenied: true,
        foreignSourceDenied: true,
        foreignScopeDenied: true,
        missingAnchorDenied: true,
        aheadAnchorDenied: true,
        staleCaseDenied: true,
        originalPagingPreserved: true,
      },
      grantTests: {
        expiresAt: expiryAt,
        caseEnteredAt,
        dbExpiredAt,
        expiryCode: 'access_denied',
        revokedAt: revocation.revokedAt,
        revokeCode: 'access_denied',
        validAfter: true,
      },
      httpTests: {
        selectorDenied: true,
        duplicateQueryDenied: true,
        hostDenied: true,
        bodyDenied: true,
        methodDenied: true,
        operatorDenied: true,
        correlatedKnown: true,
      },
      owners: { afterAbort, afterCloseTimeout, afterRelease, afterUsefulRead: reader.metrics() },
      exporter: {
        beforeRelease: beforeExportRelease,
        afterRelease: afterExportRelease,
        intakeReplay,
      },
      zeroCase: {
        revision: zeroContext.context.case.revision,
        sourceRevision: zeroContext.context.case.sourceRevision,
        requestDigest: sha(JSON.stringify(zeroContext.context.case.request)),
      },
      noReadWrites: true,
    };
    save('operations-exercise-proof.json', proof);
    return { completedGroups: proof.completedGroups, nativeBindings: 5 };
  } catch (error) {
    originalFailure = error;
    throw error;
  } finally {
    releaseExpiry();
    releaseRevoke();
    releaseIgnored();
    releaseExport();
    await cleanupTiers(
      [
        [
          () => client?.close(),
          () => server?.close(),
          ...ownedReaders.map((r) => () => r.close()),
          () => telemetry?.close(),
        ],
        [() => i.close(), () => a.close()],
      ],
      originalFailure,
    );
  }
}
async function main() {
  let result: unknown;
  switch (mode) {
    case 'install':
      result = await install();
      break;
    case 'seed':
      result = await seed();
      break;
    case 'exercise':
      result = await exercise();
      break;
    case 'serve':
      result = await serve();
      break;
    case 'advance-dispatch':
      result = await advanceDispatch();
      break;
    case 'advance-reconcile':
      result = await advanceReconcile();
      break;
    case 'advance-callback':
      result = await advanceCallback();
      break;
    case 'verify':
      result = await verify();
      break;
    case 'reopen':
      result = await reopen();
      break;
    case 'cleanup':
      result = await cleanup();
      break;
  }
  console.log(
    JSON.stringify({
      schemaVersion: 1,
      status: 'passed',
      mode,
      storageVersion: mode === 'cleanup' ? 0 : 7,
      nodeVersion: process.versions.node,
      cleanupComplete: true,
      result,
    }),
  );
}
void main().catch((error: unknown) => {
  let code: string | null = null,
    errorType = 'UnexpectedError';
  if (
    error instanceof ChannelError ||
    error instanceof OperationsError ||
    error instanceof RehydrationError
  ) {
    errorType =
      error instanceof ChannelError
        ? 'ChannelError'
        : error instanceof OperationsError
          ? 'OperationsError'
          : 'RehydrationError';
    const d = Object.getOwnPropertyDescriptor(error, 'code');
    if (
      d &&
      'value' in d &&
      typeof d.value === 'string' &&
      [
        'InvalidConfiguration',
        'InvalidEvent',
        'AccessDenied',
        'AssociationRequired',
        'AssociationRejected',
        'IdentityConflict',
        'Overloaded',
        'NotFound',
        'DispatchClaimLost',
        'DispatchUnavailable',
        'OperationConflict',
        'StorageUnavailable',
        'SchemaMismatch',
        'UpgradeRequired',
        'AcknowledgementUnknown',
        'CleanupIncomplete',
        'invalid_query',
        'access_denied',
        'cursor_stale',
        'overloaded',
        'unavailable',
        'closed',
        'context_unavailable',
      ].includes(d.value)
    )
      code = d.value;
  } else if (error instanceof assert.AssertionError) errorType = 'AssertionError';
  const frames: Array<{ file: string; line: number }> = [];
  if (error instanceof Error) {
    const d = Object.getOwnPropertyDescriptor(error, 'stack');
    if (d && 'value' in d && typeof d.value === 'string')
      for (const match of d.value.matchAll(
        /(?:^|\n).*\/(pg_operations_cases\.js|operations-lab\.js):(\d+):\d+/g,
      )) {
        if (frames.length < 8) frames.push({ file: match[1]!, line: Number(match[2]) });
      }
  }
  try {
    save('operations-failure-' + mode + '.json', {
      schemaVersion: 1,
      status: 'failed',
      mode,
      stage: substage,
      errorType,
      code,
      frames,
    });
  } catch {
    /* Preserve the original fixed failure. */
  }
  console.log(
    JSON.stringify({ schemaVersion: 1, status: 'failed', mode, code: 'operations_fixture_failed' }),
  );
  process.exitCode = 1;
});
