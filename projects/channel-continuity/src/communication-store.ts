/** Source-bound immutable evidence using the inbox transaction; owns no pool or scheduler. */
import { randomUUID } from 'node:crypto';
import type { PoolClient } from 'pg';
import { table, digest } from './database.js';
import { ChannelError, type ChannelLimits } from './public-types.js';
import { decodeStoredMessage } from './postgres-records.js';
import type { NativeStore } from './native-store.js';
import { nativeFields, nativeSha, nativeToken, nativeUuid, nativeLimits } from './native-types.js';
import {
  communicationConfig,
  communicationLimits,
  communicationSequence,
  responseAnchor,
  responseReceipt,
  sdkObservation,
  browserObservation,
  observationReceipt,
  reduceCommunicationEvidence,
  type CommunicationIntegration,
  type CommunicationSource,
  type ResponseAnchor,
  type ResponseReceipt,
  type BoundResponseAnchor,
  type SdkObservation,
  type BrowserObservation,
  type ObservationReceipt,
  type StoredObservation,
  type ResponseView,
} from './communication-types.js';
type Tx = Readonly<{
  client: PoolClient;
  bounds: ChannelLimits;
  onCommit: (action: () => void) => void;
}>;
type Account = Readonly<{
  tenantId: string;
  accountId: string;
  conversationId: string;
  caseId?: string;
}>;
export class CommunicationStore {
  readonly #schema: string;
  readonly #config: ReturnType<typeof communicationConfig>;
  readonly #native: NativeStore;
  readonly #counts = {
    responsesAccepted: 0,
    responsesReplayed: 0,
    observationsAccepted: 0,
    observationsReplayed: 0,
    identityConflicts: 0,
    rejected: 0,
    unknownAcknowledgements: 0,
    capacityRejected: 0,
    telemetryFailures: 0,
  };
  constructor(
    schema: string,
    integration: CommunicationIntegration | undefined,
    native: NativeStore,
  ) {
    this.#schema = schema;
    this.#config =
      integration === undefined
        ? Object.freeze({
            providerScope: Object.freeze({
              tenantId: 'readonly',
              provider: 'livekit',
              providerAccountId: 'readonly',
            }),
            grants: Object.freeze([]),
            rawTokens: Object.freeze([]),
          })
        : communicationConfig(integration);
    this.#native = native;
  }
  #q(n: string) {
    return table(this.#schema, n);
  }
  metrics() {
    return Object.freeze({ ...this.#counts });
  }
  telemetryFailure() {
    this.#counts.telemetryFailures = Math.min(
      Number.MAX_SAFE_INTEGER,
      this.#counts.telemetryFailures + 1,
    );
  }
  failure(error: unknown) {
    const code = error instanceof ChannelError ? error.code : undefined;
    if (code === 'AcknowledgementUnknown') this.#counts.unknownAcknowledgements++;
    else {
      this.#counts.rejected++;
      if (code === 'IdentityConflict') this.#counts.identityConflicts++;
      if (code === 'Overloaded') this.#counts.capacityRejected++;
    }
  }
  #grant(token: string, source: CommunicationSource) {
    let key: string;
    try {
      key = nativeSha(nativeToken(token));
    } catch {
      throw new ChannelError('AccessDenied');
    }
    const grant = this.#config.grants.find((g) => g.tokens[source] === key);
    if (!grant) throw new ChannelError('AccessDenied');
    return grant;
  }
  authorize(token: string, source: CommunicationSource) {
    this.#grant(token, source);
  }
  async #settings(tx: Tx) {
    const row = (
      await tx.client.query(
        `SELECT s.*, (SELECT count(*)::integer FROM ${this.#q('native_responses')}) AS actual_responses,(SELECT count(*)::integer FROM ${this.#q('native_observations')}) AS actual_observations,(SELECT COALESCE(max(n),0)::integer FROM(SELECT count(*) n FROM ${this.#q('native_observations')} GROUP BY response_id)t) AS actual_per_response FROM ${this.#q('communication_settings')} s WHERE singleton`,
      )
    ).rows;
    try {
      if (row.length !== 1) throw Error();
      const original = (
        await tx.client.query(
          `SELECT n.*,(SELECT count(*)::integer FROM ${this.#q('native_bindings')}) actual_bindings,(SELECT count(*)::integer FROM ${this.#q('inbox')}) actual_inbox,(SELECT inbox_count FROM ${this.#q('admission')} WHERE singleton) inbox_count FROM ${this.#q('native_settings')} n WHERE singleton`,
        )
      ).rows;
      if (original.length !== 1) throw Error();
      const originalRow = original[0],
        nativeBounds = nativeLimits({ maxBindings: originalRow.max_bindings });
      if (
        !Number.isSafeInteger(originalRow.binding_count) ||
        originalRow.binding_count < 0 ||
        originalRow.binding_count !== originalRow.actual_bindings ||
        originalRow.binding_count > nativeBounds.maxBindings ||
        !Number.isSafeInteger(originalRow.inbox_count) ||
        originalRow.inbox_count < 0 ||
        originalRow.inbox_count !== originalRow.actual_inbox ||
        originalRow.inbox_count > tx.bounds.maxInbox
      )
        throw Error();
      const r = row[0],
        limits = communicationLimits({
          maxResponses: r.max_responses,
          maxObservations: r.max_observations,
          maxObservationsPerResponse: r.max_observations_per_response,
        });
      nativeUuid(r.profile_id);
      if (
        !Number.isSafeInteger(r.response_count) ||
        r.response_count < 0 ||
        r.response_count !== r.actual_responses ||
        r.response_count > limits.maxResponses ||
        !Number.isSafeInteger(r.observation_count) ||
        r.observation_count < 0 ||
        r.observation_count !== r.actual_observations ||
        r.observation_count > limits.maxObservations ||
        r.actual_per_response > limits.maxObservationsPerResponse
      )
        throw Error();
      return { ...r, limits };
    } catch {
      throw new ChannelError('SchemaMismatch');
    }
  }
  async #input(tx: Tx, receiptId: string) {
    const rows = (
      await tx.client.query(
        `SELECT i.*,p.operation_key,p.state FROM ${this.#q('inbox')} i JOIN ${this.#q('processing_intents')} p USING(receipt_id) WHERE i.receipt_id=$1`,
        [receiptId],
      )
    ).rows;
    if (rows.length !== 1) throw new ChannelError('NotFound');
    return decodeStoredMessage(rows[0]);
  }
  async #bound(tx: Tx, input: ResponseAnchor, fresh: boolean): Promise<BoundResponseAnchor> {
    const binding = await this.#native.retainedBinding(tx, input.bindingId, fresh),
      stored = await this.#input(tx, input.receiptId),
      event = stored.event;
    if (this.#config.rawTokens.some((token) => nativeSha(token) === binding.bearerDigest))
      throw new ChannelError('InvalidConfiguration');
    if (
      event.type !== 'text.received' ||
      event.senderId !== input.bindingId ||
      event.eventId !== input.inputId ||
      event.messageId !== input.inputId ||
      stored.operationKey !== input.operationKey ||
      event.caseId !== binding.caseId ||
      event.conversationId !== binding.conversationId ||
      event.accountScope?.tenantId !== binding.scope.tenantId ||
      event.accountScope.accountId !== binding.scope.accountId ||
      event.providerScope.tenantId !== binding.providerScope.tenantId ||
      event.providerScope.provider !== binding.providerScope.provider ||
      event.providerScope.providerAccountId !== binding.providerScope.providerAccountId
    )
      throw new ChannelError('AccessDenied');
    if (fresh) {
      const now = (await tx.client.query('SELECT clock_timestamp() AS now')).rows[0]?.now;
      if (
        !(now instanceof Date) ||
        binding.revokedAt !== null ||
        now.getTime() >= Date.parse(binding.expiresAt)
      )
        throw new ChannelError('AccessDenied');
    }
    return Object.freeze({
      ...input,
      scope: binding.scope,
      providerScope: binding.providerScope,
      caseId: binding.caseId,
      conversationId: binding.conversationId,
      roomId: binding.roomId,
      participantId: binding.participantId,
    });
  }
  #matches(anchor: BoundResponseAnchor, grant: Account) {
    if (
      anchor.scope.tenantId !== grant.tenantId ||
      anchor.scope.accountId !== grant.accountId ||
      anchor.conversationId !== grant.conversationId ||
      (grant.caseId !== undefined && anchor.caseId !== grant.caseId)
    )
      throw new ChannelError('AccessDenied');
  }
  async #decode(tx: Tx, row: Record<string, unknown>) {
    try {
      if (
        typeof row.canonical_anchor !== 'string' ||
        digest(row.canonical_anchor) !== row.anchor_digest
      )
        throw Error();
      const v = nativeFields(JSON.parse(row.canonical_anchor), [
        'schemaVersion',
        'responseId',
        'generationId',
        'sdkSpeechId',
        'bindingId',
        'inputId',
        'receiptId',
        'operationKey',
        'caseRevision',
        'scope',
        'providerScope',
        'caseId',
        'conversationId',
        'roomId',
        'participantId',
      ]);
      const input = responseAnchor({
          schemaVersion: v.schemaVersion,
          responseId: v.responseId,
          generationId: v.generationId,
          sdkSpeechId: v.sdkSpeechId,
          bindingId: v.bindingId,
          inputId: v.inputId,
          receiptId: v.receiptId,
          operationKey: v.operationKey,
          caseRevision: v.caseRevision,
        }),
        anchor = await this.#bound(tx, input, false);
      if (
        JSON.stringify(anchor) !== row.canonical_anchor ||
        row.response_id !== anchor.responseId ||
        row.generation_id !== anchor.generationId ||
        row.binding_id !== anchor.bindingId ||
        row.input_receipt_id !== anchor.receiptId ||
        row.operation_key !== anchor.operationKey ||
        row.sdk_speech_id !== anchor.sdkSpeechId ||
        row.tenant_id !== anchor.scope.tenantId ||
        row.account_id !== anchor.scope.accountId ||
        row.conversation_id !== anchor.conversationId ||
        row.case_id !== anchor.caseId ||
        !(row.accepted_at instanceof Date)
      )
        throw Error();
      return {
        anchor,
        receipt: responseReceipt({
          responseId: row.response_id,
          receiptId: row.receipt_id,
          anchorDigest: row.anchor_digest,
          responseSequence: row.response_sequence,
          acceptedAt: row.accepted_at.toISOString(),
        }),
      };
    } catch (error) {
      if (error instanceof ChannelError && error.code === 'NotFound') throw error;
      throw new ChannelError('SchemaMismatch');
    }
  }
  async #response(tx: Tx, id: string) {
    const rows = (
      await tx.client.query(`SELECT * FROM ${this.#q('native_responses')} WHERE response_id=$1`, [
        nativeUuid(id),
      ])
    ).rows;
    if (rows.length !== 1) throw new ChannelError('NotFound');
    return this.#decode(tx, rows[0]);
  }
  async begin(tx: Tx, token: string, input: ResponseAnchor): Promise<ResponseReceipt> {
    const grant = this.#grant(token, 'publisher'),
      state = await this.#settings(tx),
      old = (
        await tx.client.query(`SELECT * FROM ${this.#q('native_responses')} WHERE response_id=$1`, [
          input.responseId,
        ])
      ).rows[0];
    if (old) {
      const original = await this.#decode(tx, old);
      this.#matches(original.anchor, {
        ...grant.scope,
        caseId: grant.caseId,
        conversationId: grant.conversationId,
      });
      if (
        original.anchor.caseId !== grant.caseId ||
        original.anchor.conversationId !== grant.conversationId ||
        JSON.stringify({
          schemaVersion: original.anchor.schemaVersion,
          responseId: original.anchor.responseId,
          generationId: original.anchor.generationId,
          sdkSpeechId: original.anchor.sdkSpeechId,
          bindingId: original.anchor.bindingId,
          inputId: original.anchor.inputId,
          receiptId: original.anchor.receiptId,
          operationKey: original.anchor.operationKey,
          caseRevision: original.anchor.caseRevision,
        }) !== JSON.stringify(input)
      )
        throw new ChannelError('IdentityConflict');
      tx.onCommit(() => {
        this.#counts.responsesReplayed++;
      });
      return original.receipt;
    }
    const anchor = await this.#bound(tx, input, true);
    this.#matches(anchor, {
      ...grant.scope,
      caseId: grant.caseId,
      conversationId: grant.conversationId,
    });
    if (anchor.caseId !== grant.caseId || anchor.conversationId !== grant.conversationId)
      throw new ChannelError('AccessDenied');
    if (state.response_count >= state.limits.maxResponses) throw new ChannelError('Overloaded');
    const collision = (
      await tx.client.query(
        `SELECT 1 FROM ${this.#q('native_responses')} WHERE binding_id=$1 AND (generation_id=$2 OR sdk_speech_id=$3)`,
        [input.bindingId, input.generationId, input.sdkSpeechId],
      )
    ).rowCount;
    if (collision) throw new ChannelError('IdentityConflict');
    const previous = (
      await tx.client.query(
        `SELECT COALESCE(max(response_sequence),0)::text AS n FROM ${this.#q('native_responses')} WHERE tenant_id=$1 AND account_id=$2 AND conversation_id=$3`,
        [anchor.scope.tenantId, anchor.scope.accountId, anchor.conversationId],
      )
    ).rows[0]?.n;
    if (typeof previous !== 'string' || !/^\d+(?![\s\S])/.test(previous))
      throw new ChannelError('SchemaMismatch');
    const canonical = JSON.stringify(anchor),
      receipt = Object.freeze({
        responseId: input.responseId,
        receiptId: randomUUID(),
        anchorDigest: digest(canonical),
        responseSequence: String(BigInt(previous) + 1n),
        acceptedAt: (
          await tx.client.query("SELECT date_trunc('milliseconds',clock_timestamp()) AS now")
        ).rows[0].now.toISOString() as string,
      });
    await tx.client.query(
      `INSERT INTO ${this.#q('native_responses')}(response_id,generation_id,sdk_speech_id,binding_id,input_receipt_id,operation_key,tenant_id,account_id,conversation_id,case_id,canonical_anchor,anchor_digest,receipt_id,response_sequence,accepted_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)`,
      [
        input.responseId,
        input.generationId,
        input.sdkSpeechId,
        input.bindingId,
        input.receiptId,
        input.operationKey,
        anchor.scope.tenantId,
        anchor.scope.accountId,
        anchor.conversationId,
        anchor.caseId,
        canonical,
        receipt.anchorDigest,
        receipt.receiptId,
        receipt.responseSequence,
        receipt.acceptedAt,
      ],
    );
    await tx.client.query(
      `UPDATE ${this.#q('communication_settings')} SET response_count=response_count+1 WHERE singleton`,
    );
    tx.onCommit(() => {
      this.#counts.responsesAccepted++;
    });
    return receipt;
  }
  async #observationRows(tx: Tx, responseId: string): Promise<StoredObservation[]> {
    const rows = (
      await tx.client.query(
        `SELECT * FROM ${this.#q('native_observations')} WHERE response_id=$1 ORDER BY observation_sequence`,
        [responseId],
      )
    ).rows;
    if (rows.length > 64) throw new ChannelError('SchemaMismatch');
    return rows.map((r, index) => {
      try {
        if (
          typeof r.canonical_payload !== 'string' ||
          digest(r.canonical_payload) !== r.payload_digest ||
          !(r.accepted_at instanceof Date) ||
          r.observation_sequence !== String(index + 1)
        )
          throw Error();
        const payload =
          r.source === 'agent_sdk'
            ? sdkObservation(JSON.parse(r.canonical_payload))
            : r.source === 'browser_client'
              ? browserObservation(JSON.parse(r.canonical_payload))
              : undefined;
        if (
          !payload ||
          JSON.stringify(payload) !== r.canonical_payload ||
          payload.responseId !== responseId ||
          payload.eventId !== r.event_id
        )
          throw Error();
        const receipt = observationReceipt({
          responseId,
          eventId: r.event_id,
          receiptId: r.receipt_id,
          payloadDigest: r.payload_digest,
          observationSequence: r.observation_sequence,
          acceptedAt: r.accepted_at.toISOString(),
        });
        return r.source === 'agent_sdk'
          ? Object.freeze({
              source: 'agent_sdk' as const,
              payload: payload as SdkObservation,
              receipt,
            })
          : Object.freeze({
              source: 'browser_client' as const,
              payload: payload as BrowserObservation,
              receipt,
            });
      } catch {
        throw new ChannelError('SchemaMismatch');
      }
    });
  }
  async observe(
    tx: Tx,
    token: string,
    source: 'agent_sdk' | 'browser_client',
    payload: SdkObservation | BrowserObservation,
  ): Promise<ObservationReceipt> {
    const grant = this.#grant(token, source),
      state = await this.#settings(tx),
      response = await this.#response(tx, payload.responseId);
    this.#matches(response.anchor, {
      ...grant.scope,
      caseId: grant.caseId,
      conversationId: grant.conversationId,
    });
    if (
      response.anchor.caseId !== grant.caseId ||
      response.anchor.conversationId !== grant.conversationId
    )
      throw new ChannelError('AccessDenied');
    if (source === 'agent_sdk') {
      const s = payload as SdkObservation;
      if (
        s.generationId !== response.anchor.generationId ||
        s.sdkSpeechId !== response.anchor.sdkSpeechId
      )
        throw new ChannelError('AccessDenied');
    }
    const canonical = JSON.stringify(payload),
      prior = (
        await tx.client.query(
          `SELECT response_id FROM ${this.#q('native_observations')} WHERE binding_id=$1 AND source=$2 AND event_id=$3`,
          [response.anchor.bindingId, source, payload.eventId],
        )
      ).rows[0];
    if (prior && prior.response_id !== payload.responseId)
      throw new ChannelError('IdentityConflict');
    const all = await this.#observationRows(tx, payload.responseId),
      old = all.find((x) => x.source === source && x.payload.eventId === payload.eventId);
    if (old) {
      if (JSON.stringify(old.payload) !== canonical) throw new ChannelError('IdentityConflict');
      tx.onCommit(() => {
        this.#counts.observationsReplayed++;
      });
      return old.receipt;
    }
    if (
      state.observation_count >= state.limits.maxObservations ||
      all.length >= state.limits.maxObservationsPerResponse
    )
      throw new ChannelError('Overloaded');
    const receipt = Object.freeze({
      responseId: payload.responseId,
      eventId: payload.eventId,
      receiptId: randomUUID(),
      payloadDigest: digest(canonical),
      observationSequence: String(all.length + 1),
      acceptedAt: (
        await tx.client.query("SELECT date_trunc('milliseconds',clock_timestamp()) AS now")
      ).rows[0].now.toISOString() as string,
    });
    await tx.client.query(
      `INSERT INTO ${this.#q('native_observations')}(binding_id,source,event_id,response_id,canonical_payload,payload_digest,receipt_id,observation_sequence,accepted_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
      [
        response.anchor.bindingId,
        source,
        payload.eventId,
        payload.responseId,
        canonical,
        receipt.payloadDigest,
        receipt.receiptId,
        receipt.observationSequence,
        receipt.acceptedAt,
      ],
    );
    await tx.client.query(
      `UPDATE ${this.#q('communication_settings')} SET observation_count=observation_count+1 WHERE singleton`,
    );
    tx.onCommit(() => {
      this.#counts.observationsAccepted++;
    });
    return receipt;
  }
  async inspect(tx: Tx, account: Account, id: string): Promise<ResponseView> {
    await this.#settings(tx);
    const response = await this.#response(tx, id);
    this.#matches(response.anchor, account);
    const values = await this.#observationRows(tx, id);
    for (const value of values)
      if (
        value.source === 'agent_sdk' &&
        (value.payload.generationId !== response.anchor.generationId ||
          value.payload.sdkSpeechId !== response.anchor.sdkSpeechId)
      )
        throw new ChannelError('SchemaMismatch');
    return Object.freeze({
      anchor: response.anchor,
      receipt: response.receipt,
      observationCount: values.length,
      ...reduceCommunicationEvidence(values),
    });
  }
  /** Read-only source-specific summary; another source's conflict never becomes a generated-text fact. */
  async historicalGeneratedState(
    tx: Tx,
    id: string,
  ): Promise<'not_observed' | 'complete' | 'conflicted'> {
    const generated = new Set(
      (await this.#observationRows(tx, id)).flatMap((value) =>
        value.source === 'agent_sdk' && value.payload.fact.type === 'generated_complete'
          ? [value.payload.fact.text]
          : [],
      ),
    );
    return generated.size === 0 ? 'not_observed' : generated.size === 1 ? 'complete' : 'conflicted';
  }
  async responses(
    tx: Tx,
    account: Account,
    query: Readonly<{ limit: number; beforeSequence?: string }>,
  ) {
    if (!Number.isSafeInteger(query.limit) || query.limit < 1 || query.limit > 32)
      throw new ChannelError('InvalidEvent');
    const before =
      query.beforeSequence === undefined ? null : communicationSequence(query.beforeSequence);
    await this.#settings(tx);
    const rows = (
      await tx.client.query(
        `SELECT response_id FROM ${this.#q('native_responses')} WHERE tenant_id=$1 AND account_id=$2 AND conversation_id=$3 AND ($4::text IS NULL OR case_id=$4) AND ($5::bigint IS NULL OR response_sequence<$5::bigint) ORDER BY response_sequence DESC LIMIT $6`,
        [
          account.tenantId,
          account.accountId,
          account.conversationId,
          account.caseId ?? null,
          before,
          query.limit,
        ],
      )
    ).rows;
    const result: ResponseView[] = [];
    for (const row of rows)
      result.push(await this.inspect(tx, account, nativeUuid(row.response_id)));
    return Object.freeze(result);
  }
  async observations(
    tx: Tx,
    account: Account,
    id: string,
    query: Readonly<{ limit: number; afterSequence?: string }>,
  ) {
    if (!Number.isSafeInteger(query.limit) || query.limit < 1 || query.limit > 8)
      throw new ChannelError('InvalidEvent');
    await this.inspect(tx, account, id);
    const after =
      query.afterSequence === undefined ? 0n : BigInt(communicationSequence(query.afterSequence));
    return Object.freeze(
      (await this.#observationRows(tx, id))
        .filter((x) => BigInt(x.receipt.observationSequence) > after)
        .slice(0, query.limit),
    );
  }
}
