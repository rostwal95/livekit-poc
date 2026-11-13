/** Explicit actual PostgreSQL ordinary-fake-send fixtures; no callbacks or provider credentials. */
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';
import { fixtureResult, observeFixtureWork, type FixtureOutcome } from './fixture-work.js';
import {
  ChannelDispatcher,
  type DispatchPorts,
  type PreparedDispatch,
  type OperationReceipt,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  ChannelOutbox,
  OutboxError,
  type SendRequest,
  type OutboxEvent,
} from '@livekit-ecosystem/channel-continuity/outbox';
import { FakeSmsSendClient } from '@livekit-ecosystem/channel-continuity/fake-sms-send';
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
  installChannelSchema,
  upgradeChannelSchemaV2,
  upgradeChannelSchemaV3,
} from '@livekit-ecosystem/channel-continuity/migrations';
const PROVIDER = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' },
  SCOPE = { tenantId: 'tenant-a', accountId: 'account-a' },
  TOKEN = 'synthetic_account_'.repeat(4),
  OTHER = 'synthetic_other_'.repeat(4),
  ALT = 'synthetic_alt_'.repeat(4),
  PUBLISH = 'synthetic_publisher_'.repeat(4),
  ALT_PUBLISH = 'synthetic_alt_publisher_'.repeat(3),
  KEY = Buffer.alloc(32, 0x61);
const DIR = env('P2_OUTBOX_DIRECTORY');
function env(key: string): string {
  const v = process.env[key];
  assert.ok(v);
  return v;
}
function db(owner = false): DatabaseSettings {
  const schema = env('P2_OUTBOX_SCHEMA');
  assert.match(schema, /^p2_outbox_[a-f0-9]{32}(?![\s\S])/);
  return {
    host: '127.0.0.1',
    port: Number(env('P2_OUTBOX_PG_PORT')),
    database: 'livekit_lab',
    user: owner ? 'continuity_migrator' : 'livekit_lab',
    password: env(owner ? 'P2_OUTBOX_OWNER_PASSWORD' : 'P2_OUTBOX_RUNTIME_PASSWORD'),
    schema,
  };
}
const accounts = () =>
  new SeededAccounts([
    { token: TOKEN, ...SCOPE, caseId: 'case-a', conversationId: 'conversation-a' },
    {
      token: OTHER,
      tenantId: 'tenant-a',
      accountId: 'account-b',
      caseId: 'case-a',
      conversationId: 'conversation-a',
    },
    { token: ALT, ...SCOPE, caseId: 'case-alt', conversationId: 'conversation-alt' },
  ]);
const integration = () => createFakeSmsIntegration(PROVIDER, KEY);
const publishers = () => [
  { token: PUBLISH, scope: SCOPE, caseId: 'case-a', conversationId: 'conversation-a' },
  { token: ALT_PUBLISH, scope: SCOPE, caseId: 'case-alt', conversationId: 'conversation-alt' },
];
const fixture = JSON.parse(readFileSync(DIR + '/fixture.json', 'utf8')) as { ids: string[] };
function signed(body: string, senderId: string) {
  const id = 'event-' + randomUUID();
  return signFakeSms(
    {
      schemaVersion: 1,
      eventId: id,
      messageId: id,
      senderId,
      body,
      occurredAt: '2030-01-01T00:00:00.000Z',
    },
    KEY,
    Math.floor(Date.now() / 1000),
    PROVIDER,
  );
}
async function association(inbox: ChannelInbox, sender: string, token = TOKEN) {
  const c = await inbox.createChallenge(token, sender),
    message = signed('LINK ' + c.challengeId + ' ' + c.secret, sender);
  return (await inbox.completeAssociation(message.raw, message.headers)).associationVersion;
}
function inbox() {
  return new ChannelInbox(db(), integration(), accounts(), {}, () => {});
}
function client() {
  return new FakeSmsSendClient(
    { host: '127.0.0.1', port: Number(env('P2_OUTBOX_CARRIER_PORT')) },
    'Bearer ' + env('P2_OUTBOX_CARRIER_TOKEN'),
    PROVIDER,
    { timeoutMs: 1000 },
  );
}
async function barrier(name: string) {
  writeFileSync(DIR + '/' + name + '.reached', String(process.pid) + '\n', {
    flag: 'wx',
    mode: 0o600,
  });
  const end = performance.now() + 10000;
  while (!existsSync(DIR + '/' + name + '.go')) {
    if (performance.now() >= end) throw new Error('barrier_timeout');
    await delay(5);
  }
}
function save(name: string, value: unknown) {
  writeFileSync(DIR + '/' + name, JSON.stringify(value) + '\n', { mode: 0o600 });
}
async function reject(work: () => unknown, code: string) {
  await assert.rejects(
    async () => work(),
    (error: unknown) => error instanceof OutboxError && error.code === code,
  );
}
function draft(n: number) {
  return {
    schemaVersion: 1 as const,
    outboundId: fixture.ids[n]!,
    responseId: 'response-' + n,
    body: n === 3 ? 'retry' : n === 5 ? 'always_fail' : 'Notice ' + n + ' é🙂\n',
  };
}
function operations(loseAck = false): DispatchPorts['operations'] {
  const path = DIR + '/operation-ledger.json';
  const rows = (): { request: PreparedDispatch; receipt: OperationReceipt }[] =>
    existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) : [];
  return {
    capabilities: 'stable_idempotency_and_lookup',
    async lookup(input) {
      const item = rows().find((x) => x.receipt.operationKey === input.operationKey);
      if (!item) return { status: 'absent' };
      assert.equal(item.receipt.payloadDigest, input.payloadDigest);
      assert.deepEqual(item.receipt.scope, input.scope);
      return { status: 'accepted', receipt: item.receipt };
    },
    async accept(request) {
      const all = rows();
      assert.ok(!all.some((x) => x.receipt.operationKey === request.submission.operationKey));
      const receipt = {
        operationKey: request.submission.operationKey,
        scope: request.submission.scope,
        payloadDigest: request.payloadDigest,
        receiptId: randomUUID(),
      };
      all.push({ request, receipt });
      save('operation-ledger.json', all);
      if (loseAck) throw new Error('owned_fixture_ack_lost');
      return receipt;
    },
  };
}
function dispatcher(loseAck = false, noPrepare = false) {
  return new ChannelDispatcher(
    db(),
    integration(),
    accounts(),
    {
      cases: {
        async inspect(ref) {
          assert.equal(noPrepare, false);
          return { ...ref, revision: '1', source: 'synthetic_read_only' };
        },
      },
      agent: {
        async prepare(input) {
          assert.equal(noPrepare, false);
          return {
            kind: 'investigation',
            source: 'scripted',
            caseRevision: input.currentCase.revision,
          };
        },
      },
      operations: operations(loseAck),
    },
    { observer: () => {} },
  );
}
let phase = 'initial';
async function main() {
  const mode = process.argv[2];
  phase = mode ?? 'missing';
  if (mode === 'install') {
    await installChannelSchema(db(true));
    await upgradeChannelSchemaV2(db(true));
    return { mode };
  }
  if (mode === 'upgrade') {
    await upgradeChannelSchemaV3(db(true), { maxReplies: 6, maxRoutes: 4, maxAttempts: 3 });
    return { mode };
  }
  if (mode === 'repeat') {
    await installChannelSchema(db(true));
    await upgradeChannelSchemaV2(db(true));
    await upgradeChannelSchemaV3(db(true), { maxReplies: 6, maxRoutes: 4, maxAttempts: 3 });
    return { mode };
  }
  if (mode === 'seed') {
    const i = inbox();
    try {
      const old = await association(i, 'sender-old'),
        race = await association(i, 'sender-race'),
        m = signed('Original immutable input', 'sender-old'),
        accepted = await i.acceptSms(m.raw, m.headers);
      const dispatch = dispatcher(true);
      try {
        await assert.rejects(
          () => dispatch.step(TOKEN, accepted.receipt.receiptId),
          (error: unknown) =>
            error instanceof Error &&
            Object.getOwnPropertyDescriptor(error, 'code')?.value === 'DispatchUnavailable',
        );
        assert.equal(
          (await dispatch.inspect(TOKEN, accepted.receipt.receiptId)).state,
          'uncertain',
        );
      } finally {
        await dispatch.close();
      }
      save('seed.json', { old, race, message: await i.inspect(TOKEN, accepted.receipt.receiptId) });
      return { mode };
    } finally {
      await i.close();
    }
  }
  if (mode === 'compatibility') {
    const i = inbox(),
      seed = JSON.parse(readFileSync(DIR + '/seed.json', 'utf8')),
      prior = dispatcher(false, true),
      fresh = dispatcher();
    try {
      assert.equal(
        (await prior.reconcile(TOKEN, seed.message.receipt.receiptId)).status,
        'dispatched',
      );
      const m = signed('New v3 accepted investigation', 'sender-old'),
        accepted = await i.acceptSms(m.raw, m.headers);
      assert.equal((await fresh.step(TOKEN, accepted.receipt.receiptId)).status, 'dispatched');
      assert.equal((await fresh.reconcile(TOKEN, accepted.receipt.receiptId)).status, 'dispatched');
      save('compatibility.json', {
        original: await prior.inspect(TOKEN, seed.message.receipt.receiptId),
        fresh: await fresh.inspect(TOKEN, accepted.receipt.receiptId),
      });
      return { mode };
    } finally {
      await prior.close();
      await fresh.close();
      await i.close();
    }
  }
  phase = 'runtime_construction';
  const carrier = client(),
    events: OutboxEvent[] = [],
    i = inbox();
  let pause = false;
  const port = {
      capabilities: 'ordinary_fake_sms_v1' as const,
      send: async (request: SendRequest, signal: AbortSignal) => {
        if (request.outboundId === fixture.ids[4]) throw new Error('PRIVATE_SENTINEL');
        if (pause && request.outboundId === fixture.ids[2]) await barrier('late');
        return carrier.send(request, signal);
      },
    },
    box = new ChannelOutbox(db(), integration(), accounts(), publishers(), port, {
      timeoutMs: 5000,
      observer: (e) => {
        events.push(e);
      },
    });
  try {
    if (mode === 'before-upgrade') {
      phase = 'before_upgrade_enqueue';
      await reject(() => box.enqueue(PUBLISH, draft(0)), 'UpgradeRequired');
      phase = 'before_upgrade_old_inspect';
      const seed = JSON.parse(readFileSync(DIR + '/seed.json', 'utf8'));
      assert.equal(
        JSON.stringify(await i.inspect(TOKEN, seed.message.receipt.receiptId)),
        JSON.stringify(seed.message),
      );
      return { mode };
    }
    if (mode === 'enqueue-kill') {
      const pair = await Promise.all([
        box.enqueue(PUBLISH, draft(0)),
        box.enqueue(PUBLISH, draft(0)),
      ]);
      assert.deepEqual(pair[0], pair[1]);
      await reject(
        () => box.enqueue(PUBLISH, { ...draft(0), body: 'changed' }),
        'IdentityConflict',
      );
      save('queued.json', { receipt: pair[0], pid: process.pid });
      await barrier('queued');
      throw new Error('expected_owned_kill');
    }
    if (mode === 'late-revoke') {
      await i.revokeAssociation(TOKEN, 'sender-new');
      const moved = await association(i, 'sender-new', OTHER),
        third = await association(i, 'sender-third'),
        current = await box.inspectRoute(TOKEN);
      await box.selectRoute(TOKEN, {
        senderId: 'sender-third',
        associationVersion: third,
        expectedRouteVersion: current.version,
      });
      save('late-revoked.json', { moved, third });
      return { mode };
    }
    if (mode === 'drift-check') {
      await reject(() => box.pending(TOKEN), 'Unavailable');
      return { mode };
    }
    if (mode === 'counter-check') {
      await reject(() => box.send(TOKEN, fixture.ids[1]!), 'Unavailable');
      return { mode };
    }
    if (mode === 'replay') {
      const frozen = JSON.parse(readFileSync(DIR + '/proof.json', 'utf8'));
      const known = await box.inspect(TOKEN, fixture.ids[0]!);
      assert.equal(JSON.stringify(known), JSON.stringify(frozen.first));
      assert.deepEqual(await box.enqueue(PUBLISH, draft(0)), known.receipt);
      assert.deepEqual(await box.send(TOKEN, fixture.ids[0]!), {
        status: 'accepted_by_provider',
        outboundId: fixture.ids[0],
        attemptId: known.attempts[0]!.request.attemptId,
      });
      const unknown = await box.inspect(TOKEN, fixture.ids[4]!);
      assert.equal(JSON.stringify(unknown), JSON.stringify(frozen.unknown));
      assert.equal(unknown.state, 'unknown');
      assert.equal(unknown.attempts.length, 1);
      assert.equal((await box.send(TOKEN, fixture.ids[4]!)).status, 'unknown');
      assert.deepEqual(
        await box.enqueue(PUBLISH, draft(0)),
        JSON.parse(readFileSync(DIR + '/queued.json', 'utf8')).receipt,
      );
      return { mode, unknownAttemptId: unknown.attempts[0]!.request.attemptId };
    }
    assert.equal(mode, 'exercise');
    const seed = JSON.parse(readFileSync(DIR + '/seed.json', 'utf8')),
      queued = JSON.parse(readFileSync(DIR + '/queued.json', 'utf8'));
    assert.deepEqual(await box.enqueue(PUBLISH, draft(0)), queued.receipt);
    assert.equal((await box.inspect(TOKEN, fixture.ids[0]!)).state, 'queued');
    assert.ok((await box.pending(TOKEN)).includes(fixture.ids[0]!));
    await reject(() => box.enqueue(TOKEN, draft(1)), 'AccessDenied');
    await reject(() => box.inspect(OTHER, fixture.ids[0]!), 'NotFound');
    await reject(() => box.enqueue(ALT_PUBLISH, draft(0)), 'IdentityConflict');
    for (let n = 1; n < 6; n++) await box.enqueue(PUBLISH, draft(n));
    await reject(
      () => box.enqueue(PUBLISH, { ...draft(0), outboundId: randomUUID() }),
      'Overloaded',
    );
    assert.deepEqual(await box.enqueue(PUBLISH, draft(0)), queued.receipt);
    assert.deepEqual(await box.send(TOKEN, fixture.ids[0]!), {
      status: 'held',
      reason: 'route_missing',
      outboundId: fixture.ids[0],
    });
    let route = await box.selectRoute(TOKEN, {
      senderId: 'sender-old',
      associationVersion: seed.old,
      expectedRouteVersion: '0',
    });
    route = await box.setSuppressed(TOKEN, {
      suppressed: true,
      expectedRouteVersion: route.version,
    });
    const fresh = await association(i, 'sender-new');
    route = await box.selectRoute(TOKEN, {
      senderId: 'sender-new',
      associationVersion: fresh,
      expectedRouteVersion: route.version,
    });
    assert.equal(route.suppressed, true);
    assert.equal((await box.send(TOKEN, fixture.ids[0]!)).status, 'held');
    assert.equal((await box.inspect(TOKEN, fixture.ids[0]!)).attempts.length, 0);
    route = await box.setSuppressed(TOKEN, {
      suppressed: false,
      expectedRouteVersion: route.version,
    });
    const sends = await Promise.all([
      box.send(TOKEN, fixture.ids[0]!),
      box.send(TOKEN, fixture.ids[0]!),
    ]);
    assert.ok(sends.some((x) => x.status === 'accepted_by_provider'));
    const first = await box.inspect(TOKEN, fixture.ids[0]!);
    assert.equal(first.attempts.length, 1);
    assert.equal(first.state, 'accepted_by_provider');
    assert.equal(first.attempts[0]!.request.senderId, 'sender-new');
    route = await box.selectRoute(TOKEN, {
      senderId: 'sender-race',
      associationVersion: seed.race,
      expectedRouteVersion: route.version,
    });
    await barrier('race_ready');
    const raceWork: Promise<FixtureOutcome<unknown>>[] = [];
    try {
      const revoke = observeFixtureWork(i.revokeAssociation(TOKEN, 'sender-race'));
      raceWork.push(revoke);
      await barrier('race_send');
      const raced = observeFixtureWork(box.send(TOKEN, fixture.ids[1]!));
      raceWork.push(raced);
      await fixtureResult(revoke);
      assert.deepEqual(await fixtureResult(raced), {
        status: 'held',
        reason: 'association_required',
        outboundId: fixture.ids[1],
      });
    } finally {
      // Every original caller remains observed while the parent proves ordering.
      await Promise.all(raceWork);
    }
    assert.equal((await box.inspect(TOKEN, fixture.ids[1]!)).attempts.length, 0);
    route = await box.selectRoute(TOKEN, {
      senderId: 'sender-new',
      associationVersion: fresh,
      expectedRouteVersion: route.version,
    });
    pause = true;
    assert.equal((await box.send(TOKEN, fixture.ids[2]!)).status, 'accepted_by_provider');
    pause = false;
    const late = await box.inspect(TOKEN, fixture.ids[2]!);
    assert.equal(late.attempts[0]!.request.senderId, 'sender-new');
    assert.equal(late.attempts[0]!.request.associationVersion, fresh);
    assert.equal((await box.inspectRoute(TOKEN)).senderId, 'sender-third');
    await reject(() => box.inspect(OTHER, fixture.ids[2]!), 'NotFound');
    const reassignedRoute = await box.inspectRoute(TOKEN);
    await reject(
      () =>
        box.selectRoute(TOKEN, {
          senderId: 'sender-new',
          associationVersion: fresh,
          expectedRouteVersion: reassignedRoute.version,
        }),
      'AccessDenied',
    );
    assert.equal((await box.send(TOKEN, fixture.ids[3]!)).status, 'definitive_not_accepted');
    assert.equal((await box.send(TOKEN, fixture.ids[3]!)).status, 'accepted_by_provider');
    const retry = await box.inspect(TOKEN, fixture.ids[3]!);
    assert.equal(retry.attempts.length, 2);
    assert.notEqual(retry.attempts[0]!.request.attemptId, retry.attempts[1]!.request.attemptId);
    assert.notEqual(
      retry.attempts[0]!.request.providerOperationKey,
      retry.attempts[1]!.request.providerOperationKey,
    );
    assert.equal((await box.send(TOKEN, fixture.ids[4]!)).status, 'unknown');
    const unknown = await box.inspect(TOKEN, fixture.ids[4]!);
    assert.equal(unknown.state, 'unknown');
    const fourth = await association(i, 'sender-fourth'),
      current = await box.inspectRoute(TOKEN);
    await box.selectRoute(TOKEN, {
      senderId: 'sender-fourth',
      associationVersion: fourth,
      expectedRouteVersion: current.version,
    });
    assert.equal((await box.send(TOKEN, fixture.ids[4]!)).status, 'unknown');
    assert.equal(
      (await box.inspect(TOKEN, fixture.ids[4]!)).attempts[0]!.request.senderId,
      'sender-third',
    );
    for (let n = 0; n < 3; n++)
      assert.equal((await box.send(TOKEN, fixture.ids[5]!)).status, 'definitive_not_accepted');
    assert.equal((await box.send(TOKEN, fixture.ids[5]!)).status, 'exhausted');
    assert.equal((await box.inspect(TOKEN, fixture.ids[5]!)).attempts.length, 3);
    assert.equal(
      JSON.stringify((await i.inspect(TOKEN, seed.message.receipt.receiptId)).event),
      JSON.stringify(seed.message.event),
    );
    assert.ok(events.some((e) => e.code === 'queued'));
    assert.ok(events.some((e) => e.code === 'replayed'));
    assert.ok(events.some((e) => e.code === 'suppressed'));
    assert.ok(events.every((e) => Object.keys(e).sort().join(',') === 'code,event'));
    assert.ok(!JSON.stringify(events).includes('Notice'));
    save('proof.json', {
      ids: fixture.ids,
      queued: queued.receipt,
      first,
      late,
      retry,
      unknown,
      events,
      metrics: box.metrics(),
    });
    return { mode };
  } finally {
    await box.close();
    await carrier.close();
    await i.close();
    assert.equal(box.metrics().active, 0);
    assert.equal(carrier.metrics().active, 0);
  }
}
main()
  .then((value) =>
    console.log(
      JSON.stringify({
        status: 'passed',
        node_version: process.versions.node,
        cleanup_complete: true,
        ...value,
      }),
    ),
  )
  .catch((error: unknown) => {
    const descriptor =
      error instanceof Error ? Object.getOwnPropertyDescriptor(error, 'code') : undefined;
    const reason =
      descriptor &&
      'value' in descriptor &&
      typeof descriptor.value === 'string' &&
      [
        'InvalidCommand',
        'AccessDenied',
        'UpgradeRequired',
        'Unavailable',
        'SchemaMismatch',
        'DispatchUnavailable',
        'ERR_ASSERTION',
      ].includes(descriptor.value)
        ? descriptor.value
        : 'unexpected';
    console.log(JSON.stringify({ status: 'failed', code: 'fixture_failed', phase, reason }));
    process.exitCode = 1;
  });
