/** Verified, bounded local inbox. No agent, provider send, or business action runs here. */
import { createHash, randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import type { Pool, PoolClient } from 'pg';
import {
  ChannelError,
  PgPool,
  watchPool,
  config,
  identifier,
  settings,
  table,
  validate,
} from './database.js';
import type { ChannelLimits, DatabaseSettings, ProcessingState } from './public-types.js';
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
import { authenticateFakeSms, WebhookError } from './security.js';
import type { FakeSmsIntegration, WebhookHeaders } from './security.js';
import { produceTextEvent } from './index.js';
import { NativeStore } from './native-store.js';
import { registerRehydrationInbox } from './rehydration-access.js';
import { CommunicationStore } from './communication-store.js';
import {
  hasCommunicationIntegration,
  communicationConfig,
  communicationFields,
  responseAnchor,
  sdkObservation,
  browserObservation,
  type CommunicationIntegration,
  type ResponseAnchor,
  type SdkObservation,
  type BrowserObservation,
} from './communication-types.js';
import {
  isNativeIntegration,
  nativeConfig,
  publication,
  nativeInput,
  nativeUuid,
  nativeToken,
  type NativeIntegration,
  type NativePublication,
  type NativeInput,
  type NativeBindingReceipt,
  type NativeAcceptance,
} from './native-types.js';
import { decodeReceipt, decodeStoredMessage } from './postgres-records.js';
import type { ChannelEvent } from './index.js';
export { ChannelError } from './public-types.js';
export type { ChannelLimits, DatabaseSettings } from './public-types.js';
export type AccountSeed = Readonly<{
  token: string;
  tenantId: string;
  accountId: string;
  conversationId: string;
  caseId?: string;
}>;
type Account = Omit<AccountSeed, 'token'>;
function hash(value: string): string {
  return createHash('sha256').update(value).digest('hex');
}
function token(value: unknown): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{32,128}(?![\s\S])/.test(value))
    throw new ChannelError('AccessDenied');
  return value;
}
/** Seeded authenticated account service, not a claim of real carrier/customer verification. */
export class SeededAccounts {
  #entries = new Map<string, Account>();
  constructor(entries: readonly AccountSeed[]) {
    if (!Array.isArray(entries) || !entries.length || entries.length > 64)
      throw new ChannelError('AccessDenied');
    for (const item of entries) {
      const key = hash(token(item.token));
      if (this.#entries.has(key)) throw new ChannelError('AccessDenied');
      const account = {
        tenantId: identifier(item.tenantId),
        accountId: identifier(item.accountId),
        conversationId: identifier(item.conversationId),
        ...(item.caseId === undefined ? {} : { caseId: identifier(item.caseId) }),
      };
      this.#entries.set(key, Object.freeze(account));
    }
  }
  authenticate(raw: string, tenant: string): Account {
    const result = this.#entries.get(hash(token(raw)));
    if (!result || result.tenantId !== tenant) throw new ChannelError('AccessDenied');
    return result;
  }
}
export type DurableReceipt = Readonly<{
  receiptId: string;
  eventId: string;
  messageId: string;
  acceptanceSequence: string;
  acceptedAt: string;
}>;
export type StoredMessage = Readonly<{
  receipt: DurableReceipt;
  event: ChannelEvent;
  operationKey: string;
  processingState: ProcessingState;
  associationVersion: string;
}>;
export type InboxHooks = Readonly<{
  beforeAcceptCommit?: () => void | Promise<void>;
  afterAcceptCommit?: () => void | Promise<void>;
  afterCommunicationCommit?: () => void | Promise<void>;
}>;
type Operation =
  | 'challenge'
  | 'associate'
  | 'revoke'
  | 'accept'
  | 'inspect'
  | 'history'
  | 'inspect_confirmation'
  | 'communication'
  | 'rehydration'
  | 'pool'
  | 'close';
export type InboxEvent = Readonly<{
  event: 'completed' | 'rejected' | 'dependency_failure' | 'closed';
  operation: Operation;
  code: string;
}>;
export type InboxObserver = (event: InboxEvent) => void | Promise<void>;
function safeObserver(event: InboxEvent): void {
  const line = JSON.stringify({ component: 'channel_inbox', ...event });
  if (event.event === 'dependency_failure') console.error(line);
  else console.info(line);
}
type Tx = Readonly<{
  client: PoolClient;
  now: Date;
  bounds: ChannelLimits;
  guard: Record<string, number>;
  onCommit: (action: () => void) => void;
}>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/;
function iso(value: unknown): string {
  if (!(value instanceof Date) || !Number.isFinite(value.getTime()))
    throw new ChannelError('SchemaMismatch');
  return value.toISOString();
}
function cursor(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !/^(0|[1-9][0-9]{0,18})(?![\s\S])/.test(value) ||
    BigInt(value) > 9223372036854775807n
  )
    throw new ChannelError('AccessDenied');
  return value;
}
/** Rejects forged webhook bytes before a connection or the admission lock is taken. The
 * signed timestamp stands in for the clock, so only the MAC and payload are checked; the
 * transaction still enforces freshness with database time. A descriptor read never runs
 * caller getters. */
function rejectForged(
  raw: Uint8Array,
  headers: WebhookHeaders,
  integration: FakeSmsIntegration,
): void {
  let signed: unknown;
  try {
    signed = Object.getOwnPropertyDescriptor(headers, 'timestamp')?.value;
  } catch {
    signed = undefined;
  }
  authenticateFakeSms(
    raw,
    headers,
    integration,
    typeof signed === 'string' ? Number(signed) : Number.NaN,
  );
}

export class ChannelInbox {
  #value: DatabaseSettings;
  #pool: Pool;
  #integration: FakeSmsIntegration;
  #accounts: SeededAccounts;
  #native: NativeStore | undefined;
  #communication: CommunicationStore | undefined;
  #ordinaryNotifications = 0;
  #ordinaryObserverDropped = 0;
  #ordinaryObserverFailures = 0;
  #communicationNotifications = 0;
  #communicationObserverDropped = 0;
  #hooks: InboxHooks;
  #observer: InboxObserver;
  #active = 0;
  #closing = false;
  #closePromise: Promise<void> | undefined;
  #onIdle: (() => void) | undefined;
  #counts = {
    accepted: 0,
    replayed: 0,
    rejected: 0,
    dependencyErrors: 0,
    overloaded: 0,
    telemetryFailures: 0,
  };
  constructor(
    input: DatabaseSettings,
    integration: FakeSmsIntegration,
    accounts: SeededAccounts,
    hooks: InboxHooks = {},
    observer: InboxObserver = safeObserver,
  ) {
    this.#value = settings(input, 'livekit_lab');
    this.#integration = integration;
    this.#accounts = accounts;
    if (isNativeIntegration(integration)) {
      const configured = nativeConfig(integration);
      for (const publisher of configured.rawPublishers) {
        let account = false;
        try {
          accounts.authenticate(publisher.token, configured.providerScope.tenantId);
          account = true;
        } catch {
          /*distinct publisher*/
        }
        if (account) throw new ChannelError('InvalidConfiguration');
      }
      this.#native = new NativeStore(this.#value.schema, integration as NativeIntegration);
      if (hasCommunicationIntegration(integration)) {
        const configuredCommunication = communicationConfig(integration);
        for (const token of configuredCommunication.rawTokens) {
          try {
            accounts.authenticate(token, configured.providerScope.tenantId);
          } catch {
            continue;
          }
          throw new ChannelError('InvalidConfiguration');
        }
        this.#communication = new CommunicationStore(
          this.#value.schema,
          integration as CommunicationIntegration,
          this.#native,
        );
      }
    }
    this.#hooks = Object.freeze({ ...hooks });
    this.#observer = observer;
    if (
      !(accounts instanceof SeededAccounts) ||
      !integration?.providerScope ||
      typeof observer !== 'function'
    )
      throw new ChannelError('AccessDenied');
    this.#pool = watchPool(new PgPool(config(this.#value)));
    this.#pool.on('error', () => {
      this.#counts.dependencyErrors++;
      this.#emit({ event: 'dependency_failure', operation: 'pool', code: 'StorageUnavailable' });
    });
    if (this.#native)
      registerRehydrationInbox(
        this,
        Object.freeze({
          schema: this.#value.schema,
          databaseIdentity: JSON.stringify([
            this.#value.host,
            this.#value.port,
            this.#value.database,
            this.#value.schema,
          ]),
          native: this.#native,
          communication:
            this.#communication ??
            new CommunicationStore(this.#value.schema, undefined, this.#native),
          transaction: <T>(protectedCheck: boolean, action: (tx: Tx) => Promise<T>) =>
            this.#transaction('rehydration', protectedCheck, action),
        }),
      );
  }
  #q(name: string): string {
    return table(this.#value.schema, name);
  }
  #scope(sender?: string): string[] {
    const p = this.#integration.providerScope;
    return [p.tenantId, p.provider, p.providerAccountId, ...(sender === undefined ? [] : [sender])];
  }
  #account(raw: string): Account {
    return this.#accounts.authenticate(raw, this.#integration.providerScope.tenantId);
  }
  #emit(event: InboxEvent): void {
    const communication = event.operation === 'communication';
    const pending = communication ? this.#communicationNotifications : this.#ordinaryNotifications;
    if (pending >= 8) {
      if (communication) this.#communicationObserverDropped++;
      else
        this.#ordinaryObserverDropped = Math.min(
          Number.MAX_SAFE_INTEGER,
          this.#ordinaryObserverDropped + 1,
        );
      return;
    }
    // Reserve before invoking caller code, including a synchronous/reentrant sink.
    if (communication) this.#communicationNotifications++;
    else this.#ordinaryNotifications++;
    const settled = () => {
      if (communication) this.#communicationNotifications--;
      else this.#ordinaryNotifications--;
    };
    const failed = () => {
      if (communication) this.#communication?.telemetryFailure();
      else
        this.#ordinaryObserverFailures = Math.min(
          Number.MAX_SAFE_INTEGER,
          this.#ordinaryObserverFailures + 1,
        );
      this.#counts.telemetryFailures++;
    };
    try {
      const emitted = this.#observer(Object.freeze(event));
      if (emitted === undefined) settled();
      else void Promise.resolve(emitted).catch(failed).finally(settled);
    } catch {
      failed();
      settled();
    }
  }
  /** Ordinary observer callbacks only; communication retains its existing separate metrics.
   * Callback promises remain visible after SQL close. The caller owns any observer transport.
   */
  telemetryMetrics(): Readonly<{
    observerPending: number;
    observerDropped: number;
    observerFailures: number;
  }> {
    return Object.freeze({
      observerPending: this.#ordinaryNotifications,
      observerDropped: this.#ordinaryObserverDropped,
      observerFailures: this.#ordinaryObserverFailures,
    });
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({ ...this.#counts, active: this.#active });
  }
  async #transaction<T>(
    operation: Operation,
    write: boolean,
    action: (tx: Tx) => Promise<T>,
    reportCompleted = true,
    precheck?: () => void,
  ): Promise<T> {
    if (this.#closing) throw new ChannelError('StorageUnavailable');
    if (this.#active >= 4) {
      this.#counts.overloaded++;
      throw new ChannelError('Overloaded');
    }
    this.#active++;
    let client: PoolClient | undefined;
    let committed = false;
    let commitStarted = false;
    let broken = false;
    try {
      precheck?.();
      client = await this.#pool.connect();
      await client.query(
        ['communication', 'rehydration'].includes(operation) && !write
          ? 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY'
          : 'BEGIN',
      );
      const committedActions: (() => void)[] = [];
      const bounds = await validate(
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
      const guarded = write
        ? await client.query(`SELECT * FROM ${this.#q('admission')} WHERE singleton FOR UPDATE`)
        : undefined;
      if (
        write &&
        (guarded?.rowCount !== 1 ||
          ['inbox_count', 'challenge_count', 'association_count', 'sender_count'].some(
            (key) => !Number.isSafeInteger(guarded.rows[0]?.[key]) || guarded.rows[0]?.[key] < 0,
          ))
      )
        throw new ChannelError('SchemaMismatch');
      const time = await client.query('SELECT clock_timestamp() AS now');
      const now = time.rows[0]?.now as unknown;
      iso(now);
      const result = await action({
        client,
        now: now as Date,
        bounds,
        guard: (guarded?.rows[0] ?? {}) as Record<string, number>,
        onCommit: (action: () => void) => {
          committedActions.push(action);
        },
      });
      if (operation === 'accept') await this.#hooks.beforeAcceptCommit?.();
      commitStarted = true;
      await client.query('COMMIT');
      committed = true;
      for (const action of committedActions) action();
      if (operation === 'communication' && write) await this.#hooks.afterCommunicationCommit?.();
      if (operation === 'accept') await this.#hooks.afterAcceptCommit?.();
      if (reportCompleted) this.#emit({ event: 'completed', operation, code: 'ok' });
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
      this.#counts.rejected++;
      const safe =
        committed || (commitStarted && write)
          ? new ChannelError('AcknowledgementUnknown')
          : error instanceof ChannelError || error instanceof WebhookError
            ? error
            : new ChannelError('StorageUnavailable');
      if (
        safe instanceof ChannelError &&
        ['StorageUnavailable', 'AcknowledgementUnknown'].includes(safe.code)
      )
        this.#counts.dependencyErrors++;
      if (operation === 'communication') this.#communication?.failure(safe);
      this.#emit({ event: 'rejected', operation, code: safe.code });
      throw safe;
    } finally {
      try {
        client?.release(broken);
      } finally {
        this.#active--;
        if (this.#active === 0) {
          this.#onIdle?.();
          this.#onIdle = undefined;
        }
      }
    }
  }
  communicationMetrics(): Readonly<Record<string, number>> {
    return this.#communication
      ? Object.freeze({
          ...this.#communication.metrics(),
          observerPending: this.#communicationNotifications,
          observerDropped: this.#communicationObserverDropped,
        })
      : Object.freeze({});
  }
  #communicationStore() {
    if (!this.#communication) throw new ChannelError('AccessDenied');
    return this.#communication;
  }
  communicationBegin(token: string, input: ResponseAnchor) {
    const store = this.#communicationStore();
    store.authorize(token, 'publisher');
    const frozen = responseAnchor(input);
    return this.#transaction('communication', true, (tx) => store.begin(tx, token, frozen));
  }
  communicationSdk(token: string, input: SdkObservation) {
    const store = this.#communicationStore();
    store.authorize(token, 'agent_sdk');
    const frozen = sdkObservation(input);
    return this.#transaction('communication', true, (tx) =>
      store.observe(tx, token, 'agent_sdk', frozen),
    );
  }
  communicationBrowser(token: string, input: BrowserObservation) {
    const store = this.#communicationStore();
    store.authorize(token, 'browser_client');
    const frozen = browserObservation(input);
    return this.#transaction('communication', true, (tx) =>
      store.observe(tx, token, 'browser_client', frozen),
    );
  }
  communicationInspect(token: string, responseId: string) {
    const store = this.#communicationStore(),
      account = this.#account(token),
      id = nativeUuid(responseId);
    return this.#transaction('communication', false, (tx) => store.inspect(tx, account, id));
  }
  #communicationQuery(value: unknown, optional: string) {
    try {
      return Object.freeze(
        communicationFields(value, [
          'limit',
          ...(Reflect.ownKeys(value as object).includes(optional) ? [optional] : []),
        ]),
      );
    } catch {
      throw new ChannelError('InvalidEvent');
    }
  }
  communicationResponses(
    token: string,
    query: Readonly<{ limit: number; beforeSequence?: string }>,
  ) {
    const store = this.#communicationStore(),
      account = this.#account(token),
      q = this.#communicationQuery(query, 'beforeSequence') as Readonly<{
        limit: number;
        beforeSequence?: string;
      }>;
    return this.#transaction('communication', false, (tx) => store.responses(tx, account, q));
  }
  communicationObservations(
    token: string,
    id: string,
    query: Readonly<{ limit: number; afterSequence?: string }>,
  ) {
    const store = this.#communicationStore(),
      account = this.#account(token),
      responseId = nativeUuid(id),
      q = this.#communicationQuery(query, 'afterSequence') as Readonly<{
        limit: number;
        afterSequence?: string;
      }>;
    return this.#transaction('communication', false, (tx) =>
      store.observations(tx, account, responseId, q),
    );
  }
  async createChallenge(
    accountToken: string,
    senderId: string,
  ): Promise<Readonly<{ challengeId: string; secret: string; expiresAt: string }>> {
    const account = this.#account(accountToken);
    identifier(senderId);
    return this.#transaction('challenge', true, async ({ client, now, bounds, guard }) => {
      const prior = await client.query(
        `SELECT epoch::text FROM ${this.#q('sender_heads')} WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND sender_id=$4`,
        this.#scope(senderId),
      );
      if (
        guard.challenge_count! >= bounds.maxChallenges ||
        (!prior.rowCount && guard.sender_count! >= bounds.maxSenders)
      )
        throw new ChannelError('Overloaded');
      if (!prior.rowCount)
        await client.query(
          `INSERT INTO ${this.#q('sender_heads')}(tenant_id,provider,provider_account_id,sender_id) VALUES($1,$2,$3,$4)`,
          this.#scope(senderId),
        );
      const challengeId = randomUUID(),
        secret = randomBytes(32).toString('base64url'),
        expires = new Date(now.getTime() + 60000);
      await client.query(
        `INSERT INTO ${this.#q('challenges')}(challenge_id,secret_digest,tenant_id,provider,provider_account_id,sender_id,account_id,conversation_id,case_id,expected_epoch,issued_at,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
        [
          challengeId,
          hash(secret),
          ...this.#scope(senderId),
          account.accountId,
          account.conversationId,
          account.caseId ?? null,
          prior.rows[0]?.epoch ?? '0',
          now,
          expires,
        ],
      );
      await client.query(
        `UPDATE ${this.#q('admission')} SET challenge_count=challenge_count+1,sender_count=sender_count+$1 WHERE singleton`,
        [prior.rowCount ? 0 : 1],
      );
      return Object.freeze({ challengeId, secret, expiresAt: expires.toISOString() });
    });
  }
  async completeAssociation(
    raw: Uint8Array,
    headers: WebhookHeaders,
  ): Promise<Readonly<{ associationVersion: string }>> {
    const result = await this.#transaction(
      'associate',
      true,
      async ({ client, now, bounds, guard }) => {
        const observed = authenticateFakeSms(
          raw,
          headers,
          this.#integration,
          Math.floor(now.getTime() / 1000),
        );
        const match = /^LINK ([0-9a-f-]{36}) ([A-Za-z0-9_-]{43})(?![\s\S])/.exec(observed.body);
        if (!match || !UUID.test(match[1]!)) throw new ChannelError('AssociationRejected');
        const found = await client.query(
          `SELECT * FROM ${this.#q('challenges')} WHERE challenge_id=$1 AND tenant_id=$2 AND provider=$3 AND provider_account_id=$4 AND sender_id=$5 FOR UPDATE`,
          [match[1], ...this.#scope(observed.senderId)],
        );
        const row = found.rows[0];
        if (
          !row ||
          row.consumed_at ||
          row.attempts >= 3 ||
          !(row.expires_at instanceof Date) ||
          row.expires_at.getTime() <= now.getTime()
        )
          return null;
        const head = await client.query(
          `SELECT epoch::text,active_epoch::text FROM ${this.#q('sender_heads')} WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND sender_id=$4 FOR UPDATE`,
          this.#scope(observed.senderId),
        );
        if (!head.rows[0] || String(row.expected_epoch) !== head.rows[0].epoch) return null;
        const correct = timingSafeEqual(
          Buffer.from(hash(match[2]!), 'hex'),
          Buffer.from(row.secret_digest as string, 'hex'),
        );
        await client.query(
          `UPDATE ${this.#q('challenges')} SET attempts=attempts+1 WHERE challenge_id=$1`,
          [row.challenge_id],
        );
        if (!correct) return null;
        if (guard.association_count! >= bounds.maxAssociations)
          throw new ChannelError('Overloaded');
        const next = (BigInt(head.rows[0].epoch as string) + 1n).toString();
        await client.query(
          `UPDATE ${this.#q('associations')} SET revoked_at=$5 WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND sender_id=$4 AND revoked_at IS NULL`,
          [...this.#scope(observed.senderId), now],
        );
        await client.query(
          `INSERT INTO ${this.#q('associations')}(tenant_id,provider,provider_account_id,sender_id,epoch,account_id,conversation_id,case_id,activated_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
          [
            ...this.#scope(observed.senderId),
            next,
            row.account_id,
            row.conversation_id,
            row.case_id,
            now,
          ],
        );
        await client.query(
          `UPDATE ${this.#q('sender_heads')} SET epoch=$5,active_epoch=$5 WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND sender_id=$4`,
          [...this.#scope(observed.senderId), next],
        );
        await client.query(
          `INSERT INTO ${this.#q('conversations')}(tenant_id,account_id,conversation_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING`,
          [row.tenant_id, row.account_id, row.conversation_id],
        );
        await client.query(
          `UPDATE ${this.#q('challenges')} SET consumed_at=$2 WHERE challenge_id=$1`,
          [row.challenge_id, now],
        );
        await client.query(
          `UPDATE ${this.#q('admission')} SET association_count=association_count+1 WHERE singleton`,
        );
        return Object.freeze({ associationVersion: next });
      },
      false,
      () => rejectForged(raw, headers, this.#integration),
    );
    if (!result) {
      this.#counts.rejected++;
      this.#emit({ event: 'rejected', operation: 'associate', code: 'AssociationRejected' });
      throw new ChannelError('AssociationRejected');
    }
    this.#emit({ event: 'completed', operation: 'associate', code: 'ok' });
    return result;
  }
  async revokeAssociation(
    accountToken: string,
    senderId: string,
  ): Promise<Readonly<{ revoked: boolean; associationVersion: string }>> {
    const account = this.#account(accountToken);
    identifier(senderId);
    return this.#transaction('revoke', true, async ({ client, now }) => {
      const current = await client.query(
        `SELECT h.epoch::text,h.active_epoch::text,a.account_id,a.conversation_id FROM ${this.#q('sender_heads')} h LEFT JOIN ${this.#q('associations')} a ON a.tenant_id=h.tenant_id AND a.provider=h.provider AND a.provider_account_id=h.provider_account_id AND a.sender_id=h.sender_id AND a.epoch=h.active_epoch WHERE h.tenant_id=$1 AND h.provider=$2 AND h.provider_account_id=$3 AND h.sender_id=$4`,
        this.#scope(senderId),
      );
      const row = current.rows[0];
      if (row && row.active_epoch === null) {
        const last = await client.query(
          `SELECT account_id,conversation_id FROM ${this.#q('associations')} WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND sender_id=$4 ORDER BY epoch DESC LIMIT 1`,
          this.#scope(senderId),
        );
        if (
          last.rows[0]?.account_id === account.accountId &&
          last.rows[0]?.conversation_id === account.conversationId
        )
          return Object.freeze({ revoked: false, associationVersion: row.epoch as string });
      }
      if (
        !row ||
        row.account_id !== account.accountId ||
        row.conversation_id !== account.conversationId
      )
        throw new ChannelError('AccessDenied');
      const next = (BigInt(row.epoch as string) + 1n).toString();
      await client.query(
        `UPDATE ${this.#q('associations')} SET revoked_at=$5 WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND sender_id=$4 AND epoch=$6`,
        [...this.#scope(senderId), now, row.active_epoch],
      );
      await client.query(
        `UPDATE ${this.#q('sender_heads')} SET epoch=$5,active_epoch=NULL WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND sender_id=$4`,
        [...this.#scope(senderId), next],
      );
      return Object.freeze({ revoked: true, associationVersion: next });
    });
  }
  async bindNative(
    publisherToken: string,
    input: NativePublication,
  ): Promise<NativeBindingReceipt> {
    if (!this.#native) throw new ChannelError('AccessDenied');
    const publisher = nativeToken(publisherToken);
    const copied = publication(input);
    let account = false;
    try {
      this.#accounts.authenticate(copied.bearer, this.#integration.providerScope.tenantId);
      account = true;
    } catch {
      /*native bearer is not an account credential*/
    }
    if (account) throw new ChannelError('AccessDenied');
    return this.#transaction('associate', true, (tx) => this.#native!.bind(tx, publisher, copied));
  }
  revokeNative(
    publisherToken: string,
    bindingId: string,
  ): Promise<Readonly<{ bindingId: string; revokedAt: string }>> {
    if (!this.#native) throw new ChannelError('AccessDenied');
    const id = nativeUuid(bindingId),
      publisher = nativeToken(publisherToken);
    return this.#transaction('revoke', true, (tx) => this.#native!.revoke(tx, publisher, id));
  }
  async acceptNative(bearer: string, input: NativeInput): Promise<NativeAcceptance> {
    if (!this.#native) throw new ChannelError('AccessDenied');
    const key = nativeToken(bearer),
      copied = nativeInput(input);
    const result = await this.#transaction('accept', true, (tx) =>
      this.#native!.accept(tx, key, copied),
    );
    this.#counts[result.status === 'replayed' ? 'replayed' : 'accepted']++;
    return result;
  }
  async acceptSms(
    raw: Uint8Array,
    headers: WebhookHeaders,
  ): Promise<Readonly<{ receipt: DurableReceipt; replayed: boolean }>> {
    const result = await this.#transaction(
      'accept',
      true,
      async ({ client, now, bounds, guard }) => {
        const observed = authenticateFakeSms(
          raw,
          headers,
          this.#integration,
          Math.floor(now.getTime() / 1000),
        );
        if (observed.body.startsWith('LINK ')) throw new ChannelError('AssociationRejected');
        const associated = await client.query(
          `SELECT a.* FROM ${this.#q('sender_heads')} h JOIN ${this.#q('associations')} a ON a.tenant_id=h.tenant_id AND a.provider=h.provider AND a.provider_account_id=h.provider_account_id AND a.sender_id=h.sender_id AND a.epoch=h.active_epoch WHERE h.tenant_id=$1 AND h.provider=$2 AND h.provider_account_id=$3 AND h.sender_id=$4 AND a.revoked_at IS NULL`,
          this.#scope(observed.senderId),
        );
        const binding = associated.rows[0];
        if (!binding) throw new ChannelError('AssociationRequired');
        const normalized = produceTextEvent(
          {
            eventId: observed.eventId,
            providerScope: { ...observed.providerScope },
            accountScope: {
              tenantId: binding.tenant_id as string,
              accountId: binding.account_id as string,
            },
            conversationId: binding.conversation_id as string,
            ...(binding.case_id === null ? {} : { caseId: binding.case_id as string }),
            receivedAt: now.toISOString(),
            occurredAt: observed.occurredAt,
            channel: 'sms',
            messageId: observed.messageId,
            senderId: observed.senderId,
            body: observed.body,
          },
          {
            providerScope: observed.providerScope,
            accountScope: {
              tenantId: binding.tenant_id as string,
              accountId: binding.account_id as string,
            },
          },
        );
        const existing = await client.query(
          `SELECT i.*,p.operation_key,p.state FROM ${this.#q('inbox')} i LEFT JOIN ${this.#q('processing_intents')} p USING(receipt_id) WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND event_id=$4`,
          [...this.#scope(), observed.eventId],
        );
        const original = existing.rows[0];
        if (original) {
          if (
            original.account_id !== binding.account_id ||
            original.conversation_id !== binding.conversation_id
          )
            throw new ChannelError('AccessDenied');
          if (original.canonical_payload !== normalized.canonical)
            throw new ChannelError('IdentityConflict');
          return Object.freeze({ receipt: decodeStoredMessage(original).receipt, replayed: true });
        }
        if (guard.inbox_count! >= bounds.maxInbox) throw new ChannelError('Overloaded');
        const sequence = await client.query(
          `UPDATE ${this.#q('conversations')} SET last_sequence=last_sequence+1 WHERE tenant_id=$1 AND account_id=$2 AND conversation_id=$3 RETURNING last_sequence::text`,
          [binding.tenant_id, binding.account_id, binding.conversation_id],
        );
        if (sequence.rowCount !== 1) throw new ChannelError('SchemaMismatch');
        const id = randomUUID();
        const inserted = await client.query(
          `INSERT INTO ${this.#q('inbox')}(receipt_id,tenant_id,provider,provider_account_id,event_id,message_id,account_id,conversation_id,association_epoch,canonical_payload,wire_json,acceptance_sequence,accepted_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING *`,
          [
            id,
            ...this.#scope(),
            observed.eventId,
            observed.messageId,
            binding.account_id,
            binding.conversation_id,
            String(binding.epoch),
            normalized.canonical,
            normalized.wireJson,
            sequence.rows[0].last_sequence,
            now,
          ],
        );
        await client.query(
          `INSERT INTO ${this.#q('processing_intents')}(receipt_id,operation_key,state) VALUES($1,$2,'pending')`,
          [id, randomUUID()],
        );
        await client.query(
          `UPDATE ${this.#q('admission')} SET inbox_count=inbox_count+1 WHERE singleton`,
        );
        return Object.freeze({ receipt: decodeReceipt(inserted.rows[0]!), replayed: false });
      },
      true,
      () => rejectForged(raw, headers, this.#integration),
    );
    this.#counts[result.replayed ? 'replayed' : 'accepted']++;
    return result;
  }
  async inspect(accountToken: string, receiptId: string): Promise<StoredMessage> {
    const account = this.#account(accountToken);
    if (typeof receiptId !== 'string' || !UUID.test(receiptId)) throw new ChannelError('NotFound');
    return this.#transaction('inspect', false, async ({ client }) => {
      const result = await client.query(
        `SELECT i.*,p.operation_key,p.state FROM ${this.#q('inbox')} i LEFT JOIN ${this.#q('processing_intents')} p USING(receipt_id) WHERE i.receipt_id=$1 AND tenant_id=$2 AND account_id=$3 AND conversation_id=$4`,
        [receiptId, account.tenantId, account.accountId, account.conversationId],
      );
      if (result.rowCount !== 1) throw new ChannelError('NotFound');
      return decodeStoredMessage(result.rows[0]!);
    });
  }
  /** Current original sender/association preflight only; no cross-authority commit fence. */
  async inspectForConfirmation(accountToken: string, receiptId: string): Promise<StoredMessage> {
    const account = this.#account(accountToken);
    if (typeof receiptId !== 'string' || !UUID.test(receiptId)) throw new ChannelError('NotFound');
    return this.#transaction('inspect_confirmation', false, async ({ client }) => {
      const result = await client.query(
        `SELECT i.*,p.operation_key,p.state FROM ${this.#q('inbox')} i LEFT JOIN ${this.#q('processing_intents')} p USING(receipt_id) WHERE i.receipt_id=$1 AND tenant_id=$2 AND account_id=$3 AND conversation_id=$4`,
        [receiptId, account.tenantId, account.accountId, account.conversationId],
      );
      if (result.rowCount !== 1) throw new ChannelError('AccessDenied');
      const message = decodeStoredMessage(result.rows[0]!);
      const event = message.event,
        provider = this.#integration.providerScope;
      if (
        event.type !== 'text.received' ||
        event.providerScope.tenantId !== provider.tenantId ||
        event.providerScope.provider !== provider.provider ||
        event.providerScope.providerAccountId !== provider.providerAccountId ||
        event.caseId !== account.caseId
      )
        throw new ChannelError('AccessDenied');
      const current = await client.query(
        `SELECT a.epoch FROM ${this.#q('sender_heads')} h JOIN ${this.#q('associations')} a ON a.tenant_id=h.tenant_id AND a.provider=h.provider AND a.provider_account_id=h.provider_account_id AND a.sender_id=h.sender_id AND a.epoch=h.active_epoch WHERE h.tenant_id=$1 AND h.provider=$2 AND h.provider_account_id=$3 AND h.sender_id=$4 AND a.epoch=$5 AND a.account_id=$6 AND a.conversation_id=$7 AND a.case_id=$8 AND a.revoked_at IS NULL`,
        [
          provider.tenantId,
          provider.provider,
          provider.providerAccountId,
          event.senderId,
          message.associationVersion,
          account.accountId,
          account.conversationId,
          account.caseId,
        ],
      );
      if (current.rowCount !== 1) throw new ChannelError('AccessDenied');
      return message;
    });
  }
  async history(
    accountToken: string,
    options: Readonly<{ after?: string; limit?: number }> = {},
  ): Promise<Readonly<{ messages: readonly StoredMessage[]; nextCursor?: string }>> {
    const account = this.#account(accountToken),
      after = cursor(options.after ?? '0'),
      limit = options.limit ?? 25;
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100)
      throw new ChannelError('AccessDenied');
    return this.#transaction('history', false, async ({ client }) => {
      const result = await client.query(
        `SELECT i.*,p.operation_key,p.state FROM ${this.#q('inbox')} i LEFT JOIN ${this.#q('processing_intents')} p USING(receipt_id) WHERE tenant_id=$1 AND account_id=$2 AND conversation_id=$3 AND acceptance_sequence>$4 ORDER BY acceptance_sequence LIMIT $5`,
        [account.tenantId, account.accountId, account.conversationId, after, limit + 1],
      );
      const messages = Object.freeze(
        result.rows
          .slice(0, limit)
          .map((row) => decodeStoredMessage(row as Record<string, unknown>)),
      );
      return Object.freeze({
        messages,
        ...(result.rows.length > limit
          ? { nextCursor: messages.at(-1)!.receipt.acceptanceSequence }
          : {}),
      });
    });
  }
  close(): Promise<void> {
    if (this.#closePromise) return this.#closePromise;
    this.#closing = true;
    const idle =
      this.#active === 0
        ? Promise.resolve()
        : new Promise<void>((resolve) => {
            this.#onIdle = resolve;
          });
    this.#closePromise = this.#finishClose(idle);
    return this.#closePromise;
  }
  async #finishClose(idle: Promise<void>): Promise<void> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all([this.#pool.end(), idle]),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(() => reject(new ChannelError('CleanupIncomplete')), 6000);
        }),
      ]);
    } catch {
      throw new ChannelError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
    this.#emit({ event: 'closed', operation: 'close', code: 'ok' });
  }
}
