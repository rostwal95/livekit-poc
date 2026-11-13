/** Explicit local application fixture: public product APIs, separately marked owner reconciliation. */
import assert from 'node:assert/strict';
import { randomUUID, createHash } from 'node:crypto';
import { readFileSync, writeFileSync, renameSync, existsSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';
import pg from 'pg';
import {
  ChannelInbox,
  SeededAccounts,
  ChannelError,
  type DatabaseSettings,
  type StoredMessage,
} from '@livekit-ecosystem/channel-continuity/postgres';
import {
  createFakeSmsIntegration,
  signFakeSms,
  type FakeSmsMessage,
} from '@livekit-ecosystem/channel-continuity/security';
import {
  createNativeIntegration,
  NativeAgentHttpClient,
  type NativeAcceptance,
} from '@livekit-ecosystem/channel-continuity/native';
import {
  CommunicationInbox,
  CommunicationGateway,
  createCommunicationIntegration,
  type ResponseAnchor,
} from '@livekit-ecosystem/channel-continuity/communication';
import {
  ChannelDispatcher,
  type DispatchPorts,
  type OperationReceipt,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  ChannelRehydrator,
  RehydrationHttpServer,
  CurrentCaseHttpClient,
  referenceCurrentCase,
  DEFAULT_REHYDRATION_QUERY,
  RehydrationError,
  rehydrationContext,
  type CurrentCasePort,
  type RehydrationContext,
  type RehydrationQuery,
} from '@livekit-ecosystem/channel-continuity/rehydration';
import { ChannelOutbox } from '@livekit-ecosystem/channel-continuity/outbox';
import {
  ReferenceCaseAuthority,
  installReferenceCaseSchema,
} from '@livekit-ecosystem/channel-continuity/reference-case';
import {
  RevisionRouter,
  encodeRevisionCommand,
  type InvestigationRequest,
} from '@livekit-ecosystem/channel-continuity/routing';
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
  'seed',
  'exercise',
  'expiry',
  'revocation',
  'crash',
  'replay',
  'verify',
  'cleanup',
  'media-install',
  'media-seed',
  'media-serve',
  'media-sms',
  'media-verify',
  'media-cleanup',
] as const;
const pendingAssertions: Promise<unknown>[] = [];
function observed<T>(promise: Promise<T>): Promise<T> {
  void promise.catch(() => {});
  pendingAssertions.push(promise);
  return promise;
}
const mode = process.argv[2];
type EntryObservation = {
  phase: 'none' | 'concurrent_case' | 'slow_case' | 'revocation_case';
  entered: boolean;
  caller: 'pending' | 'fulfilled' | 'rejected';
  cause: 'pending' | 'entry' | 'caller_settled' | 'watchdog';
};
let entryObservation: EntryObservation = {
  phase: 'none',
  entered: false,
  caller: 'pending',
  cause: 'pending',
};
async function awaitCaseEntry(
  phase: Exclude<EntryObservation['phase'], 'none'>,
  entered: Promise<void>,
  caller: Promise<unknown>,
): Promise<void> {
  const observation: EntryObservation = {
    phase,
    entered: false,
    caller: 'pending',
    cause: 'pending',
  };
  entryObservation = observation;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    observation.cause = await Promise.race([
      entered.then(() => {
        observation.entered = true;
        return 'entry' as const;
      }),
      caller.then(
        () => {
          observation.caller = 'fulfilled';
          return 'caller_settled' as const;
        },
        () => {
          observation.caller = 'rejected';
          return 'caller_settled' as const;
        },
      ),
      new Promise<'watchdog'>((resolve) => {
        timer = setTimeout(() => resolve('watchdog'), 2000);
      }),
    ]);
    if (observation.cause !== 'entry') throw new RehydrationError('context_unavailable');
  } finally {
    clearTimeout(timer);
  }
}
assert.ok(process.argv.length === 3 && MODES.includes(mode as (typeof MODES)[number]));
const owner = [
  'install',
  'verify',
  'cleanup',
  'media-install',
  'media-verify',
  'media-cleanup',
].includes(mode!);
function env(k: string) {
  const v = process.env[k];
  assert.ok(v && v.length <= 4096);
  return v;
}
const DIR = env('P2_REHYDRATION_DIRECTORY'),
  schema = env('P2_REHYDRATION_SCHEMA');
assert.match(schema, /^p2_rehydration_[a-f0-9]{32}(?![\s\S])/);
const caseSchema = 'p2_case_rehydration_' + schema.slice(-32);
assert.equal(
  process.env[owner ? 'P2_REHYDRATION_RUNTIME_PASSWORD' : 'P2_REHYDRATION_OWNER_PASSWORD'],
  undefined,
);
type Binding = {
  bindingId: string;
  roomId: string;
  participantId: string;
  agentId: string;
  bindingToken: string;
};
type Fixture = {
  schemaVersion: 1;
  providerScope: { tenantId: string; provider: string; providerAccountId: string };
  scope: { tenantId: string; accountId: string };
  caseId: string;
  conversationId: string;
  accountToken: string;
  publisherToken: string;
  prepareToken: string;
  expiresAt: string;
  bindings: { A: Binding; B: Binding };
  ids: { voice: string; text: string; sms: string; newText: string };
  communication: { publisherToken: string; sdkToken: string; browserToken: string };
  sms: {
    providerScope: { tenantId: string; provider: string; providerAccountId: string };
    senderId: string;
    hmacKeyBase64: string;
  };
  referenceRequest: InvestigationRequest;
};
function load<T>(name: string): T {
  return JSON.parse(readFileSync(DIR + '/' + name, 'utf8')) as T;
}
function save(name: string, value: unknown) {
  const file = DIR + '/' + name,
    temp = file + '.pending';
  writeFileSync(temp, JSON.stringify(value) + '\n', { flag: 'wx', mode: 0o600 });
  renameSync(temp, file);
}
const f = load<Fixture>('fixture.json');
assert.equal(f.schemaVersion, 1);
const sha = (s: string) => createHash('sha256').update(s).digest('hex');
function id(label: string) {
  const h = sha(f.bindings.A.bindingId + ':' + label);
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
function token(label: string) {
  return createHash('sha256')
    .update(f.accountToken + ':' + label)
    .digest('base64url');
}
const REF = { scope: f.scope, caseId: f.caseId, conversationId: f.conversationId };
const CASE_REF = { scope: f.scope, caseId: f.caseId };
const FOREIGN = {
  scope: { tenantId: f.scope.tenantId, accountId: f.scope.accountId + '-other' },
  caseId: f.caseId + '-other',
  conversationId: f.conversationId + '-other',
  token: token('foreign-account'),
  publisher: token('foreign-publisher'),
  binding: {
    bindingId: id('foreign-binding'),
    roomId: 'foreign-room',
    participantId: 'foreign-participant',
    agentId: 'foreign-agent',
    bindingToken: token('foreign-binding'),
  },
};
const key = Buffer.from(f.sms.hmacKeyBase64, 'base64');
assert.equal(key.length, 32);
const smsIntegration = () => createFakeSmsIntegration(f.sms.providerScope, key);
function db(target = schema): DatabaseSettings {
  return {
    host: '127.0.0.1',
    port: Number(env('P2_REHYDRATION_PG_PORT')),
    database: 'livekit_lab',
    user: owner ? 'continuity_migrator' : 'livekit_lab',
    password: env(owner ? 'P2_REHYDRATION_OWNER_PASSWORD' : 'P2_REHYDRATION_RUNTIME_PASSWORD'),
    schema: target,
  };
}
function seeds() {
  return [
    { ...f.scope, token: f.accountToken, caseId: f.caseId, conversationId: f.conversationId },
    {
      ...FOREIGN.scope,
      token: FOREIGN.token,
      caseId: FOREIGN.caseId,
      conversationId: FOREIGN.conversationId,
    },
  ];
}
function accounts() {
  return new SeededAccounts(seeds());
}
function integration() {
  return createCommunicationIntegration(
    createNativeIntegration(f.providerScope, [
      { token: f.publisherToken, ...REF },
      {
        token: FOREIGN.publisher,
        scope: FOREIGN.scope,
        caseId: FOREIGN.caseId,
        conversationId: FOREIGN.conversationId,
      },
    ]),
    [
      { ...REF, ...f.communication },
      {
        scope: FOREIGN.scope,
        caseId: FOREIGN.caseId,
        conversationId: FOREIGN.conversationId,
        publisherToken: token('foreign-response-publisher'),
        sdkToken: token('foreign-sdk'),
        browserToken: token('foreign-browser'),
      },
    ],
  );
}
function inbox() {
  return new CommunicationInbox(db(), integration(), accounts(), {}, () => {});
}
function smsInbox() {
  return new ChannelInbox(db(), smsIntegration(), accounts(), {}, () => {});
}
function publication(b: Binding, expiresAt = f.expiresAt) {
  return {
    bindingId: b.bindingId,
    bearer: b.bindingToken,
    roomId: b.roomId,
    participantId: b.participantId,
    expiresAt,
  };
}
function input(
  b: Binding,
  inputId: string,
  body = 'INVESTIGATE',
  channel: 'web_chat' | 'voice_transcript' = 'web_chat',
) {
  return {
    schemaVersion: 1 as const,
    inputId,
    channel,
    body,
    roomId: b.roomId,
    participantId: b.participantId,
  };
}
const request = (day: string): InvestigationRequest => ({ ...f.referenceRequest, newCheckIn: day });
function sign(message: FakeSmsMessage) {
  return signFakeSms(message, key, Math.floor(Date.now() / 1000), f.sms.providerScope);
}
function smsMessage(body: string, eventId = f.ids.sms, senderId = f.sms.senderId): FakeSmsMessage {
  return {
    schemaVersion: 1,
    eventId,
    messageId: eventId,
    senderId,
    body,
    occurredAt: '2030-01-01T00:00:00.000Z',
  };
}
async function link(i: ChannelInbox, sender = f.sms.senderId, account = f.accountToken) {
  const c = await i.createChallenge(account, sender),
    signed = sign(
      smsMessage(
        'LINK ' + c.challengeId + ' ' + c.secret,
        id('link:' + sender + ':' + c.challengeId),
        sender,
      ),
    );
  return i.completeAssociation(signed.raw, signed.headers);
}
async function reject(work: () => unknown, code: string) {
  await assert.rejects(
    async () => work(),
    (e) => e instanceof Error && Object.getOwnPropertyDescriptor(e, 'code')?.value === code,
  );
}
function reached(name: string) {
  writeFileSync(DIR + '/' + name + '.reached', process.pid + '\n', { flag: 'wx', mode: 0o600 });
}
async function barrier(name: string, ms = 10000) {
  reached(name);
  const end = performance.now() + ms;
  while (!existsSync(DIR + '/' + name + '.released')) {
    assert.ok(performance.now() < end);
    await delay(5);
  }
  assert.equal(readFileSync(DIR + '/' + name + '.released', 'utf8'), process.pid + '\n');
}
function authority() {
  return new ReferenceCaseAuthority(db(caseSchema), [
    CASE_REF,
    { scope: FOREIGN.scope, caseId: FOREIGN.caseId },
  ]);
}
function ports(a: ReferenceCaseAuthority, file = 'rehydration-operations.json'): DispatchPorts {
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
      async inspect(ref, signal) {
        const v = await a.inspect(ref, signal);
        return {
          scope: v.scope,
          caseId: v.caseId,
          revision: v.revision,
          source: 'synthetic_read_only',
        };
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
        const prior = rows().find((r) => r.receipt.operationKey === v.operationKey);
        if (!prior) return { status: 'absent' };
        assert.deepEqual(prior.receipt.scope, v.scope);
        assert.equal(prior.payloadDigest, v.payloadDigest);
        return { status: 'accepted', receipt: prior.receipt };
      },
      async accept(v) {
        const all = rows();
        let prior = all.find((r) => r.receipt.operationKey === v.submission.operationKey);
        if (prior) {
          assert.equal(prior.canonicalPayload, v.canonicalPayload);
          assert.equal(prior.payloadDigest, v.payloadDigest);
        } else {
          prior = {
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
          all.push(prior);
          save(file, all);
        }
        return prior.receipt;
      },
    },
  };
}
async function ownerSql<T>(work: (client: pg.Client) => Promise<T>) {
  assert.ok(owner);
  const c = new pg.Client({
    ...db(),
    ssl: false,
    application_name: 'p2-rehydration-owner-' + mode,
    connectionTimeoutMillis: 1000,
    statement_timeout: 2000,
  });
  await c.connect();
  try {
    return await work(c);
  } finally {
    await c.end();
  }
}
async function install() {
  await installChannelSchema(db());
  await upgradeChannelSchemaV2(db());
  await upgradeChannelSchemaV3(db());
  await upgradeChannelSchemaV4(db());
  await upgradeChannelSchemaV5(db());
  await upgradeChannelSchemaV6(db(), { maxBindings: 8 });
  await upgradeChannelSchemaV7(db(), {
    maxResponses: 32,
    maxObservations: 128,
    maxObservationsPerResponse: 8,
  });
  await installReferenceCaseSchema(db(caseSchema), [
    {
      scope: f.scope,
      caseId: f.caseId,
      revision: '1',
      request: f.referenceRequest,
      cancelled: false,
      committed: false,
    },
    {
      scope: FOREIGN.scope,
      caseId: FOREIGN.caseId,
      revision: '1',
      request: f.referenceRequest,
      cancelled: false,
      committed: false,
    },
  ]);
  return { currentCaseSource: 'standalone_reference_v1' };
}
async function cleanup() {
  await ownerSql(async (c) => {
    for (const target of [schema, caseSchema]) {
      const row = (
        await c.query(
          "SELECT pg_get_userbyid(nspowner) owner,obj_description(oid,'pg_namespace') marker FROM pg_namespace WHERE nspname=$1",
          [target],
        )
      ).rows[0];
      if (row) {
        assert.equal(row.owner, 'continuity_migrator');
        if (target === schema) assert.match(row.marker, /^p2-channel-schema-v[1-7]$/);
        else assert.equal(row.marker, 'p2-reference-case-v1');
        await c.query('DROP SCHEMA "' + target + '" CASCADE');
      }
      assert.equal(
        (await c.query('SELECT 1 FROM pg_namespace WHERE nspname=$1', [target])).rowCount,
        0,
      );
    }
  });
  return { storageVersion: 0, ownedSchemaAbsent: true, cleanupComplete: true };
}
async function mediaSeed() {
  const i = inbox();
  try {
    for (const b of Object.values(f.bindings)) await i.bind(f.publisherToken, publication(b));
    assert.equal((await i.history(f.accountToken)).messages.length, 0);
    return { nativeBindings: 2, nativeInputs: 0 };
  } finally {
    await i.close();
  }
}
async function mediaServe() {
  const endpoint = load<{ host: '127.0.0.1'; port: number }>('python-endpoint.json'),
    a = authority(),
    client = new NativeAgentHttpClient(
      endpoint,
      'Bearer ' + f.prepareToken,
      Object.values(f.bindings).map((b) => ({ bindingId: b.bindingId, ...REF })),
      { timeoutMs: 4500 },
    );
  const gateway = new CommunicationGateway({
    database: db(),
    integration: integration(),
    accounts: seeds(),
    ports: { ...ports(a), agent: client.port },
    options: { pollMs: 20, observer: () => {} },
  });
  const context = new ChannelRehydrator(gateway, referenceCurrentCase(a), smsIntegration(), {
      observer: () => {},
    }),
    http = new RehydrationHttpServer(context);
  let stop!: () => void;
  const ending = new Promise<void>((resolve) => {
    stop = resolve;
  });
  process.once('SIGTERM', stop);
  process.once('SIGINT', stop);
  try {
    const address = await gateway.listen(),
      readAddress = await http.start();
    save('node-endpoint.json', address);
    save('rehydration-endpoint.json', readAddress);
    reached('node_ready');
    await ending;
  } finally {
    await closeAll([
      () => http.close(),
      () => context.close(),
      () => gateway.close(),
      () => client.close(),
      () => a.close(),
    ]);
  }
  const all = gateway.metrics(),
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
  const metrics = Object.fromEntries(
    keys.map((k) => {
      assert.ok(Object.hasOwn(all, k) && Number.isSafeInteger(all[k]));
      return [k, all[k]];
    }),
  );
  const report = {
    cleanupComplete: true,
    metrics,
    rehydrationMetrics: context.metrics(),
    readHttpMetrics: http.metrics(),
    communicationMetrics: gateway.communicationMetrics(),
  };
  save('rehydration-node-private-proof.json', report);
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
async function mediaSms() {
  const i = smsInbox(),
    a = authority(),
    d = new ChannelDispatcher(db(), smsIntegration(), accounts(), ports(a), { observer: () => {} }),
    router = new RevisionRouter(i, a, [CASE_REF], { observer: () => {} });
  try {
    await link(i);
    const body = encodeRevisionCommand({
        schemaVersion: 1,
        kind: 'case.revise_investigation',
        expectedRevision: '1',
        request: request('2030-01-13'),
      }),
      message = smsMessage(body),
      signed = sign(message),
      accepted = await i.acceptSms(signed.raw, signed.headers),
      routed = await router.route(f.accountToken, accepted.receipt.receiptId);
    assert.equal(routed.status, 'revised');
    assert.equal((await a.inspect(CASE_REF, new AbortController().signal)).revision, '2');
    assert.equal((await d.step(f.accountToken, accepted.receipt.receiptId)).status, 'dispatched');
    const result = {
      schemaVersion: 1,
      status: 'passed',
      smsAccepted: 1,
      caseRevision: '2',
      receiptId: accepted.receipt.receiptId,
      operationKey: (await i.inspect(f.accountToken, accepted.receipt.receiptId)).operationKey,
      eventId: message.eventId,
    };
    save('rehydration-sms-result.json', result);
    return result;
  } finally {
    await router.close();
    await d.close();
    await i.close();
    await a.close();
  }
}

const CASES = [
  'native_current_scope_derived',
  'accepted_sms_current_epoch_derived',
  'unaccepted_or_bad_hmac_no_disclosure',
  'wrong_tenant_account_case_denied',
  'native_expiry_behind_lock_denied',
  'revocation_first_denied_and_valid_progress',
  'sms_reassignment_old_receipt_denied',
  'disclosure_admitted_first_not_retracted',
  'standalone_current_authority_over_stale_history',
  'p1_public_current_facts_and_supplier_source',
  'coherent_p2_snapshot_during_append',
  'separate_scoped_paging_and_case_fingerprint',
  'byte_bound_whole_record_paging',
  'no_read_side_effects_or_new_owner',
  'retained_io_timeout_and_later_progress',
  'historical_responses_not_new_room_controls',
  'fresh_process_same_history_new_current_case',
  'original_v7_populated_restore_preserved',
] as const;
async function closeAll(actions: readonly (() => Promise<unknown>)[]) {
  let primary: unknown;
  for (const action of actions)
    try {
      await action();
    } catch (error) {
      primary ??= error;
    }
  if (primary !== undefined) throw primary;
}
async function seed() {
  const i = inbox(),
    sms = smsInbox(),
    a = authority(),
    d = new ChannelDispatcher(db(), integration(), accounts(), ports(a), { observer: () => {} });
  try {
    for (const b of Object.values(f.bindings)) await i.bind(f.publisherToken, publication(b));
    const text = await i.accept(
        f.bindings.A.bindingToken,
        input(f.bindings.A, f.ids.text, 'Older accepted text café 🧭'),
      ),
      voice = await i.accept(
        f.bindings.A.bindingToken,
        input(f.bindings.A, f.ids.voice, 'Older committed voice', 'voice_transcript'),
      );
    assert.ok(text.receiptId && text.operationKey);
    assert.equal((await d.step(f.accountToken, text.receiptId)).status, 'dispatched');
    await link(sms);
    const message = smsMessage('Older accepted SMS');
    const signed = sign(message),
      accepted = await sms.acceptSms(signed.raw, signed.headers);
    const anchor: ResponseAnchor = {
      schemaVersion: 1,
      responseId: id('old-response'),
      generationId: id('old-generation'),
      sdkSpeechId: 'old-speech',
      bindingId: f.bindings.A.bindingId,
      inputId: f.ids.text,
      receiptId: text.receiptId,
      operationKey: text.operationKey,
      caseRevision: '1',
    };
    const response = await i.beginResponse(f.communication.publisherToken, anchor),
      observations = [];
    observations.push(
      await i.observeSdk(f.communication.sdkToken, {
        schemaVersion: 1,
        eventId: id('old-generated'),
        responseId: anchor.responseId,
        generationId: anchor.generationId,
        sdkSpeechId: anchor.sdkSpeechId,
        fact: { type: 'generated_complete', text: 'Original complete generated text' },
      }),
    );
    observations.push(
      await i.observeSdk(f.communication.sdkToken, {
        schemaVersion: 1,
        eventId: id('old-sdk'),
        responseId: anchor.responseId,
        generationId: anchor.generationId,
        sdkSpeechId: anchor.sdkSpeechId,
        fact: { type: 'speech_settled', state: 'interrupted', sdkText: 'Original complete' },
      }),
    );
    observations.push(
      await i.observeBrowser(f.communication.browserToken, {
        schemaVersion: 1,
        eventId: id('old-browser'),
        responseId: anchor.responseId,
        state: 'partial',
        observedAudioMs: 120,
      }),
    );
    await i.bind(FOREIGN.publisher, publication(FOREIGN.binding));
    const foreign = await i.accept(
      FOREIGN.binding.bindingToken,
      input(FOREIGN.binding, id('foreign-input'), 'Different verified account'),
    );
    const box = new ChannelOutbox(
      db(),
      smsIntegration(),
      accounts(),
      [{ ...REF, token: token('reply-publisher') }],
      {
        capabilities: 'ordinary_fake_sms_v1',
        async send() {
          throw new Error('carrier_must_not_run');
        },
      },
      { observer: () => {} },
    );
    let queued;
    try {
      queued = await box.enqueue(token('reply-publisher'), {
        schemaVersion: 1,
        outboundId: id('old-outbound'),
        responseId: anchor.responseId,
        body: 'Pending bounded notice café 🧭',
      });
    } finally {
      await box.close();
    }
    const proof = {
      text,
      voice,
      sms: {
        message,
        receipt: accepted.receipt,
        stored: await sms.inspect(f.accountToken, accepted.receipt.receiptId),
      },
      foreign,
      anchor,
      response,
      observations,
      reply: queued,
      history: await i.history(f.accountToken),
    };
    save('rehydration-seed-proof.json', proof);
    return { bindings: 3, acceptedInputs: 4 };
  } finally {
    await closeAll([() => d.close(), () => i.close(), () => sms.close(), () => a.close()]);
  }
}
type SeedProof = {
  text: NativeAcceptance;
  voice: NativeAcceptance;
  sms: { message: FakeSmsMessage; receipt: { receiptId: string }; stored: StoredMessage };
  foreign: NativeAcceptance;
  anchor: ResponseAnchor;
  response: unknown;
  observations: unknown[];
  reply: unknown;
  history: unknown;
};
async function exercise() {
  const i = inbox(),
    sms = smsInbox(),
    a = authority(),
    base = referenceCurrentCase(a);
  let caseCalls = 0;
  const observedCase: CurrentCasePort = {
    async inspect(ref, signal) {
      caseCalls++;
      return base.inspect(ref, signal);
    },
  };
  const r = new ChannelRehydrator(i, observedCase, smsIntegration(), { observer: () => {} });
  const seed = load<SeedProof>('rehydration-seed-proof.json');
  const completed: string[] = [];
  const phaseClosures: (() => Promise<unknown>)[] = [];
  let primary: unknown;
  try {
    const initial = await r.native(f.bindings.B.bindingToken);
    assert.deepEqual(initial.access, {
      kind: 'native',
      bindingId: f.bindings.B.bindingId,
      roomId: f.bindings.B.roomId,
      participantId: f.bindings.B.participantId,
    });
    assert.equal(initial.case.revision, '1');
    assert.equal(initial.history.messages.length, 3);
    assert.deepEqual(
      new Set(initial.history.messages.map((m) => m.event.providerScope.provider)),
      new Set(['livekit', 'fake_sms']),
    );
    completed.push(CASES[0]);
    const signed = sign(seed.sms.message),
      fromSms = await r.sms(signed.raw, signed.headers);
    assert.equal(fromSms.access.kind, 'sms');
    assert.equal(fromSms.case.caseId, f.caseId);
    assert.deepEqual(fromSms.history.messages, initial.history.messages);
    completed.push(CASES[1]);
    let before = caseCalls;
    const unseen = sign(smsMessage('unaccepted', id('unaccepted')));
    await reject(() => r.sms(unseen.raw, unseen.headers), 'access_denied');
    await reject(
      () => r.sms(signed.raw, { ...signed.headers, signature: '0'.repeat(64) }),
      'access_denied',
    );
    assert.equal(caseCalls, before);
    completed.push(CASES[2]);
    before = caseCalls;
    await reject(() => r.native(token('wrong-bearer')), 'access_denied');
    assert.equal(caseCalls, before);
    const foreign = await r.native(FOREIGN.binding.bindingToken);
    assert.equal(foreign.history.messages.length, 1);
    assert.equal(foreign.case.scope.accountId, FOREIGN.scope.accountId);
    assert.ok(
      foreign.history.messages.every((m) => m.event.conversationId === FOREIGN.conversationId),
    );
    completed.push(CASES[3]);
    const sender = 'reassigned-sender';
    await link(sms, sender);
    const oldMessage = smsMessage(
        'Original before sender reassignment',
        id('reassigned-input'),
        sender,
      ),
      oldSigned = sign(oldMessage),
      oldAck = await sms.acceptSms(oldSigned.raw, oldSigned.headers);
    await link(sms, sender, FOREIGN.token);
    await reject(() => r.sms(oldSigned.raw, oldSigned.headers), 'access_denied');
    assert.equal(
      (await sms.inspect(f.accountToken, oldAck.receipt.receiptId)).event.conversationId,
      f.conversationId,
    );
    completed.push(CASES[6]);
    const changed = await a.revise(
      { ...CASE_REF, expectedRevision: '1', request: request('2030-01-14') },
      new AbortController().signal,
    );
    assert.equal(changed.revision, '2');
    const current = await r.native(f.bindings.B.bindingToken);
    assert.equal(current.case.revision, '2');
    assert.equal(current.case.request.newCheckIn, '2030-01-14');
    assert.equal(initial.case.revision, '1');
    assert.equal(current.case.supplierResult, null);
    completed.push(CASES[8]);
    const integrated = new CurrentCaseHttpClient(
      { host: '127.0.0.1', port: Number(env('P2_REHYDRATION_CURRENT_CASE_PORT')) },
      'Bearer ' + env('P2_REHYDRATION_CURRENT_CASE_TOKEN'),
      [REF],
    );
    const p1 = new ChannelRehydrator(i, integrated, smsIntegration(), { observer: () => {} });
    let p1Context: RehydrationContext;
    try {
      p1Context = await p1.native(f.bindings.B.bindingToken);
      assert.equal(p1Context.case.source, 'p1_public_v4');
      assert.notEqual(p1Context.case.workflow, null);
      assert.equal(p1Context.case.revision, '0');
      assert.equal(p1Context.case.supplierResult, null);
      assert.equal(p1Context.case.intent.state, 'not_committed');
      assert.ok(!JSON.stringify(p1Context.case).includes('confirmation_payload'));
      save('rehydration-p1-before.json', { schemaVersion: 1, context: p1Context });
      const original = JSON.stringify(p1Context);
      await barrier('rehydration_p1_advance');
      const after = await p1.native(f.bindings.B.bindingToken);
      assert.equal(after.case.source, 'p1_public_v4');
      assert.equal(after.case.revision, '0');
      assert.notEqual(after.case.sourceRevision, p1Context.case.sourceRevision);
      assert.equal(after.case.intent.state, 'committed');
      assert.equal(after.case.mutation.state, 'succeeded');
      assert.equal(after.case.mutation.outcome, 'succeeded');
      assert.ok(
        after.case.mutation.effectId &&
          after.case.mutation.outcomeEventId &&
          after.case.supplierResult,
      );
      assert.equal(JSON.stringify(p1Context), original);
      save('rehydration-p1-after.json', { schemaVersion: 1, context: after });
    } finally {
      await p1.close();
      await integrated.close();
    }
    completed.push(CASES[9]);
    let enter!: () => void, release!: () => void;
    const entered = new Promise<void>((resolve) => {
        enter = resolve;
      }),
      held = new Promise<void>((resolve) => {
        release = resolve;
      });
    const concurrent = new ChannelRehydrator(
      i,
      {
        async inspect(ref, signal) {
          const value = await base.inspect(ref, signal);
          enter();
          await held;
          return value;
        },
      },
      smsIntegration(),
      { observer: () => {} },
    );
    const pending = concurrent.native(f.bindings.B.bindingToken);
    phaseClosures.push(async () => {
      release();
      await concurrent.close();
    });
    await awaitCaseEntry('concurrent_case', entered, pending);
    const appendedMessage = smsMessage(
        'Accepted while an external readonly authority is held',
        id('concurrent-append'),
      ),
      appendSigned = sign(appendedMessage),
      appendAck = await sms.acceptSms(appendSigned.raw, appendSigned.headers);
    release();
    const beforeAppend = await pending;
    assert.ok(
      !beforeAppend.history.messages.some(
        (m) => m.receipt.receiptId === appendAck.receipt.receiptId,
      ),
    );
    assert.equal(beforeAppend.observed.atomic, false);
    await concurrent.close();
    assert.ok(
      (await r.native(f.bindings.B.bindingToken)).history.messages.some(
        (m) => m.receipt.receiptId === appendAck.receipt.receiptId,
      ),
    );
    completed.push(CASES[10]);
    for (let n = 0; n < 8; n++) {
      const long = sign(smsMessage('界'.repeat(1365), id('long-' + n)));
      await sms.acceptSms(long.raw, long.headers);
    }
    const first = await r.native(f.bindings.B.bindingToken);
    assert.ok(first.history.hasMore && first.history.nextCursor);
    assert.ok(first.history.messages.length < 8);
    assert.ok(
      Buffer.byteLength(JSON.stringify({ schemaVersion: 1, status: 'known', context: first })) <=
        65536,
    );
    for (const m of first.history.messages)
      assert.equal((m.event as { body: string }).body, '界'.repeat(1365));
    const query: RehydrationQuery = {
      ...DEFAULT_REHYDRATION_QUERY,
      historyCursor: first.history.nextCursor,
    };
    const second = await r.native(f.bindings.B.bindingToken, query);
    assert.ok(second.history.messages.length > 0);
    assert.ok(
      !second.history.messages.some((m) =>
        first.history.messages.some((x) => x.receipt.receiptId === m.receipt.receiptId),
      ),
    );
    await reject(() => r.native(FOREIGN.binding.bindingToken, query), 'invalid_query');
    completed.push(CASES[11], CASES[12]);
    const operations = load<unknown[]>('rehydration-operations.json').length;
    await r.native(f.bindings.B.bindingToken);
    assert.equal(load<unknown[]>('rehydration-operations.json').length, operations);
    assert.equal(operations, 1);
    completed.push(CASES[13]);
    let releaseSlow!: () => void;
    let timeoutPortEntered = false;
    const slowHeld = new Promise<void>((resolve) => {
      releaseSlow = resolve;
    });
    const slow = new ChannelRehydrator(
      i,
      {
        async inspect(ref, signal) {
          const value = await base.inspect(ref, signal);
          timeoutPortEntered = true;
          await slowHeld;
          return value;
        },
      },
      smsIntegration(),
      { timeoutMs: 30, maxActive: 1, observer: () => {} },
    );
    phaseClosures.push(async () => {
      releaseSlow();
      await slow.close();
    });
    const timed = observed(slow.native(f.bindings.B.bindingToken));
    const caught = observed(
      assert.rejects(
        timed,
        (e) => e instanceof RehydrationError && e.code === 'context_unavailable',
      ),
    );
    await caught;
    const deadlinePortObserved = timeoutPortEntered;
    releaseSlow();
    await slow.close();
    assert.equal(slow.metrics().active, 0);
    let releaseAbandoned!: () => void, abandonedEnter!: () => void;
    const abandonedHeld = new Promise<void>((resolve) => {
      releaseAbandoned = resolve;
    });
    const abandonedEntered = new Promise<void>((resolve) => {
      abandonedEnter = resolve;
    });
    const abandonedReader = new ChannelRehydrator(
      i,
      {
        async inspect(ref, signal) {
          const value = await base.inspect(ref, signal);
          abandonedEnter();
          await abandonedHeld;
          return value;
        },
      },
      smsIntegration(),
      { maxActive: 1, cleanupMs: 30, observer: () => {} },
    );
    phaseClosures.push(async () => {
      releaseAbandoned();
      await abandonedReader.close();
    });
    const controller = new AbortController();
    const abandoned = observed(
      abandonedReader.native(f.bindings.B.bindingToken, undefined, controller.signal),
    );
    const abandonedRejected = observed(
      assert.rejects(
        abandoned,
        (e) => e instanceof RehydrationError && e.code === 'context_unavailable',
      ),
    );
    await awaitCaseEntry('slow_case', abandonedEntered, abandoned);
    controller.abort();
    await abandonedRejected;
    assert.equal(abandonedReader.metrics().active, 1);
    await reject(() => abandonedReader.native(f.bindings.B.bindingToken), 'overloaded');
    await reject(() => abandonedReader.close(), 'context_unavailable');
    assert.equal(abandonedReader.metrics().active, 1);
    releaseAbandoned();
    await abandonedReader.close();
    assert.equal(abandonedReader.metrics().active, 0);
    assert.equal((await r.native(f.bindings.B.bindingToken)).case.revision, '2');
    completed.push(CASES[14]);
    const response = first.responses.items[0]!;
    assert.equal(response.historical, true);
    assert.equal(response.anchor.bindingId, f.bindings.A.bindingId);
    assert.equal(response.anchor.responseId, seed.anchor.responseId);
    assert.equal(response.sdk.state, 'interrupted');
    assert.equal(response.browserState, 'partial');
    assert.equal(response.generated.state, 'complete');
    assert.equal(Object.hasOwn(response, 'generatedText'), false);
    assert.deepEqual(
      await i.inspectResponse(f.accountToken, seed.anchor.responseId),
      await i.inspectResponse(f.accountToken, seed.anchor.responseId),
    );
    completed.push(CASES[15]);
    const proof = {
      schemaVersion: 1,
      completedGroups: completed,
      initial,
      fromSms,
      current,
      p1Context,
      foreign,
      beforeAppend,
      appendedReceipt: appendAck.receipt,
      firstPage: first,
      secondPage: second,
      operations,
      metrics: r.metrics(),
      timeoutAndAbandonment: {
        deadlineMs: 30,
        deadlinePortEntered: deadlinePortObserved,
        deadlineCode: 'context_unavailable',
        abortAfterActualPortEntry: true,
        retainedUntilRelease: true,
        settledActive: abandonedReader.metrics().active,
      },
    };
    save('rehydration-exercise-proof.json', proof);
    return {
      completedGroups: completed,
      caseSourceKinds: ['standalone_reference_v1', 'p1_public_v4'],
      readonlyOperations: operations,
    };
  } catch (error) {
    primary = error;
    throw error;
  } finally {
    try {
      await closeAll([
        ...phaseClosures,
        () => r.close(),
        () => i.close(),
        () => sms.close(),
        () => a.close(),
      ]);
    } catch (error) {
      if (primary === undefined) throw error;
    }
  }
}

function captureExpiryBackend() {
  const original = pg.Pool.prototype.connect;
  let published = false;
  const wrapped = async function (this: pg.Pool) {
    const client = await (original as (this: pg.Pool) => Promise<pg.PoolClient>).call(this);
    try {
      const rows = (await client.query('SELECT pg_backend_pid() AS pid')).rows;
      assert.equal(rows.length, 1);
      assert.ok(Number.isSafeInteger(rows[0].pid) && rows[0].pid > 0);
      assert.equal(published, false);
      save('rehydration-expiry-backends.json', {
        schemaVersion: 1,
        phase: 'expiry',
        processId: process.pid,
        schema,
        backendIds: [rows[0].pid],
      });
      published = true;
      reached('rehydration_expiry_waiting');
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
async function expiry() {
  const i = inbox(),
    a = authority(),
    base = referenceCurrentCase(a),
    short = {
      ...f.bindings.B,
      bindingId: id('short-binding'),
      bindingToken: token('short-binding'),
      roomId: 'short-room',
      participantId: 'short-participant',
    },
    expiresAt = new Date(Date.now() + 1400).toISOString();
  let restore = () => {};
  const r = new ChannelRehydrator(
    i,
    {
      async inspect(ref, signal) {
        const value = await base.inspect(ref, signal);
        save('rehydration-expiry-ready.json', {
          schemaVersion: 1,
          bindingId: short.bindingId,
          expiresAt,
          processId: process.pid,
          schema,
        });
        await barrier('rehydration_expiry_ready');
        restore = captureExpiryBackend();
        return value;
      },
    },
    smsIntegration(),
    { timeoutMs: 5000, observer: () => {} },
  );
  try {
    const receipt = await i.bind(f.publisherToken, publication(short, expiresAt));
    await reject(() => r.native(short.bindingToken), 'access_denied');
    restore();
    restore = () => {};
    const fresh = new ChannelRehydrator(i, base, smsIntegration(), { observer: () => {} });
    let context: RehydrationContext;
    try {
      context = await fresh.native(f.bindings.B.bindingToken);
    } finally {
      await fresh.close();
    }
    const retained = await i.history(f.accountToken);
    assert.ok(retained.messages.length >= 3);
    save('rehydration-expiry-proof.json', {
      schemaVersion: 1,
      bindingId: short.bindingId,
      expiresAt,
      deniedCode: 'access_denied',
      freshBindingId: f.bindings.B.bindingId,
      freshContextId: context.contextId,
      originalHistoryRetained: true,
    });
    save('rehydration-expiry-private.json', { receipt, context, retained });
    return { completedGroups: [CASES[4]] };
  } finally {
    restore();
    await closeAll([() => r.close(), () => i.close(), () => a.close()]);
  }
}
async function revocation() {
  const i = inbox(),
    a = authority(),
    base = referenceCurrentCase(a);
  const first = {
      ...f.bindings.B,
      bindingId: id('revocation-before-binding'),
      bindingToken: token('revocation-before'),
      roomId: 'revocation-before-room',
    },
    second = {
      ...f.bindings.B,
      bindingId: id('revocation-after-binding'),
      bindingToken: token('revocation-after'),
      roomId: 'revocation-after-room',
    };
  let enter!: () => void, release!: () => void;
  const entered = new Promise<void>((resolve) => {
      enter = resolve;
    }),
    held = new Promise<void>((resolve) => {
      release = resolve;
    });
  const delayed = new ChannelRehydrator(
      i,
      {
        async inspect(ref, signal) {
          const value = await base.inspect(ref, signal);
          enter();
          await held;
          return value;
        },
      },
      smsIntegration(),
      { observer: () => {} },
    ),
    normal = new ChannelRehydrator(i, base, smsIntegration(), { observer: () => {} });
  try {
    const beforeGrant = await i.bind(f.publisherToken, publication(first));
    await i.bind(f.publisherToken, publication(second));
    const reading = delayed.native(first.bindingToken);
    const denied = observed(reject(() => reading, 'access_denied'));
    await awaitCaseEntry('revocation_case', entered, reading);
    const revokedBefore = await i.revoke(f.publisherToken, first.bindingId);
    release();
    await denied;
    const known = await normal.native(second.bindingToken),
      canonical = JSON.stringify(known);
    const revokedAfter = await i.revoke(f.publisherToken, second.bindingId);
    assert.equal(JSON.stringify(known), canonical);
    await reject(() => normal.native(second.bindingToken), 'access_denied');
    const progress = await normal.native(f.bindings.B.bindingToken);
    save('rehydration-revocation-proof.json', {
      schemaVersion: 1,
      beforeGrant,
      revokedBefore,
      deniedCode: 'access_denied',
      known,
      revokedAfter,
      knownBytesUnchanged: true,
      freshContextId: progress.contextId,
    });
    return { completedGroups: [CASES[5], CASES[7]] };
  } finally {
    release();
    await closeAll([() => delayed.close(), () => normal.close(), () => i.close(), () => a.close()]);
  }
}
async function crash(): Promise<never> {
  const i = inbox(),
    a = authority(),
    r = new ChannelRehydrator(i, referenceCurrentCase(a), smsIntegration(), { observer: () => {} });
  try {
    const context = await r.native(f.bindings.B.bindingToken),
      operations = load<unknown[]>('rehydration-operations.json');
    save('rehydration-crash-original.json', { schemaVersion: 1, context, operations });
    await barrier('rehydration_after_read');
    throw new Error('expected_owned_termination');
  } finally {
    await closeAll([() => r.close(), () => i.close(), () => a.close()]);
  }
}
async function replay() {
  const original = load<{ context: RehydrationContext; operations: unknown[] }>(
      'rehydration-crash-original.json',
    ),
    i = inbox(),
    a = authority(),
    r = new ChannelRehydrator(i, referenceCurrentCase(a), smsIntegration(), { observer: () => {} });
  try {
    const fresh = await r.native(f.bindings.B.bindingToken),
      retained = rehydrationContext(original.context, REF);
    for (const key of ['case', 'access', 'history', 'work', 'responses', 'replies'] as const)
      assert.deepEqual(fresh[key], retained[key]);
    assert.notEqual(fresh.contextId, original.context.contextId);
    assert.deepEqual(load('rehydration-operations.json'), original.operations);
    const seed = load<SeedProof>('rehydration-seed-proof.json');
    assert.deepEqual(
      await i.inspectResponse(f.accountToken, seed.anchor.responseId),
      await i.inspectResponse(f.accountToken, seed.anchor.responseId),
    );
    const proof = {
      schemaVersion: 1,
      context: fresh,
      operations: original.operations,
      originalFactsPreserved: true,
      newContextId: fresh.contextId,
      readSideEffects: 0,
    };
    const name = existsSync(DIR + '/rehydration-replay-proof.json')
      ? 'rehydration-restored-replay-proof.json'
      : 'rehydration-replay-proof.json';
    save(name, proof);
    return { completedGroups: [CASES[16]], factsPreserved: true, readSideEffects: 0 };
  } finally {
    await closeAll([() => r.close(), () => i.close(), () => a.close()]);
  }
}
async function verify(media = false) {
  return ownerSql(async (c) => {
    const rows = (
      await c.query(
        `SELECT i.*,p.operation_key,p.state FROM "${schema}".inbox i JOIN "${schema}".processing_intents p USING(receipt_id) ORDER BY tenant_id,account_id,conversation_id,acceptance_sequence`,
      )
    ).rows;
    const bindings = (
        await c.query(`SELECT * FROM "${schema}".native_bindings ORDER BY binding_id`)
      ).rows,
      responses = (await c.query(`SELECT * FROM "${schema}".native_responses ORDER BY response_id`))
        .rows,
      observations = (
        await c.query(
          `SELECT * FROM "${schema}".native_observations ORDER BY response_id,observation_sequence`,
        )
      ).rows,
      plans = (await c.query(`SELECT * FROM "${schema}".dispatch_plans ORDER BY receipt_id`)).rows;
    const operations = load<
      Array<{
        submission: {
          message: { receiptId: string };
          operationKey: string;
          scope: unknown;
          caseId: string;
          caseRevision: string;
        };
        canonicalPayload: string;
        payloadDigest: string;
        receipt: OperationReceipt;
      }>
    >('rehydration-operations.json');
    for (const op of operations) {
      const matches = rows.filter(
        (row) =>
          row.receipt_id === op.submission.message.receiptId &&
          row.operation_key === op.submission.operationKey &&
          row.tenant_id === f.scope.tenantId &&
          row.account_id === f.scope.accountId,
      );
      assert.equal(matches.length, 1);
      const plan = plans.find((p) => p.receipt_id === matches[0].receipt_id);
      assert.ok(plan);
      assert.equal(plan.payload_json, op.canonicalPayload);
      assert.equal(plan.payload_digest, sha(op.canonicalPayload));
      assert.equal(op.payloadDigest, plan.payload_digest);
      assert.equal(op.receipt.operationKey, op.submission.operationKey);
      assert.deepEqual(op.receipt.scope, op.submission.scope);
      assert.equal(op.submission.caseId, f.caseId);
    }
    for (const response of responses) {
      assert.equal(sha(response.canonical_anchor), response.anchor_digest);
      const anchor = JSON.parse(response.canonical_anchor);
      const input = rows.find((row) => row.receipt_id === anchor.receiptId);
      assert.ok(input);
      assert.equal(input.operation_key, anchor.operationKey);
      assert.equal(anchor.responseId, response.response_id);
      assert.equal(anchor.bindingId, response.binding_id);
      assert.equal(anchor.generationId, response.generation_id);
      assert.equal(anchor.sdkSpeechId, response.sdk_speech_id);
      assert.equal(anchor.caseId, f.caseId);
      assert.equal(anchor.conversationId, f.conversationId);
      assert.equal(anchor.scope.accountId, f.scope.accountId);
      assert.ok(
        bindings.some(
          (b) =>
            b.binding_id === anchor.bindingId &&
            b.room_id === anchor.roomId &&
            b.participant_id === anchor.participantId,
        ),
      );
      for (const observation of observations.filter(
        (o) => o.response_id === response.response_id,
      )) {
        assert.equal(sha(observation.canonical_payload), observation.payload_digest);
        const value = JSON.parse(observation.canonical_payload);
        assert.equal(value.eventId, observation.event_id);
        assert.equal(value.responseId, response.response_id);
        if (observation.source === 'agent_sdk') {
          assert.equal(value.generationId, anchor.generationId);
          assert.equal(value.sdkSpeechId, anchor.sdkSpeechId);
        }
      }
    }
    const proof = {
      schemaVersion: 1,
      rows,
      bindings,
      responses,
      observations,
      plans,
      operations,
      exactIdentityJoins: true,
    };
    save(
      media
        ? 'rehydration-media-owner-proof.json'
        : existsSync(DIR + '/rehydration-owner-proof.json')
          ? 'rehydration-restored-owner-proof.json'
          : 'rehydration-owner-proof.json',
      proof,
    );
    if (media) {
      assert.equal(rows.length, 4);
      assert.equal(bindings.length, 2);
      assert.equal(operations.length, 4);
      assert.equal(plans.length, 4);
      assert.equal(responses.length, 3);
      assert.equal(observations.filter((o) => o.source === 'agent_sdk').length, 6);
      assert.equal(rows.filter((row) => row.provider === 'livekit').length, 3);
      assert.equal(rows.filter((row) => row.provider === 'fake_sms').length, 1);
      const first = responses.filter((row) => row.binding_id === f.bindings.A.bindingId),
        second = responses.filter((row) => row.binding_id === f.bindings.B.bindingId);
      assert.equal(first.length, 2);
      assert.equal(second.length, 1);
      assert.equal(JSON.parse(second[0].canonical_anchor).caseRevision, '2');
      return {
        nativeInputs: 3,
        smsInputs: 1,
        operationAcceptances: 4,
        nativeReplies: 3,
        sameCase: true,
        oldFactsPreserved: true,
      };
    }
    assert.equal(rows.length, 14);
    assert.equal(bindings.length, 6);
    assert.equal(operations.length, 1);
    assert.equal(plans.length, 1);
    assert.equal(responses.length, 1);
    assert.equal(observations.length, 3);
    return { snapshotRowsMatched: true, readSideEffects: 0 };
  });
}
async function main() {
  switch (mode) {
    case 'install':
    case 'media-install':
      return install();
    case 'seed':
      return seed();
    case 'media-seed':
      return mediaSeed();
    case 'exercise':
      return exercise();
    case 'expiry':
      return expiry();
    case 'revocation':
      return revocation();
    case 'crash':
      return crash();
    case 'replay':
      return replay();
    case 'verify':
      return verify();
    case 'media-verify':
      return verify(true);
    case 'media-serve':
      return mediaServe();
    case 'media-sms':
      return mediaSms();
    case 'cleanup':
    case 'media-cleanup':
      return cleanup();
    default:
      throw new Error('invalid_mode');
  }
}
try {
  const extra = await main();
  await Promise.allSettled(pendingAssertions);
  console.info(
    JSON.stringify({
      schemaVersion: 1,
      status: 'passed',
      mode,
      nodeVersion: process.versions.node,
      storageVersion: 7,
      ...extra,
    }),
  );
} catch (error) {
  await Promise.allSettled(pendingAssertions);
  const descriptor =
    error instanceof RehydrationError || error instanceof ChannelError
      ? Object.getOwnPropertyDescriptor(error, 'code')
      : undefined;
  const code =
    descriptor &&
    'value' in descriptor &&
    typeof descriptor.value === 'string' &&
    [
      'access_denied',
      'invalid_query',
      'context_unavailable',
      'overloaded',
      'closed',
      'AccessDenied',
      'SchemaMismatch',
      'StorageUnavailable',
      'UpgradeRequired',
      'OperationConflict',
      'IdentityConflict',
      'Overloaded',
      'InvalidConfiguration',
    ].includes(descriptor.value)
      ? descriptor.value
      : null;
  save('rehydration-failure-' + mode + '.json', {
    schemaVersion: 1,
    mode,
    errorType:
      error instanceof assert.AssertionError
        ? 'AssertionError'
        : error instanceof RehydrationError
          ? 'RehydrationError'
          : error instanceof ChannelError
            ? 'ChannelError'
            : 'DependencyError',
    code,
    entryObservation,
    frames:
      error instanceof Error
        ? (error.stack ?? '')
            .split('\n')
            .flatMap((line) => {
              const match = /pg_rehydration_cases\.js:([1-9][0-9]*):[0-9]+/.exec(line);
              return match ? [{ file: 'pg_rehydration_cases.js', line: Number(match[1]) }] : [];
            })
            .slice(0, 4)
        : [],
  });
  console.error(JSON.stringify({ status: 'failed', code: 'rehydration_fixture_failed' }));
  process.exitCode = 1;
}
