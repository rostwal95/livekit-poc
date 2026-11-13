/** Equivalent actual PostgreSQL routing fixtures; no native/media or confirmation claims. */
import assert from 'node:assert/strict';
import { existsSync, writeFileSync, unlinkSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import {
  RevisionRouter,
  RoutingError,
  CaseAuthorityHttpClient,
  encodeRevisionCommand,
  type CaseAuthorityPort,
  type CaseSnapshot,
  type InvestigationRequest,
} from '@livekit-ecosystem/channel-continuity/routing';
import {
  ReferenceCaseAuthority,
  installReferenceCaseSchema,
} from '@livekit-ecosystem/channel-continuity/reference-case';
import {
  ChannelInbox,
  SeededAccounts,
  type DatabaseSettings,
} from '@livekit-ecosystem/channel-continuity/postgres';
import { installChannelSchema } from '@livekit-ecosystem/channel-continuity/migrations';
import {
  createFakeSmsIntegration,
  signFakeSms,
} from '@livekit-ecosystem/channel-continuity/security';
const REF = { scope: { tenantId: 'tenant-a', accountId: 'account-a' }, caseId: 'case-a' };
const PROVIDER = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' };
const KEY = Buffer.alloc(32, 0x61),
  TOKEN = 'synthetic-routing-account-' + 'a'.repeat(40);
const CASES = [
  'normal_current_case_inspection',
  'controlled_competing_revision_transition',
  'stale_replay_never_infers_original_acceptance',
  'ambiguous_text_clarification',
  'cross_account_routing_denied',
  'current_command_valid_progress',
  'known_unchanged_request',
  'postcommit_ack_loss_stays_unknown',
  'owned_adapter_cleanup',
];
function env(name: string) {
  const value = process.env[name];
  assert.ok(value);
  return value;
}
function database(schema: string, owner = false): DatabaseSettings {
  assert.match(schema, /^p2_(case|inbox)_[a-z0-9_]{1,54}(?![\s\S])/);
  return {
    host: '127.0.0.1',
    port: Number(env('P2_ROUTING_PG_PORT')),
    database: 'livekit_lab',
    user: owner ? 'continuity_migrator' : 'livekit_lab',
    password: env(owner ? 'P2_ROUTING_OWNER_PASSWORD' : 'P2_ROUTING_RUNTIME_PASSWORD'),
    schema,
  };
}
function request(day: number): InvestigationRequest {
  return {
    schemaVersion: 1,
    kind: 'booking_investigation',
    bookingReference: 'DEMO-BK-001',
    newCheckIn: '2030-12-' + String(day),
    investigationConsent: true,
  };
}
function command(expectedRevision: string, day: number): string {
  return encodeRevisionCommand({
    schemaVersion: 1,
    kind: 'case.revise_investigation',
    expectedRevision,
    request: request(day),
  });
}
const directory = env('P2_ROUTING_DIRECTORY'),
  group = env('P2_ROUTING_GROUP');
const inboxSchema = env('P2_ROUTING_INBOX_SCHEMA'),
  caseSchema = env('P2_ROUTING_REFERENCE_SCHEMA');
function signed(body: string, sender: string, eventId: string, occurredAt: string) {
  return signFakeSms(
    { schemaVersion: 1, eventId, messageId: eventId, senderId: sender, body, occurredAt },
    KEY,
    Math.floor(Date.now() / 1000),
    PROVIDER,
  );
}
async function barrier() {
  writeFileSync(directory + '/race.reached', String(process.pid) + '\n', {
    flag: 'wx',
    mode: 0o600,
  });
  const deadline = performance.now() + 5000;
  while (!existsSync(directory + '/race.go')) {
    assert.ok(performance.now() < deadline);
    await delay(10);
  }
}
let stage = 'setup';
let raceStatuses: string[] = [];
async function main() {
  if (process.argv[2] === 'setup') {
    assert.equal(process.env.P2_ROUTING_RUNTIME_PASSWORD, undefined);
    await installChannelSchema(database(inboxSchema, true));
    if (group === 'reference')
      await installReferenceCaseSchema(database(caseSchema, true), [
        { ...REF, revision: '0', request: request(10), cancelled: false, committed: false },
      ]);
    console.info(JSON.stringify({ status: 'passed', mode: 'setup' }));
    return;
  }
  assert.equal(process.env.P2_ROUTING_OWNER_PASSWORD, undefined);
  const accounts = new SeededAccounts([
    { token: TOKEN, ...REF.scope, conversationId: 'conversation-a', caseId: REF.caseId },
  ]);
  const integration = createFakeSmsIntegration(PROVIDER, KEY),
    inbox = new ChannelInbox(database(inboxSchema), integration, accounts, {}, () => {});
  const underlying =
    group === 'reference'
      ? new ReferenceCaseAuthority(database(caseSchema), [REF])
      : new CaseAuthorityHttpClient(
          { host: '127.0.0.1', port: Number(env('P2_ROUTING_BRIDGE_PORT')) },
          'Bearer ' + env('P2_ROUTING_BRIDGE_TOKEN'),
          [REF],
        );
  const authority: CaseAuthorityPort =
    group === 'reference'
      ? {
          inspect: (ref, signal) => underlying.inspect(ref, signal),
          async revise(change, signal) {
            const result = await underlying.revise(change, signal);
            if (existsSync(directory + '/drop-next')) {
              unlinkSync(directory + '/drop-next');
              throw new RoutingError('OutcomeUnknown');
            }
            return result;
          },
        }
      : underlying;
  const events: unknown[] = [],
    router = new RevisionRouter(inbox, authority, [REF], {
      observer: (event) => {
        assert.ok(events.length < 64);
        events.push(event);
      },
    });
  const observed: string[] = [];
  let initial: CaseSnapshot | undefined;
  try {
    for (const sender of ['sender-a', 'sender-b']) {
      const challenge = await inbox.createChallenge(TOKEN, sender);
      const link = signed(
        `LINK ${challenge.challengeId} ${challenge.secret}`,
        sender,
        'link-' + randomUUID(),
        '2030-01-01T00:00:00.000Z',
      );
      await inbox.completeAssociation(link.raw, link.headers);
    }
    async function accept(
      body: string,
      sender = 'sender-a',
      occurredAt = '2030-01-01T00:00:00.000Z',
    ) {
      const sms = signed(body, sender, 'event-' + randomUUID(), occurredAt);
      const accepted = await inbox.acceptSms(sms.raw, sms.headers);
      return { ...accepted, sms, original: await inbox.inspect(TOKEN, accepted.receipt.receiptId) };
    }
    stage = 'accepted_inputs';
    const a = await accept(command('0', 11), 'sender-a', '2099-01-01T00:00:00.000Z');
    const b = await accept(command('0', 12), 'sender-b', '2000-01-01T00:00:00.000Z');
    stage = 'initial_inspect';
    initial = await router.inspect(TOKEN, a.receipt.receiptId);
    assert.equal(initial.revision, '0');
    observed.push(CASES[0]!);
    stage = 'barrier';
    await barrier();
    stage = 'race';
    const race = await Promise.all([
      router.route(TOKEN, a.receipt.receiptId),
      router.route(TOKEN, b.receipt.receiptId),
    ]);
    raceStatuses = race.map((value) => value.status);
    stage = 'race_outcomes';
    assert.deepEqual(race.map((value) => value.status).sort(), ['revised', 'revision_conflict']);
    const winner = race.findIndex((value) => value.status === 'revised');
    const winnerMessage = winner === 0 ? a : b;
    stage = 'winner_snapshot';
    const current = await router.inspect(TOKEN, a.receipt.receiptId);
    assert.equal(current.revision, '1');
    assert.deepEqual(current.request, request(winner === 0 ? 11 : 12));
    assert.equal(a.original.event.occurredAt, '2099-01-01T00:00:00.000Z');
    assert.equal(b.original.event.occurredAt, '2000-01-01T00:00:00.000Z');
    observed.push(CASES[1]!);
    stage = 'stale_replay';
    assert.equal(
      (await router.route(TOKEN, winnerMessage.receipt.receiptId)).status,
      'revision_conflict',
    );
    assert.equal(
      (await router.route(TOKEN, (winner === 0 ? b : a).receipt.receiptId)).status,
      'revision_conflict',
    );
    observed.push(CASES[2]!);
    stage = 'clarification';
    const ambiguous = await accept('yes');
    assert.equal(
      (await router.route(TOKEN, ambiguous.receipt.receiptId)).status,
      'clarification_required',
    );
    observed.push(CASES[3]!);
    stage = 'cross_account';
    await assert.rejects(
      router.route('forged-account', a.receipt.receiptId),
      (error) => error instanceof RoutingError && error.code === 'AccessDenied',
    );
    assert.equal((await router.inspect(TOKEN, a.receipt.receiptId)).revision, '1');
    observed.push(CASES[4]!);
    stage = 'valid_progress';
    const next = await accept(command('1', 13));
    assert.equal((await router.route(TOKEN, next.receipt.receiptId)).status, 'revised');
    assert.equal((await router.inspect(TOKEN, next.receipt.receiptId)).revision, '2');
    observed.push(CASES[5]!);
    stage = 'unchanged';
    const unchanged = await accept(command('2', 13));
    assert.equal((await router.route(TOKEN, unchanged.receipt.receiptId)).status, 'unchanged');
    observed.push(CASES[6]!);
    stage = 'ack_loss';
    writeFileSync(directory + '/drop-next', 'trusted\n', { flag: 'wx', mode: 0o600 });
    const unknown = await accept(command('2', 14));
    const lost = await router.route(TOKEN, unknown.receipt.receiptId);
    assert.equal(lost.status, 'outcome_unknown');
    stage = 'fresh_inspect';
    const fresh = await router.inspect(TOKEN, unknown.receipt.receiptId);
    assert.equal(fresh.revision, '3');
    assert.deepEqual(fresh.request, request(14));
    // Observation after loss does not change the original command's unknown outcome.
    assert.equal(lost.status, 'outcome_unknown');
    assert.equal(
      (await router.route(TOKEN, unknown.receipt.receiptId)).status,
      'revision_conflict',
    );
    stage = 'intake_replay';
    const replay = await inbox.acceptSms(unknown.sms.raw, unknown.sms.headers);
    assert.equal(replay.replayed, true);
    assert.deepEqual(replay.receipt, unknown.receipt);
    assert.equal(
      (await inbox.inspect(TOKEN, unknown.receipt.receiptId)).operationKey,
      unknown.original.operationKey,
    );
    observed.push(CASES[7]!);
    assert.equal(JSON.stringify(events).includes(TOKEN), false);
    assert.equal(JSON.stringify(events).includes('DEMO-BK'), false);
    stage = 'proof';
    writeFileSync(
      directory + '/proof.json',
      JSON.stringify({
        group,
        revision: fresh.revision,
        request: fresh.request,
        winner: winnerMessage.original.event.eventId,
        race: race.map((value) => value.status),
        unknown_original_status: lost.status,
        original_receipt_preserved: true,
        accepted_inputs: 6,
        observer_events: events,
      }),
      { flag: 'wx', mode: 0o600 },
    );
  } finally {
    await router.close();
    await underlying.close();
    await inbox.close();
    assert.equal(router.metrics().active, 0);
    assert.equal(underlying.metrics().active, 0);
  }
  observed.push(CASES[8]!);
  assert.deepEqual(observed, CASES);
  console.info(
    JSON.stringify({
      status: 'passed',
      group,
      cases: observed,
      node_version: process.versions.node,
      cleanup_complete: true,
    }),
  );
}
main().catch((error) => {
  console.info(
    JSON.stringify({
      status: 'failed',
      code: error instanceof RoutingError ? error.code : 'routing_fixture_failed',
      stage,
      race_statuses: raceStatuses,
    }),
  );
  process.exitCode = 1;
});
