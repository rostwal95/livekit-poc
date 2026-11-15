/** Persisted P2 message-dispatch observations; external business work is owned by its port. */
import { randomUUID } from 'node:crypto';
import type { Pool, PoolClient } from 'pg';
import { PgPool, watchPool, config, settings, table, validate } from './database.js';
import { ChannelError, type DatabaseSettings } from './public-types.js';
import { SeededAccounts, type StoredMessage } from './postgres.js';
import { decodeStoredMessage } from './postgres-records.js';
import type { FakeSmsIntegration } from './security.js';
import { NativeStore } from './native-store.js';
import { isNativeIntegration, type NativeIntegration } from './native-types.js';
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
  dispatchLimits,
  type DispatchLimits,
} from './migrations.js';
import {
  dispatchUuid,
  parsePreparedDispatch,
  sameDispatchScope,
  type DispatchObservation,
  type DispatchStepResult,
  type OperationReceipt,
  type PreparedDispatch,
} from './dispatch-types.js';
type Account = ReturnType<SeededAccounts['authenticate']>;
export type DispatchClaim = Readonly<{
  receiptId: string;
  operationKey: string;
  ownerId: string;
  epoch: string;
  kind: 'dispatch' | 'reconcile';
  message: StoredMessage;
  prepared: PreparedDispatch | null;
  possibleExternal: boolean;
}>;
export type ClaimOutcome =
  Readonly<{ claim: DispatchClaim }> | Readonly<{ result: DispatchStepResult }>;
type Row = Record<string, unknown>;
function date(value: unknown): Date {
  if (!(value instanceof Date) || !Number.isFinite(value.getTime()))
    throw new ChannelError('SchemaMismatch');
  return value;
}
function bigint(value: unknown): string {
  const text = String(value);
  if (!/^(0|[1-9][0-9]{0,18})(?![\s\S])/.test(text) || BigInt(text) > 9223372036854775807n)
    throw new ChannelError('SchemaMismatch');
  return text;
}
export class DispatchStore {
  readonly #native: NativeStore | undefined;
  readonly #value: DatabaseSettings;
  readonly #pool: Pool;
  readonly #integration: FakeSmsIntegration;
  readonly #accounts: SeededAccounts;
  #active = 0;
  #closing = false;
  #idle: (() => void) | undefined;
  #ending: Promise<unknown> | undefined;
  #closed: Promise<void> | undefined;
  constructor(input: DatabaseSettings, integration: FakeSmsIntegration, accounts: SeededAccounts) {
    this.#value = settings(input, 'livekit_lab');
    this.#integration = integration;
    if (isNativeIntegration(integration))
      this.#native = new NativeStore(this.#value.schema, integration as NativeIntegration);
    this.#accounts = accounts;
    if (!(accounts instanceof SeededAccounts) || !integration?.providerScope)
      throw new ChannelError('AccessDenied');
    this.#pool = watchPool(new PgPool(config(this.#value)));
    this.#pool.on('error', () => undefined);
  }
  #q(name: string): string {
    return table(this.#value.schema, name);
  }
  #account(token: string): Account {
    return this.#accounts.authenticate(token, this.#integration.providerScope.tenantId);
  }
  async #tx<T>(
    write: boolean,
    work: (client: PoolClient, bounds: DispatchLimits) => Promise<T>,
  ): Promise<T> {
    if (this.#closing) throw new ChannelError('StorageUnavailable');
    if (this.#active >= 4) throw new ChannelError('Overloaded');
    this.#active++;
    let client: PoolClient | undefined,
      committed = false,
      commitStarted = false,
      broken = false;
    try {
      client = await this.#pool.connect();
      await client.query('BEGIN');
      await validate(
        client,
        this.#value,
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
      const metadata = await client.query(
        `SELECT version FROM ${this.#q('schema_metadata')} WHERE singleton`,
      );
      if (![2, 3, 4, 5, 6, 7, 8, 9].includes(metadata.rows[0]?.version))
        throw new ChannelError('UpgradeRequired');
      if (write) {
        const lock = await client.query(
          `SELECT singleton FROM ${this.#q('admission')} WHERE singleton FOR UPDATE`,
        );
        if (lock.rowCount !== 1) throw new ChannelError('SchemaMismatch');
      }
      const policy = await client.query(
        `SELECT max_active,max_attempts,lease_ms,retry_delay_ms FROM ${this.#q('dispatch_settings')} WHERE singleton`,
      );
      if (policy.rowCount !== 1) throw new ChannelError('SchemaMismatch');
      const row = policy.rows[0]!;
      const bounds = dispatchLimits({
        maxActive: row.max_active,
        maxAttempts: row.max_attempts,
        leaseMs: row.lease_ms,
        retryDelayMs: row.retry_delay_ms,
      });
      const result = await work(client, bounds);
      commitStarted = true;
      await client.query('COMMIT');
      committed = true;
      return result;
    } catch (error) {
      // Reuse a connection only after a clean rollback; an uncertain commit discards it.
      broken = commitStarted && !committed;
      if (client && !committed)
        try {
          await client.query('ROLLBACK');
        } catch {
          broken = true;
        }
      if (committed || (commitStarted && write)) throw new ChannelError('AcknowledgementUnknown');
      if (error instanceof ChannelError) throw error;
      throw new ChannelError('StorageUnavailable');
    } finally {
      try {
        client?.release(broken);
      } finally {
        this.#active--;
        if (this.#active === 0) {
          this.#idle?.();
          this.#idle = undefined;
        }
      }
    }
  }
  async #row(client: PoolClient, account: Account, receiptId: string, lock: boolean): Promise<Row> {
    const p = this.#integration.providerScope;
    const found = await client.query(
      `SELECT i.*,p.operation_key,p.state,p.claim_epoch,p.claim_owner,p.claim_until,p.claim_kind,p.attempt_count,p.next_attempt_at,p.possible_external,p.external_receipt_id,p.last_code FROM ${this.#q('inbox')} i JOIN ${this.#q('processing_intents')} p USING(receipt_id) WHERE i.receipt_id=$1 AND i.tenant_id=$2 AND i.provider=$3 AND i.provider_account_id=$4 AND i.account_id=$5 AND i.conversation_id=$6${lock ? ' FOR UPDATE OF p' : ''}`,
      [
        receiptId,
        p.tenantId,
        p.provider,
        p.providerAccountId,
        account.accountId,
        account.conversationId,
      ],
    );
    if (found.rowCount !== 1) throw new ChannelError('NotFound');
    const row = found.rows[0] as Row;
    decodeStoredMessage(row);
    if (
      typeof row.possible_external !== 'boolean' ||
      !Number.isSafeInteger(row.attempt_count) ||
      (row.attempt_count as number) < 0 ||
      (row.attempt_count as number) > 5
    )
      throw new ChannelError('SchemaMismatch');
    bigint(row.claim_epoch);
    return row;
  }
  async #clock(client: PoolClient): Promise<Date> {
    return date((await client.query('SELECT clock_timestamp() AS now')).rows[0]?.now);
  }
  async #binding(client: PoolClient, message: StoredMessage): Promise<string | null> {
    if (message.event.type === 'text.received' && message.event.channel !== 'sms')
      return this.#native ? this.#native.binding(client, message) : null;
    if (
      message.event.type !== 'text.received' ||
      message.event.channel !== 'sms' ||
      !message.event.accountScope ||
      !message.event.caseId
    )
      return null;
    const p = message.event.providerScope;
    const head = await client.query(
      `SELECT epoch,active_epoch FROM ${this.#q('sender_heads')} WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND sender_id=$4 FOR UPDATE`,
      [p.tenantId, p.provider, p.providerAccountId, message.event.senderId],
    );
    if (!head.rows[0] || head.rows[0].active_epoch === null) return null;
    const current = await client.query(
      `SELECT epoch::text,account_id,conversation_id,case_id FROM ${this.#q('associations')} WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND sender_id=$4 AND epoch=$5 AND revoked_at IS NULL`,
      [
        p.tenantId,
        p.provider,
        p.providerAccountId,
        message.event.senderId,
        head.rows[0].active_epoch,
      ],
    );
    const row = current.rows[0];
    if (
      !row ||
      row.account_id !== message.event.accountScope.accountId ||
      row.conversation_id !== message.event.conversationId ||
      row.case_id !== message.event.caseId
    )
      return null;
    return bigint(row.epoch);
  }
  async #prepared(client: PoolClient, row: Row): Promise<PreparedDispatch | null> {
    const found = await client.query(
      `SELECT payload_json,payload_digest FROM ${this.#q('dispatch_plans')} WHERE receipt_id=$1`,
      [row.receipt_id],
    );
    if (found.rowCount === 0) return null;
    if (found.rowCount !== 1) throw new ChannelError('SchemaMismatch');
    const prepared = parsePreparedDispatch(
      found.rows[0]!.payload_json,
      found.rows[0]!.payload_digest,
    );
    this.#samePrepared(row, prepared);
    return prepared;
  }
  #samePrepared(row: Row, prepared: PreparedDispatch): void {
    const message = decodeStoredMessage(row),
      submission = prepared.submission;
    if (
      message.event.type !== 'text.received' ||
      !message.event.accountScope ||
      submission.operationKey !== message.operationKey ||
      !sameDispatchScope(submission.scope, message.event.accountScope) ||
      submission.caseId !== message.event.caseId ||
      submission.conversationId !== message.event.conversationId ||
      submission.message.receiptId !== message.receipt.receiptId ||
      submission.message.eventId !== message.event.eventId ||
      submission.message.messageId !== message.event.messageId ||
      submission.message.senderId !== message.event.senderId ||
      submission.message.body !== message.event.body
    )
      throw new ChannelError('OperationConflict');
  }
  #result(row: Row, status: DispatchStepResult['status']): DispatchStepResult {
    if (status === 'dispatched')
      return Object.freeze({
        status,
        receiptId: String(row.receipt_id),
        operationKey: String(row.operation_key),
        externalReceiptId: dispatchUuid(row.external_receipt_id),
        reconciled: true,
      });
    return Object.freeze({
      status,
      receiptId: String(row.receipt_id),
      operationKey: String(row.operation_key),
    });
  }
  async claim(
    token: string,
    receiptId: string,
    kind: 'dispatch' | 'reconcile',
  ): Promise<ClaimOutcome> {
    const account = this.#account(token);
    dispatchUuid(receiptId);
    return this.#tx(true, async (client, bounds) => {
      const row = await this.#row(client, account, receiptId, true),
        message = decodeStoredMessage(row);
      const association = kind === 'dispatch' ? await this.#binding(client, message) : null;
      const now = await this.#clock(client);
      if (row.state === 'dispatched') return { result: this.#result(row, 'dispatched') };
      if (row.claim_owner !== null && date(row.claim_until).getTime() > now.getTime())
        return { result: this.#result(row, 'busy') };
      if (row.claim_owner !== null) {
        if (row.claim_kind === 'dispatch')
          await client.query(
            `UPDATE ${this.#q('dispatch_attempts')} SET finished_at=$3,disposition='lease_expired' WHERE receipt_id=$1 AND epoch=$2 AND disposition='started'`,
            [receiptId, row.claim_epoch, now],
          );
        await client.query(
          `UPDATE ${this.#q('processing_intents')} SET claim_owner=NULL,claim_until=NULL,claim_kind=NULL,state=CASE WHEN possible_external THEN 'uncertain' WHEN attempt_count>=$2 THEN 'exhausted' ELSE 'pending' END,last_code='claim_lost' WHERE receipt_id=$1`,
          [receiptId, bounds.maxAttempts],
        );
      }
      if (kind === 'reconcile' && !row.possible_external)
        return { result: this.#result(row, 'not_needed') };
      if (kind === 'dispatch' && !association) {
        const state = row.possible_external ? 'uncertain' : 'blocked';
        await client.query(
          `UPDATE ${this.#q('processing_intents')} SET state=$2,last_code='association_required' WHERE receipt_id=$1`,
          [receiptId, state],
        );
        return { result: this.#result(row, row.possible_external ? 'uncertain' : 'blocked') };
      }
      if (kind === 'dispatch' && (row.attempt_count as number) >= bounds.maxAttempts) {
        const state = row.possible_external ? 'uncertain' : 'exhausted';
        await client.query(
          `UPDATE ${this.#q('processing_intents')} SET state=$2 WHERE receipt_id=$1`,
          [receiptId, state],
        );
        return { result: this.#result(row, state) };
      }
      if (row.next_attempt_at !== null && date(row.next_attempt_at).getTime() > now.getTime())
        return { result: this.#result(row, 'not_due') };
      const count = await client.query(
        `SELECT count(*)::integer AS active FROM ${this.#q('processing_intents')} WHERE claim_owner IS NOT NULL AND claim_until>$1`,
        [now],
      );
      if (count.rows[0]?.active >= bounds.maxActive) throw new ChannelError('Overloaded');
      const epoch = (BigInt(bigint(row.claim_epoch)) + 1n).toString(),
        ownerId = randomUUID(),
        until = new Date(now.getTime() + bounds.leaseMs);
      const state = row.possible_external ? 'uncertain' : 'running';
      await client.query(
        `UPDATE ${this.#q('processing_intents')} SET state=$2,claim_epoch=$3,claim_owner=$4,claim_until=$5,claim_kind=$6,attempt_count=attempt_count+$7,last_code='none' WHERE receipt_id=$1`,
        [receiptId, state, epoch, ownerId, until, kind, kind === 'dispatch' ? 1 : 0],
      );
      if (kind === 'dispatch')
        await client.query(
          `INSERT INTO ${this.#q('dispatch_attempts')}(receipt_id,epoch,owner_id,started_at,disposition) VALUES($1,$2,$3,$4,'started')`,
          [receiptId, epoch, ownerId, now],
        );
      const prepared = await this.#prepared(client, row);
      if (kind === 'reconcile' && !prepared) throw new ChannelError('SchemaMismatch');
      return {
        claim: Object.freeze({
          receiptId,
          operationKey: message.operationKey,
          ownerId,
          epoch,
          kind,
          message,
          prepared,
          possibleExternal: row.possible_external as boolean,
        }),
      };
    });
  }
  #guard(row: Row, claim: DispatchClaim, now: Date): void {
    if (
      row.claim_owner !== claim.ownerId ||
      bigint(row.claim_epoch) !== claim.epoch ||
      row.claim_kind !== claim.kind ||
      row.claim_until === null ||
      date(row.claim_until).getTime() <= now.getTime()
    )
      throw new ChannelError('DispatchClaimLost');
  }
  async prepare(
    token: string,
    claim: DispatchClaim,
    prepared: PreparedDispatch,
  ): Promise<PreparedDispatch | null> {
    const account = this.#account(token);
    return this.#tx(true, async (client) => {
      const row = await this.#row(client, account, claim.receiptId, true),
        association = await this.#binding(client, decodeStoredMessage(row)),
        now = await this.#clock(client);
      this.#guard(row, claim, now);
      if (!association) {
        await this.#fail(client, row, claim, now, 'association_required', null);
        return null;
      }
      this.#samePrepared(row, prepared);
      const original = await this.#prepared(client, row);
      if (original) {
        if (original.canonicalPayload !== prepared.canonicalPayload)
          throw new ChannelError('OperationConflict');
        return original;
      }
      await client.query(
        `INSERT INTO ${this.#q('dispatch_plans')}(receipt_id,operation_key,payload_json,payload_digest,prepared_at,association_epoch) VALUES($1,$2,$3,$4,$5,$6)`,
        [
          claim.receiptId,
          claim.operationKey,
          prepared.canonicalPayload,
          prepared.payloadDigest,
          now,
          association,
        ],
      );
      return prepared;
    });
  }
  async reserve(token: string, claim: DispatchClaim): Promise<boolean> {
    const account = this.#account(token);
    return this.#tx(true, async (client) => {
      const row = await this.#row(client, account, claim.receiptId, true),
        association = await this.#binding(client, decodeStoredMessage(row)),
        now = await this.#clock(client);
      this.#guard(row, claim, now);
      if (!association) {
        await this.#fail(client, row, claim, now, 'association_required', null);
        return false;
      }
      if (!(await this.#prepared(client, row))) throw new ChannelError('SchemaMismatch');
      await client.query(
        `UPDATE ${this.#q('processing_intents')} SET possible_external=true,state='uncertain' WHERE receipt_id=$1`,
        [claim.receiptId],
      );
      return true;
    });
  }
  async finish(token: string, claim: DispatchClaim, receipt: OperationReceipt): Promise<void> {
    const account = this.#account(token);
    await this.#tx(true, async (client) => {
      const row = await this.#row(client, account, claim.receiptId, true),
        now = await this.#clock(client);
      this.#guard(row, claim, now);
      const prepared = await this.#prepared(client, row);
      if (
        !prepared ||
        receipt.operationKey !== prepared.submission.operationKey ||
        receipt.payloadDigest !== prepared.payloadDigest ||
        !sameDispatchScope(receipt.scope, prepared.submission.scope)
      )
        throw new ChannelError('OperationConflict');
      dispatchUuid(receipt.receiptId);
      await client.query(
        `UPDATE ${this.#q('processing_intents')} SET state='dispatched',possible_external=true,external_receipt_id=$2,claim_owner=NULL,claim_until=NULL,claim_kind=NULL,next_attempt_at=NULL,last_code='accepted' WHERE receipt_id=$1`,
        [claim.receiptId, receipt.receiptId],
      );
      if (claim.kind === 'dispatch')
        await client.query(
          `UPDATE ${this.#q('dispatch_attempts')} SET finished_at=$3,disposition='accepted' WHERE receipt_id=$1 AND epoch=$2 AND disposition='started'`,
          [claim.receiptId, claim.epoch, now],
        );
    });
  }
  async #fail(
    client: PoolClient,
    row: Row,
    claim: DispatchClaim,
    now: Date,
    code:
      | 'timeout'
      | 'adapter_unavailable'
      | 'adapter_invalid'
      | 'association_required'
      | 'operation_conflict'
      | 'lookup_absent',
    retry: number | null,
  ): Promise<void> {
    const state = row.possible_external
      ? 'uncertain'
      : code === 'association_required'
        ? 'blocked'
        : retry === null
          ? 'exhausted'
          : 'pending';
    await client.query(
      `UPDATE ${this.#q('processing_intents')} SET state=$2,claim_owner=NULL,claim_until=NULL,claim_kind=NULL,next_attempt_at=$3,last_code=$4 WHERE receipt_id=$1`,
      [
        claim.receiptId,
        state,
        retry === null ? null : new Date(now.getTime() + retry),
        code === 'timeout' ? 'adapter_unavailable' : code,
      ],
    );
    if (claim.kind === 'dispatch')
      await client.query(
        `UPDATE ${this.#q('dispatch_attempts')} SET finished_at=$3,disposition=$4 WHERE receipt_id=$1 AND epoch=$2 AND disposition='started'`,
        [
          claim.receiptId,
          claim.epoch,
          now,
          code === 'lookup_absent' ? 'adapter_unavailable' : code,
        ],
      );
  }
  async fail(
    token: string,
    claim: DispatchClaim,
    code:
      | 'timeout'
      | 'adapter_unavailable'
      | 'adapter_invalid'
      | 'operation_conflict'
      | 'lookup_absent',
  ): Promise<void> {
    const account = this.#account(token);
    await this.#tx(true, async (client, bounds) => {
      const row = await this.#row(client, account, claim.receiptId, true),
        now = await this.#clock(client);
      this.#guard(row, claim, now);
      await this.#fail(
        client,
        row,
        claim,
        now,
        code,
        (row.attempt_count as number) >= bounds.maxAttempts && claim.kind === 'dispatch'
          ? null
          : bounds.retryDelayMs,
      );
    });
  }
  /** Bounded persisted eligibility observation; claim() revalidates all authority.
   * Possible-external input held for a missing association waits for an explicit step or reconcile.
   */
  async eligible(token: string, limit = 4): Promise<readonly string[]> {
    const account = this.#account(token);
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 16)
      throw new ChannelError('AccessDenied');
    return this.#tx(false, async (client, bounds) => {
      const now = await this.#clock(client),
        p = this.#integration.providerScope;
      const found = await client.query(
        `SELECT i.receipt_id::text FROM ${this.#q('inbox')} i JOIN ${this.#q('processing_intents')} d USING(receipt_id) WHERE i.tenant_id=$1 AND i.provider=$2 AND i.provider_account_id=$3 AND i.account_id=$4 AND i.conversation_id=$5 AND d.state IN ('pending','running','uncertain') AND NOT (d.state='uncertain' AND d.last_code='association_required') AND d.attempt_count<$6 AND (d.claim_owner IS NULL OR d.claim_until<=$7) AND (d.next_attempt_at IS NULL OR d.next_attempt_at<=$7) ORDER BY i.acceptance_sequence LIMIT $8`,
        [
          p.tenantId,
          p.provider,
          p.providerAccountId,
          account.accountId,
          account.conversationId,
          bounds.maxAttempts,
          now,
          limit,
        ],
      );
      return Object.freeze(found.rows.map((row) => dispatchUuid(row.receipt_id)));
    });
  }
  /** Read retained original bytes; account access grants no new dispatch authority. */
  async readPrepared(token: string, receiptId: string): Promise<PreparedDispatch | null> {
    const account = this.#account(token);
    dispatchUuid(receiptId);
    return this.#tx(false, async (client) => {
      const row = await this.#row(client, account, receiptId, false);
      return this.#prepared(client, row);
    });
  }
  async inspect(token: string, receiptId: string): Promise<DispatchObservation> {
    const account = this.#account(token);
    dispatchUuid(receiptId);
    return this.#tx(false, async (client, bounds) => {
      const row = await this.#row(client, account, receiptId, false);
      const history = await client.query(
        `SELECT epoch::text,started_at,finished_at,disposition FROM ${this.#q('dispatch_attempts')} WHERE receipt_id=$1 ORDER BY epoch LIMIT $2`,
        [receiptId, bounds.maxAttempts],
      );
      return Object.freeze({
        receiptId,
        operationKey: String(row.operation_key),
        state: decodeStoredMessage(row).processingState,
        epoch: bigint(row.claim_epoch),
        attempts: row.attempt_count as number,
        possibleExternal: row.possible_external as boolean,
        externalReceiptId:
          row.external_receipt_id === null ? null : dispatchUuid(row.external_receipt_id),
        nextAttemptAt:
          row.next_attempt_at === null ? null : date(row.next_attempt_at).toISOString(),
        lastCode: String(row.last_code),
        history: Object.freeze(
          history.rows.map((item) =>
            Object.freeze({
              epoch: bigint(item.epoch),
              startedAt: date(item.started_at).toISOString(),
              finishedAt: item.finished_at === null ? null : date(item.finished_at).toISOString(),
              disposition: String(item.disposition),
            }),
          ),
        ),
      });
    });
  }
  close(): Promise<void> {
    if (this.#closed) return this.#closed;
    this.#closing = true;
    if (!this.#ending) {
      const idle =
        this.#active === 0
          ? Promise.resolve()
          : new Promise<void>((done) => {
              this.#idle = done;
            });
      this.#ending = Promise.all([this.#pool.end(), idle]);
    }
    const closed = this.#closeOwned(this.#ending);
    this.#closed = closed;
    void closed.catch(() => {
      this.#closed = undefined;
    });
    return closed;
  }
  async #closeOwned(ending: Promise<unknown>): Promise<void> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = performance.now() + 6000;
    try {
      await Promise.race([
        ending,
        new Promise<never>((_done, reject) => {
          timer = setTimeout(() => reject(new ChannelError('CleanupIncomplete')), 6000);
        }),
      ]);
      if (performance.now() >= deadline) throw new ChannelError('CleanupIncomplete');
    } catch {
      throw new ChannelError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
