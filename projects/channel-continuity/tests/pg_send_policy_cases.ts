/** Explicit local v5 send-policy fixture. Public SDK only; parent owns SQL and provider. */
import assert from 'node:assert/strict';
import { randomUUID, createHash } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';
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
  ChannelOutbox,
  OutboxError,
  providerOperationFromRequest,
  operationDigest,
  type CarrierSendPort,
  type SendRequest,
  type RecoveryCommandView,
  type ProviderOperation,
  type ProviderLookup,
  type OutboxReceipt,
  type OutboxObservation,
} from '@livekit-ecosystem/channel-continuity/outbox';
import { FakeSmsSendClient } from '@livekit-ecosystem/channel-continuity/fake-sms-send';
import { IdempotentFakeSmsClient } from '@livekit-ecosystem/channel-continuity/idempotent-fake-sms';
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
} from '@livekit-ecosystem/channel-continuity/migrations';
const DIR = env('P2_SEND_POLICY_DIRECTORY'),
  SCOPE = { tenantId: 'tenant-a', accountId: 'account-a' },
  PROVIDER = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' },
  TOKEN = 'synthetic_account_'.repeat(4),
  OTHER = 'synthetic_other_'.repeat(4),
  PUB = 'synthetic_publisher_'.repeat(4),
  CONTROL = 'synthetic_controller_'.repeat(4),
  KEY = Buffer.alloc(32, 0x61),
  CBKEY = Buffer.alloc(32, 0x71);
function env(k: string) {
  const v = process.env[k];
  assert.ok(v);
  return v;
}
const fixture = JSON.parse(readFileSync(DIR + '/fixture.json', 'utf8')) as {
  ids: string[];
  port: number;
  token: string;
};
const ids = fixture.ids,
  sha = (v: string) => createHash('sha256').update(v).digest('hex');
const pendingAssertions: Promise<unknown>[] = [];
function observed<T>(promise: Promise<T>): Promise<T> {
  void promise.catch(() => {});
  pendingAssertions.push(promise);
  return promise;
}
type EntryObservation = {
  phase: 'none' | 'temporal_lookup' | 'ignored_lookup' | 'callback_inverse_send';
  entered: boolean;
  caller: 'pending' | 'fulfilled' | 'rejected';
  callerCode: 'AcknowledgementUnknown' | 'Unavailable' | 'AccessDenied' | 'Overloaded' | null;
  cause: 'pending' | 'entry' | 'caller_settled' | 'watchdog';
};
let entryObservation: EntryObservation = {
  phase: 'none',
  entered: false,
  caller: 'pending',
  callerCode: null,
  cause: 'pending',
};
async function awaitEntry(
  phase: Exclude<EntryObservation['phase'], 'none'>,
  entered: Promise<void>,
  caller: Promise<unknown>,
): Promise<void> {
  const observation: EntryObservation = {
    phase,
    entered: false,
    caller: 'pending',
    callerCode: null,
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
        (error: unknown) => {
          observation.caller = 'rejected';
          if (
            error instanceof OutboxError &&
            ['AcknowledgementUnknown', 'Unavailable', 'AccessDenied', 'Overloaded'].includes(
              error.code,
            )
          )
            observation.callerCode = error.code as NonNullable<EntryObservation['callerCode']>;
          return 'caller_settled' as const;
        },
      ),
      new Promise<'watchdog'>((resolve) => {
        timer = setTimeout(() => resolve('watchdog'), 2000);
      }),
    ]);
    if (observation.cause !== 'entry') throw new OutboxError('AcknowledgementUnknown');
  } finally {
    clearTimeout(timer);
  }
}
function save(name: string, value: unknown) {
  writeFileSync(DIR + '/' + name, JSON.stringify(value) + '\n', { mode: 0o600 });
}
function load<T>(name: string): T {
  return JSON.parse(readFileSync(DIR + '/' + name, 'utf8')) as T;
}
function db(owner = false): DatabaseSettings {
  const schema = env('P2_SEND_POLICY_SCHEMA');
  assert.match(schema, /^p2_send_policy_[a-f0-9]{32}$/);
  return {
    host: '127.0.0.1',
    port: Number(env('P2_SEND_POLICY_PG_PORT')),
    database: 'livekit_lab',
    user: owner ? 'continuity_migrator' : 'livekit_lab',
    password: env(owner ? 'P2_SEND_POLICY_OWNER_PASSWORD' : 'P2_SEND_POLICY_RUNTIME_PASSWORD'),
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
  ]);
const integration = () => createFakeSmsIntegration(PROVIDER, KEY),
  binding = { scope: SCOPE, caseId: 'case-a', conversationId: 'conversation-a' };
const policy = { maxRecoveryCommands: 128, maxPerOperation: 8 };
const native = () =>
  new IdempotentFakeSmsClient(
    { host: '127.0.0.1', port: fixture.port },
    'Bearer ' + fixture.token,
    PROVIDER,
    { timeoutMs: 1500 },
  );
const ordinary = () =>
  new FakeSmsSendClient(
    { host: '127.0.0.1', port: fixture.port },
    'Bearer ' + fixture.token,
    PROVIDER,
    { timeoutMs: 1500 },
  );
function box(port: CarrierSendPort, options: ConstructorParameters<typeof ChannelOutbox>[5] = {}) {
  return new ChannelOutbox(db(), integration(), accounts(), [{ token: PUB, ...binding }], port, {
    observer: () => {},
    recoveryControllers: [{ token: CONTROL, ...binding }],
    timeoutMs: 2000,
    ...options,
  });
}
function inbox() {
  return new ChannelInbox(db(), integration(), accounts(), {}, () => {});
}
async function barrier(name: string) {
  writeFileSync(DIR + '/' + name + '.reached', String(process.pid) + '\n', {
    flag: 'wx',
    mode: 0o600,
  });
  const end = performance.now() + 10000;
  while (!existsSync(DIR + '/' + name + '.go')) {
    if (performance.now() > end) throw Error('barrier_timeout');
    await delay(5);
  }
}
async function link(i: ChannelInbox, sender = 'sender-original') {
  const c = await i.createChallenge(TOKEN, sender),
    id = 'link-' + randomUUID(),
    m = signFakeSms(
      {
        schemaVersion: 1,
        eventId: id,
        messageId: id,
        senderId: sender,
        body: 'LINK ' + c.challengeId + ' ' + c.secret,
        occurredAt: '2030-01-01T00:00:00.000Z',
      },
      KEY,
      Math.floor(Date.now() / 1000),
      PROVIDER,
    );
  return (await i.completeAssociation(m.raw, m.headers)).associationVersion;
}
async function route(b: ChannelOutbox, sender = 'sender-original') {
  const i = inbox();
  try {
    const epoch = await link(i, sender),
      r = await b.inspectRoute(TOKEN);
    await b.selectRoute(TOKEN, {
      expectedRouteVersion: r.version,
      senderId: sender,
      associationVersion: epoch,
    });
    return epoch;
  } finally {
    await i.close();
  }
}
async function enqueue(b: ChannelOutbox, n: number, body: string) {
  return b.enqueue(PUB, {
    schemaVersion: 1,
    outboundId: ids[n]!,
    responseId: 'response-' + n,
    body,
  });
}
async function attempt(b: ChannelOutbox, n: number) {
  const a = (await b.inspect(TOKEN, ids[n]!)).attempts.at(-1);
  assert.ok(a);
  return a.request;
}
const command = (n: number) => ids[n]!;
async function reconcile(b: ChannelOutbox, r: SendRequest, key: string = randomUUID()) {
  return b.reconcile(CONTROL, { commandId: key, outboundId: r.outboundId, attemptId: r.attemptId });
}
async function retry(b: ChannelOutbox, r: SendRequest, key: string = randomUUID()) {
  return b.retry(CONTROL, {
    commandId: key,
    outboundId: r.outboundId,
    expectedAttemptId: r.attemptId,
  });
}
async function reject(work: () => unknown, code: string) {
  await assert.rejects(
    async () => work(),
    (e: unknown) =>
      e instanceof Error && Object.getOwnPropertyDescriptor(e, 'code')?.value === code,
  );
}
function callback(r: SendRequest, id: string) {
  return signFakeSmsCallback(
    {
      schemaVersion: 1,
      eventId: id,
      attemptId: r.attemptId,
      providerOperationKey: r.providerOperationKey,
      requestDigest: sha(JSON.stringify(r)),
      providerMessageId: 'provider-' + r.providerOperationKey,
      state: 'delivered',
      occurredAt: '2030-01-01T00:00:00.000Z',
    },
    CBKEY,
    Math.floor(Date.now() / 1000),
    PROVIDER,
  );
}
function cb() {
  return new CallbackInbox(db(), createFakeSmsCallbackIntegration(PROVIDER, CBKEY), accounts(), {
    observer: () => {},
  });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
let stage = 'startup';
async function main() {
  const mode = process.argv[2];
  stage = mode ?? 'missing';
  if (mode === 'install') {
    await installChannelSchema(db(true));
    await upgradeChannelSchemaV2(db(true));
    await upgradeChannelSchemaV3(db(true), { maxReplies: 32, maxRoutes: 4, maxAttempts: 5 });
    await upgradeChannelSchemaV4(db(true));
  } else if (mode === 'upgrade') {
    await upgradeChannelSchemaV5(db(true), policy);
  } else if (mode === 'repeat') {
    await installChannelSchema(db(true));
    await upgradeChannelSchemaV2(db(true));
    await upgradeChannelSchemaV3(db(true), { maxReplies: 32, maxRoutes: 4, maxAttempts: 5 });
    await upgradeChannelSchemaV4(db(true));
    await upgradeChannelSchemaV5(db(true), policy);
  } else if (mode === 'seed') {
    const p = ordinary(),
      b = box(p);
    try {
      await route(b);
      const receipt = await enqueue(b, 0, 'original é🙂\n\"\\ retained');
      assert.equal((await b.send(TOKEN, ids[0]!)).status, 'accepted_by_provider');
      save('seed.json', { receipt, view: await b.inspect(TOKEN, ids[0]!) });
    } finally {
      await b.close();
      await p.close();
    }
  } else if (mode === 'exercise' && existsSync(DIR + '/negative.json')) {
    const p = native(),
      b = box(p);
    try {
      const negative = load<{ defect: string }>('negative.json');
      if (negative.defect === 'counter')
        await reject(async () => reconcile(b, await attempt(b, 8)), 'Unavailable');
      else await reject(() => b.inspectRecovery(TOKEN, ids[5]!), 'Unavailable');
    } finally {
      await b.close();
      await p.close();
    }
  } else if (mode === 'exercise') {
    const p = native(),
      b = box(p),
      o = ordinary(),
      bo = box(o);
    const checks: string[] = [],
      receipts: OutboxReceipt[] = [],
      views: RecoveryCommandView[] = [];
    try {
      stage = 'scope';
      await reject(
        () =>
          b.reconcile(TOKEN, { commandId: randomUUID(), outboundId: ids[0]!, attemptId: ids[0]! }),
        'AccessDenied',
      );
      await reject(() => b.inspectRecovery(OTHER, ids[0]!), 'NotFound');
      checks.push('scope');
      stage = 'normal';
      receipts.push(await enqueue(b, 1, 'normal'));
      assert.equal((await b.send(TOKEN, ids[1]!)).status, 'accepted_by_provider');
      assert.equal((await b.send(TOKEN, ids[1]!)).status, 'accepted_by_provider');
      checks.push('normal');
      stage = 'negative';
      await enqueue(b, 2, 'terminal_negative');
      assert.equal((await b.send(TOKEN, ids[2]!)).status, 'definitive_not_accepted');
      const negative = await attempt(b, 2);
      assert.equal((await b.send(TOKEN, ids[2]!)).status, 'definitive_not_accepted');
      const negative2 = await attempt(b, 2);
      assert.notEqual(negative.providerOperationKey, negative2.providerOperationKey);
      assert.equal(
        (await p.send(negative, new AbortController().signal)).status,
        'definitive_not_accepted',
      );
      checks.push('negative');
      stage = 'ordinary';
      await enqueue(bo, 3, 'ordinary_drop');
      assert.equal((await bo.send(TOKEN, ids[3]!)).status, 'unknown');
      const old = await attempt(bo, 3);
      const ordinaryHeld = await retry(bo, old);
      assert.equal(ordinaryHeld.receipt.code, 'ordinary_no_resend');
      views.push(ordinaryHeld);
      assert.equal((await reconcile(bo, old)).receipt.code, 'ordinary_no_resend');
      await route(bo, 'sender-new');
      assert.equal(
        (await bo.inspect(TOKEN, ids[3]!)).attempts[0]!.request.senderId,
        'sender-original',
      );
      assert.equal((await bo.send(TOKEN, ids[3]!)).status, 'unknown');
      await route(bo);
      checks.push('ordinary');
      stage = 'idempotent';
      await enqueue(b, 4, 'idem_drop');
      assert.equal((await b.send(TOKEN, ids[4]!)).status, 'unknown');
      const a = await attempt(b, 4),
        before = await reconcile(b, a, command(20));
      assert.equal(before.observation?.state, 'accepted_by_provider');
      views.push(before);
      assert.equal((await retry(b, a)).receipt.code, 'known_accepted');
      assert.deepEqual(await reconcile(b, a, command(20)), before);
      checks.push('lookup');
      stage = 'retry';
      await enqueue(b, 5, 'idem_drop');
      assert.equal((await b.send(TOKEN, ids[5]!)).status, 'unknown');
      const r = await attempt(b, 5),
        recovered = await retry(b, r, command(21));
      assert.equal(recovered.receipt.decision, 'retry_reserved');
      assert.equal(recovered.observation?.state, 'accepted_by_provider');
      const next = await attempt(b, 5);
      assert.notEqual(next.attemptId, r.attemptId);
      assert.equal(next.providerOperationKey, r.providerOperationKey);
      assert.equal(
        operationDigest(providerOperationFromRequest(next, p.capabilities)),
        operationDigest(providerOperationFromRequest(r, p.capabilities)),
      );
      assert.deepEqual(await retry(b, r, command(21)), recovered);
      await reject(
        () =>
          b.reconcile(CONTROL, {
            commandId: command(21),
            outboundId: r.outboundId,
            attemptId: r.attemptId,
          }),
        'IdentityConflict',
      );
      await reject(() => retry(b, r), 'RevisionConflict');
      views.push(recovered);
      checks.push('retry');
      stage = 'absent';
      await enqueue(b, 6, 'absent_drop');
      assert.equal((await b.send(TOKEN, ids[6]!)).status, 'unknown');
      const absent = await attempt(b, 6),
        ar = await reconcile(b, absent);
      assert.equal(ar.observation?.state, 'absent');
      assert.equal((await b.send(TOKEN, ids[6]!)).status, 'unknown');
      const recoveredAbsent = await retry(b, absent);
      assert.equal(recoveredAbsent.observation?.state, 'accepted_by_provider');
      views.push(ar, recoveredAbsent);
      checks.push('absent');
      stage = 'permissions';
      await enqueue(b, 7, 'idem_drop');
      await b.send(TOKEN, ids[7]!);
      const frozen = await attempt(b, 7);
      await b.setSuppressed(TOKEN, {
        suppressed: true,
        expectedRouteVersion: (await b.inspectRoute(TOKEN)).version,
      });
      assert.equal((await retry(b, frozen)).receipt.code, 'suppressed');
      const hist = await reconcile(b, frozen);
      assert.equal(hist.observation?.state, 'accepted_by_provider');
      await b.setSuppressed(TOKEN, {
        suppressed: false,
        expectedRouteVersion: (await b.inspectRoute(TOKEN)).version,
      });
      await enqueue(b, 8, 'absent_drop');
      await b.send(TOKEN, ids[8]!);
      const change = await attempt(b, 8);
      await route(b, 'sender-other');
      assert.equal((await retry(b, change)).receipt.code, 'route_changed');
      await route(b);
      const revoked = inbox();
      try {
        await revoked.revokeAssociation(TOKEN, 'sender-original');
      } finally {
        await revoked.close();
      }
      assert.equal((await retry(b, change)).receipt.code, 'association_required');
      await route(b);
      const unavailablePort = {
          capabilities: 'idempotent_fake_sms_v1' as const,
          send: p.send.bind(p),
          async lookup() {
            throw Error('synthetic_provider_unavailable');
          },
        },
        unavailable = box(unavailablePort);
      try {
        assert.equal((await reconcile(unavailable, change)).observation?.state, 'unknown');
      } finally {
        await unavailable.close();
      }
      checks.push('permissions');
      stage = 'attempt_cap';
      await enqueue(b, 16, 'terminal_negative');
      for (let k = 0; k < 5; k++)
        assert.equal((await b.send(TOKEN, ids[16]!)).status, 'definitive_not_accepted');
      assert.equal((await b.send(TOKEN, ids[16]!)).status, 'exhausted');
      const exhausted = await attempt(b, 16);
      assert.equal((await retry(b, exhausted)).receipt.code, 'known_not_accepted');
      checks.push('attempt_cap');
      stage = 'capacity';
      for (let n = 0; n < 6; n++) await retry(bo, old);
      await reject(() => retry(bo, old), 'Overloaded');
      assert.equal(
        (await bo.inspectRecovery(TOKEN, old.outboundId)).operations[0]!.commandCount,
        8,
      );
      checks.push('capacity');
      stage = 'temporal_history';
      const delayed = deferred<ProviderLookup>(),
        started = deferred<void>();
      const temporalPort = {
        capabilities: 'idempotent_fake_sms_v1' as const,
        send: p.send.bind(p),
        async lookup(_operation: ProviderOperation, _signal: AbortSignal) {
          started.resolve();
          return delayed.promise;
        },
      };
      const temporal = box(temporalPort);
      let temporalFallback: ProviderLookup | undefined;
      let temporalError: unknown;
      try {
        await enqueue(temporal, 14, 'temporal_terminal');
        await temporal.send(TOKEN, ids[14]!);
        const initial = await attempt(temporal, 14),
          late = observed(reconcile(temporal, initial));
        const originalOperation = providerOperationFromRequest(initial, p.capabilities);
        temporalFallback = {
          schemaVersion: 1,
          providerScope: PROVIDER,
          providerOperationKey: originalOperation.providerOperationKey,
          operationDigest: operationDigest(originalOperation),
          state: 'unknown',
          providerMessageId: null,
        };
        await awaitEntry('temporal_lookup', started.promise, late);
        const denied = await retry(temporal, initial);
        assert.equal(denied.observation?.state, 'definitive_not_accepted');
        assert.equal((await temporal.send(TOKEN, ids[14]!)).status, 'definitive_not_accepted');
        const before = await temporal.inspect(TOKEN, ids[14]!),
          bRequest = await attempt(temporal, 14);
        assert.notEqual(bRequest.providerOperationKey, initial.providerOperationKey);
        const op = providerOperationFromRequest(initial, p.capabilities);
        delayed.resolve({
          schemaVersion: 1,
          providerScope: PROVIDER,
          providerOperationKey: op.providerOperationKey,
          operationDigest: operationDigest(op),
          state: 'accepted_by_provider',
          providerMessageId: 'deliberate-provider-contract-conflict',
        });
        const contradiction = await late;
        assert.equal(contradiction.observation?.assessment, 'conflicted');
        assert.deepEqual(await temporal.inspect(TOKEN, ids[14]!), before);
        assert.equal((await temporal.send(TOKEN, ids[14]!)).status, 'unknown');
        assert.equal((await retry(temporal, bRequest)).receipt.code, 'prior_operation_evidence');
        save('temporal.json', {
          before,
          contradiction,
          summary: await temporal.inspectRecovery(TOKEN, ids[14]!),
          label: 'deliberate_provider_contract_contradiction_no_physical_guarantee',
        });
      } catch (error) {
        temporalError = error;
        throw error;
      } finally {
        if (temporalFallback) delayed.resolve(temporalFallback);
        try {
          await temporal.close();
        } catch (error) {
          if (temporalError === undefined) throw error;
        }
      }
      checks.push('temporal');
      stage = 'ignored_lifetime';
      const held = deferred<ProviderLookup>();
      let timeoutPortEntered = false;
      const ignoring = {
        capabilities: 'idempotent_fake_sms_v1' as const,
        send: p.send.bind(p),
        async lookup(_op: ProviderOperation, _signal: AbortSignal) {
          timeoutPortEntered = true;
          return held.promise;
        },
      };
      // Arrange the retained original send under the normal fixture budget.
      await enqueue(b, 15, 'absent_drop');
      await b.send(TOKEN, ids[15]!);
      const lifetimeRequest = await attempt(b, 15),
        op = providerOperationFromRequest(lifetimeRequest, p.capabilities);
      const fallback: ProviderLookup = {
        schemaVersion: 1,
        providerScope: PROVIDER,
        providerOperationKey: op.providerOperationKey,
        operationDigest: operationDigest(op),
        state: 'unknown',
        providerMessageId: null,
      };
      const bounded = box(ignoring, { timeoutMs: 25, cleanupMs: 25 });
      const deadlineCommandId = randomUUID();
      let ignoredError: unknown;
      let deadlinePortObserved = false;
      try {
        const unknown = observed(reconcile(bounded, lifetimeRequest, deadlineCommandId));
        const rejected = observed(reject(() => unknown, 'AcknowledgementUnknown'));
        await rejected;
        deadlinePortObserved = timeoutPortEntered;
      } catch (error) {
        ignoredError = error;
        throw error;
      } finally {
        held.resolve(fallback);
        const end = performance.now() + 2000;
        let drainError: unknown;
        try {
          while (bounded.metrics().active) {
            assert.ok(performance.now() < end);
            await delay(1);
          }
        } catch (error) {
          drainError = error;
        }
        try {
          await bounded.close();
        } catch (error) {
          drainError ??= error;
        }
        if (ignoredError === undefined && drainError !== undefined) throw drainError;
      }
      assert.equal(bounded.metrics().active, 0);
      assert.equal(bounded.metrics().recoveryAcknowledgementUnknown, 1);
      assert.equal(bounded.metrics().recoveryRejected, 0);
      const entered = deferred<void>(),
        abandonedHeld = deferred<ProviderLookup>();
      const abandoning = {
        capabilities: 'idempotent_fake_sms_v1' as const,
        send: p.send.bind(p),
        async lookup(_op: ProviderOperation, _signal: AbortSignal) {
          entered.resolve();
          return abandonedHeld.promise;
        },
      };
      const abandonedBox = box(abandoning, { maxActive: 1, cleanupMs: 25 });
      const abandonedCommandId = randomUUID();
      let abandonedError: unknown;
      try {
        const controller = new AbortController();
        const abandoned = observed(
          abandonedBox.reconcile(
            CONTROL,
            {
              commandId: abandonedCommandId,
              outboundId: lifetimeRequest.outboundId,
              attemptId: lifetimeRequest.attemptId,
            },
            controller.signal,
          ),
        );
        const rejected = observed(reject(() => abandoned, 'AcknowledgementUnknown'));
        await awaitEntry('ignored_lookup', entered.promise, abandoned);
        controller.abort();
        await rejected;
        assert.equal(abandonedBox.metrics().active, 1);
        await reject(
          () =>
            abandonedBox.reconcile(CONTROL, {
              commandId: randomUUID(),
              outboundId: lifetimeRequest.outboundId,
              attemptId: lifetimeRequest.attemptId,
            }),
          'Overloaded',
        );
        await reject(() => abandonedBox.close(), 'CleanupIncomplete');
        assert.equal(abandonedBox.metrics().active, 1);
        abandonedHeld.resolve(fallback);
        const end = performance.now() + 2000;
        while (abandonedBox.metrics().active) {
          assert.ok(performance.now() < end);
          await delay(1);
        }
        const deadlineCommand = await b.recoveryCommand(TOKEN, deadlineCommandId);
        const abandonedCommand = await b.recoveryCommand(TOKEN, abandonedCommandId);
        assert.ok(abandonedCommand?.observation);
        const providerStartedBefore = p.metrics().started!;
        const lookupInvocationsBefore = b.metrics().lookupInvocations!;
        const retryInvocationsBefore = b.metrics().retryInvocations!;
        if (deadlineCommand)
          assert.deepEqual(await reconcile(b, lifetimeRequest, deadlineCommandId), deadlineCommand);
        assert.deepEqual(await reconcile(b, lifetimeRequest, abandonedCommandId), abandonedCommand);
        const replay = {
          deadlineReplayed: deadlineCommand !== null,
          abandonedReplayed: true,
          providerStartedBefore,
          providerStartedAfter: p.metrics().started!,
          lookupInvocationsBefore,
          lookupInvocationsAfter: b.metrics().lookupInvocations!,
          retryInvocationsBefore,
          retryInvocationsAfter: b.metrics().retryInvocations!,
        };
        assert.equal(replay.providerStartedAfter, replay.providerStartedBefore);
        assert.equal(replay.lookupInvocationsAfter, replay.lookupInvocationsBefore);
        assert.equal(replay.retryInvocationsAfter, replay.retryInvocationsBefore);
        save('bounded.json', {
          ...bounded.metrics(),
          timeoutAndAbandonment: {
            deadlineMs: 25,
            deadlinePortEntered: deadlinePortObserved,
            deadlineCode: 'AcknowledgementUnknown',
            abortAfterActualPortEntry: true,
            retainedUntilRelease: true,
            settledActive: abandonedBox.metrics().active,
            deadlineCommandId,
            deadlineCommand,
            abandonedCommandId,
            abandonedCommand,
            replay,
          },
        });
      } catch (error) {
        abandonedError = error;
        throw error;
      } finally {
        abandonedHeld.resolve(fallback);
        try {
          await abandonedBox.close();
        } catch (error) {
          if (abandonedError === undefined) throw error;
        }
      }
      checks.push('lifetime');
      stage = 'telemetry';
      assert.ok(b.metrics().retryInvocations! >= 2);
      assert.ok(bo.metrics().ordinaryHolds! >= 8);
      assert.ok(b.metrics().permissionVetoes! >= 2);
      assert.equal(b.metrics().active, 0);
      checks.push('telemetry');
      save('exercise.json', {
        checks,
        receipts,
        views,
        normal: await b.inspect(TOKEN, ids[1]!),
        ordinary: await bo.inspect(TOKEN, ids[3]!),
        known: await b.inspect(TOKEN, ids[4]!),
        retry: await b.inspect(TOKEN, ids[5]!),
        absent: await b.inspect(TOKEN, ids[6]!),
        policy: await b.inspectRecovery(TOKEN, ids[5]!),
        metrics: b.metrics(),
      });
    } finally {
      await b.close();
      await bo.close();
      await p.close();
      await o.close();
    }
  } else if (mode === 'race') {
    const p = native(),
      b = box(p);
    try {
      await enqueue(b, 9, 'absent_drop');
      await b.send(TOKEN, ids[9]!);
      const r = await attempt(b, 9);
      save('race-input.json', r);
      await barrier('race_ready');
      const one = observed(retry(b, r, command(22)));
      await barrier('race_first');
      const two = observed(retry(b, r, command(23)));
      await barrier('race_second');
      const outcomes = await Promise.allSettled([one, two]);
      assert.equal(outcomes.filter((x) => x.status === 'fulfilled').length, 1);
      const rejected = outcomes.find((x) => x.status === 'rejected');
      assert.ok(rejected && rejected.status === 'rejected');
      assert.equal((rejected.reason as OutboxError).code, 'RevisionConflict');
      save('race.json', {
        outcomes: outcomes.map((x) => x.status),
        view: await b.inspect(TOKEN, r.outboundId),
      });
    } finally {
      await b.close();
      await p.close();
    }
  } else if (mode === 'callback-race') {
    const p = native(),
      b = box(p),
      c = cb();
    try {
      await enqueue(b, 10, 'absent_drop');
      await b.send(TOKEN, ids[10]!);
      const r = await attempt(b, 10),
        event = callback(r, 'callback-first');
      save('callback-input.json', r);
      await barrier('callback_ready');
      const first = observed(c.accept(event.raw, event.headers));
      await barrier('callback_first');
      const next = observed(retry(b, r, command(24)));
      await barrier('callback_second');
      const receipt = await first,
        result = await next;
      assert.equal(result.receipt.code, 'callback_veto');
      save('callback-race.json', { receipt, result });
      await enqueue(b, 11, 'absent_drop');
      await b.send(TOKEN, ids[11]!);
      const admitted = await attempt(b, 11),
        held = deferred<void>(),
        release = deferred<void>();
      let incoming: SendRequest | undefined;
      const port = {
        capabilities: 'idempotent_fake_sms_v1' as const,
        lookup: p.lookup.bind(p),
        async send(request: SendRequest, signal: AbortSignal) {
          incoming = request;
          held.resolve();
          await release.promise;
          return p.send(request, signal);
        },
      };
      const other = box(port);
      let inverseError: unknown;
      try {
        const pending = observed(retry(other, admitted));
        await awaitEntry('callback_inverse_send', held.promise, pending);
        assert.ok(incoming);
        const i = inbox();
        try {
          await i.revokeAssociation(TOKEN, 'sender-original');
        } finally {
          await i.close();
        }
        const late = callback(admitted, 'retry-first');
        await c.accept(late.raw, late.headers);
        release.resolve();
        assert.equal((await pending).observation?.state, 'accepted_by_provider');
        const current = await attempt(b, 11);
        assert.notEqual(current.attemptId, admitted.attemptId);
        const second = callback(current, 'new-attempt');
        await c.accept(second.raw, second.headers);
        assert.equal(
          (
            await c.inspectAttempt(TOKEN, {
              outboundId: admitted.outboundId,
              attemptId: admitted.attemptId,
            })
          ).observations.length,
          1,
        );
        assert.equal(
          (
            await c.inspectAttempt(TOKEN, {
              outboundId: admitted.outboundId,
              attemptId: current.attemptId,
            })
          ).observations.length,
          1,
        );
        save('callback-inverse.json', { old: admitted, current });
        await route(b);
      } catch (error) {
        inverseError = error;
        throw error;
      } finally {
        release.resolve();
        try {
          await other.close();
        } catch (error) {
          if (inverseError === undefined) throw error;
        }
      }
    } finally {
      await b.close();
      await p.close();
      await c.close();
    }
  } else if (mode === 'crash-observed') {
    const p = native();
    let initial = true;
    const port = {
      capabilities: 'idempotent_fake_sms_v1' as const,
      lookup: p.lookup.bind(p),
      async send(r: SendRequest, s: AbortSignal) {
        const result = await p.send(r, s);
        if (!initial) {
          save('observed-request.json', r);
          await barrier('observed');
        }
        return result;
      },
    };
    const b = box(port);
    await enqueue(b, 12, 'absent_drop');
    await b.send(TOKEN, ids[12]!);
    initial = false;
    const original = await attempt(b, 12);
    save('observed-original.json', original);
    await retry(b, original, command(28));
    throw Error('expected_sigkill');
  } else if (mode === 'crash-reserved') {
    const p = native();
    let original: SendRequest | undefined;
    const port = {
      capabilities: 'idempotent_fake_sms_v1' as const,
      lookup: p.lookup.bind(p),
      async send(r: SendRequest, s: AbortSignal) {
        if (original) {
          save('reserved-request.json', r);
          await barrier('reserved');
        }
        return p.send(r, s);
      },
    };
    const b = box(port);
    await enqueue(b, 13, 'absent_drop');
    await b.send(TOKEN, ids[13]!);
    original = await attempt(b, 13);
    save('reserved-original.json', original);
    await retry(b, original, command(25));
    throw Error('expected_sigkill');
  } else if (mode === 'reopen') {
    const p = native(),
      b = box(p);
    try {
      const restoreOnly = existsSync(DIR + '/restore-only');
      const bounded = load<{
        timeoutAndAbandonment: {
          deadlineCommand: RecoveryCommandView | null;
          abandonedCommand: RecoveryCommandView;
        };
      }>('bounded.json').timeoutAndAbandonment;
      const originals = bounded.deadlineCommand
        ? [bounded.deadlineCommand, bounded.abandonedCommand]
        : [bounded.abandonedCommand];
      const providerStartedBefore = p.metrics().started!;
      const lookupInvocationsBefore = b.metrics().lookupInvocations!;
      const retryInvocationsBefore = b.metrics().retryInvocations!;
      for (const original of originals) {
        assert.equal(original.receipt.kind, 'reconcile');
        assert.deepEqual(await b.recoveryCommand(TOKEN, original.receipt.commandId), original);
        assert.deepEqual(
          await b.reconcile(CONTROL, {
            commandId: original.receipt.commandId,
            outboundId: original.receipt.outboundId,
            attemptId: original.receipt.sourceAttemptId,
          }),
          original,
        );
      }
      const replay = {
        providerStartedBefore,
        providerStartedAfter: p.metrics().started!,
        lookupInvocationsBefore,
        lookupInvocationsAfter: b.metrics().lookupInvocations!,
        retryInvocationsBefore,
        retryInvocationsAfter: b.metrics().retryInvocations!,
      };
      assert.equal(replay.providerStartedAfter, replay.providerStartedBefore);
      assert.equal(replay.lookupInvocationsAfter, replay.lookupInvocationsBefore);
      assert.equal(replay.retryInvocationsAfter, replay.retryInvocationsBefore);
      save('bounded-replay.json', {
        schemaVersion: 1,
        restoreOnly,
        commandIds: originals.map((original) => original.receipt.commandId),
        deadlineNotInvoked: bounded.deadlineCommand === null,
        replay,
      });
      const old = load<{ receipt: OutboxReceipt; view: unknown }>('seed.json');
      assert.deepEqual((await b.inspect(TOKEN, ids[0]!)).receipt, old.receipt);
      const ex = load<{ views: RecoveryCommandView[] }>('exercise.json');
      for (const v of ex.views) {
        assert.deepEqual(await b.recoveryCommand(TOKEN, v.receipt.commandId), v);
        if (v.receipt.kind === 'reconcile')
          assert.deepEqual(
            await b.reconcile(CONTROL, {
              commandId: v.receipt.commandId,
              outboundId: v.receipt.outboundId,
              attemptId: v.receipt.sourceAttemptId,
            }),
            v,
          );
        else
          assert.deepEqual(
            await b.retry(CONTROL, {
              commandId: v.receipt.commandId,
              outboundId: v.receipt.outboundId,
              expectedAttemptId: v.receipt.sourceAttemptId,
            }),
            v,
          );
      }
      const historical = load<{ ordinary: OutboxObservation }>('exercise.json');
      assert.deepEqual(await b.inspect(TOKEN, ids[3]!), historical.ordinary);
      assert.equal(historical.ordinary.state, 'unknown');
      assert.equal(historical.ordinary.attempts[0]!.request.senderId, 'sender-original');
      assert.equal((await b.send(TOKEN, ids[3]!)).status, 'unknown');
      if (restoreOnly) {
        const first = load<{
          found: RecoveryCommandView;
          reserved: RecoveryCommandView;
          useful: RecoveryCommandView;
        }>('reopen.json');
        for (const v of [first.found, first.reserved, first.useful]) {
          assert.deepEqual(await b.recoveryCommand(TOKEN, v.receipt.commandId), v);
          if (v.receipt.kind === 'reconcile')
            assert.deepEqual(
              await b.reconcile(CONTROL, {
                commandId: v.receipt.commandId,
                outboundId: v.receipt.outboundId,
                attemptId: v.receipt.sourceAttemptId,
              }),
              v,
            );
          else
            assert.deepEqual(
              await b.retry(CONTROL, {
                commandId: v.receipt.commandId,
                outboundId: v.receipt.outboundId,
                expectedAttemptId: v.receipt.sourceAttemptId,
              }),
              v,
            );
        }
      } else {
        const originalObserved = load<SendRequest>('observed-original.json'),
          originalPermission = await b.recoveryCommand(TOKEN, command(28));
        assert.ok(originalPermission);
        assert.equal(originalPermission.observation, null);
        assert.deepEqual(await retry(b, originalObserved, command(28)), originalPermission);
        const observed = await attempt(b, 12);
        assert.equal((await b.inspect(TOKEN, ids[12]!)).state, 'unknown');
        const found = await reconcile(b, observed, command(26));
        assert.equal(found.observation?.state, 'accepted_by_provider');
        assert.deepEqual(await reconcile(b, observed, command(26)), found);
        const reserved = await b.recoveryCommand(TOKEN, command(25));
        assert.ok(reserved);
        assert.equal(reserved.receipt.decision, 'retry_reserved');
        assert.equal(reserved.observation, null);
        const original = load<SendRequest>('reserved-original.json');
        assert.deepEqual(await retry(b, original, command(25)), reserved);
        const latest = await attempt(b, 13),
          useful = await retry(b, latest, command(27));
        assert.equal(useful.observation?.state, 'accepted_by_provider');
        save('reopen.json', {
          found,
          reserved,
          useful,
          policy: await b.inspectRecovery(TOKEN, ids[13]!),
          seed: old.receipt,
        });
        let total = 0;
        const candidates: { request: SendRequest; remaining: number }[] = [];
        for (let n = 0; n <= 16; n++) {
          const view = await b.inspect(TOKEN, ids[n]!),
            summary = await b.inspectRecovery(TOKEN, ids[n]!);
          for (const op of summary.operations) {
            total += op.commandCount;
            if (op.state !== 'unknown' || op.capability === 'ordinary_fake_sms_v1') {
              const request = view.attempts.find(
                (a) => a.request.attemptId === op.firstAttemptId,
              )?.request;
              assert.ok(request);
              candidates.push({ request, remaining: 8 - op.commandCount });
            }
          }
        }
        const countBefore = total;
        let originalCapacity: RecoveryCommandView | undefined;
        for (const entry of candidates) {
          for (let k = 0; k < entry.remaining && total < 128; k++) {
            const view = await reconcile(b, entry.request);
            assert.notEqual(view.receipt.decision, 'lookup_authorized');
            originalCapacity ??= view;
            total++;
          }
        }
        assert.equal(total, 128);
        assert.ok(originalCapacity);
        const unknown = await attempt(b, 8);
        await reject(() => reconcile(b, unknown), 'Overloaded');
        assert.deepEqual(
          await b.reconcile(CONTROL, {
            commandId: originalCapacity.receipt.commandId,
            outboundId: originalCapacity.receipt.outboundId,
            attemptId: originalCapacity.receipt.sourceAttemptId,
          }),
          originalCapacity,
        );
        save('capacity.json', {
          countBefore,
          countAfter: total,
          original: originalCapacity,
          inspection: await b.inspectRecovery(TOKEN, originalCapacity.receipt.outboundId),
        });
      }
    } finally {
      await b.close();
      await p.close();
    }
  } else if (mode === 'verify') {
    await upgradeChannelSchemaV5(db(true), policy);
  } else throw Error('invalid_mode');
  console.log(
    JSON.stringify({
      status: 'passed',
      mode,
      cleanup_complete: true,
      node_version: process.versions.node,
    }),
  );
}
void main()
  .finally(async () => {
    await Promise.allSettled(pendingAssertions);
  })
  .catch(() => {
    console.log(
      JSON.stringify({
        status: 'failed',
        mode: process.argv[2],
        code: 'fixture_failed',
        stage,
        entryObservation,
      }),
    );
    process.exitCode = 1;
  });
