/** Durable callback evidence. Global admission is acquired before callback growth. */
import { randomUUID } from 'node:crypto';
import type { Pool, PoolClient } from 'pg';
import { PgPool, config, settings, table, validate } from './database.js';
import {
  DEFINITION_DIGEST,
  DISPATCH_DEFINITION_DIGEST,
  OUTBOX_DEFINITION_DIGEST,
  CALLBACK_DEFINITION_DIGEST,
  SEND_POLICY_DEFINITION_DIGEST,
  NATIVE_DEFINITION_DIGEST,
  COMMUNICATION_DEFINITION_DIGEST,
  RESULT_RECEIVER_DEFINITION_DIGEST,
} from './migrations.js';
import type { DatabaseSettings } from './public-types.js';
import { SeededAccounts } from './postgres.js';
import { checkedSignal, isAborted } from './routing-types.js';
import {
  record,
  sendRequest,
  carrierResult,
  sha,
  uuid,
  timestamp,
  recipient,
  type SendRequest,
  type CarrierResult,
} from './outbox-types.js';
import {
  CALLBACK_WINDOW_SECONDS,
  authenticateFakeSmsCallback,
  configuredCallbackScope,
  parseCallbackWire,
  type FakeSmsCallbackIntegration,
  type VerifiedCallback,
} from './callback-security.js';
import {
  CallbackError,
  callbackLimits,
  callbackObservation,
  safeCallback,
  reduceCallbackEvidence,
  type CallbackLimits,
  type CallbackReceipt,
  type RetainedCallback,
  type CallbackAttempt,
} from './callback-types.js';
import type { WebhookHeaders } from './security.js';
type Tx = { client: PoolClient; bounds: CallbackLimits; signal: AbortSignal };
export class CallbackStore {
  readonly #database: DatabaseSettings;
  readonly #pool: Pool;
  readonly #integration: FakeSmsCallbackIntegration;
  readonly #accounts: SeededAccounts;
  readonly #calls = new Set<Promise<unknown>>();
  #closing = false;
  #ending: Promise<void> | undefined;
  constructor(
    database: DatabaseSettings,
    integration: FakeSmsCallbackIntegration,
    accounts: SeededAccounts,
  ) {
    this.#database = settings(database, 'livekit_lab');
    if (!(accounts instanceof SeededAccounts)) throw new CallbackError('InvalidCommand');
    configuredCallbackScope(integration);
    this.#integration = integration;
    this.#accounts = accounts;
    this.#pool = new PgPool(config(this.#database));
    this.#pool.on('error', () => undefined);
  }
  #q(name: string) {
    return table(this.#database.schema, name);
  }
  #run<T>(write: boolean, signal: AbortSignal, action: (tx: Tx) => Promise<T>): Promise<T> {
    try {
      checkedSignal(signal);
    } catch {
      throw new CallbackError('InvalidCommand');
    }
    if (this.#closing) return Promise.reject(new CallbackError('Closed'));
    if (this.#calls.size >= 4) return Promise.reject(new CallbackError('Overloaded'));
    if (isAborted(signal)) return Promise.reject(new CallbackError('Unavailable'));
    const work = Promise.resolve().then(async () => {
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
        );
        const version = (
          await client.query(`SELECT version FROM ${this.#q('schema_metadata')} WHERE singleton`)
        ).rows[0]?.version;
        if (version !== 4 && version !== 5 && version !== 6 && version !== 7 && version !== 8)
          throw new CallbackError('UpgradeRequired');
        if (write) {
          const lock = await client.query(
            `SELECT singleton FROM ${this.#q('admission')} WHERE singleton FOR UPDATE`,
          );
          if (lock.rowCount !== 1) throw new CallbackError('Unavailable');
        }
        const rows = (
          await client.query(`SELECT * FROM ${this.#q('callback_settings')} WHERE singleton`)
        ).rows;
        if (rows.length !== 1 || rows[0].rule_version !== 1) throw new CallbackError('Unavailable');
        const bounds = callbackLimits({
          maxGlobal: rows[0].max_global,
          maxPerAttempt: rows[0].max_per_attempt,
        });
        if (isAborted(signal)) throw new CallbackError('Unavailable');
        const value = await action({ client, bounds, signal });
        if (isAborted(signal)) throw new CallbackError('Unavailable');
        committing = write;
        await client.query('COMMIT');
        began = false;
        committing = false;
        if (isAborted(signal))
          throw new CallbackError(write ? 'AcknowledgementUnknown' : 'Unavailable');
        return value;
      } catch (error) {
        if (client && began)
          try {
            await client.query('ROLLBACK');
          } catch {
            broken = true;
          }
        if (committing) {
          broken = true;
          throw new CallbackError('AcknowledgementUnknown');
        }
        throw safeCallback(error);
      } finally {
        client?.release(broken);
      }
    });
    this.#calls.add(work);
    void work.then(
      () => this.#calls.delete(work),
      () => this.#calls.delete(work),
    );
    return work;
  }
  #decode(row: Record<string, unknown>): RetainedCallback {
    try {
      if (
        typeof row.canonical_payload !== 'string' ||
        sha(row.canonical_payload) !== row.payload_digest
      )
        throw Error();
      const observation = callbackObservation(JSON.parse(row.canonical_payload));
      if (
        typeof row.first_wire !== 'string' ||
        JSON.stringify(parseCallbackWire(row.first_wire)) !== row.canonical_payload ||
        JSON.stringify(observation) !== row.canonical_payload ||
        observation.attemptId !== row.attempt_id ||
        observation.eventId !== row.event_id
      )
        throw Error();
      return Object.freeze({
        observation,
        receipt: Object.freeze({
          receiptId: uuid(row.receipt_id),
          eventId: observation.eventId,
          attemptId: observation.attemptId,
          payloadDigest: sha(row.canonical_payload),
          acceptedAt: timestamp(row.accepted_at),
        }),
      });
    } catch {
      throw new CallbackError('Unavailable');
    }
  }
  async #attempt(
    tx: Tx,
    attemptId: string,
  ): Promise<{ request: SendRequest; result: CarrierResult | null }> {
    const rows = (
      await tx.client.query(
        `SELECT a.*,r.canonical_result FROM ${this.#q('send_attempts')} a LEFT JOIN ${this.#q('send_results')} r USING(attempt_id) WHERE a.attempt_id=$1`,
        [attemptId],
      )
    ).rows;
    if (rows.length !== 1) throw new CallbackError('AccessDenied');
    try {
      const row = rows[0],
        request = sendRequest(JSON.parse(row.canonical_request));
      if (
        JSON.stringify(request) !== row.canonical_request ||
        sha(row.canonical_request) !== row.request_digest ||
        request.attemptId !== row.attempt_id ||
        request.providerOperationKey !== row.provider_operation_key ||
        request.scope.tenantId !== row.tenant_id ||
        request.scope.accountId !== row.account_id ||
        request.outboundId !== row.outbound_id
      )
        throw Error();
      const result =
        row.canonical_result === null
          ? null
          : carrierResult(JSON.parse(row.canonical_result), request);
      if (result !== null && JSON.stringify(result) !== row.canonical_result) throw Error();
      return { request, result };
    } catch {
      throw new CallbackError('Unavailable');
    }
  }
  accept(
    raw: Uint8Array,
    headers: WebhookHeaders,
    signal: AbortSignal,
  ): Promise<{ receipt: CallbackReceipt; created: boolean }> {
    // Authenticate and copy BEFORE scheduling any I/O. Every replay authenticates anew.
    const verified = authenticateFakeSmsCallback(
      raw,
      headers,
      this.#integration,
      Math.floor(Date.now() / 1000),
    );
    return this.#run(true, signal, (tx) => this.#accept(tx, verified));
  }
  async #accept(
    tx: Tx,
    verified: VerifiedCallback,
  ): Promise<{ receipt: CallbackReceipt; created: boolean }> {
    const p = verified.providerScope,
      o = verified.observation,
      canonical = JSON.stringify(o),
      clock = (
        await tx.client.query(
          'SELECT floor(extract(epoch FROM clock_timestamp()))::bigint AS seconds',
        )
      ).rows[0]?.seconds;
    if (
      typeof clock !== 'string' ||
      !/^[0-9]{10}$/.test(clock) ||
      Math.abs(Number(clock) - verified.transportSeconds) > CALLBACK_WINDOW_SECONDS
    )
      throw new CallbackError('WebhookRejected');
    const prior = await tx.client.query(
      `SELECT * FROM ${this.#q('callback_observations')} WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND event_id=$4`,
      [p.tenantId, p.provider, p.providerAccountId, o.eventId],
    );
    if (prior.rowCount) {
      if (prior.rows[0].canonical_payload !== canonical)
        throw new CallbackError('IdentityConflict');
      return { receipt: this.#decode(prior.rows[0]).receipt, created: false };
    }
    const { request } = await this.#attempt(tx, o.attemptId);
    if (
      JSON.stringify(request.providerScope) !== JSON.stringify(p) ||
      request.providerOperationKey !== o.providerOperationKey ||
      sha(JSON.stringify(request)) !== o.requestDigest
    )
      throw new CallbackError('AccessDenied');
    const guard = await tx.client.query(
        `SELECT callback_count FROM ${this.#q('callback_admission')} WHERE singleton FOR UPDATE`,
      ),
      counts = await tx.client.query(
        `SELECT count(*)::integer AS total,count(*) FILTER(WHERE attempt_id=$1)::integer AS local FROM ${this.#q('callback_observations')}`,
        [o.attemptId],
      ),
      g = guard.rows[0]?.callback_count,
      c = counts.rows[0];
    if (
      guard.rowCount !== 1 ||
      !Number.isSafeInteger(g) ||
      g < 0 ||
      g > tx.bounds.maxGlobal ||
      g !== c?.total ||
      !Number.isSafeInteger(c?.local) ||
      c.local < 0 ||
      c.local > tx.bounds.maxPerAttempt
    )
      throw new CallbackError('Unavailable');
    if (g >= tx.bounds.maxGlobal || c.local >= tx.bounds.maxPerAttempt)
      throw new CallbackError('Overloaded');
    if (isAborted(tx.signal)) throw new CallbackError('Unavailable');
    const saved = await tx.client.query(
      `INSERT INTO ${this.#q('callback_observations')} VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,clock_timestamp()) RETURNING *`,
      [
        p.tenantId,
        p.provider,
        p.providerAccountId,
        o.eventId,
        randomUUID(),
        o.attemptId,
        c.local + 1,
        canonical,
        sha(canonical),
        verified.raw,
      ],
    );
    await tx.client.query(
      `UPDATE ${this.#q('callback_admission')} SET callback_count=callback_count+1 WHERE singleton`,
    );
    return { receipt: this.#decode(saved.rows[0]).receipt, created: true };
  }
  inspectAttempt(
    token: string,
    input: Readonly<{ outboundId: string; attemptId: string }>,
    signal: AbortSignal,
  ): Promise<CallbackAttempt> {
    let ref: ReturnType<typeof recipient>, outboundId: string, attemptId: string;
    try {
      const desc = record(input, ['outboundId', 'attemptId']);
      outboundId = uuid(desc.outboundId);
      attemptId = uuid(desc.attemptId);
      const a = this.#accounts.authenticate(token, this.#integration.providerScope.tenantId);
      ref = recipient({
        scope: { tenantId: a.tenantId, accountId: a.accountId },
        caseId: a.caseId,
        conversationId: a.conversationId,
      });
    } catch {
      throw new CallbackError('AccessDenied');
    }
    return this.#run(false, signal, async (tx) => {
      const { request, result } = await this.#attempt(tx, attemptId);
      if (
        request.outboundId !== outboundId ||
        JSON.stringify(request.providerScope) !== JSON.stringify(this.#integration.providerScope) ||
        JSON.stringify(
          recipient({
            scope: request.scope,
            caseId: request.caseId,
            conversationId: request.conversationId,
          }),
        ) !== JSON.stringify(ref)
      )
        throw new CallbackError('AccessDenied');
      const rows = await tx.client.query(
        `SELECT * FROM ${this.#q('callback_observations')} WHERE attempt_id=$1 ORDER BY ordinal LIMIT 33`,
        [attemptId],
      );
      if (rows.rows.length > tx.bounds.maxPerAttempt) throw new CallbackError('Unavailable');
      const observations = Object.freeze(
        rows.rows.map((row, i) => {
          if (
            row.ordinal !== i + 1 ||
            row.tenant_id !== request.providerScope.tenantId ||
            row.provider !== request.providerScope.provider ||
            row.provider_account_id !== request.providerScope.providerAccountId
          )
            throw new CallbackError('Unavailable');
          const v = this.#decode(row);
          if (
            v.observation.providerOperationKey !== request.providerOperationKey ||
            v.observation.requestDigest !== sha(JSON.stringify(request))
          )
            throw new CallbackError('Unavailable');
          return v;
        }),
      );
      return Object.freeze({
        outboundId,
        attemptId,
        requestDigest: sha(JSON.stringify(request)),
        providerOperationKey: request.providerOperationKey,
        observations,
        evidence: reduceCallbackEvidence(
          observations.map((v) => v.observation),
          result,
        ),
      });
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
          timer = setTimeout(() => reject(new CallbackError('CleanupIncomplete')), 2000);
        }),
      ]);
      if (this.#calls.size || this.#pool.totalCount) throw new CallbackError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
