/** Native grants/input SQL over the existing inbox transaction. Owns no pool or queue. */
import { randomUUID } from 'node:crypto';
import type { PoolClient } from 'pg';
import { ChannelError, table } from './database.js';
import type { ChannelLimits } from './public-types.js';
import { produceTextEvent } from './index.js';
import { decodeStoredMessage } from './postgres-records.js';
import type { StoredMessage } from './postgres.js';
import {
  nativeConfig,
  nativeFields,
  nativeId,
  nativeUuid,
  nativeSha,
  nativeToken,
  nativeIso,
  nativeLimits,
  type NativeIntegration,
  type NativePublication,
  type NativeInput,
  type NativeBindingReceipt,
  type NativeAcceptance,
} from './native-types.js';
type Tx = Readonly<{
  client: PoolClient;
  now: Date;
  bounds: ChannelLimits;
  guard: Record<string, number>;
}>;
export class NativeStore {
  readonly #schema: string;
  readonly #config: ReturnType<typeof nativeConfig>;
  constructor(schema: string, integration: NativeIntegration) {
    this.#schema = schema;
    this.#config = nativeConfig(integration);
  }
  #q(name: string) {
    return table(this.#schema, name);
  }
  async #settings(tx: Tx) {
    const version = (
      await tx.client.query(`SELECT version FROM ${this.#q('schema_metadata')} WHERE singleton`)
    ).rows[0]?.version;
    if (version !== 6 && version !== 7 && version !== 8) throw new ChannelError('UpgradeRequired');
    const rows = (
      await tx.client.query(`SELECT * FROM ${this.#q('native_settings')} WHERE singleton`)
    ).rows;
    if (rows.length !== 1) throw new ChannelError('SchemaMismatch');
    let limit;
    try {
      limit = nativeLimits({ maxBindings: rows[0].max_bindings });
    } catch {
      throw new ChannelError('SchemaMismatch');
    }
    const counts = (
      await tx.client.query(
        `SELECT (SELECT count(*)::integer FROM ${this.#q('native_bindings')}) AS bindings,(SELECT count(*)::integer FROM ${this.#q('inbox')}) AS inbox`,
      )
    ).rows[0];
    if (
      !counts ||
      !Number.isSafeInteger(rows[0].binding_count) ||
      rows[0].binding_count < 0 ||
      rows[0].binding_count !== counts.bindings ||
      counts.bindings > limit.maxBindings ||
      !Number.isSafeInteger(counts.inbox) ||
      counts.inbox !== tx.guard.inbox_count ||
      counts.inbox > tx.bounds.maxInbox
    )
      throw new ChannelError('SchemaMismatch');
    return { limit, count: rows[0].binding_count as number };
  }
  #publisher(token: string) {
    const key = nativeSha(nativeToken(token)),
      grant = this.#config.publishers.find((x) => x.tokenDigest === key);
    if (!grant) throw new ChannelError('AccessDenied');
    return grant;
  }
  #canonical(
    pub: ReturnType<typeof nativeConfig>['publishers'][number],
    input: NativePublication,
  ): string {
    return JSON.stringify({
      schemaVersion: 1,
      bindingId: input.bindingId,
      providerScope: this.#config.providerScope,
      scope: pub.scope,
      caseId: pub.caseId,
      conversationId: pub.conversationId,
      roomId: input.roomId,
      participantId: input.participantId,
      expiresAt: input.expiresAt,
    });
  }
  #decode(row: Record<string, unknown>) {
    try {
      if (
        typeof row.canonical_binding !== 'string' ||
        nativeSha(row.canonical_binding) !== row.binding_digest
      )
        throw Error();
      const value = nativeFields(JSON.parse(row.canonical_binding), [
        'schemaVersion',
        'bindingId',
        'providerScope',
        'scope',
        'caseId',
        'conversationId',
        'roomId',
        'participantId',
        'expiresAt',
      ]);
      const expected = {
        schemaVersion: 1,
        bindingId: nativeUuid(row.binding_id),
        providerScope: this.#config.providerScope,
        scope: { tenantId: nativeId(row.tenant_id), accountId: nativeId(row.account_id) },
        caseId: nativeId(row.case_id),
        conversationId: nativeId(row.conversation_id),
        roomId: nativeId(row.room_id),
        participantId: nativeId(row.participant_id),
        expiresAt: nativeIso(value.expiresAt),
      };
      if (JSON.stringify(expected) !== row.canonical_binding) throw Error();
      if (
        value.schemaVersion !== 1 ||
        value.bindingId !== row.binding_id ||
        value.roomId !== row.room_id ||
        value.participantId !== row.participant_id ||
        value.caseId !== row.case_id ||
        value.conversationId !== row.conversation_id ||
        JSON.stringify(value.providerScope) !== JSON.stringify(this.#config.providerScope) ||
        row.tenant_id !== this.#config.providerScope.tenantId ||
        row.provider !== 'livekit' ||
        row.provider_account_id !== this.#config.providerScope.providerAccountId ||
        JSON.stringify(value.scope) !==
          JSON.stringify({ tenantId: row.tenant_id, accountId: row.account_id }) ||
        typeof row.bearer_digest !== 'string' ||
        !/^[0-9a-f]{64}(?![\s\S])/.test(row.bearer_digest) ||
        !(row.published_at instanceof Date) ||
        !(row.expires_at instanceof Date) ||
        nativeIso(value.expiresAt) !== row.expires_at.toISOString() ||
        (row.revoked_at !== null && !(row.revoked_at instanceof Date))
      )
        throw Error();
      return {
        value,
        receipt: Object.freeze({
          bindingId: row.binding_id as string,
          bindingDigest: row.binding_digest as string,
          publishedAt: row.published_at.toISOString(),
          expiresAt: row.expires_at.toISOString(),
        }),
      };
    } catch {
      throw new ChannelError('SchemaMismatch');
    }
  }
  /** Retained immutable grant for communication evidence; revocation is not historical erasure. */
  async retainedBinding(tx: Pick<Tx, 'client'>, bindingId: string, lock = false) {
    const rows = (
      await tx.client.query(
        `SELECT * FROM ${this.#q('native_bindings')} WHERE binding_id=$1${lock ? ' FOR UPDATE' : ''}`,
        [nativeUuid(bindingId)],
      )
    ).rows;
    if (rows.length !== 1) throw new ChannelError('NotFound');
    const row = rows[0],
      { value } = this.#decode(row);
    return Object.freeze({
      scope: Object.freeze({ ...(value.scope as { tenantId: string; accountId: string }) }),
      providerScope: Object.freeze({
        ...(value.providerScope as {
          tenantId: string;
          provider: string;
          providerAccountId: string;
        }),
      }),
      caseId: value.caseId as string,
      conversationId: value.conversationId as string,
      roomId: value.roomId as string,
      participantId: value.participantId as string,
      expiresAt: value.expiresAt as string,
      revokedAt: row.revoked_at as Date | null,
      bearerDigest: row.bearer_digest as string,
    });
  }
  /** Current bearer disclosure admission, separate from retained immutable history. */
  async currentBearer(client: PoolClient, bearer: string, lock: boolean) {
    const rows = (
      await client.query(
        `SELECT * FROM ${this.#q('native_bindings')} WHERE bearer_digest=$1${lock ? ' FOR UPDATE' : ''}`,
        [nativeSha(nativeToken(bearer))],
      )
    ).rows;
    if (rows.length !== 1) throw new ChannelError('AccessDenied');
    const row = rows[0];
    this.#decode(row);
    const grant = await this.retainedBinding({ client }, nativeUuid(row.binding_id));
    const now = (await client.query("SELECT date_trunc('milliseconds',clock_timestamp()) AS now"))
      .rows[0]?.now;
    if (
      !(now instanceof Date) ||
      grant.revokedAt !== null ||
      Date.parse(grant.expiresAt) <= now.getTime()
    )
      throw new ChannelError('AccessDenied');
    return Object.freeze({
      ...grant,
      bindingId: row.binding_id as string,
      admittedAt: now.toISOString(),
    });
  }
  async bind(tx: Tx, token: string, input: NativePublication): Promise<NativeBindingReceipt> {
    const pub = this.#publisher(token),
      state = await this.#settings(tx),
      raw = this.#canonical(pub, input),
      secret = nativeSha(input.bearer),
      old = (
        await tx.client.query(`SELECT * FROM ${this.#q('native_bindings')} WHERE binding_id=$1`, [
          input.bindingId,
        ])
      ).rows[0];
    if (old) {
      const original = this.#decode(old);
      if (old.canonical_binding !== raw || old.bearer_digest !== secret)
        throw new ChannelError('IdentityConflict');
      return original.receipt;
    }
    if (this.#config.publishers.some((x) => x.tokenDigest === secret))
      throw new ChannelError('AccessDenied');
    const now = (
      await tx.client.query("SELECT date_trunc('milliseconds',clock_timestamp()) AS now")
    ).rows[0]?.now;
    if (
      !(now instanceof Date) ||
      Date.parse(input.expiresAt) <= now.getTime() ||
      Date.parse(input.expiresAt) - now.getTime() > 300000
    )
      throw new ChannelError('AccessDenied');
    if (state.count >= state.limit.maxBindings) throw new ChannelError('Overloaded');
    await tx.client.query(
      `INSERT INTO ${this.#q('conversations')}(tenant_id,account_id,conversation_id,last_sequence) VALUES($1,$2,$3,0) ON CONFLICT DO NOTHING`,
      [pub.scope.tenantId, pub.scope.accountId, pub.conversationId],
    );
    const p = this.#config.providerScope,
      rows = (
        await tx.client.query(
          `INSERT INTO ${this.#q('native_bindings')} VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,null) RETURNING *`,
          [
            input.bindingId,
            p.tenantId,
            p.provider,
            p.providerAccountId,
            pub.scope.accountId,
            pub.conversationId,
            pub.caseId,
            input.roomId,
            input.participantId,
            secret,
            raw,
            nativeSha(raw),
            now,
            input.expiresAt,
          ],
        )
      ).rows;
    await tx.client.query(
      `UPDATE ${this.#q('native_settings')} SET binding_count=binding_count+1 WHERE singleton`,
    );
    return this.#decode(rows[0]).receipt;
  }
  async revoke(
    tx: Tx,
    token: string,
    bindingId: string,
  ): Promise<Readonly<{ bindingId: string; revokedAt: string }>> {
    const pub = this.#publisher(token);
    await this.#settings(tx);
    const row = (
      await tx.client.query(
        `SELECT * FROM ${this.#q('native_bindings')} WHERE binding_id=$1 FOR UPDATE`,
        [bindingId],
      )
    ).rows[0];
    if (!row) throw new ChannelError('NotFound');
    this.#decode(row);
    if (
      row.tenant_id !== pub.scope.tenantId ||
      row.account_id !== pub.scope.accountId ||
      row.case_id !== pub.caseId ||
      row.conversation_id !== pub.conversationId
    )
      throw new ChannelError('AccessDenied');
    if (row.revoked_at === null) {
      const updated = (
        await tx.client.query(
          `UPDATE ${this.#q('native_bindings')} SET revoked_at=date_trunc('milliseconds',clock_timestamp()) WHERE binding_id=$1 RETURNING revoked_at`,
          [bindingId],
        )
      ).rows[0];
      if (!(updated?.revoked_at instanceof Date)) throw new ChannelError('SchemaMismatch');
      return Object.freeze({ bindingId, revokedAt: updated.revoked_at.toISOString() });
    }
    return Object.freeze({ bindingId, revokedAt: (row.revoked_at as Date).toISOString() });
  }
  async accept(tx: Tx, bearer: string, input: NativeInput): Promise<NativeAcceptance> {
    await this.#settings(tx);
    const row = (
      await tx.client.query(
        `SELECT * FROM ${this.#q('native_bindings')} WHERE bearer_digest=$1 FOR UPDATE`,
        [nativeSha(nativeToken(bearer))],
      )
    ).rows[0];
    if (!row) throw new ChannelError('AccessDenied');
    const decoded = this.#decode(row),
      now = (await tx.client.query("SELECT date_trunc('milliseconds',clock_timestamp()) AS now"))
        .rows[0]?.now;
    if (!(now instanceof Date)) throw new ChannelError('SchemaMismatch');
    if (
      row.revoked_at !== null ||
      (row.expires_at as Date).getTime() <= now.getTime() ||
      row.room_id !== input.roomId ||
      row.participant_id !== input.participantId
    )
      throw new ChannelError('AccessDenied');
    const p = this.#config.providerScope,
      scope = { tenantId: p.tenantId, accountId: row.account_id as string },
      normalized = produceTextEvent(
        {
          eventId: input.inputId,
          providerScope: p,
          accountScope: scope,
          conversationId: row.conversation_id as string,
          caseId: row.case_id as string,
          receivedAt: now.toISOString(),
          channel: input.channel,
          messageId: input.inputId,
          senderId: row.binding_id as string,
          body: input.body,
        },
        { providerScope: p, accountScope: scope },
      );
    const old = (
      await tx.client.query(
        `SELECT i.*,p.operation_key,p.state FROM ${this.#q('inbox')} i JOIN ${this.#q('processing_intents')} p USING(receipt_id) WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND event_id=$4`,
        [p.tenantId, p.provider, p.providerAccountId, input.inputId],
      )
    ).rows[0];
    if (old) {
      if (old.account_id !== scope.accountId || old.conversation_id !== row.conversation_id)
        throw new ChannelError('AccessDenied');
      if (old.canonical_payload !== normalized.canonical)
        throw new ChannelError('IdentityConflict');
      const stored = decodeStoredMessage(old);
      return Object.freeze({
        schemaVersion: 1,
        bindingId: row.binding_id as string,
        inputId: input.inputId,
        channel: input.channel,
        status: 'replayed',
        receiptId: stored.receipt.receiptId,
        operationKey: stored.operationKey,
        acceptanceSequence: stored.receipt.acceptanceSequence,
        code: null,
      });
    }
    if (tx.guard.inbox_count! >= tx.bounds.maxInbox) throw new ChannelError('Overloaded');
    const seq = (
      await tx.client.query(
        `UPDATE ${this.#q('conversations')} SET last_sequence=last_sequence+1 WHERE tenant_id=$1 AND account_id=$2 AND conversation_id=$3 RETURNING last_sequence::text`,
        [p.tenantId, row.account_id, row.conversation_id],
      )
    ).rows[0]?.last_sequence;
    if (typeof seq !== 'string') throw new ChannelError('SchemaMismatch');
    const receipt = randomUUID(),
      operation = randomUUID();
    await tx.client.query(
      `INSERT INTO ${this.#q('inbox')} VALUES($1,$2,$3,$4,$5,$6,$7,$8,1,$9,$10,$11,$12)`,
      [
        receipt,
        p.tenantId,
        p.provider,
        p.providerAccountId,
        input.inputId,
        input.inputId,
        row.account_id,
        row.conversation_id,
        normalized.canonical,
        normalized.wireJson,
        seq,
        now,
      ],
    );
    await tx.client.query(
      `INSERT INTO ${this.#q('processing_intents')}(receipt_id,operation_key,state) VALUES($1,$2,'pending')`,
      [receipt, operation],
    );
    await tx.client.query(
      `UPDATE ${this.#q('admission')} SET inbox_count=inbox_count+1 WHERE singleton`,
    );
    return Object.freeze({
      schemaVersion: 1,
      bindingId: decoded.receipt.bindingId,
      inputId: input.inputId,
      channel: input.channel,
      status: 'accepted',
      receiptId: receipt,
      operationKey: operation,
      acceptanceSequence: seq,
      code: null,
    });
  }

  async binding(client: PoolClient, message: StoredMessage): Promise<string | null> {
    if (
      message.event.type !== 'text.received' ||
      !['web_chat', 'voice_transcript'].includes(message.event.channel) ||
      !message.event.accountScope ||
      !message.event.caseId
    )
      return null;
    const rows = (
      await client.query(
        `SELECT * FROM ${this.#q('native_bindings')} WHERE binding_id=$1 FOR UPDATE`,
        [message.event.senderId],
      )
    ).rows;
    if (rows.length !== 1) return null;
    const row = rows[0];
    this.#decode(row);
    const settings = (
      await client.query(
        `SELECT *, (SELECT count(*)::integer FROM ${this.#q('native_bindings')}) AS actual FROM ${this.#q('native_settings')} WHERE singleton`,
      )
    ).rows[0];
    if (
      !settings ||
      settings.binding_count !== settings.actual ||
      settings.binding_count > settings.max_bindings
    )
      throw new ChannelError('SchemaMismatch');
    const fresh = (await client.query('SELECT clock_timestamp() AS now')).rows[0]?.now;
    if (!(fresh instanceof Date)) throw new ChannelError('SchemaMismatch');
    if (
      row.revoked_at !== null ||
      (row.expires_at as Date).getTime() <= fresh.getTime() ||
      row.tenant_id !== message.event.accountScope.tenantId ||
      row.account_id !== message.event.accountScope.accountId ||
      row.case_id !== message.event.caseId ||
      row.conversation_id !== message.event.conversationId ||
      row.provider !== message.event.providerScope.provider ||
      row.provider_account_id !== message.event.providerScope.providerAccountId ||
      message.associationVersion !== '1'
    )
      return null;
    return '1';
  }
}
