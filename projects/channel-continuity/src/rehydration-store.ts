/** Read-only queries over the existing inbox transaction and original retained source rows. */
import { table } from './database.js';
import { ChannelError } from './public-types.js';
import { decodeStoredMessage } from './postgres-records.js';
import { authenticateFakeSms, type FakeSmsIntegration, type WebhookHeaders } from './security.js';
import { produceTextEvent } from './index.js';
import { envelope, sendRequest, carrierResult } from './outbox-types.js';
import { callbackObservation, callbackDigest } from './callback-types.js';
import { nativeIso, nativeUuid } from './native-types.js';
import type { RehydrationInboxAccess, RehydrationTx } from './rehydration-access.js';
import {
  RehydrationError,
  scopeDigest,
  sha256,
  workReference,
  replyReference,
  REHYDRATION_SECTION_BYTES,
  type CurrentCaseReference,
  type RehydrationAccess,
  type RehydrationQuery,
  type RehydrationContext,
  type SequenceCursor,
  type HistoricalResponse,
  type ReplyReference,
} from './rehydration-types.js';
export type Source =
  | Readonly<{ kind: 'native'; bearer: string }>
  | Readonly<{ kind: 'sms'; raw: Buffer; headers: WebhookHeaders }>;
export type Snapshot = Readonly<{
  ref: CurrentCaseReference;
  access: RehydrationAccess;
  history: RehydrationContext['history'];
  work: RehydrationContext['work'];
  responses: RehydrationContext['responses'];
  replies: RehydrationContext['replies'];
  p2ObservedAt: string;
}>;
export class RehydrationStore {
  constructor(
    readonly access: RehydrationInboxAccess,
    readonly sms: FakeSmsIntegration,
  ) {}
  #q(n: string) {
    return table(this.access.schema, n);
  }
  /** Preserve only our finite read semantics after the shared transaction has rolled back/released.
   * Legacy observers receive existing expected-error classes, never a fabricated dependency outage.
   */
  async #read<T>(protectedCheck: boolean, action: (tx: RehydrationTx) => Promise<T>): Promise<T> {
    let semantic: RehydrationError | undefined, translated: ChannelError['code'] | undefined;
    try {
      return await this.access.transaction(protectedCheck, async (tx) => {
        try {
          return await action(tx);
        } catch (error) {
          if (error instanceof RehydrationError) {
            semantic = new RehydrationError(error.code);
            translated =
              semantic.code === 'access_denied'
                ? 'AccessDenied'
                : semantic.code === 'invalid_query'
                  ? 'InvalidConfiguration'
                  : semantic.code === 'overloaded'
                    ? 'Overloaded'
                    : 'SchemaMismatch';
            throw new ChannelError(translated);
          }
          throw error;
        }
      });
    } catch (error) {
      if (semantic !== undefined && error instanceof ChannelError && error.code === translated)
        throw semantic;
      throw error;
    }
  }

  async authorize(tx: RehydrationTx, source: Source, protectedCheck: boolean) {
    if (source.kind === 'native') {
      const g = await this.access.native.currentBearer(tx.client, source.bearer, protectedCheck);
      return Object.freeze({
        ref: Object.freeze({ scope: g.scope, caseId: g.caseId, conversationId: g.conversationId }),
        access: Object.freeze({
          kind: 'native' as const,
          bindingId: g.bindingId,
          roomId: g.roomId,
          participantId: g.participantId,
        }),
        admittedAt: g.admittedAt,
      });
    }
    const clock = (
      await tx.client.query("SELECT date_trunc('milliseconds',clock_timestamp()) AS now")
    ).rows[0]?.now;
    if (!(clock instanceof Date)) throw new RehydrationError();
    let observed;
    try {
      observed = authenticateFakeSms(
        source.raw,
        source.headers,
        this.sms,
        Math.floor(clock.getTime() / 1000),
      );
    } catch {
      throw new RehydrationError('access_denied');
    }
    const p = observed.providerScope;
    if (protectedCheck)
      await tx.client.query(
        `SELECT sender_id FROM ${this.#q('sender_heads')} WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND sender_id=$4 FOR UPDATE`,
        [p.tenantId, p.provider, p.providerAccountId, observed.senderId],
      );
    const rows = (
      await tx.client.query(
        `SELECT i.*,p.operation_key,p.state,a.epoch AS current_epoch,a.account_id AS current_account_id,a.conversation_id AS current_conversation_id,a.case_id AS current_case_id FROM ${this.#q('inbox')} i JOIN ${this.#q('processing_intents')} p USING(receipt_id) JOIN ${this.#q('sender_heads')} h ON h.tenant_id=i.tenant_id AND h.provider=i.provider AND h.provider_account_id=i.provider_account_id AND h.sender_id=$4 JOIN ${this.#q('associations')} a ON a.tenant_id=h.tenant_id AND a.provider=h.provider AND a.provider_account_id=h.provider_account_id AND a.sender_id=h.sender_id AND a.epoch=h.active_epoch AND a.revoked_at IS NULL WHERE i.tenant_id=$1 AND i.provider=$2 AND i.provider_account_id=$3 AND i.event_id=$5`,
        [p.tenantId, p.provider, p.providerAccountId, observed.senderId, observed.eventId],
      )
    ).rows;
    if (rows.length !== 1) throw new RehydrationError('access_denied');
    const row = rows[0],
      message = decodeStoredMessage(row),
      e = message.event;
    if (
      e.type !== 'text.received' ||
      !e.accountScope ||
      !e.caseId ||
      e.channel !== 'sms' ||
      e.senderId !== observed.senderId ||
      e.messageId !== observed.messageId ||
      e.body !== observed.body ||
      e.occurredAt !== observed.occurredAt ||
      message.associationVersion !== String(row.current_epoch) ||
      e.accountScope.accountId !== row.current_account_id ||
      e.conversationId !== row.current_conversation_id ||
      e.caseId !== row.current_case_id
    )
      throw new RehydrationError('access_denied');
    const normalized = produceTextEvent(
      {
        eventId: observed.eventId,
        providerScope: p,
        accountScope: e.accountScope,
        conversationId: e.conversationId,
        caseId: e.caseId,
        receivedAt: message.receipt.acceptedAt,
        occurredAt: observed.occurredAt,
        channel: 'sms',
        messageId: observed.messageId,
        senderId: observed.senderId,
        body: observed.body,
      },
      { providerScope: p, accountScope: e.accountScope },
    );
    if (normalized.canonical !== row.canonical_payload) throw new RehydrationError('access_denied');
    // After locks, use a fresh clock again. The external current-case read may consume the signing window.
    const final = (
      await tx.client.query("SELECT date_trunc('milliseconds',clock_timestamp()) AS now")
    ).rows[0]?.now;
    if (!(final instanceof Date)) throw new RehydrationError();
    try {
      authenticateFakeSms(source.raw, source.headers, this.sms, Math.floor(final.getTime() / 1000));
    } catch {
      throw new RehydrationError('access_denied');
    }
    return Object.freeze({
      ref: Object.freeze({
        scope: e.accountScope,
        caseId: e.caseId,
        conversationId: e.conversationId,
      }),
      access: Object.freeze({
        kind: 'sms' as const,
        receiptId: message.receipt.receiptId,
        eventId: e.eventId,
        senderId: e.senderId,
        associationVersion: message.associationVersion,
      }),
      admittedAt: final.toISOString(),
    });
  }
  async snapshot(source: Source, query: RehydrationQuery): Promise<Snapshot> {
    return this.#read(false, async (tx) => {
      const grant = await this.authorize(tx, source, false),
        ref = grant.ref,
        d = scopeDigest(ref),
        args = [ref.scope.tenantId, ref.scope.accountId, ref.conversationId, ref.caseId];
      for (const c of [
        query.historyCursor,
        query.workCursor,
        query.responseCursor,
        query.replyCursor,
      ])
        if (c !== null && c.scopeDigest !== d) throw new RehydrationError('invalid_query');
      const page = <T, C>(
        values: readonly T[],
        limit: number,
        max: number,
        cursor: (item: T) => C,
      ) => {
        const kept: T[] = [];
        for (const v of values.slice(0, limit)) {
          if (Buffer.byteLength(JSON.stringify([...kept, v])) > max - 512) {
            if (kept.length === 0) throw new RehydrationError();
            break;
          }
          kept.push(v);
        }
        const hasMore = kept.length < values.length;
        return Object.freeze({
          items: Object.freeze(kept),
          nextCursor: hasMore ? cursor(kept.at(-1)!) : null,
          hasMore,
        });
      };
      const before = (c: SequenceCursor | null) => c?.beforeSequence ?? null;
      const historyRows = (
        await tx.client.query(
          `SELECT i.*,p.operation_key,p.state FROM ${this.#q('inbox')} i JOIN ${this.#q('processing_intents')} p USING(receipt_id) WHERE i.tenant_id=$1 AND i.account_id=$2 AND i.conversation_id=$3 AND i.wire_json::jsonb->>'caseId'=$4 AND ($5::bigint IS NULL OR acceptance_sequence<$5::bigint) ORDER BY acceptance_sequence DESC LIMIT $6`,
          [...args, before(query.historyCursor), query.limits.history + 1],
        )
      ).rows;
      const historyPage = page(
        historyRows.map((row) => decodeStoredMessage(row)),
        query.limits.history,
        REHYDRATION_SECTION_BYTES.history,
        (m) =>
          Object.freeze({
            kind: 'history' as const,
            scopeDigest: d,
            beforeSequence: m.receipt.acceptanceSequence,
          }),
      );
      const history = Object.freeze({
        messages: historyPage.items,
        nextCursor: historyPage.nextCursor,
        hasMore: historyPage.hasMore,
      });
      const workRows = (
        await tx.client.query(
          `SELECT i.*,p.operation_key,p.state,p.possible_external,p.external_receipt_id,p.attempt_count,p.next_attempt_at,p.last_code FROM ${this.#q('inbox')} i JOIN ${this.#q('processing_intents')} p USING(receipt_id) WHERE i.tenant_id=$1 AND i.account_id=$2 AND i.conversation_id=$3 AND i.wire_json::jsonb->>'caseId'=$4 AND p.state<>'dispatched' AND ($5::bigint IS NULL OR acceptance_sequence<$5::bigint) ORDER BY acceptance_sequence DESC LIMIT $6`,
          [...args, before(query.workCursor), query.limits.work + 1],
        )
      ).rows;
      const work = page(
        workRows.map((row) => {
          decodeStoredMessage(row);
          return workReference({
            receiptId: row.receipt_id,
            operationKey: row.operation_key,
            acceptanceSequence: row.acceptance_sequence,
            state: row.state,
            possibleExternal: row.possible_external,
            externalReceiptId: row.external_receipt_id,
            attempts: row.attempt_count,
            nextAttemptAt:
              row.next_attempt_at === null ? null : (row.next_attempt_at as Date).toISOString(),
            lastCode: row.last_code,
          });
        }),
        query.limits.work,
        REHYDRATION_SECTION_BYTES.work,
        (m) =>
          Object.freeze({
            kind: 'work' as const,
            scopeDigest: d,
            beforeSequence: m.acceptanceSequence,
          }),
      );
      const account = {
        tenantId: ref.scope.tenantId,
        accountId: ref.scope.accountId,
        caseId: ref.caseId,
        conversationId: ref.conversationId,
      };
      const views = await this.access.communication.responses(tx, account, {
        limit: query.limits.responses + 1,
        ...(query.responseCursor ? { beforeSequence: query.responseCursor.beforeSequence } : {}),
      });
      const summaries: HistoricalResponse[] = [];
      for (const view of views) {
        const summary = (text: string | null, state: string) =>
          Object.freeze({
            state,
            textDigest: text === null ? null : sha256(text),
            textBytes: text === null ? null : Buffer.byteLength(text),
          });
        summaries.push(
          Object.freeze({
            historical: true,
            anchor: view.anchor,
            receipt: view.receipt,
            observationCount: view.observationCount,
            generated: summary(
              view.generatedText,
              await this.access.communication.historicalGeneratedState(tx, view.anchor.responseId),
            ) as HistoricalResponse['generated'],
            sdk: summary(view.sdkText, view.sdkState) as HistoricalResponse['sdk'],
            browserState: view.browserState,
            conflicted: view.conflicted,
          }),
        );
      }
      const responses = page(
        summaries,
        query.limits.responses,
        REHYDRATION_SECTION_BYTES.responses,
        (m) =>
          Object.freeze({
            kind: 'responses' as const,
            scopeDigest: d,
            beforeSequence: m.receipt.responseSequence,
          }),
      );
      const cursor = query.replyCursor;
      const replyRows = (
        await tx.client.query(
          `SELECT * FROM ${this.#q('reply_intents')} WHERE tenant_id=$1 AND account_id=$2 AND conversation_id=$3 AND case_id=$4 AND ($5::timestamptz IS NULL OR (accepted_at,outbound_id)<($5::timestamptz,$6::uuid)) ORDER BY accepted_at DESC,outbound_id DESC LIMIT $7`,
          [
            ...args,
            cursor?.beforeAcceptedAt ?? null,
            cursor?.beforeOutboundId ?? null,
            query.limits.replies + 1,
          ],
        )
      ).rows;
      const replyValues: ReplyReference[] = [];
      for (const row of replyRows) {
        const reply = envelope(JSON.parse(row.canonical_payload as string));
        if (
          JSON.stringify(reply) !== row.canonical_payload ||
          sha256(row.canonical_payload as string) !== row.intent_digest ||
          sha256(reply.body) !== row.body_digest ||
          reply.outboundId !== row.outbound_id ||
          reply.responseId !== row.response_id ||
          reply.scope.tenantId !== ref.scope.tenantId ||
          reply.scope.accountId !== ref.scope.accountId ||
          reply.caseId !== ref.caseId ||
          reply.conversationId !== ref.conversationId
        )
          throw new RehydrationError();
        const attempts = (
          await tx.client.query(
            `SELECT a.*,r.canonical_result FROM ${this.#q('send_attempts')} a LEFT JOIN ${this.#q('send_results')} r USING(attempt_id) WHERE a.tenant_id=$1 AND a.account_id=$2 AND a.outbound_id=$3 ORDER BY ordinal`,
            [ref.scope.tenantId, ref.scope.accountId, reply.outboundId],
          )
        ).rows;
        if (attempts.length > 5) throw new RehydrationError();
        let lastAttempt: ReplyReference['lastAttempt'] = null;
        const requests = new Map<string, ReturnType<typeof sendRequest>>();
        for (let n = 0; n < attempts.length; n++) {
          const a = attempts[n],
            request = sendRequest(JSON.parse(a.canonical_request as string));
          if (
            a.ordinal !== n + 1 ||
            request.attemptId !== a.attempt_id ||
            request.providerOperationKey !== a.provider_operation_key ||
            JSON.stringify(request) !== a.canonical_request ||
            sha256(a.canonical_request as string) !== a.request_digest ||
            request.outboundId !== reply.outboundId ||
            request.body !== reply.body ||
            request.responseId !== reply.responseId ||
            request.scope.tenantId !== ref.scope.tenantId ||
            request.scope.accountId !== ref.scope.accountId ||
            request.caseId !== ref.caseId ||
            request.conversationId !== ref.conversationId
          )
            throw new RehydrationError();
          requests.set(request.attemptId, request);
          let result = null;
          if (a.canonical_result !== null) {
            result = carrierResult(JSON.parse(a.canonical_result as string), request);
            if (JSON.stringify(result) !== a.canonical_result) throw new RehydrationError();
          }
          lastAttempt = Object.freeze({
            attemptId: request.attemptId,
            providerOperationKey: request.providerOperationKey,
            requestDigest: a.request_digest as string,
            result: result?.status ?? 'unknown',
            providerMessageId:
              result?.status === 'accepted_by_provider' ? result.providerMessageId : null,
          });
        }
        const callbackRows = (
          await tx.client.query(
            `SELECT c.* FROM ${this.#q('callback_observations')} c JOIN ${this.#q('send_attempts')} a USING(attempt_id) WHERE a.tenant_id=$1 AND a.account_id=$2 AND a.outbound_id=$3 ORDER BY c.accepted_at DESC,c.receipt_id DESC LIMIT 5`,
            [ref.scope.tenantId, ref.scope.accountId, reply.outboundId],
          )
        ).rows;
        const callbackObservations = callbackRows.slice(0, 4).map((c) => {
          const o = callbackObservation(JSON.parse(c.canonical_payload as string)),
            request = requests.get(o.attemptId);
          if (
            !request ||
            o.eventId !== c.event_id ||
            o.attemptId !== c.attempt_id ||
            o.providerOperationKey !== request.providerOperationKey ||
            o.requestDigest !== sha256(JSON.stringify(request)) ||
            JSON.stringify(o) !== c.canonical_payload ||
            callbackDigest(o) !== c.payload_digest ||
            c.tenant_id !== request.providerScope.tenantId ||
            c.provider !== request.providerScope.provider ||
            c.provider_account_id !== request.providerScope.providerAccountId
          )
            throw new RehydrationError();
          return Object.freeze({
            attemptId: o.attemptId,
            eventId: o.eventId,
            receiptId: nativeUuid(c.receipt_id),
            state: o.state,
          });
        });
        replyValues.push(
          replyReference({
            outboundId: reply.outboundId,
            responseId: reply.responseId,
            receiptId: row.receipt_id,
            acceptedAt: (row.accepted_at as Date).toISOString(),
            bodyDigest: row.body_digest,
            attemptCount: attempts.length,
            lastAttempt,
            callbackObservations,
            callbacksTruncated: callbackRows.length > 4,
          }),
        );
      }
      const replies = page(
        replyValues,
        query.limits.replies,
        REHYDRATION_SECTION_BYTES.replies,
        (m) =>
          Object.freeze({
            kind: 'replies' as const,
            scopeDigest: d,
            beforeAcceptedAt: m.acceptedAt,
            beforeOutboundId: m.outboundId,
          }),
      );
      return Object.freeze({
        ref,
        access: grant.access,
        history,
        work,
        responses,
        replies,
        p2ObservedAt: nativeIso(tx.now.toISOString()),
      });
    });
  }
  async disclose(source: Source, original: Snapshot) {
    return this.#read(true, async (tx) => {
      const latest = await this.authorize(tx, source, true);
      if (
        JSON.stringify(latest.ref) !== JSON.stringify(original.ref) ||
        JSON.stringify(latest.access) !== JSON.stringify(original.access)
      )
        throw new RehydrationError('access_denied');
      return latest.admittedAt;
    });
  }
}
