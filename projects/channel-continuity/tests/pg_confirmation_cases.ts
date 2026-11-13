/** Actual P1 exact confirmation and immutable P2 prompt/accepted SMS fixtures. */
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import {
  ConfirmationRouter,
  ConfirmationHttpClient,
  ConfirmationError,
  encodeConfirmation,
  quoteDigest,
  type ConfirmationPrompt,
} from '@livekit-ecosystem/channel-continuity/confirmation';
import {
  PromptRegistry,
  installPromptRegistry,
} from '@livekit-ecosystem/channel-continuity/prompt-registry';
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
const PROVIDER = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' },
  ACCOUNT = { tenantId: 'tenant-a', accountId: 'account-a' };
const MAIN = { scope: ACCOUNT, caseId: 'case-main' },
  RACE = { scope: ACCOUNT, caseId: 'case-race' };
const MAIN_TOKEN = 'synthetic-main-account-' + 'a'.repeat(40),
  RACE_TOKEN = 'synthetic-race-account-' + 'r'.repeat(40),
  OTHER_TOKEN = 'synthetic-other-account-' + 'b'.repeat(40),
  KEY = Buffer.alloc(32, 0x61);
const CASES = [
  'distinct_publisher_authentication',
  'immutable_response_across_cases',
  'concurrent_publication_and_replay_at_cap',
  'missing_or_unlinked_text_clarification',
  'stale_linked_quote_zero_commit',
  'altered_digest_zero_commit',
  'case_authority_atomic_revision_race',
  'valid_linked_ack_loss_stays_unknown',
  'explicit_original_receipt_replay',
  'known_receipt_after_late_case_cancel',
  'revoked_sender_blocks_new_confirm',
  'reassigned_sender_cannot_transfer',
  'safe_observation_fields',
  'owned_runtime_cleanup',
];
let stage = 'setup';
function env(name: string): string {
  const value = process.env[name];
  assert.ok(value);
  return value;
}
function database(schema: string, owner = false): DatabaseSettings {
  assert.match(schema, /^p2_(inbox|prompt)_[a-f0-9]{32}(?![\s\S])/);
  return {
    host: '127.0.0.1',
    port: Number(env('P2_CONFIRM_PG_PORT')),
    database: 'livekit_lab',
    user: owner ? 'continuity_migrator' : 'livekit_lab',
    password: env(owner ? 'P2_CONFIRM_OWNER_PASSWORD' : 'P2_CONFIRM_RUNTIME_PASSWORD'),
    schema,
  };
}
function signed(body: string, sender: string, occurredAt = '2030-01-01T00:00:00.000Z') {
  const event = 'event-' + randomUUID();
  return signFakeSms(
    { schemaVersion: 1, eventId: event, messageId: event, senderId: sender, body, occurredAt },
    KEY,
    Math.floor(Date.now() / 1000),
    PROVIDER,
  );
}
async function rejects(work: () => Promise<unknown>, code: string) {
  await assert.rejects(work, (err) => err instanceof ConfirmationError && err.code === code);
}
async function barrier(directory: string, name: string) {
  writeFileSync(directory + '/' + name + '.reached', String(process.pid) + '\n', {
    flag: 'wx',
    mode: 0o600,
  });
  const end = performance.now() + 10000;
  while (!existsSync(directory + '/' + name + '.go')) {
    assert.ok(performance.now() < end);
    await delay(10);
  }
}
async function main() {
  const inboxSchema = env('P2_CONFIRM_INBOX_SCHEMA'),
    promptSchema = env('P2_CONFIRM_PROMPT_SCHEMA'),
    directory = env('P2_CONFIRM_DIRECTORY');
  if (process.argv[2] === 'setup') {
    assert.equal(process.env.P2_CONFIRM_RUNTIME_PASSWORD, undefined);
    await installChannelSchema(database(inboxSchema, true));
    await installPromptRegistry(database(promptSchema, true), 3);
    console.info(JSON.stringify({ status: 'passed', mode: 'setup' }));
    return;
  }
  assert.equal(process.env.P2_CONFIRM_OWNER_PASSWORD, undefined);
  const accounts = new SeededAccounts([
    { token: MAIN_TOKEN, ...ACCOUNT, conversationId: 'conversation-main', caseId: MAIN.caseId },
    { token: RACE_TOKEN, ...ACCOUNT, conversationId: 'conversation-race', caseId: RACE.caseId },
    {
      token: OTHER_TOKEN,
      tenantId: 'tenant-a',
      accountId: 'account-b',
      conversationId: 'conversation-other',
      caseId: 'case-other',
    },
  ]);
  const inbox = new ChannelInbox(
    database(inboxSchema),
    createFakeSmsIntegration(PROVIDER, KEY),
    accounts,
    {},
    () => {},
  );
  const publisherMain = env('P2_CONFIRM_PUBLISH_MAIN_TOKEN'),
    publisherRace = env('P2_CONFIRM_PUBLISH_RACE_TOKEN');
  const registry = new PromptRegistry(database(promptSchema), [
    { token: publisherMain, ...MAIN, conversationId: 'conversation-main' },
    { token: publisherRace, ...RACE, conversationId: 'conversation-race' },
  ]);
  const authority = new ConfirmationHttpClient(
    { host: '127.0.0.1', port: Number(env('P2_CONFIRM_BRIDGE_PORT')) },
    'Bearer ' + env('P2_CONFIRM_BRIDGE_TOKEN'),
    [MAIN, RACE],
  );
  const events: unknown[] = [];
  const router = new ConfirmationRouter(inbox, registry, authority, [MAIN, RACE], {
    observer: (event) => {
      assert.ok(events.length < 128);
      events.push(event);
    },
  });
  const observed: string[] = [],
    acceptedIds: string[] = [];
  try {
    const content = JSON.parse(readFileSync(env('P2_CONFIRM_QUOTES_FILE'), 'utf8')) as {
      prompts: ConfirmationPrompt[];
    };
    assert.equal(content.prompts.length, 3);
    const a = content.prompts.find((p) => p.responseId === 'response-a')!,
      b = content.prompts.find((p) => p.responseId === 'response-b')!,
      r = content.prompts.find((p) => p.responseId === 'response-race')!;
    assert.ok(a && b && r);
    for (const value of [a, b, r]) assert.equal(quoteDigest(value.quoteJson), value.quoteDigest);
    async function bind(token: string, sender: string) {
      const challenge = await inbox.createChallenge(token, sender);
      const frame = signed(`LINK ${challenge.challengeId} ${challenge.secret}`, sender);
      await inbox.completeAssociation(frame.raw, frame.headers);
    }
    await bind(MAIN_TOKEN, 'sender-main');
    await bind(RACE_TOKEN, 'sender-race');
    async function accept(body: string, sender = 'sender-main', time = '2030-01-01T00:00:00.000Z') {
      const frame = signed(body, sender, time),
        value = await inbox.acceptSms(frame.raw, frame.headers);
      acceptedIds.push(value.receipt.receiptId);
      return { ...value, frame };
    }
    stage = 'publisher_auth';
    await rejects(
      async () => registry.publish(MAIN_TOKEN, a, new AbortController().signal),
      'AccessDenied',
    );
    await rejects(
      async () =>
        registry.find(
          {
            caseId: a.caseId,
            conversationId: a.conversationId,
            responseId: a.responseId,
            scope: { tenantId: 'tenant-a', accountId: 'account-b' },
          },
          new AbortController().signal,
        ),
      'AccessDenied',
    );
    observed.push(CASES[0]!);
    stage = 'prompt_publication';
    const equal = await Promise.all([
      registry.publish(publisherMain, a, new AbortController().signal),
      registry.publish(publisherMain, a, new AbortController().signal),
    ]);
    assert.deepEqual(equal[0], equal[1]);
    await registry.publish(publisherMain, b, new AbortController().signal);
    await registry.publish(publisherRace, r, new AbortController().signal);
    stage = 'nonce_identity';
    await rejects(
      async () =>
        registry.publish(
          publisherRace,
          { ...r, responseId: a.responseId },
          new AbortController().signal,
        ),
      'IdentityConflict',
    );
    assert.deepEqual(
      await registry.find(
        {
          scope: a.scope,
          caseId: a.caseId,
          conversationId: a.conversationId,
          responseId: a.responseId,
        },
        new AbortController().signal,
      ),
      equal[0],
    );
    observed.push(CASES[1]!);
    stage = 'prompt_capacity';
    assert.deepEqual(
      await registry.publish(publisherMain, a, new AbortController().signal),
      equal[0],
    );
    await rejects(
      async () =>
        registry.publish(
          publisherMain,
          { ...b, responseId: 'fourth-response' },
          new AbortController().signal,
        ),
      'Overloaded',
    );
    assert.equal(registry.metrics().published, 3);
    observed.push(CASES[2]!);
    stage = 'clarification';
    const bare = await accept('YES'),
      missing = await accept('YES missing-response');
    const before = authority.metrics().started;
    assert.equal(
      (await router.confirm(MAIN_TOKEN, bare.receipt.receiptId)).status,
      'clarification_required',
    );
    assert.equal(
      (await router.confirm(MAIN_TOKEN, missing.receipt.receiptId)).status,
      'clarification_required',
    );
    assert.equal(authority.metrics().started, before);
    observed.push(CASES[3]!);
    stage = 'stale_original_quote';
    const stale = await accept('YES ' + a.responseId, 'sender-main', '2099-01-01T00:00:00.000Z');
    assert.equal(
      (await router.confirm(MAIN_TOKEN, stale.receipt.receiptId)).status,
      'clarification_required',
    );
    observed.push(CASES[4]!);
    stage = 'altered_digest';
    const altered = await accept(
      encodeConfirmation({
        schemaVersion: 1,
        kind: 'case.confirm_quote',
        responseId: b.responseId,
        expectedRevision: b.revision,
        quoteDigest: 'a'.repeat(64),
        explicit: true,
      }),
    );
    const beforeAltered = authority.metrics().started;
    assert.equal(
      (await router.confirm(MAIN_TOKEN, altered.receipt.receiptId)).status,
      'clarification_required',
    );
    assert.equal(authority.metrics().started, beforeAltered);
    observed.push(CASES[5]!);
    stage = 'atomic_race';
    const racing = await accept('YES ' + r.responseId, 'sender-race');
    await barrier(directory, 'race');
    assert.equal(
      (await router.confirm(RACE_TOKEN, racing.receipt.receiptId)).status,
      'clarification_required',
    );
    observed.push(CASES[6]!);
    stage = 'current_lost_ack';
    const current = await accept('YES ' + b.responseId, 'sender-main', '2000-01-01T00:00:00.000Z');
    writeFileSync(directory + '/drop-confirm-next', 'trusted\n', { flag: 'wx', mode: 0o600 });
    const unknown = await router.confirm(MAIN_TOKEN, current.receipt.receiptId);
    assert.equal(unknown.status, 'outcome_unknown');
    observed.push(CASES[7]!);
    stage = 'original_command_replay';
    const known = await router.confirm(MAIN_TOKEN, current.receipt.receiptId);
    assert.equal(known.status, 'accepted');
    assert.ok(known.status === 'accepted');
    assert.equal(unknown.status, 'outcome_unknown');
    const original = await inbox.inspect(MAIN_TOKEN, current.receipt.receiptId);
    assert.equal(known.receipt.commandId, original.operationKey);
    assert.equal(known.receipt.quoteDigest, b.quoteDigest);
    const intakeReplay = await inbox.acceptSms(current.frame.raw, current.frame.headers);
    assert.equal(intakeReplay.replayed, true);
    assert.deepEqual(intakeReplay.receipt, current.receipt);
    observed.push(CASES[8]!);
    stage = 'cancelled_case_receipt';
    await barrier(directory, 'cancel');
    const afterCancel = await router.confirm(MAIN_TOKEN, current.receipt.receiptId);
    assert.deepEqual(afterCancel, known);
    observed.push(CASES[9]!);
    stage = 'revoked_input';
    const beforeDeny = authority.metrics().started;
    await inbox.revokeAssociation(MAIN_TOKEN, 'sender-main');
    assert.equal(
      (await inbox.inspect(MAIN_TOKEN, current.receipt.receiptId)).operationKey,
      original.operationKey,
    );
    await rejects(() => router.confirm(MAIN_TOKEN, current.receipt.receiptId), 'AccessDenied');
    assert.equal(authority.metrics().started, beforeDeny);
    observed.push(CASES[10]!);
    stage = 'reassigned_input';
    await bind(OTHER_TOKEN, 'sender-main');
    await rejects(() => router.confirm(MAIN_TOKEN, current.receipt.receiptId), 'AccessDenied');
    await rejects(() => router.confirm(OTHER_TOKEN, current.receipt.receiptId), 'AccessDenied');
    assert.equal(authority.metrics().started, beforeDeny);
    observed.push(CASES[11]!);
    stage = 'safe_observations';
    const serialized = JSON.stringify(events);
    for (const value of [MAIN_TOKEN, publisherMain, publisherRace, b.quoteJson, b.quoteId])
      assert.equal(serialized.includes(value), false);
    observed.push(CASES[12]!);
    assert.equal(acceptedIds.length, 6);
    writeFileSync(
      directory + '/proof.json',
      JSON.stringify({
        accepted_inputs: acceptedIds.length,
        prompt_count: registry.metrics().published,
        retained_receipt: current.receipt,
        operation_key: original.operationKey,
        command_id: known.receipt.commandId,
        quote_digest: known.receipt.quoteDigest,
        quote_id: known.receipt.quoteId,
        revision: known.receipt.revision,
        intent_id: known.receipt.intentId,
        effect_id: known.receipt.effectId,
        unknown_original_status: unknown.status,
        authority_calls_before_denied: beforeDeny,
        authority_calls_after_denied: authority.metrics().started,
        observer_events: events,
      }),
      { flag: 'wx', mode: 0o600 },
    );
  } finally {
    const closed = await Promise.allSettled([
      router.close(),
      authority.close(),
      registry.close(),
      inbox.close(),
    ]);
    assert.ok(closed.every((result) => result.status === 'fulfilled'));
    assert.equal(router.metrics().active, 0);
    assert.equal(authority.metrics().active, 0);
    assert.equal(registry.metrics().active, 0);
  }
  observed.push(CASES[13]!);
  assert.deepEqual(observed, CASES);
  console.info(
    JSON.stringify({
      status: 'passed',
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
      stage,
      code: error instanceof ConfirmationError ? error.code : 'fixture_failed',
    }),
  );
  process.exitCode = 1;
});
