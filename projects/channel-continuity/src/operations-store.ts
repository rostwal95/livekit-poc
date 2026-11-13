/** Scoped immutable cursor anchors over the existing inbox transaction budget. */
import { createHmac, timingSafeEqual } from 'node:crypto';
import { table } from './database.js';
import { ChannelError } from './public-types.js';
import { nativeToken } from './native-types.js';
import type { RehydrationInboxAccess, RehydrationTx } from './rehydration-access.js';
import {
  currentReference,
  sameCurrentReference,
  scopeDigest,
  sequenceCursor,
  replyCursor,
  DEFAULT_REHYDRATION_QUERY,
  digestValue,
  type CurrentCaseReference,
  type RehydrationContext,
  type RehydrationQuery,
  type SequenceCursor,
  type ReplyCursor,
} from './rehydration-types.js';
import {
  OperationsError,
  operationsRecord,
  operationsText,
  operationsUuid,
  operationsQuery,
  type OperationsQuery,
  type OperationsSection,
  type OperationsCursors,
} from './operations-types.js';

import type { OperationsProfile } from './operations.js';

type FixedProfile = Readonly<Omit<OperationsProfile, 'cursorKey'> & { cursorKey: Buffer }>;
type CursorPayload = Readonly<{
  schemaVersion: 1;
  profileId: string;
  sourceId: string;
  bindingId: string;
  section: OperationsSection;
  scopeDigest: string;
  caseSource: string;
  caseSourceRevision: string;
  cursor: SequenceCursor | ReplyCursor;
  anchor: Readonly<{ id: string; position: string }>;
}>;
export type PreparedOperationsQuery = Readonly<{
  query: RehydrationQuery;
  cursor: CursorPayload | null;
}>;
function fixedProfile(value: OperationsProfile): FixedProfile {
  try {
    const r = operationsRecord(value, [
      'profileId',
      'sourceId',
      'reference',
      'bindingId',
      'nativeToken',
      'cursorKey',
    ]);
    const bytes = r.cursorKey;
    if (
      !(bytes instanceof Uint8Array) ||
      ![Uint8Array.prototype, Buffer.prototype].includes(Object.getPrototypeOf(bytes)) ||
      bytes.byteLength !== 32 ||
      Reflect.ownKeys(bytes).length !== 32
    )
      throw Error();
    const key = Buffer.alloc(32);
    for (let n = 0; n < 32; n++) key[n] = bytes[n]!;
    return Object.freeze({
      profileId: operationsUuid(r.profileId),
      sourceId: operationsText(r.sourceId, 128, true),
      reference: currentReference(r.reference),
      bindingId: operationsUuid(r.bindingId),
      nativeToken: nativeToken(r.nativeToken),
      cursorKey: key,
    });
  } catch {
    throw new OperationsError('invalid_query');
  }
}
export class OperationsCursorStore {
  readonly #profile: FixedProfile;
  constructor(
    readonly access: RehydrationInboxAccess,
    profile: OperationsProfile,
  ) {
    this.#profile = fixedProfile(profile);
  }
  get reference(): CurrentCaseReference {
    return this.#profile.reference;
  }
  get nativeToken(): string {
    return this.#profile.nativeToken;
  }
  distinctOperator(authorization: string): void {
    if (
      authorization === 'Bearer ' + this.#profile.nativeToken ||
      authorization === 'Bearer ' + this.#profile.cursorKey.toString('base64url')
    )
      throw new OperationsError('invalid_query');
  }
  async #read<T>(action: (tx: RehydrationTx) => Promise<T>): Promise<T> {
    let own: OperationsError | undefined;
    try {
      return await this.access.transaction(false, async (tx) => {
        try {
          return await action(tx);
        } catch (error) {
          if (error instanceof OperationsError) {
            own = new OperationsError(error.code);
            throw new ChannelError(
              own.code === 'access_denied' ? 'AccessDenied' : 'InvalidConfiguration',
            );
          }
          throw error;
        }
      });
    } catch (error) {
      if (
        own &&
        error instanceof ChannelError &&
        (error.code === 'AccessDenied' || error.code === 'InvalidConfiguration')
      )
        throw own;
      if (error instanceof ChannelError && error.code === 'AccessDenied')
        throw new OperationsError('access_denied');
      throw new OperationsError('unavailable');
    }
  }
  #decode(token: string, section: OperationsSection): CursorPayload {
    try {
      const pieces = token.split('.');
      if (pieces.length !== 2) throw Error();
      const raw = Buffer.from(pieces[0]!, 'base64url'),
        signature = Buffer.from(pieces[1]!, 'base64url');
      if (
        raw.length > 1400 ||
        raw.toString('base64url') !== pieces[0] ||
        signature.length !== 32 ||
        signature.toString('base64url') !== pieces[1]
      )
        throw Error();
      const expected = createHmac('sha256', this.#profile.cursorKey).update(raw).digest();
      if (!timingSafeEqual(signature, expected)) throw Error();
      const parsed: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(raw));
      const r = operationsRecord(parsed, [
        'schemaVersion',
        'profileId',
        'sourceId',
        'bindingId',
        'section',
        'scopeDigest',
        'caseSource',
        'caseSourceRevision',
        'cursor',
        'anchor',
      ]);
      const anchor = operationsRecord(r.anchor, ['id', 'position']);
      if (
        r.schemaVersion !== 1 ||
        r.profileId !== this.#profile.profileId ||
        r.sourceId !== this.#profile.sourceId ||
        r.bindingId !== this.#profile.bindingId ||
        r.section !== section ||
        r.scopeDigest !== scopeDigest(this.reference) ||
        !['standalone_reference_v1', 'p1_public_v4'].includes(r.caseSource as string)
      )
        throw Error();
      const cursor =
        section === 'replies' ? replyCursor(r.cursor) : sequenceCursor(r.cursor, section);
      if (!cursor || cursor.scopeDigest !== r.scopeDigest) throw Error();
      const position =
        section === 'replies'
          ? (cursor as ReplyCursor).beforeAcceptedAt
          : (cursor as SequenceCursor).beforeSequence;
      const result: CursorPayload = Object.freeze({
        schemaVersion: 1,
        profileId: this.#profile.profileId,
        sourceId: this.#profile.sourceId,
        bindingId: this.#profile.bindingId,
        section,
        scopeDigest: scopeDigest(this.reference),
        caseSource: r.caseSource as string,
        caseSourceRevision: digestValue(r.caseSourceRevision),
        cursor,
        anchor: Object.freeze({
          id: operationsUuid(anchor.id),
          position: operationsText(anchor.position, 32),
        }),
      });
      if (
        result.anchor.position !== position ||
        (section === 'replies' && (cursor as ReplyCursor).beforeOutboundId !== result.anchor.id) ||
        Buffer.from(JSON.stringify(result)).compare(raw) !== 0
      )
        throw Error();
      return result;
    } catch {
      throw new OperationsError('invalid_query');
    }
  }
  async prepare(input: OperationsQuery): Promise<PreparedOperationsQuery> {
    const value = operationsQuery(input),
      cursor = value.cursor === null ? null : this.#decode(value.cursor, value.section);
    await this.#read(async (tx) => {
      const grant = await this.access.native.currentBearer(
        tx.client,
        this.#profile.nativeToken,
        false,
      );
      const ref = {
        scope: grant.scope,
        caseId: grant.caseId,
        conversationId: grant.conversationId,
      };
      if (grant.bindingId !== this.#profile.bindingId || !sameCurrentReference(ref, this.reference))
        throw new OperationsError('access_denied');
      if (!cursor) return;
      const args = [
        ref.scope.tenantId,
        ref.scope.accountId,
        ref.conversationId,
        ref.caseId,
        cursor.anchor.id,
      ];
      let rows: Record<string, unknown>[];
      if (cursor.section === 'history' || cursor.section === 'work') {
        rows = (
          await tx.client.query(
            `SELECT i.acceptance_sequence FROM ${table(this.access.schema, 'inbox')} i JOIN ${table(this.access.schema, 'processing_intents')} p USING(receipt_id) WHERE i.tenant_id=$1 AND i.account_id=$2 AND i.conversation_id=$3 AND i.wire_json::jsonb->>'caseId'=$4 AND i.receipt_id=$5::uuid`,
            args,
          )
        ).rows as Record<string, unknown>[];
        if (rows.length !== 1 || rows[0]!.acceptance_sequence !== cursor.anchor.position)
          throw new OperationsError('invalid_query');
      } else if (cursor.section === 'responses') {
        rows = (
          await tx.client.query(
            `SELECT response_sequence FROM ${table(this.access.schema, 'native_responses')} WHERE tenant_id=$1 AND account_id=$2 AND conversation_id=$3 AND case_id=$4 AND response_id=$5::uuid`,
            args,
          )
        ).rows as Record<string, unknown>[];
        if (rows.length !== 1 || rows[0]!.response_sequence !== cursor.anchor.position)
          throw new OperationsError('invalid_query');
      } else {
        rows = (
          await tx.client.query(
            `SELECT accepted_at FROM ${table(this.access.schema, 'reply_intents')} WHERE tenant_id=$1 AND account_id=$2 AND conversation_id=$3 AND case_id=$4 AND outbound_id=$5::uuid`,
            args,
          )
        ).rows as Record<string, unknown>[];
        if (
          rows.length !== 1 ||
          !(rows[0]!.accepted_at instanceof Date) ||
          (rows[0]!.accepted_at as Date).toISOString() !== cursor.anchor.position
        )
          throw new OperationsError('invalid_query');
      }
    });
    return Object.freeze({
      query: Object.freeze({
        ...DEFAULT_REHYDRATION_QUERY,
        ...(cursor
          ? {
              [value.section === 'history'
                ? 'historyCursor'
                : value.section === 'work'
                  ? 'workCursor'
                  : value.section === 'responses'
                    ? 'responseCursor'
                    : 'replyCursor']: cursor.cursor,
            }
          : {}),
      }),
      cursor,
    });
  }
  #mint(
    section: OperationsSection,
    context: RehydrationContext,
    raw: SequenceCursor | ReplyCursor | null,
    id: string | undefined,
    position: string | undefined,
  ): string | null {
    if (!raw) return null;
    if (!id || !position) throw new OperationsError('unavailable');
    const payload: CursorPayload = Object.freeze({
      schemaVersion: 1,
      profileId: this.#profile.profileId,
      sourceId: this.#profile.sourceId,
      bindingId: this.#profile.bindingId,
      section,
      scopeDigest: scopeDigest(this.reference),
      caseSource: context.case.source,
      caseSourceRevision: context.case.sourceRevision,
      cursor: raw,
      anchor: Object.freeze({ id, position }),
    });
    const bytes = Buffer.from(JSON.stringify(payload));
    const token =
      bytes.toString('base64url') +
      '.' +
      createHmac('sha256', this.#profile.cursorKey).update(bytes).digest('base64url');
    if (Buffer.byteLength(token) > 2048) throw new OperationsError('unavailable');
    return token;
  }
  finish(context: RehydrationContext, prepared: PreparedOperationsQuery): OperationsCursors {
    if (
      !sameCurrentReference(context.case, this.reference) ||
      context.access.kind !== 'native' ||
      context.access.bindingId !== this.#profile.bindingId
    )
      throw new OperationsError('access_denied');
    if (
      prepared.cursor &&
      (prepared.cursor.caseSource !== context.case.source ||
        prepared.cursor.caseSourceRevision !== context.case.sourceRevision)
    )
      throw new OperationsError('cursor_stale');
    const h = context.history.messages.at(-1),
      w = context.work.items.at(-1),
      s = context.responses.items.at(-1),
      r = context.replies.items.at(-1);
    return Object.freeze({
      history: this.#mint(
        'history',
        context,
        context.history.nextCursor,
        h?.receipt.receiptId,
        h?.receipt.acceptanceSequence,
      ),
      work: this.#mint(
        'work',
        context,
        context.work.nextCursor,
        w?.receiptId,
        w?.acceptanceSequence,
      ),
      responses: this.#mint(
        'responses',
        context,
        context.responses.nextCursor,
        s?.anchor.responseId,
        s?.receipt.responseSequence,
      ),
      replies: this.#mint(
        'replies',
        context,
        context.replies.nextCursor,
        r?.outboundId,
        r?.acceptedAt,
      ),
    });
  }
}
