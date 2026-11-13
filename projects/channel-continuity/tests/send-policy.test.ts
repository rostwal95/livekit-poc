import { afterEach, describe, it, expect, vi } from 'vitest';
import { randomUUID } from 'node:crypto';
import type { PoolClient } from 'pg';
import {
  ChannelOutbox,
  OutboxError,
  type SendRequest,
  type IdempotentCarrierSendPort,
} from '../src/outbox.js';
import { OutboxStore, type RecoveryReservation } from '../src/outbox-store.js';
import { SendPolicyStore } from '../src/send-policy-store.js';
import { sendRequest, sha } from '../src/outbox-types.js';
import {
  operation,
  operationFrom,
  operationDigest,
  lookup,
  sendPolicyLimits,
  recoveryReceipt,
  recoveryObservation,
  type ProviderLookup,
} from '../src/send-policy-types.js';
import { SeededAccounts } from '../src/postgres.js';
import { createFakeSmsIntegration } from '../src/security.js';
const PROVIDER = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'provider-a' },
  ACCOUNT = { tenantId: 'tenant-a', accountId: 'account-a' },
  REF = { scope: ACCOUNT, caseId: 'case-a', conversationId: 'conversation-a' },
  TOKEN = 'account_'.repeat(6),
  PUBLISH = 'publisher_'.repeat(5),
  CONTROL = 'controller_'.repeat(5),
  KEY = Buffer.alloc(32, 9),
  DB = {
    host: '127.0.0.1',
    port: 15432,
    database: 'livekit_lab',
    user: 'livekit_lab',
    password: 'x'.repeat(40),
    schema: 'p2_policy_unit',
  };
const REQUEST: SendRequest = sendRequest({
    schemaVersion: 1,
    outboundId: randomUUID(),
    responseId: 'response-a',
    body: 'Notice café🙂\n',
    ...REF,
    attemptId: randomUUID(),
    providerOperationKey: randomUUID(),
    providerScope: PROVIDER,
    senderId: 'sender-a',
    associationVersion: '1',
    routeVersion: '2',
  }),
  OP = operationFrom(REQUEST, 'idempotent_fake_sms_v1'),
  COMMAND = randomUUID(),
  RECEIPT = recoveryReceipt({
    schemaVersion: 1,
    receiptId: randomUUID(),
    commandId: COMMAND,
    kind: 'reconcile',
    outboundId: REQUEST.outboundId,
    sourceAttemptId: REQUEST.attemptId,
    providerOperationKey: OP.providerOperationKey,
    operationDigest: operationDigest(OP),
    decision: 'lookup_authorized',
    code: 'lookup',
    newAttemptId: null,
    acceptedAt: '2030-01-01T00:00:00.000Z',
  });
const accepted = (): ProviderLookup =>
  lookup(
    {
      schemaVersion: 1,
      providerScope: PROVIDER,
      providerOperationKey: OP.providerOperationKey,
      operationDigest: operationDigest(OP),
      state: 'accepted_by_provider',
      providerMessageId: 'message-a',
    },
    OP,
  );
const directory = () =>
  new SeededAccounts([
    { token: TOKEN, ...ACCOUNT, caseId: REF.caseId, conversationId: REF.conversationId },
  ]);
const runtime = (
  carrier: IdempotentCarrierSendPort,
  options: ConstructorParameters<typeof ChannelOutbox>[5] = {},
) =>
  new ChannelOutbox(
    DB,
    createFakeSmsIntegration(PROVIDER, KEY),
    directory(),
    [{ token: PUBLISH, ...REF }],
    carrier,
    { observer: () => {}, recoveryControllers: [{ token: CONTROL, ...REF }], ...options },
  );
const port = (): IdempotentCarrierSendPort => ({
  capabilities: 'idempotent_fake_sms_v1',
  async send() {
    throw Error('unexpected send');
  },
  async lookup() {
    return accepted();
  },
});
const deferred = <T>() => {
  let resolve!: (x: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};
const reservation = (): RecoveryReservation => ({
  view: { receipt: RECEIPT, observation: null },
  created: true,
  action: 'lookup',
  operation: OP,
  request: null,
});
afterEach(() => vi.restoreAllMocks());
describe('immutable operation versus local invocation identity', () => {
  it('preserves one provider payload/key/digest across new local attempt and route observation epochs', () => {
    const changed = sendRequest({
      ...REQUEST,
      attemptId: randomUUID(),
      associationVersion: '9',
      routeVersion: '10',
    });
    expect(operationFrom(changed, 'idempotent_fake_sms_v1')).toEqual(OP);
    expect(operationDigest(operationFrom(changed, 'idempotent_fake_sms_v1'))).toBe(
      operationDigest(OP),
    );
    expect(sha(JSON.stringify(changed))).not.toBe(sha(JSON.stringify(REQUEST)));
  });
  it.each([
    { body: 'changed' },
    { senderId: 'other' },
    { responseId: 'other' },
    { outboundId: randomUUID() },
    { caseId: 'other' },
    { conversationId: 'other' },
    { scope: { ...ACCOUNT, accountId: 'other' } },
    { providerScope: { ...PROVIDER, providerAccountId: 'other' } },
  ])('binds changed operation field %j', (change) => {
    expect(
      operationDigest(
        operationFrom(sendRequest({ ...REQUEST, ...change }), 'idempotent_fake_sms_v1'),
      ),
    ).not.toBe(operationDigest(OP));
  });
  it('separates adopted ordinary provenance from new idempotent capability', () => {
    expect(operationDigest(operationFrom(REQUEST, 'ordinary_fake_sms_v1'))).not.toBe(
      operationDigest(OP),
    );
  });
  it.each([
    {},
    null,
    [],
    { ...OP, schemaVersion: 2 },
    { ...OP, extra: 'bad' },
    { ...OP, body: '\ud800' },
    { ...OP, capability: 'real_provider' },
    { ...OP, providerOperationKey: 'not-a-uuid' },
  ])('rejects malformed operation without coercion %j', (value) =>
    expect(() => operation(value)).toThrow(OutboxError),
  );
  it('rejects getters and custom coercion without executing them', () => {
    let touched = 0;
    const op = { ...OP };
    Object.defineProperty(op, 'body', {
      enumerable: true,
      get() {
        touched++;
        return 'bad';
      },
    });
    expect(() => operation(op)).toThrow(OutboxError);
    expect(() =>
      operation({
        ...OP,
        senderId: {
          toString() {
            touched++;
            return 'x';
          },
        },
      }),
    ).toThrow(OutboxError);
    expect(touched).toBe(0);
  });
  it.each([
    { providerOperationKey: randomUUID() },
    { operationDigest: '0'.repeat(64) },
    { providerScope: { ...PROVIDER, providerAccountId: 'other' } },
    { providerMessageId: null },
    { state: ['accepted_by_provider'] },
  ])('rejects unrelated lookup evidence %j', (change) =>
    expect(() => lookup({ ...accepted(), ...change }, OP)).toThrow(OutboxError),
  );
  it('retains known reported ID even when the separate assessment is conflicted', () => {
    const value = recoveryObservation(
      {
        schemaVersion: 1,
        commandId: COMMAND,
        providerOperationKey: OP.providerOperationKey,
        operationDigest: operationDigest(OP),
        source: 'lookup',
        state: 'accepted_by_provider',
        assessment: 'conflicted',
        providerMessageId: 'other-known-id',
        observedAt: '2030-01-01T00:00:00.000Z',
      },
      RECEIPT,
    );
    expect(value.providerMessageId).toBe('other-known-id');
    expect(value.assessment).toBe('conflicted');
  });
  it.each([
    { maxRecoveryCommands: 0, maxPerOperation: 1 },
    { maxRecoveryCommands: 100001, maxPerOperation: 1 },
    { maxRecoveryCommands: 1, maxPerOperation: 33 },
    { maxRecoveryCommands: true, maxPerOperation: 1 },
  ])('rejects nonfinite or oversized policy %j', (v) =>
    expect(() => sendPolicyLimits(v)).toThrow(OutboxError),
  );
});
describe('explicit recovery command actual lifetime', () => {
  it('replay returns original receipt without either carrier method or observation write', async () => {
    const r = reservation();
    vi.spyOn(OutboxStore.prototype, 'reserveRecovery').mockResolvedValue({
      ...r,
      created: false,
      action: 'none',
    });
    const record = vi.spyOn(OutboxStore.prototype, 'recordRecovery');
    vi.spyOn(OutboxStore.prototype, 'close').mockResolvedValue();
    const carrier = port(),
      send = vi.spyOn(carrier, 'send'),
      find = vi.spyOn(carrier, 'lookup'),
      c = runtime(carrier);
    expect(
      await c.reconcile(CONTROL, {
        commandId: COMMAND,
        outboundId: REQUEST.outboundId,
        attemptId: REQUEST.attemptId,
      }),
    ).toEqual(r.view);
    expect(send).not.toHaveBeenCalled();
    expect(find).not.toHaveBeenCalled();
    expect(record).not.toHaveBeenCalled();
    expect(c.metrics().recoveryReplayed).toBe(1);
    await c.close();
  });
  it('retries are explicit new local invocation with original operation and safe fixed logs', async () => {
    const next = sendRequest({ ...REQUEST, attemptId: randomUUID() }),
      receipt = recoveryReceipt({
        ...RECEIPT,
        kind: 'retry',
        decision: 'retry_reserved',
        code: 'retry_reserved',
        newAttemptId: next.attemptId,
      }),
      r: RecoveryReservation = {
        ...reservation(),
        view: { receipt, observation: null },
        action: 'send',
        request: next,
      };
    vi.spyOn(OutboxStore.prototype, 'reserveRecovery').mockResolvedValue(r);
    const save = vi
      .spyOn(OutboxStore.prototype, 'recordRecovery')
      .mockImplementation(async (receipt) => ({ receipt, observation: null }));
    vi.spyOn(OutboxStore.prototype, 'close').mockResolvedValue();
    const carrier = port();
    vi.spyOn(carrier, 'send').mockResolvedValue({
      schemaVersion: 1,
      attemptId: next.attemptId,
      requestDigest: sha(JSON.stringify(next)),
      status: 'accepted_by_provider',
      providerMessageId: 'message-a',
    });
    const events: unknown[] = [],
      c = runtime(carrier, {
        observer: (e) => {
          events.push(e);
        },
      });
    await c.retry(CONTROL, {
      commandId: COMMAND,
      outboundId: REQUEST.outboundId,
      expectedAttemptId: REQUEST.attemptId,
    });
    expect(carrier.send).toHaveBeenCalledWith(next, expect.any(AbortSignal));
    expect(save.mock.calls[0]![1]).toEqual(OP);
    expect(c.metrics()).toMatchObject({
      retryReservations: 1,
      retryInvocations: 1,
      lookupInvocations: 0,
    });
    expect(JSON.stringify(events)).not.toContain(OP.providerOperationKey);
    await c.close();
  });
  it('retains ignored lookup after timeout/close and records late known observation', async () => {
    vi.spyOn(OutboxStore.prototype, 'reserveRecovery').mockResolvedValue(reservation());
    const saved = vi
      .spyOn(OutboxStore.prototype, 'recordRecovery')
      .mockImplementation(async (receipt) => ({ receipt, observation: null }));
    vi.spyOn(OutboxStore.prototype, 'close').mockResolvedValue();
    const held = deferred<ProviderLookup>(),
      carrier = port();
    vi.spyOn(carrier, 'lookup').mockReturnValue(held.promise);
    const c = runtime(carrier, { timeoutMs: 20, cleanupMs: 20 });
    await expect(
      c.reconcile(CONTROL, {
        commandId: COMMAND,
        outboundId: REQUEST.outboundId,
        attemptId: REQUEST.attemptId,
      }),
    ).rejects.toMatchObject({ code: 'AcknowledgementUnknown' });
    expect(c.metrics().active).toBe(1);
    await expect(c.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
    expect(c.metrics().active).toBe(1);
    held.resolve(accepted());
    await new Promise((r) => setImmediate(r));
    expect(saved).toHaveBeenCalledTimes(1);
    expect(saved.mock.calls[0]![2]).toEqual(accepted());
    expect(c.metrics().active).toBe(0);
    await c.close();
  });
  it('does not begin lookup after abandonment while SQL admission is held', async () => {
    const held = deferred<RecoveryReservation>();
    vi.spyOn(OutboxStore.prototype, 'reserveRecovery').mockReturnValue(held.promise);
    vi.spyOn(OutboxStore.prototype, 'close').mockResolvedValue();
    const carrier = port(),
      find = vi.spyOn(carrier, 'lookup'),
      c = runtime(carrier, { timeoutMs: 20 });
    await expect(
      c.reconcile(CONTROL, {
        commandId: COMMAND,
        outboundId: REQUEST.outboundId,
        attemptId: REQUEST.attemptId,
      }),
    ).rejects.toMatchObject({ code: 'AcknowledgementUnknown' });
    held.resolve(reservation());
    await new Promise((r) => setImmediate(r));
    expect(find).not.toHaveBeenCalled();
    expect(c.metrics().active).toBe(0);
    await c.close();
  });
  it('final monotonic guard includes a synchronous settled observer', async () => {
    vi.spyOn(OutboxStore.prototype, 'reserveRecovery').mockResolvedValue({
      ...reservation(),
      created: false,
      action: 'none',
    });
    vi.spyOn(OutboxStore.prototype, 'close').mockResolvedValue();
    const c = runtime(port(), {
      timeoutMs: 20,
      observer: (e) => {
        if (e.code === 'recovery_replayed') {
          const end = performance.now() + 25;
          while (performance.now() < end) {
            /*controlled observer*/
          }
        }
      },
    });
    await expect(
      c.reconcile(CONTROL, {
        commandId: COMMAND,
        outboundId: REQUEST.outboundId,
        attemptId: REQUEST.attemptId,
      }),
    ).rejects.toMatchObject({ code: 'AcknowledgementUnknown' });
    await c.close();
  });
  it('validates malformed signals/commands before allocation', async () => {
    const reserve = vi.spyOn(OutboxStore.prototype, 'reserveRecovery');
    vi.spyOn(OutboxStore.prototype, 'close').mockResolvedValue();
    const c = runtime(port());
    expect(() =>
      c.retry(
        CONTROL,
        {
          commandId: COMMAND,
          outboundId: REQUEST.outboundId,
          expectedAttemptId: REQUEST.attemptId,
        },
        { aborted: false } as unknown as AbortSignal,
      ),
    ).toThrow(OutboxError);
    let touched = 0;
    const bad = {
      commandId: COMMAND,
      outboundId: REQUEST.outboundId,
      get expectedAttemptId() {
        touched++;
        return REQUEST.attemptId;
      },
    };
    expect(() => c.retry(CONTROL, bad)).toThrow(OutboxError);
    expect(touched).toBe(0);
    expect(reserve).not.toHaveBeenCalled();
    await c.close();
  });
  it('requires distinct trusted controller credentials', () => {
    expect(() => runtime(port(), { recoveryControllers: [{ token: TOKEN, ...REF }] })).toThrow(
      OutboxError,
    );
    expect(() => runtime(port(), { recoveryControllers: [{ token: PUBLISH, ...REF }] })).toThrow(
      OutboxError,
    );
  });
});
describe('original immutable namespace and anchor validation', () => {
  const row = () => ({
    provider_operation_key: OP.providerOperationKey,
    tenant_id: ACCOUNT.tenantId,
    account_id: ACCOUNT.accountId,
    outbound_id: REQUEST.outboundId,
    provider: PROVIDER.provider,
    provider_account_id: PROVIDER.providerAccountId,
    first_attempt_id: REQUEST.attemptId,
    capability: OP.capability,
    canonical_operation: JSON.stringify(OP),
    operation_digest: operationDigest(OP),
    first_request_digest: sha(JSON.stringify(REQUEST)),
    canonical_request: JSON.stringify(REQUEST),
    request_digest: sha(JSON.stringify(REQUEST)),
    anchor_key: OP.providerOperationKey,
    anchor_tenant: ACCOUNT.tenantId,
    anchor_account: ACCOUNT.accountId,
    anchor_outbound: REQUEST.outboundId,
    anchor_ordinal: 1,
    admission_proof: JSON.stringify({ schemaVersion: 1, kind: 'first_operation' }),
    admission_digest: sha(JSON.stringify({ schemaVersion: 1, kind: 'first_operation' })),
  });
  it.each([
    { provider_account_id: 'foreign' },
    { anchor_key: randomUUID() },
    { anchor_tenant: 'foreign' },
    { anchor_account: 'foreign' },
    { anchor_outbound: randomUUID() },
    { first_attempt_id: randomUUID() },
    { first_request_digest: '0'.repeat(64) },
  ])('rejects corrupted namespace/composite anchor %j', async (change) => {
    const client = {
      query: vi.fn().mockResolvedValue({ rows: [{ ...row(), ...change }] }),
    } as unknown as PoolClient;
    await expect(
      new SendPolicyStore(DB.schema, PROVIDER).loadOperation(client, OP.providerOperationKey, REF),
    ).rejects.toMatchObject({ code: 'Unavailable' });
  });
  it('returns a deeply frozen operation snapshot independent of returned driver-row mutation', async () => {
    const input = row(),
      client = { query: vi.fn().mockResolvedValue({ rows: [input] }) } as unknown as PoolClient,
      value = await new SendPolicyStore(DB.schema, PROVIDER).loadOperation(
        client,
        OP.providerOperationKey,
        REF,
      );
    input.canonical_operation = 'changed';
    expect(value.operation).toEqual(OP);
    expect(Object.isFrozen(value.operation.scope)).toBe(true);
  });
});

describe('closed recovery receipt semantics and fixed actual producers', () => {
  it.each([
    {
      kind: 'reconcile',
      decision: 'retry_reserved',
      code: 'retry_reserved',
      newAttemptId: randomUUID(),
    },
    { kind: 'retry', decision: 'lookup_authorized', code: 'lookup' },
    { decision: 'terminal', code: 'route_missing' },
    { decision: 'held', code: 'lookup' },
    { decision: 'held', code: 'suppressed' },
    {
      kind: 'retry',
      decision: 'retry_reserved',
      code: 'retry_reserved',
      newAttemptId: RECEIPT.sourceAttemptId,
    },
  ])('rejects impossible permission semantics %j', (change) =>
    expect(() => recoveryReceipt({ ...RECEIPT, ...change })).toThrow(OutboxError),
  );
  it('never executes configured port getters', () => {
    let touched = 0;
    const value = {
      get capabilities() {
        touched++;
        throw Error('secret');
      },
      send: async () => {
        throw Error('unexpected');
      },
    };
    expect(() => runtime(value as unknown as IdempotentCarrierSendPort)).toThrow(OutboxError);
    expect(touched).toBe(0);
  });
  it.each([
    ['ordinary_no_resend', 'ordinaryHolds'],
    ['callback_veto', 'callbackVetoes'],
    ['suppressed', 'permissionVetoes'],
    ['attempt_exhausted', 'attemptLimitHolds'],
    ['prior_operation_evidence', 'priorOperationVetoes'],
  ] as const)('counts durable held %s without I/O', async (code, metric) => {
    const receipt = recoveryReceipt({ ...RECEIPT, kind: 'retry', decision: 'held', code });
    vi.spyOn(OutboxStore.prototype, 'reserveRecovery').mockResolvedValue({
      ...reservation(),
      view: { receipt, observation: null },
      action: 'none',
    });
    vi.spyOn(OutboxStore.prototype, 'close').mockResolvedValue();
    const carrier = port(),
      send = vi.spyOn(carrier, 'send'),
      find = vi.spyOn(carrier, 'lookup'),
      c = runtime(carrier);
    await c.retry(CONTROL, {
      commandId: COMMAND,
      outboundId: REQUEST.outboundId,
      expectedAttemptId: REQUEST.attemptId,
    });
    expect(c.metrics()[metric]).toBe(1);
    expect(send).not.toHaveBeenCalled();
    expect(find).not.toHaveBeenCalled();
    await c.close();
  });
  it.each([
    ['accepted_by_provider', 'reported', 'lookupAccepted'],
    ['definitive_not_accepted', 'reported', 'lookupDefinitiveFailure'],
    ['absent', 'reported', 'lookupAbsent'],
    ['unknown', 'reported', 'lookupUnknown'],
    ['accepted_by_provider', 'conflicted', 'lookupConflicts'],
  ] as const)('counts observed lookup %s %s', async (state, assessment, metric) => {
    vi.spyOn(OutboxStore.prototype, 'reserveRecovery').mockResolvedValue(reservation());
    vi.spyOn(OutboxStore.prototype, 'recordRecovery').mockImplementation(async (receipt) => ({
      receipt,
      observation: recoveryObservation(
        {
          schemaVersion: 1,
          commandId: receipt.commandId,
          providerOperationKey: OP.providerOperationKey,
          operationDigest: operationDigest(OP),
          source: 'lookup',
          state,
          assessment,
          providerMessageId: state === 'accepted_by_provider' ? 'message-a' : null,
          observedAt: RECEIPT.acceptedAt,
        },
        receipt,
      ),
    }));
    vi.spyOn(OutboxStore.prototype, 'close').mockResolvedValue();
    const c = runtime(port());
    await c.reconcile(CONTROL, {
      commandId: COMMAND,
      outboundId: REQUEST.outboundId,
      attemptId: REQUEST.attemptId,
    });
    expect(c.metrics()[metric]).toBe(1);
    await c.close();
  });
  it('keeps waiter acknowledgement uncertainty separate from definitive rejection', async () => {
    const held = deferred<RecoveryReservation>();
    vi.spyOn(OutboxStore.prototype, 'reserveRecovery').mockReturnValue(held.promise);
    vi.spyOn(OutboxStore.prototype, 'close').mockResolvedValue();
    const c = runtime(port(), { timeoutMs: 20 });
    await expect(
      c.reconcile(CONTROL, {
        commandId: COMMAND,
        outboundId: REQUEST.outboundId,
        attemptId: REQUEST.attemptId,
      }),
    ).rejects.toMatchObject({ code: 'AcknowledgementUnknown' });
    expect(c.metrics()).toMatchObject({ recoveryAcknowledgementUnknown: 1, recoveryRejected: 0 });
    held.resolve({ ...reservation(), created: false, action: 'none' });
    await new Promise((r) => setImmediate(r));
    await c.close();
  });
});

describe('later evidence never rewrites a retained earlier admission', () => {
  it('held prior-operation veto carries uncertainty while original terminal facts stay separately inspectable', () => {
    const held = recoveryReceipt({
      ...RECEIPT,
      kind: 'retry',
      decision: 'held',
      code: 'prior_operation_evidence',
    });
    expect(
      recoveryObservation(
        {
          schemaVersion: 1,
          commandId: held.commandId,
          providerOperationKey: OP.providerOperationKey,
          operationDigest: operationDigest(OP),
          source: 'policy',
          state: 'unknown',
          assessment: 'reported',
          providerMessageId: null,
          observedAt: RECEIPT.acceptedAt,
        },
        held,
      ).state,
    ).toBe('unknown');
    expect(() =>
      recoveryObservation(
        {
          schemaVersion: 1,
          commandId: held.commandId,
          providerOperationKey: OP.providerOperationKey,
          operationDigest: operationDigest(OP),
          source: 'policy',
          state: 'definitive_not_accepted',
          assessment: 'reported',
          providerMessageId: null,
          observedAt: RECEIPT.acceptedAt,
        },
        held,
      ),
    ).toThrow(OutboxError);
  });
});
