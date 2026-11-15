/** Same-schema recipient permission and immutable outbox records; no provider I/O in transactions. */
import { randomUUID } from 'node:crypto';
import type { Pool, PoolClient } from 'pg';
import { ChannelError, PgPool, watchPool, config, settings, table, validate } from './database.js';
import {
  DEFINITION_DIGEST,
  DISPATCH_DEFINITION_DIGEST,
  OUTBOX_DEFINITION_DIGEST,
  CALLBACK_DEFINITION_DIGEST,
  SEND_POLICY_DEFINITION_DIGEST,
  NATIVE_DEFINITION_DIGEST,
  COMMUNICATION_DEFINITION_DIGEST,
  RESULT_RECEIVER_DEFINITION_DIGEST,
  INDEX_DEFINITION_DIGEST,
} from './migrations.js';
import { SeededAccounts } from './postgres.js';
import type { DatabaseSettings } from './public-types.js';
import type { FakeSmsIntegration } from './security.js';
import { checkedSignal, isAborted } from './routing-types.js';
import {
  OutboxError,
  record,
  identifier,
  decimal,
  uuid,
  sha,
  draft,
  recipient,
  envelope,
  route,
  sendRequest,
  carrierResult,
  timestamp,
  outboxLimits,
  safe,
  type OutboxPublisher,
  type ReplyDraft,
  type ReplyEnvelope,
  type OutboxReceipt,
  type OutboundRoute,
  type OutboxObservation,
  type SendAttempt,
  type SendRequest,
  type CarrierResult,
  type SendOutcome,
  type OutboxLimits,
} from './outbox-types.js';
import { SendPolicyStore } from './send-policy-store.js';
import {
  RESULT_NOTICE,
  RESULT_NATIVE_VIEW_BYTES,
  type P1ResultIntent,
  type P1ResultReceipt,
  type ResultRouteBinding,
  type ResultNativeView,
} from './result-receiver-types.js';
import {
  encodeResultIntent,
  parseResultIntent,
  matchResultReceipt,
  resultReceipt,
} from './result-receiver-codec.js';
import type { RehydrationInboxAccess } from './rehydration-access.js';
import { currentCase, type CurrentCasePort } from './rehydration-types.js';
import {
  operation as operationFromOperation,
  operationFrom,
  operationDigest,
  lookup,
  recoveryReceipt,
  type ProviderOperation,
  type ProviderLookup,
  type SendCapability,
  type RecoveryController,
  type RecoveryKind,
  type RecoveryCommandView,
  type RecoveryReceipt,
  type RecoveryCode,
  type RecoveryObservation,
  type RecoverySummary,
} from './send-policy-types.js';
export type RecoveryReservation = Readonly<{
  view: RecoveryCommandView;
  created: boolean;
  action: 'none' | 'lookup' | 'send';
  operation: ProviderOperation;
  request: SendRequest | null;
}>;
type Account = Omit<OutboxPublisher, 'token'>;
type Tx = {
  client: PoolClient;
  bounds: OutboxLimits;
  receiverId: string;
  signal: AbortSignal;
  version: number;
};
export type Reservation = { request: SendRequest } | { result: SendOutcome };
export class OutboxStore {
  readonly #database: DatabaseSettings;
  readonly #pool: Pool;
  readonly #integration: FakeSmsIntegration;
  readonly #accounts: SeededAccounts;
  readonly #publishers = new Map<string, Account>();
  readonly #controllers = new Map<string, Account>();
  readonly #policy: SendPolicyStore;
  readonly #calls = new Set<Promise<unknown>>();
  #recordings = 0;
  #closing = false;
  #ending: Promise<void> | undefined;
  constructor(
    input: DatabaseSettings,
    integration: FakeSmsIntegration,
    accounts: SeededAccounts,
    publishers: readonly OutboxPublisher[],
    controllers: readonly RecoveryController[] = [],
  ) {
    this.#database = settings(input, 'livekit_lab');
    const provider = record(integration?.providerScope, [
      'tenantId',
      'provider',
      'providerAccountId',
    ]);
    this.#integration = Object.freeze({
      providerScope: Object.freeze({
        tenantId: identifier(provider.tenantId),
        provider: identifier(provider.provider),
        providerAccountId: identifier(provider.providerAccountId),
      }),
    });
    this.#accounts = accounts;
    if (
      !(accounts instanceof SeededAccounts) ||
      !integration?.providerScope ||
      !Array.isArray(publishers) ||
      publishers.length < 1 ||
      publishers.length > 64
    )
      throw new OutboxError('InvalidCommand');
    for (const raw of publishers) {
      const p = record(raw, ['token', 'scope', 'caseId', 'conversationId']),
        key = this.#token(p.token),
        ref = recipient({ scope: p.scope, caseId: p.caseId, conversationId: p.conversationId });
      if (
        ref.scope.tenantId !== this.#integration.providerScope.tenantId ||
        this.#publishers.has(key)
      )
        throw new OutboxError('InvalidCommand');
      let accountCredential = false;
      try {
        accounts.authenticate(p.token as string, ref.scope.tenantId);
        accountCredential = true;
      } catch {
        /* distinct capability */
      }
      if (accountCredential) throw new OutboxError('InvalidCommand');
      this.#publishers.set(key, ref);
    }
    if (
      !Array.isArray(controllers) ||
      Object.getPrototypeOf(controllers) !== Array.prototype ||
      controllers.length > 64 ||
      Object.getOwnPropertySymbols(controllers).length
    )
      throw new OutboxError('InvalidCommand');
    const descriptors = Object.getOwnPropertyDescriptors(controllers) as unknown as Record<
      string,
      PropertyDescriptor
    >;
    if (Object.keys(descriptors).length !== controllers.length + 1)
      throw new OutboxError('InvalidCommand');
    for (let index = 0; index < controllers.length; index++) {
      const d = descriptors[String(index)];
      if (!d || !('value' in d) || !d.enumerable) throw new OutboxError('InvalidCommand');
      const v = record(d.value, ['token', 'scope', 'caseId', 'conversationId']),
        key = this.#token(v.token),
        ref = recipient({ scope: v.scope, caseId: v.caseId, conversationId: v.conversationId });
      if (
        ref.scope.tenantId !== this.#integration.providerScope.tenantId ||
        this.#controllers.has(key) ||
        this.#publishers.has(key)
      )
        throw new OutboxError('InvalidCommand');
      let account = false;
      try {
        accounts.authenticate(v.token as string, ref.scope.tenantId);
        account = true;
      } catch {
        /*separate controller capability*/
      }
      if (account) throw new OutboxError('InvalidCommand');
      this.#controllers.set(key, ref);
    }
    this.#policy = new SendPolicyStore(this.#database.schema, this.#integration.providerScope);
    this.#pool = watchPool(new PgPool(config(this.#database)));
    this.#pool.on('error', () => undefined);
  }
  #token(value: unknown): string {
    if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{32,128}(?![\s\S])/.test(value))
      throw new OutboxError('AccessDenied');
    return sha(value);
  }
  #account(token: string): Account {
    try {
      const a = this.#accounts.authenticate(token, this.#integration.providerScope.tenantId);
      if (a.caseId === undefined) throw new Error();
      return recipient({
        scope: { tenantId: a.tenantId, accountId: a.accountId },
        caseId: a.caseId,
        conversationId: a.conversationId,
      });
    } catch {
      throw new OutboxError('AccessDenied');
    }
  }
  #q(name: string): string {
    return table(this.#database.schema, name);
  }
  #args(ref: Account): string[] {
    return [ref.scope.tenantId, ref.scope.accountId, ref.conversationId, ref.caseId];
  }
  get databaseIdentity(): string {
    return JSON.stringify([
      this.#database.host,
      this.#database.port,
      this.#database.database,
      this.#database.schema,
    ]);
  }
  get actualCalls(): number {
    return this.#calls.size;
  }
  #reserve<T>(signal: AbortSignal, action: () => Promise<T>, recording = false): Promise<T> {
    try {
      checkedSignal(signal);
    } catch {
      throw new OutboxError('InvalidCommand');
    }
    if (this.#closing) return Promise.reject(new OutboxError('Closed'));
    if (recording ? this.#recordings >= 4 : this.#calls.size - this.#recordings >= 4)
      return Promise.reject(new OutboxError('Overloaded'));
    if (isAborted(signal)) return Promise.reject(new OutboxError('Unavailable'));
    if (recording) this.#recordings++;
    const work = Promise.resolve().then(action);
    this.#calls.add(work);
    const settled = () => {
      this.#calls.delete(work);
      if (recording) this.#recordings--;
    };
    void work.then(settled, settled);
    return work;
  }
  #run<T>(write: boolean, signal: AbortSignal, action: (tx: Tx) => Promise<T>): Promise<T> {
    return this.#reserve(signal, () => this.#transaction(write, signal, action));
  }
  /** Carrier-result recording has its own four slots (the outbox task maximum), so ordinary
   * calls cannot turn a known result into unknown.
   */
  #record<T>(action: (tx: Tx) => Promise<T>): Promise<T> {
    const signal = new AbortController().signal;
    return this.#reserve(signal, () => this.#transaction(true, signal, action), true);
  }
  async #transaction<T>(
    write: boolean,
    signal: AbortSignal,
    action: (tx: Tx) => Promise<T>,
  ): Promise<T> {
    if (isAborted(signal)) throw new OutboxError('Unavailable');
    let client: PoolClient | undefined,
      began = false,
      committing = false,
      broken = false;
    try {
      client = await this.#pool.connect();
      await client.query(write ? 'BEGIN' : 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY');
      began = true;
      await validate(
        client,
        this.#database,
        DEFINITION_DIGEST,
        false,
        DISPATCH_DEFINITION_DIGEST,
        OUTBOX_DEFINITION_DIGEST,
        CALLBACK_DEFINITION_DIGEST,
        SEND_POLICY_DEFINITION_DIGEST,
        NATIVE_DEFINITION_DIGEST,
        COMMUNICATION_DEFINITION_DIGEST,
        RESULT_RECEIVER_DEFINITION_DIGEST,
        INDEX_DEFINITION_DIGEST,
      );
      const version = (
        await client.query(`SELECT version FROM ${this.#q('schema_metadata')} WHERE singleton`)
      ).rows[0]?.version;
      if (
        version !== 3 &&
        version !== 4 &&
        version !== 5 &&
        version !== 6 &&
        version !== 7 &&
        version !== 8 &&
        version !== 9
      )
        throw new OutboxError('UpgradeRequired');
      if (write) {
        const guard = await client.query(
          `SELECT singleton FROM ${this.#q('admission')} WHERE singleton FOR UPDATE`,
        );
        if (guard.rowCount !== 1) throw new OutboxError('Unavailable');
      }
      const policy = await client.query(
        `SELECT * FROM ${this.#q('outbox_settings')} WHERE singleton`,
      );
      if (policy.rows.length !== 1) throw new OutboxError('Unavailable');
      const p = policy.rows[0],
        bounds = outboxLimits({
          maxReplies: p.max_replies,
          maxRoutes: p.max_routes,
          maxAttempts: p.max_attempts,
        }),
        receiverId = uuid(p.receiver_id);
      if (isAborted(signal)) throw new OutboxError('Unavailable');
      const result = await action({ client, bounds, receiverId, signal, version });
      if (isAborted(signal)) throw new OutboxError('Unavailable');
      committing = write;
      await client.query('COMMIT');
      began = false;
      committing = false;
      if (isAborted(signal))
        throw new OutboxError(write ? 'AcknowledgementUnknown' : 'Unavailable');
      return result;
    } catch (error) {
      if (client && began)
        try {
          await client.query('ROLLBACK');
        } catch {
          broken = true;
        }
      if (committing) {
        broken = true;
        throw new OutboxError('AcknowledgementUnknown');
      }
      throw safe(error);
    } finally {
      client?.release(broken);
    }
  }
  async #counts(tx: Tx): Promise<{ reply_count: number; route_count: number }> {
    const result = await tx.client.query(
        `SELECT * FROM ${this.#q('outbox_admission')} WHERE singleton FOR UPDATE`,
      ),
      row = result.rows[0];
    if (
      result.rowCount !== 1 ||
      !Number.isSafeInteger(row.reply_count) ||
      !Number.isSafeInteger(row.route_count) ||
      row.reply_count < 0 ||
      row.route_count < 0 ||
      row.reply_count > tx.bounds.maxReplies ||
      row.route_count > tx.bounds.maxRoutes
    )
      throw new OutboxError('Unavailable');
    const counts = await tx.client.query(
      `SELECT (SELECT count(*)::integer FROM ${this.#q('reply_intents')}) AS replies,(SELECT count(*)::integer FROM ${this.#q('outbound_routes')}) AS routes`,
    );
    if (counts.rows[0]?.replies !== row.reply_count || counts.rows[0]?.routes !== row.route_count)
      throw new OutboxError('Unavailable');
    if (tx.version >= 5) await this.#policy.policy(tx.client, true);
    return row as { reply_count: number; route_count: number };
  }
  async #growth(tx: Tx, kind: 'reply' | 'route'): Promise<void> {
    const row = await this.#counts(tx);
    if (
      row[kind === 'reply' ? 'reply_count' : 'route_count'] >=
      tx.bounds[kind === 'reply' ? 'maxReplies' : 'maxRoutes']
    )
      throw new OutboxError('Overloaded');
    await tx.client.query(
      `UPDATE ${this.#q('outbox_admission')} SET ${kind}_count=${kind}_count+1 WHERE singleton`,
    );
  }

  #decode(
    row: Record<string, unknown>,
    receiverId: string,
    ref: Account,
  ): { reply: ReplyEnvelope; receipt: OutboxReceipt } {
    try {
      const raw = row.canonical_payload;
      if (typeof raw !== 'string' || sha(raw) !== row.intent_digest) throw new Error();
      const reply = envelope(JSON.parse(raw));
      if (
        JSON.stringify(reply) !== raw ||
        reply.scope.tenantId !== row.tenant_id ||
        reply.scope.accountId !== row.account_id ||
        reply.outboundId !== row.outbound_id ||
        reply.responseId !== row.response_id ||
        reply.caseId !== row.case_id ||
        reply.conversationId !== row.conversation_id ||
        sha(reply.body) !== row.body_digest ||
        JSON.stringify(
          recipient({
            scope: reply.scope,
            caseId: reply.caseId,
            conversationId: reply.conversationId,
          }),
        ) !== JSON.stringify(ref)
      )
        throw new Error();
      return {
        reply,
        receipt: Object.freeze({
          receiverId,
          receiptId: uuid(row.receipt_id),
          outboundId: reply.outboundId,
          intentDigest: sha(raw),
          bodyDigest: sha(reply.body),
          acceptedAt: timestamp(row.accepted_at),
        }),
      };
    } catch {
      throw new OutboxError('Unavailable');
    }
  }
  async #reply(
    tx: Tx,
    ref: Account,
    outboundId: string,
  ): Promise<{ reply: ReplyEnvelope; receipt: OutboxReceipt }> {
    const r = await tx.client.query(
      `SELECT * FROM ${this.#q('reply_intents')} WHERE tenant_id=$1 AND account_id=$2 AND outbound_id=$3 AND conversation_id=$4 AND case_id=$5`,
      [ref.scope.tenantId, ref.scope.accountId, outboundId, ref.conversationId, ref.caseId],
    );
    if (r.rowCount !== 1) throw new OutboxError('NotFound');
    return this.#decode(r.rows[0], tx.receiverId, ref);
  }
  enqueue(
    publisherToken: string,
    input: ReplyDraft,
    signal: AbortSignal,
  ): Promise<{ receipt: OutboxReceipt; created: boolean }> {
    const ref = this.#publishers.get(this.#token(publisherToken));
    if (!ref) throw new OutboxError('AccessDenied');
    const e = Object.freeze({ ...draft(input), ...ref }),
      canonical = JSON.stringify(e);
    return this.#run(true, signal, (tx) => this.#enqueueWithin(tx, ref, e, canonical));
  }
  async #enqueueWithin(
    tx: Tx,
    ref: Account,
    e: ReplyEnvelope,
    canonical: string,
  ): Promise<{ receipt: OutboxReceipt; created: boolean }> {
    const prior = await tx.client.query(
      `SELECT * FROM ${this.#q('reply_intents')} WHERE tenant_id=$1 AND account_id=$2 AND outbound_id=$3`,
      [ref.scope.tenantId, ref.scope.accountId, e.outboundId],
    );
    if (prior.rowCount) {
      if (prior.rows[0].canonical_payload !== canonical) throw new OutboxError('IdentityConflict');
      return { receipt: this.#decode(prior.rows[0], tx.receiverId, ref).receipt, created: false };
    }
    await this.#growth(tx, 'reply');
    const saved = await tx.client.query(
      `INSERT INTO ${this.#q('reply_intents')} VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,clock_timestamp()) RETURNING *`,
      [
        ref.scope.tenantId,
        ref.scope.accountId,
        e.outboundId,
        randomUUID(),
        ref.conversationId,
        ref.caseId,
        e.responseId,
        canonical,
        sha(canonical),
        sha(e.body),
      ],
    );
    return { receipt: this.#decode(saved.rows[0], tx.receiverId, ref).receipt, created: true };
  }
  #resultBinding(
    token: string,
    route: ResultRouteBinding,
    receiverId: string,
    intent?: P1ResultIntent,
  ): Account {
    const ref = this.#publishers.get(this.#token(token));
    if (
      !ref ||
      JSON.stringify(ref) !==
        JSON.stringify(
          recipient({
            scope: route.scope,
            caseId: route.caseId,
            conversationId: route.conversationId,
          }),
        )
    )
      throw new OutboxError('AccessDenied');
    if (
      intent &&
      (intent.receiver_id !== receiverId ||
        intent.recipient_id !== route.recipientId ||
        intent.scope.tenant_id !== route.scope.tenantId ||
        intent.scope.account_id !== route.scope.accountId)
    )
      throw new OutboxError('AccessDenied');
    return ref;
  }
  #resultVersion(tx: Tx, receiverId: string): void {
    if (tx.version < 8) throw new OutboxError('UpgradeRequired');
    if (tx.receiverId !== receiverId) throw new OutboxError('IdentityConflict');
  }
  async #resultWithin(
    tx: Tx,
    route: ResultRouteBinding,
    deliveryId: string,
  ): Promise<{ intent: P1ResultIntent; receipt: P1ResultReceipt } | null> {
    const rows = (
      await tx.client.query(
        `SELECT * FROM ${this.#q('result_receipts')} WHERE delivery_id=$1::uuid AND tenant_id=$2 AND account_id=$3 AND case_id=$4 AND conversation_id=$5`,
        [
          deliveryId,
          route.scope.tenantId,
          route.scope.accountId,
          route.caseId,
          route.conversationId,
        ],
      )
    ).rows;
    if (rows.length === 0) return null;
    if (rows.length !== 1) throw new OutboxError('Unavailable');
    try {
      const row = rows[0],
        intent = parseResultIntent(row.canonical_intent as string);
      if (
        intent.delivery_id !== deliveryId ||
        intent.work_id !== row.work_id ||
        intent.attempt_id !== row.attempt_id ||
        intent.result_sha256 !== row.result_sha256 ||
        intent.recipient_id !== route.recipientId ||
        intent.recipient_id !== row.recipient_id ||
        intent.scope.tenant_id !== row.tenant_id ||
        intent.scope.account_id !== row.account_id ||
        intent.receiver_id !== tx.receiverId ||
        row.outbound_id !== deliveryId
      )
        throw new OutboxError('Unavailable');
      const original = await this.#reply(
        tx,
        recipient({
          scope: route.scope,
          caseId: route.caseId,
          conversationId: route.conversationId,
        }),
        deliveryId,
      );
      if (
        original.reply.body !== RESULT_NOTICE ||
        original.reply.responseId !== 'p3_' + intent.work_id.replaceAll('-', '')
      )
        throw new OutboxError('Unavailable');
      const receipt = resultReceipt({
        delivery_id: deliveryId,
        receipt_id: original.receipt.receiptId,
        receiver_id: original.receipt.receiverId,
        recipient_id: intent.recipient_id,
        result_sha256: intent.result_sha256,
        accepted_at_ms: Date.parse(original.receipt.acceptedAt),
      });
      matchResultReceipt(intent, receipt);
      return Object.freeze({ intent, receipt });
    } catch {
      throw new OutboxError('Unavailable');
    }
  }
  acceptResult(
    token: string,
    receiverId: string,
    route: ResultRouteBinding,
    intent: P1ResultIntent,
    signal: AbortSignal,
  ): Promise<P1ResultReceipt> {
    const ref = this.#resultBinding(token, route, receiverId, intent),
      canonical = encodeResultIntent(intent);
    return this.#run(true, signal, async (tx) => {
      this.#resultVersion(tx, receiverId);
      const original = await this.#resultWithin(tx, route, intent.delivery_id);
      if (original) {
        if (encodeResultIntent(original.intent) !== canonical)
          throw new OutboxError('IdentityConflict');
        return original.receipt;
      }
      const collision = await tx.client.query(
        `SELECT 1 FROM ${this.#q('result_receipts')} WHERE delivery_id=$1::uuid UNION ALL SELECT 1 FROM ${this.#q('reply_intents')} WHERE tenant_id=$2 AND account_id=$3 AND outbound_id=$1::uuid`,
        [intent.delivery_id, route.scope.tenantId, route.scope.accountId],
      );
      if (collision.rowCount) throw new OutboxError('IdentityConflict');
      const e = envelope({
        schemaVersion: 1,
        outboundId: intent.delivery_id,
        responseId: 'p3_' + intent.work_id.replaceAll('-', ''),
        body: RESULT_NOTICE,
        ...ref,
      });
      const queued = await this.#enqueueWithin(tx, ref, e, JSON.stringify(e));
      await tx.client.query(
        `INSERT INTO ${this.#q('result_receipts')}(delivery_id,tenant_id,account_id,work_id,attempt_id,result_sha256,recipient_id,case_id,conversation_id,outbound_id,canonical_intent) VALUES($1::uuid,$2,$3,$4::uuid,$5::uuid,$6,$7,$8,$9,$1::uuid,$10)`,
        [
          intent.delivery_id,
          route.scope.tenantId,
          route.scope.accountId,
          intent.work_id,
          intent.attempt_id,
          intent.result_sha256,
          intent.recipient_id,
          route.caseId,
          route.conversationId,
          canonical,
        ],
      );
      return resultReceipt({
        delivery_id: intent.delivery_id,
        receipt_id: queued.receipt.receiptId,
        receiver_id: queued.receipt.receiverId,
        recipient_id: intent.recipient_id,
        result_sha256: intent.result_sha256,
        accepted_at_ms: Date.parse(queued.receipt.acceptedAt),
      });
    });
  }
  findResult(
    token: string,
    receiverId: string,
    route: ResultRouteBinding,
    intent: P1ResultIntent,
    signal: AbortSignal,
  ): Promise<P1ResultReceipt | null> {
    this.#resultBinding(token, route, receiverId, intent);
    const canonical = encodeResultIntent(intent);
    return this.#run(false, signal, async (tx) => {
      this.#resultVersion(tx, receiverId);
      const original = await this.#resultWithin(tx, route, intent.delivery_id);
      if (!original) return null;
      if (encodeResultIntent(original.intent) !== canonical)
        throw new OutboxError('IdentityConflict');
      return original.receipt;
    });
  }
  async #resultGrant(
    access: RehydrationInboxAccess,
    client: PoolClient,
    bearer: string,
    lock: boolean,
  ) {
    try {
      return await access.native.currentBearer(client, bearer, lock);
    } catch (error) {
      // Preserve this native authorization result before the legacy outbox-only safe boundary.
      if (error instanceof ChannelError && error.code === 'AccessDenied')
        throw new OutboxError('AccessDenied');
      throw error;
    }
  }
  readNativeResult(
    receiverId: string,
    routes: readonly ResultRouteBinding[],
    access: RehydrationInboxAccess,
    cases: CurrentCasePort,
    bearer: string,
    deliveryId: string,
    signal: AbortSignal,
  ): Promise<ResultNativeView | null> {
    if (access.databaseIdentity !== this.databaseIdentity)
      return Promise.reject(new OutboxError('AccessDenied'));
    return this.#reserve(signal, async () => {
      const first = await this.#transaction(false, signal, async (tx) => {
        this.#resultVersion(tx, receiverId);
        const grant = await this.#resultGrant(access, tx.client, bearer, false);
        const route = routes.find(
          (r) =>
            r.scope.tenantId === grant.scope.tenantId &&
            r.scope.accountId === grant.scope.accountId &&
            r.caseId === grant.caseId &&
            r.conversationId === grant.conversationId,
        );
        if (!route) throw new OutboxError('AccessDenied');
        const result = await this.#resultWithin(tx, route, deliveryId);
        const now = (
          await tx.client.query("SELECT date_trunc('milliseconds',clock_timestamp()) AS now")
        ).rows[0]?.now;
        if (!(now instanceof Date)) throw new OutboxError('Unavailable');
        return { grant, route, result, p2ObservedAt: now.toISOString() };
      });
      const ref = Object.freeze({
        scope: first.route.scope,
        caseId: first.route.caseId,
        conversationId: first.route.conversationId,
      });
      const observedCase = currentCase(await cases.inspect(ref, signal), ref),
        caseObservedAt = new Date().toISOString();
      if (
        observedCase.source !== 'p1_public_v4' ||
        Buffer.byteLength(JSON.stringify(observedCase)) > 4096 ||
        isAborted(signal)
      )
        throw new OutboxError('Unavailable');
      const disclosureAdmittedAt = await this.#transaction(true, signal, async (tx) => {
        this.#resultVersion(tx, receiverId);
        const g = await this.#resultGrant(access, tx.client, bearer, true);
        if (
          g.bindingId !== first.grant.bindingId ||
          g.roomId !== first.grant.roomId ||
          g.participantId !== first.grant.participantId ||
          g.scope.tenantId !== ref.scope.tenantId ||
          g.scope.accountId !== ref.scope.accountId ||
          g.caseId !== ref.caseId ||
          g.conversationId !== ref.conversationId
        )
          throw new OutboxError('AccessDenied');
        return g.admittedAt;
      });
      if (!first.result) return null;
      const view: ResultNativeView = Object.freeze({
        schemaVersion: 1,
        intent: first.result.intent,
        receipt: first.result.receipt,
        case: observedCase,
        observed: Object.freeze({
          p2ObservedAt: first.p2ObservedAt,
          caseObservedAt,
          disclosureAdmittedAt,
          atomic: false,
        }),
      });
      if (Buffer.byteLength(JSON.stringify(view)) > RESULT_NATIVE_VIEW_BYTES)
        throw new OutboxError('Unavailable');
      return view;
    });
  }
  async #route(tx: Tx, ref: Account): Promise<OutboundRoute> {
    const p = this.#integration.providerScope,
      r = await tx.client.query(
        `SELECT * FROM ${this.#q('outbound_routes')} WHERE tenant_id=$1 AND account_id=$2 AND conversation_id=$3`,
        this.#args(ref).slice(0, 3),
      );
    if (!r.rowCount)
      return Object.freeze({
        version: '0',
        senderId: null,
        associationVersion: null,
        suppressed: false,
      });
    const x = r.rows[0];
    if (
      r.rowCount !== 1 ||
      x.case_id !== ref.caseId ||
      x.provider !== p.provider ||
      x.provider_account_id !== p.providerAccountId
    )
      throw new OutboxError('AccessDenied');
    return route({
      version: String(x.version),
      senderId: x.sender_id,
      associationVersion: x.association_epoch === null ? null : String(x.association_epoch),
      suppressed: x.suppressed,
    });
  }
  inspectRoute(accountToken: string, signal: AbortSignal): Promise<OutboundRoute> {
    const ref = this.#account(accountToken);
    return this.#run(false, signal, (tx) => this.#route(tx, ref));
  }
  async #associated(tx: Tx, ref: Account, sender: string, epoch: string): Promise<boolean> {
    const p = this.#integration.providerScope,
      r = await tx.client.query(
        `SELECT a.epoch FROM ${this.#q('sender_heads')} h JOIN ${this.#q('associations')} a ON a.tenant_id=h.tenant_id AND a.provider=h.provider AND a.provider_account_id=h.provider_account_id AND a.sender_id=h.sender_id AND a.epoch=h.active_epoch WHERE h.tenant_id=$1 AND h.provider=$2 AND h.provider_account_id=$3 AND h.sender_id=$4 AND a.epoch=$5 AND a.account_id=$6 AND a.conversation_id=$7 AND a.case_id=$8 AND a.revoked_at IS NULL`,
        [
          p.tenantId,
          p.provider,
          p.providerAccountId,
          sender,
          epoch,
          ref.scope.accountId,
          ref.conversationId,
          ref.caseId,
        ],
      );
    return r.rowCount === 1;
  }
  selectRoute(
    accountToken: string,
    input: Readonly<{ senderId: string; associationVersion: string; expectedRouteVersion: string }>,
    signal: AbortSignal,
  ): Promise<OutboundRoute> {
    const ref = this.#account(accountToken),
      p = record(input, ['senderId', 'associationVersion', 'expectedRouteVersion']),
      sender = identifier(p.senderId),
      epoch = decimal(p.associationVersion),
      expected = decimal(p.expectedRouteVersion);
    if (epoch === '0') throw new OutboxError('InvalidCommand');
    return this.#run(true, signal, async (tx) => {
      await this.#counts(tx);
      const old = await this.#route(tx, ref);
      if (old.version !== expected) throw new OutboxError('RevisionConflict');
      if (!(await this.#associated(tx, ref, sender, epoch))) throw new OutboxError('AccessDenied');
      if (old.senderId === sender && old.associationVersion === epoch) return old;
      return this.#saveRoute(tx, ref, old, {
        senderId: sender,
        associationVersion: epoch,
        suppressed: old.suppressed,
      });
    });
  }
  setSuppressed(
    accountToken: string,
    input: Readonly<{ suppressed: boolean; expectedRouteVersion: string }>,
    signal: AbortSignal,
  ): Promise<OutboundRoute> {
    const ref = this.#account(accountToken),
      p = record(input, ['suppressed', 'expectedRouteVersion']),
      expected = decimal(p.expectedRouteVersion);
    if (typeof p.suppressed !== 'boolean') throw new OutboxError('InvalidCommand');
    const suppressed = p.suppressed;
    return this.#run(true, signal, async (tx) => {
      await this.#counts(tx);
      const old = await this.#route(tx, ref);
      if (old.version !== expected) throw new OutboxError('RevisionConflict');
      if (old.version !== '0' && old.suppressed === suppressed) return old;
      return this.#saveRoute(tx, ref, old, {
        senderId: old.senderId,
        associationVersion: old.associationVersion,
        suppressed,
      });
    });
  }
  async #saveRoute(
    tx: Tx,
    ref: Account,
    old: OutboundRoute,
    proposed: Omit<OutboundRoute, 'version'>,
  ): Promise<OutboundRoute> {
    const next = (BigInt(old.version) + 1n).toString();
    decimal(next);
    if (old.version === '0') await this.#growth(tx, 'route');
    const p = this.#integration.providerScope;
    await tx.client.query(
      `INSERT INTO ${this.#q('outbound_routes')} VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(tenant_id,account_id,conversation_id) DO UPDATE SET version=EXCLUDED.version,sender_id=EXCLUDED.sender_id,association_epoch=EXCLUDED.association_epoch,suppressed=EXCLUDED.suppressed`,
      [
        ...this.#args(ref),
        p.provider,
        p.providerAccountId,
        next,
        proposed.senderId,
        proposed.associationVersion,
        proposed.suppressed,
      ],
    );
    return route({ version: next, ...proposed });
  }
  async #attempts(tx: Tx, reply: ReplyEnvelope): Promise<readonly SendAttempt[]> {
    const rows = await tx.client.query(
      `SELECT a.*,r.canonical_result,r.observed_at FROM ${this.#q('send_attempts')} a LEFT JOIN ${this.#q('send_results')} r USING(attempt_id) WHERE a.tenant_id=$1 AND a.account_id=$2 AND a.outbound_id=$3 ORDER BY a.ordinal LIMIT 6`,
      [reply.scope.tenantId, reply.scope.accountId, reply.outboundId],
    );
    if (rows.rows.length > tx.bounds.maxAttempts) throw new OutboxError('Unavailable');
    const attempts = Object.freeze(
      rows.rows.map((x, i) => {
        try {
          const request = sendRequest(JSON.parse(x.canonical_request));
          if (
            x.ordinal !== i + 1 ||
            request.attemptId !== x.attempt_id ||
            request.providerOperationKey !== x.provider_operation_key ||
            JSON.stringify(request) !== x.canonical_request ||
            sha(x.canonical_request) !== x.request_digest ||
            JSON.stringify(
              envelope({
                schemaVersion: 1,
                outboundId: request.outboundId,
                responseId: request.responseId,
                body: request.body,
                scope: request.scope,
                caseId: request.caseId,
                conversationId: request.conversationId,
              }),
            ) !== JSON.stringify(reply)
          )
            throw new Error();
          const result =
            x.canonical_result === null
              ? null
              : carrierResult(JSON.parse(x.canonical_result), request);
          if (
            (x.canonical_result === null) !== (x.observed_at === null) ||
            (result !== null && JSON.stringify(result) !== x.canonical_result) ||
            (tx.version < 5 &&
              i > 0 &&
              rows.rows[i - 1].canonical_result !== null &&
              JSON.parse(rows.rows[i - 1].canonical_result).status !== 'definitive_not_accepted') ||
            (tx.version < 5 && i > 0 && rows.rows[i - 1].canonical_result === null)
          )
            throw new Error();
          return Object.freeze({
            request,
            requestDigest: sha(x.canonical_request),
            reservedAt: timestamp(x.reserved_at),
            result,
            observedAt: x.observed_at === null ? null : timestamp(x.observed_at),
          });
        } catch {
          throw new OutboxError('Unavailable');
        }
      }),
    );
    if (tx.version >= 5) {
      const seen = new Set<string>();
      const ref = recipient({
        scope: reply.scope,
        caseId: reply.caseId,
        conversationId: reply.conversationId,
      });
      for (let index = 0; index < attempts.length; index++) {
        const current = attempts[index]!.request,
          { operation: op, firstAttemptId } = await this.#policy.loadOperation(
            tx.client,
            current.providerOperationKey,
            ref,
          );
        if (JSON.stringify(operationFrom(current, op.capability)) !== JSON.stringify(op))
          throw new OutboxError('Unavailable');
        if (firstAttemptId === current.attemptId) {
          if (seen.has(op.providerOperationKey)) throw new OutboxError('Unavailable');
          if (index > 0) {
            const previous = attempts[index - 1]!.request,
              proofRow = (
                await tx.client.query(
                  `SELECT admission_proof FROM ${this.#q('send_operations')} WHERE provider_operation_key=$1`,
                  [op.providerOperationKey],
                )
              ).rows[0];
            if (
              !proofRow ||
              JSON.parse(proofRow.admission_proof).predecessorAttemptId !== previous.attemptId
            )
              throw new OutboxError('Unavailable');
          }
          seen.add(op.providerOperationKey);
        } else {
          if (index === 0 || !seen.has(op.providerOperationKey))
            throw new OutboxError('Unavailable');
          await this.#policy.validateRetry(tx.client, current, attempts[index - 1]!.request, op);
        }
      }
    }
    return attempts;
  }
  #state(attempts: readonly SendAttempt[], maximum: number): OutboxObservation['state'] {
    const last = attempts.at(-1);
    if (!last) return 'queued';
    if (!last.result) return 'unknown';
    if (last.result.status === 'accepted_by_provider') return 'accepted_by_provider';
    return attempts.length >= maximum ? 'exhausted' : 'definitive_not_accepted';
  }
  inspect(
    accountToken: string,
    outboundId: string,
    signal: AbortSignal,
  ): Promise<OutboxObservation> {
    const ref = this.#account(accountToken),
      key = uuid(outboundId);
    return this.#run(false, signal, async (tx) => {
      const value = await this.#reply(tx, ref, key),
        attempts = await this.#attempts(tx, value.reply);
      return Object.freeze({
        ...value,
        state: this.#state(attempts, tx.bounds.maxAttempts),
        attempts,
      });
    });
  }
  pending(accountToken: string, limit: number, signal: AbortSignal): Promise<readonly string[]> {
    const ref = this.#account(accountToken);
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 32)
      throw new OutboxError('InvalidCommand');
    return this.#run(false, signal, async (tx) => {
      if (tx.version >= 5) {
        const rows = await tx.client.query(
          `SELECT i.outbound_id FROM ${this.#q('reply_intents')} i WHERE i.tenant_id=$1 AND i.account_id=$2 AND i.conversation_id=$3 AND i.case_id=$4 AND NOT EXISTS(SELECT 1 FROM ${this.#q('send_attempts')} pa JOIN ${this.#q('send_results')} pr USING(attempt_id) WHERE pa.tenant_id=i.tenant_id AND pa.account_id=i.account_id AND pa.outbound_id=i.outbound_id AND pr.canonical_result::jsonb->>'status'='accepted_by_provider') AND NOT EXISTS(SELECT 1 FROM ${this.#q('send_recovery_commands')} pc JOIN ${this.#q('send_recovery_observations')} po USING(command_id) WHERE pc.tenant_id=i.tenant_id AND pc.account_id=i.account_id AND pc.outbound_id=i.outbound_id AND (po.canonical_observation::jsonb->>'state'='accepted_by_provider' OR po.canonical_observation::jsonb->>'assessment'='conflicted')) AND NOT EXISTS(SELECT 1 FROM ${this.#q('send_attempts')} ca JOIN ${this.#q('callback_observations')} cb USING(attempt_id) WHERE ca.tenant_id=i.tenant_id AND ca.account_id=i.account_id AND ca.outbound_id=i.outbound_id) AND (NOT EXISTS(SELECT 1 FROM ${this.#q('send_attempts')} a WHERE a.tenant_id=i.tenant_id AND a.account_id=i.account_id AND a.outbound_id=i.outbound_id) OR ((SELECT count(*) FROM ${this.#q('send_attempts')} a WHERE a.tenant_id=i.tenant_id AND a.account_id=i.account_id AND a.outbound_id=i.outbound_id)<$5 AND EXISTS(SELECT 1 FROM ${this.#q('send_operations')} op WHERE op.provider_operation_key=(SELECT a.provider_operation_key FROM ${this.#q('send_attempts')} a WHERE a.tenant_id=i.tenant_id AND a.account_id=i.account_id AND a.outbound_id=i.outbound_id ORDER BY ordinal DESC LIMIT 1) AND (EXISTS(SELECT 1 FROM ${this.#q('send_attempts')} a JOIN ${this.#q('send_results')} r USING(attempt_id) WHERE a.provider_operation_key=op.provider_operation_key AND r.canonical_result::jsonb->>'status'='definitive_not_accepted') OR EXISTS(SELECT 1 FROM ${this.#q('send_recovery_commands')} c JOIN ${this.#q('send_recovery_observations')} r USING(command_id) WHERE c.provider_operation_key=op.provider_operation_key AND r.canonical_observation::jsonb->>'state'='definitive_not_accepted')) AND NOT EXISTS(SELECT 1 FROM ${this.#q('send_attempts')} a JOIN ${this.#q('send_results')} r USING(attempt_id) WHERE a.provider_operation_key=op.provider_operation_key AND r.canonical_result::jsonb->>'status'='accepted_by_provider') AND NOT EXISTS(SELECT 1 FROM ${this.#q('send_recovery_commands')} c JOIN ${this.#q('send_recovery_observations')} r USING(command_id) WHERE c.provider_operation_key=op.provider_operation_key AND (r.canonical_observation::jsonb->>'state'='accepted_by_provider' OR r.canonical_observation::jsonb->>'assessment'='conflicted'))))) ORDER BY i.accepted_at,i.outbound_id LIMIT $6`,
          [...this.#args(ref), tx.bounds.maxAttempts, limit],
        );
        return Object.freeze(rows.rows.map((x) => uuid(x.outbound_id)));
      }
      const rows = await tx.client.query(
        `SELECT i.outbound_id FROM ${this.#q('reply_intents')} i WHERE i.tenant_id=$1 AND i.account_id=$2 AND i.conversation_id=$3 AND i.case_id=$4 AND ${tx.version >= 4 ? `NOT EXISTS(SELECT 1 FROM ${this.#q('send_attempts')} ca JOIN ${this.#q('callback_observations')} co USING(attempt_id) WHERE ca.tenant_id=i.tenant_id AND ca.account_id=i.account_id AND ca.outbound_id=i.outbound_id) AND ` : ''}(NOT EXISTS(SELECT 1 FROM ${this.#q('send_attempts')} a WHERE a.tenant_id=i.tenant_id AND a.account_id=i.account_id AND a.outbound_id=i.outbound_id) OR ((SELECT count(*) FROM ${this.#q('send_attempts')} a WHERE a.tenant_id=i.tenant_id AND a.account_id=i.account_id AND a.outbound_id=i.outbound_id)<$5 AND NOT EXISTS(SELECT 1 FROM ${this.#q('send_attempts')} a LEFT JOIN ${this.#q('send_results')} r USING(attempt_id) WHERE a.tenant_id=i.tenant_id AND a.account_id=i.account_id AND a.outbound_id=i.outbound_id AND (r.attempt_id IS NULL OR r.canonical_result::jsonb->>'status'<>'definitive_not_accepted')))) ORDER BY i.accepted_at,i.outbound_id LIMIT $6`,
        [...this.#args(ref), tx.bounds.maxAttempts, limit],
      );
      return Object.freeze(rows.rows.map((x) => uuid(x.outbound_id)));
    });
  }
  async #priorOperationVeto(
    tx: Tx,
    attempts: readonly SendAttempt[],
    currentKey: string,
    ref: Account,
  ): Promise<boolean> {
    for (const key of new Set(attempts.map((x) => x.request.providerOperationKey))) {
      if (key === currentKey) continue;
      const { operation: op } = await this.#policy.loadOperation(tx.client, key, ref);
      if ((await this.#policy.state(tx.client, op)).state !== 'definitive_not_accepted')
        return true;
    }
    return false;
  }
  reserve(
    accountToken: string,
    outboundId: string,
    signal: AbortSignal,
    mode: SendCapability = 'ordinary_fake_sms_v1',
  ): Promise<Reservation> {
    const ref = this.#account(accountToken),
      key = uuid(outboundId);
    return this.#run(true, signal, async (tx) => {
      const { reply } = await this.#reply(tx, ref, key),
        attempts = await this.#attempts(tx, reply);
      let state = this.#state(attempts, tx.bounds.maxAttempts);
      if (tx.version >= 5 && attempts.length) {
        const { operation: op } = await this.#policy.loadOperation(
            tx.client,
            attempts.at(-1)!.request.providerOperationKey,
            ref,
          ),
          known = await this.#policy.state(tx.client, op);
        state =
          known.state === 'conflicted'
            ? 'unknown'
            : known.state === 'definitive_not_accepted'
              ? attempts.length >= tx.bounds.maxAttempts
                ? 'exhausted'
                : 'definitive_not_accepted'
              : known.state;
        if (['queued', 'definitive_not_accepted'].includes(state) && op.capability !== mode)
          throw new OutboxError('IdentityConflict');
      }
      if (!['queued', 'definitive_not_accepted'].includes(state))
        return {
          result: Object.freeze({
            status: state as 'unknown' | 'accepted_by_provider' | 'exhausted',
            outboundId: key,
            attemptId: attempts.at(-1)?.request.attemptId ?? null,
          }),
        };
      if (
        tx.version >= 5 &&
        attempts.length &&
        (await this.#priorOperationVeto(
          tx,
          attempts,
          attempts.at(-1)!.request.providerOperationKey,
          ref,
        ))
      )
        return {
          result: Object.freeze({
            status: 'unknown',
            outboundId: key,
            attemptId: attempts.at(-1)!.request.attemptId,
          }),
        };
      if (mode === 'idempotent_fake_sms_v1' && tx.version < 5)
        throw new OutboxError('UpgradeRequired');
      await this.#counts(tx);
      if (tx.version >= 4) {
        const callbacks = await tx.client.query(
          `SELECT 1 FROM ${this.#q('send_attempts')} a JOIN ${this.#q('callback_observations')} c USING(attempt_id) WHERE a.tenant_id=$1 AND a.account_id=$2 AND a.outbound_id=$3 LIMIT 1`,
          [ref.scope.tenantId, ref.scope.accountId, key],
        );
        if (callbacks.rowCount)
          return {
            result: Object.freeze({
              status: 'unknown',
              outboundId: key,
              attemptId: attempts.at(-1)?.request.attemptId ?? null,
            }),
          };
      }
      const current = await this.#route(tx, ref),
        held = (reason: 'route_missing' | 'association_required' | 'suppressed'): Reservation => ({
          result: Object.freeze({ status: 'held', reason, outboundId: key }),
        });
      if (current.suppressed) return held('suppressed');
      if (!current.senderId || !current.associationVersion) return held('route_missing');
      if (!(await this.#associated(tx, ref, current.senderId, current.associationVersion)))
        return held('association_required');
      const request = sendRequest({
          ...reply,
          attemptId: randomUUID(),
          providerOperationKey: randomUUID(),
          providerScope: this.#integration.providerScope,
          senderId: current.senderId,
          associationVersion: current.associationVersion,
          routeVersion: current.version,
        }),
        canonical = JSON.stringify(request);
      if (tx.version >= 5)
        await this.#policy.createOperation(
          tx.client,
          request,
          mode,
          await this.#policy.admissionFor(tx.client, attempts.at(-1)?.request, ref),
        );
      await tx.client.query(
        `INSERT INTO ${this.#q('send_attempts')} VALUES($1,$2,$3,$4,$5,$6,$7,$8,clock_timestamp())`,
        [
          request.attemptId,
          ref.scope.tenantId,
          ref.scope.accountId,
          key,
          attempts.length + 1,
          request.providerOperationKey,
          canonical,
          sha(canonical),
        ],
      );
      return { request };
    });
  }
  recordResult(request: SendRequest, input: CarrierResult): Promise<CarrierResult> {
    const expected = sendRequest(request),
      result = carrierResult(input, expected);
    return this.#record(async (tx) => {
      const rows = await tx.client.query(
        `SELECT canonical_request FROM ${this.#q('send_attempts')} WHERE attempt_id=$1 AND tenant_id=$2 AND account_id=$3 AND outbound_id=$4`,
        [
          expected.attemptId,
          expected.scope.tenantId,
          expected.scope.accountId,
          expected.outboundId,
        ],
      );
      if (rows.rowCount !== 1 || rows.rows[0].canonical_request !== JSON.stringify(expected))
        throw new OutboxError('IdentityConflict');
      const old = await tx.client.query(
        `SELECT canonical_result FROM ${this.#q('send_results')} WHERE attempt_id=$1`,
        [expected.attemptId],
      );
      if (old.rowCount) {
        if (old.rows[0].canonical_result !== JSON.stringify(result))
          throw new OutboxError('IdentityConflict');
        return result;
      }
      await tx.client.query(
        `INSERT INTO ${this.#q('send_results')} VALUES($1,$2,clock_timestamp())`,
        [expected.attemptId, JSON.stringify(result)],
      );
      return result;
    });
  }

  #controller(token: string): Account {
    const ref = this.#controllers.get(this.#token(token));
    if (!ref) throw new OutboxError('AccessDenied');
    return ref;
  }
  recoveryCommand(
    token: string,
    commandId: string,
    signal: AbortSignal,
    controller = false,
  ): Promise<RecoveryCommandView | null> {
    const ref = controller ? this.#controller(token) : this.#account(token),
      key = uuid(commandId);
    return this.#run(false, signal, async (tx) => {
      if (tx.version < 5) throw new OutboxError('UpgradeRequired');
      return this.#policy.command(tx.client, key, ref);
    });
  }
  inspectRecovery(
    token: string,
    outboundId: string,
    signal: AbortSignal,
  ): Promise<RecoverySummary> {
    const ref = this.#account(token),
      key = uuid(outboundId);
    return this.#run(false, signal, async (tx) => {
      if (tx.version < 5) throw new OutboxError('UpgradeRequired');
      const { reply } = await this.#reply(tx, ref, key),
        attempts = await this.#attempts(tx, reply),
        keys = [...new Set(attempts.map((x) => x.request.providerOperationKey))],
        operations = [];
      for (const id of keys) {
        const { operation: op, firstAttemptId } = await this.#policy.loadOperation(
            tx.client,
            id,
            ref,
          ),
          state = await this.#policy.state(tx.client, op);
        operations.push(
          Object.freeze({
            providerOperationKey: id,
            operationDigest: operationDigest(op),
            capability: op.capability,
            firstAttemptId,
            state: state.state,
            providerMessageIdsSample: Object.freeze(state.ids.slice(0, 2)),
            providerMessageIdCount: state.ids.length,
            callbackVeto: state.callbackVeto,
            commandCount: state.commandCount,
            latestCommandId: state.latestCommandId,
          }),
        );
      }
      const result = Object.freeze({ outboundId: key, operations: Object.freeze(operations) });
      if (Buffer.byteLength(JSON.stringify(result)) > 8192) throw new OutboxError('Unavailable');
      return result;
    });
  }
  reserveRecovery(
    token: string,
    kind: RecoveryKind,
    commandId: string,
    outboundId: string,
    sourceAttemptId: string,
    mode: SendCapability,
    signal: AbortSignal,
  ): Promise<RecoveryReservation> {
    const ref = this.#controller(token),
      key = uuid(commandId),
      outbound = uuid(outboundId),
      attempt = uuid(sourceAttemptId);
    return this.#run(true, signal, async (tx) => {
      if (tx.version < 5) throw new OutboxError('UpgradeRequired');
      const original = await this.#policy.command(tx.client, key, ref);
      if (original) {
        this.#policy.match(original, kind, outbound, attempt);
        const { operation: op } = await this.#policy.loadOperation(
          tx.client,
          original.receipt.providerOperationKey,
          ref,
        );
        return Object.freeze({
          view: original,
          created: false,
          action: 'none',
          operation: op,
          request: null,
        });
      }
      const { reply } = await this.#reply(tx, ref, outbound),
        attempts = await this.#attempts(tx, reply),
        source = attempts.find((x) => x.request.attemptId === attempt)?.request;
      if (!source) throw new OutboxError('NotFound');
      if (kind === 'retry' && attempts.at(-1)?.request.attemptId !== attempt)
        throw new OutboxError('RevisionConflict');
      const { operation: op } = await this.#policy.loadOperation(
          tx.client,
          source.providerOperationKey,
          ref,
        ),
        known = await this.#policy.state(tx.client, op);
      await this.#counts(tx);
      let decision: RecoveryReceipt['decision'] = 'held',
        code: RecoveryCode = 'ordinary_no_resend',
        action: RecoveryReservation['action'] = 'none',
        next: SendRequest | null = null;
      if (known.state === 'accepted_by_provider') {
        decision = 'terminal';
        code = 'known_accepted';
      } else if (
        kind === 'retry' &&
        (await this.#priorOperationVeto(tx, attempts, op.providerOperationKey, ref))
      ) {
        code = 'prior_operation_evidence';
      } else if (known.state === 'conflicted') code = 'conflicted';
      else if (known.state === 'definitive_not_accepted') {
        decision = 'terminal';
        code = 'known_not_accepted';
      } else if (op.capability === 'ordinary_fake_sms_v1') code = 'ordinary_no_resend';
      else {
        if (mode !== 'idempotent_fake_sms_v1') throw new OutboxError('IdentityConflict');
        if (kind === 'reconcile') {
          decision = 'lookup_authorized';
          code = 'lookup';
          action = 'lookup';
        } else if (known.callbackVeto) code = 'callback_veto';
        else if (attempts.length >= tx.bounds.maxAttempts) code = 'attempt_exhausted';
        else {
          const route = await this.#route(tx, ref);
          if (route.suppressed) code = 'suppressed';
          else if (!route.senderId || !route.associationVersion) code = 'route_missing';
          else if (route.senderId !== op.senderId) code = 'route_changed';
          else if (!(await this.#associated(tx, ref, op.senderId, route.associationVersion)))
            code = 'association_required';
          else {
            next = sendRequest({
              ...source,
              attemptId: randomUUID(),
              associationVersion: route.associationVersion,
              routeVersion: route.version,
            });
            if (JSON.stringify(operationFrom(next, op.capability)) !== JSON.stringify(op))
              throw new OutboxError('IdentityConflict');
            decision = 'retry_reserved';
            code = 'retry_reserved';
            action = 'send';
          }
        }
      }
      let view = await this.#policy.insertCommand(
        tx.client,
        ref,
        kind,
        key,
        source,
        op,
        decision,
        code,
        next?.attemptId ?? null,
      );
      if (next) {
        await tx.client.query(
          `INSERT INTO ${this.#q('send_attempts')} VALUES($1,$2,$3,$4,$5,$6,$7,$8,clock_timestamp())`,
          [
            next.attemptId,
            ref.scope.tenantId,
            ref.scope.accountId,
            outbound,
            attempts.length + 1,
            next.providerOperationKey,
            JSON.stringify(next),
            sha(JSON.stringify(next)),
          ],
        );
      }
      if (action === 'none') {
        const state =
            decision === 'terminal' && known.state === 'accepted_by_provider'
              ? 'accepted_by_provider'
              : decision === 'terminal' && known.state === 'definitive_not_accepted'
                ? 'definitive_not_accepted'
                : 'unknown',
          result = lookup(
            {
              schemaVersion: 1,
              providerScope: op.providerScope,
              providerOperationKey: op.providerOperationKey,
              operationDigest: operationDigest(op),
              state,
              providerMessageId: state === 'accepted_by_provider' ? known.ids[0]! : null,
            },
            op,
          );
        view = await this.#policy.observe(tx.client, view.receipt, op, result, 'policy');
      }
      return Object.freeze({ view, created: true, action, operation: op, request: next });
    });
  }
  recordRecovery(
    receiptInput: RecoveryReceipt,
    operationInput: ProviderOperation,
    resultInput: ProviderLookup,
    source: RecoveryObservation['source'],
    sent?: Readonly<{ request: SendRequest; result: CarrierResult }>,
  ): Promise<RecoveryCommandView> {
    const receipt = recoveryReceipt(receiptInput),
      op = operationFromOperation(operationInput),
      result = lookup(resultInput, op),
      snapshot =
        sent === undefined
          ? undefined
          : Object.freeze({
              request: sendRequest(sent.request),
              result: carrierResult(sent.result, sendRequest(sent.request)),
            }),
      ref = recipient({ scope: op.scope, caseId: op.caseId, conversationId: op.conversationId });
    return this.#record(async (tx) => {
      if (tx.version < 5) throw new OutboxError('UpgradeRequired');
      const current = await this.#policy.command(tx.client, receipt.commandId, ref);
      if (!current || JSON.stringify(current.receipt) !== JSON.stringify(receipt))
        throw new OutboxError('IdentityConflict');
      if (current.observation) return current;
      if (snapshot) {
        if (
          source !== 'send' ||
          snapshot.request.attemptId !== receipt.newAttemptId ||
          JSON.stringify(operationFrom(snapshot.request, op.capability)) !== JSON.stringify(op)
        )
          throw new OutboxError('IdentityConflict');
        const rows = (
          await tx.client.query(
            `SELECT canonical_request FROM ${this.#q('send_attempts')} WHERE attempt_id=$1`,
            [snapshot.request.attemptId],
          )
        ).rows;
        if (rows.length !== 1 || rows[0].canonical_request !== JSON.stringify(snapshot.request))
          throw new OutboxError('IdentityConflict');
        const old = (
          await tx.client.query(
            `SELECT canonical_result FROM ${this.#q('send_results')} WHERE attempt_id=$1`,
            [snapshot.request.attemptId],
          )
        ).rows;
        if (old.length && old[0].canonical_result !== JSON.stringify(snapshot.result))
          throw new OutboxError('IdentityConflict');
        if (!old.length)
          await tx.client.query(
            `INSERT INTO ${this.#q('send_results')} VALUES($1,$2,clock_timestamp())`,
            [snapshot.request.attemptId, JSON.stringify(snapshot.result)],
          );
      }
      return this.#policy.observe(tx.client, receipt, op, result, source);
    });
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({ active: this.#calls.size, connections: this.#pool.totalCount });
  }
  async close(): Promise<void> {
    this.#closing = true;
    this.#ending ??= Promise.allSettled([...this.#calls]).then(() => this.#pool.end());
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        this.#ending,
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new OutboxError('CleanupIncomplete')), 2000);
        }),
      ]);
      if (this.#calls.size || this.#pool.totalCount) throw new OutboxError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
