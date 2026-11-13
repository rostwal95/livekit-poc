/** Read-only current case plus retained source facts. No field is an execution capability. */
import { createHash } from 'node:crypto';
import { nativeFields, nativeId, nativeIso, nativeUuid } from './native-types.js';
import { reference, revision, acceptedMessage } from './routing-types.js';
import {
  responseAnchor,
  responseReceipt,
  communicationSequence,
  type BoundResponseAnchor,
  type ResponseReceipt,
} from './communication-types.js';
import type { AccountScope } from './index.js';
import type { StoredMessage } from './postgres.js';
import type { InvestigationRequest } from './routing-types.js';
export type RehydrationCode =
  'access_denied' | 'invalid_query' | 'context_unavailable' | 'overloaded' | 'closed';
export class RehydrationError extends Error {
  readonly code!: RehydrationCode;
  constructor(code: RehydrationCode = 'context_unavailable') {
    const safe: RehydrationCode =
      typeof code === 'string' &&
      ['access_denied', 'invalid_query', 'context_unavailable', 'overloaded', 'closed'].includes(
        code,
      )
        ? code
        : 'context_unavailable';
    super(safe);
    Object.defineProperty(this, 'code', {
      value: safe,
      enumerable: true,
      writable: false,
      configurable: false,
    });
    this.name = 'RehydrationError';
  }
}

export type CurrentCaseReference = Readonly<{
  scope: AccountScope;
  caseId: string;
  conversationId: string;
}>;
export type CurrentCase = CurrentCaseReference &
  Readonly<{
    schemaVersion: 1;
    source: 'standalone_reference_v1' | 'p1_public_v4';
    revision: string;
    request: InvestigationRequest;
    workflow: null | Readonly<{
      taskId: string;
      state:
        | 'ready'
        | 'running'
        | 'retry_wait'
        | 'inquiry_complete'
        | 'waiting'
        | 'intent_committed'
        | 'failed'
        | 'uncertain'
        | 'completed'
        | 'cancelled';
      version: string;
    }>;
    intent: Readonly<{ state: 'not_committed' | 'committed'; intentId: string | null }>;
    mutation: Readonly<{
      state:
        | 'not_observed'
        | 'pending'
        | 'claimed'
        | 'dispatched'
        | 'succeeded'
        | 'failed'
        | 'uncertain'
        | 'cancelled';
      outcome: 'not_observed' | 'succeeded' | 'failed' | 'uncertain' | 'cancelled';
      cancellation:
        | 'not_observed'
        | 'not_requested'
        | 'cancelled_before_commit'
        | 'cancelled_before_dispatch'
        | 'requested_best_effort'
        | 'already_terminal';
      effectId: string | null;
      outcomeEventId: string | null;
    }>;
    supplierResult: null | Readonly<{
      supplierId: string;
      revision: string;
      bookingReference: string;
      newCheckIn: string;
    }>;
    sourceRevision: string;
  }>;
export interface CurrentCasePort {
  inspect(reference: CurrentCaseReference, signal: AbortSignal): Promise<CurrentCase>;
}
export type SequenceCursor = Readonly<{
  kind: 'history' | 'work' | 'responses';
  scopeDigest: string;
  beforeSequence: string;
}>;
export type ReplyCursor = Readonly<{
  kind: 'replies';
  scopeDigest: string;
  beforeAcceptedAt: string;
  beforeOutboundId: string;
}>;
export type RehydrationQuery = Readonly<{
  historyCursor: SequenceCursor | null;
  workCursor: SequenceCursor | null;
  responseCursor: SequenceCursor | null;
  replyCursor: ReplyCursor | null;
  limits: Readonly<{ history: number; work: number; responses: number; replies: number }>;
}>;
export const DEFAULT_REHYDRATION_QUERY: RehydrationQuery = Object.freeze({
  historyCursor: null,
  workCursor: null,
  responseCursor: null,
  replyCursor: null,
  limits: Object.freeze({ history: 8, work: 8, responses: 4, replies: 4 }),
});
export const WORK_CODES = [
  'none',
  'association_required',
  'adapter_invalid',
  'adapter_unavailable',
  'operation_conflict',
  'claim_lost',
  'accepted',
  'lookup_absent',
] as const;
export type WorkReference = Readonly<{
  receiptId: string;
  operationKey: string;
  acceptanceSequence: string;
  state: 'pending' | 'running' | 'uncertain' | 'blocked' | 'exhausted';
  possibleExternal: boolean;
  externalReceiptId: string | null;
  attempts: number;
  nextAttemptAt: string | null;
  lastCode: (typeof WORK_CODES)[number];
}>;
export type HistoricalResponse = Readonly<{
  historical: true;
  anchor: BoundResponseAnchor;
  receipt: ResponseReceipt;
  observationCount: number;
  generated: Readonly<{
    state: 'not_observed' | 'complete' | 'conflicted';
    textDigest: string | null;
    textBytes: number | null;
  }>;
  sdk: Readonly<{
    state: 'unknown' | 'completed' | 'interrupted' | 'conflicted';
    textDigest: string | null;
    textBytes: number | null;
  }>;
  browserState:
    'unknown' | 'started' | 'partial' | 'interrupted' | 'completed_reported' | 'conflicted';
  conflicted: boolean;
}>;
export type ReplyReference = Readonly<{
  outboundId: string;
  responseId: string;
  receiptId: string;
  acceptedAt: string;
  bodyDigest: string;
  attemptCount: number;
  lastAttempt: null | Readonly<{
    attemptId: string;
    providerOperationKey: string;
    requestDigest: string;
    result: 'unknown' | 'accepted_by_provider' | 'definitive_not_accepted';
    providerMessageId: string | null;
  }>;
  callbackObservations: readonly Readonly<{
    attemptId: string;
    eventId: string;
    receiptId: string;
    state: 'accepted_by_provider' | 'delivered' | 'failed' | 'unknown' | 'read_reported';
  }>[];
  callbacksTruncated: boolean;
}>;
export type RehydrationAccess =
  | Readonly<{ kind: 'native'; bindingId: string; roomId: string; participantId: string }>
  | Readonly<{
      kind: 'sms';
      receiptId: string;
      eventId: string;
      senderId: string;
      associationVersion: string;
    }>;
export type RehydrationPage<T, C> = Readonly<{
  items: readonly T[];
  nextCursor: C | null;
  hasMore: boolean;
}>;
export type RehydrationContext = Readonly<{
  schemaVersion: 1;
  contextId: string;
  access: RehydrationAccess;
  case: CurrentCase;
  history: Readonly<{
    messages: readonly StoredMessage[];
    nextCursor: SequenceCursor | null;
    hasMore: boolean;
  }>;
  work: RehydrationPage<WorkReference, SequenceCursor>;
  responses: RehydrationPage<HistoricalResponse, SequenceCursor>;
  replies: RehydrationPage<ReplyReference, ReplyCursor>;
  observed: Readonly<{
    p2ObservedAt: string;
    caseObservedAt: string;
    disclosureAdmittedAt: string;
    atomic: false;
  }>;
}>;
export const REHYDRATION_MAX_BYTES = 65536;
export const REHYDRATION_SECTION_BYTES = Object.freeze({
  history: 28672,
  case: 4096,
  responses: 12288,
  work: 4096,
  replies: 8192,
});
export function rehydrationFields(v: unknown, keys: readonly string[]): Record<string, unknown> {
  try {
    return nativeFields(v, keys);
  } catch {
    throw new RehydrationError('invalid_query');
  }
}
export function strictArray(v: unknown, maximum: number): readonly unknown[] {
  if (!Array.isArray(v) || Object.getPrototypeOf(v) !== Array.prototype || v.length > maximum)
    throw new RehydrationError('invalid_query');
  const d = Object.getOwnPropertyDescriptors(v);
  if (Reflect.ownKeys(d).length !== v.length + 1) throw new RehydrationError('invalid_query');
  const r: unknown[] = [];
  for (let n = 0; n < v.length; n++) {
    const x = d[String(n)];
    if (!x || !('value' in x) || !x.enumerable) throw new RehydrationError('invalid_query');
    r.push(x.value);
  }
  return Object.freeze(r);
}
export function sha256(v: string): string {
  return createHash('sha256').update(v).digest('hex');
}
export function digestValue(v: unknown): string {
  if (typeof v !== 'string' || !/^[a-f0-9]{64}(?![\s\S])/.test(v)) throw new RehydrationError();
  return v;
}
export function canonicalUuid(v: unknown): string {
  if (
    typeof v !== 'string' ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![\s\S])/.test(v)
  )
    throw new RehydrationError();
  return v;
}
export function enumValue<T extends string>(v: unknown, values: readonly T[]): T {
  if (typeof v !== 'string' || !values.includes(v as T)) throw new RehydrationError();
  return v as T;
}
export function intValue(v: unknown, max: number): number {
  if (!Number.isSafeInteger(v) || Number(v) < 0 || Number(v) > max) throw new RehydrationError();
  return Number(v);
}
export function bool(v: unknown): boolean {
  if (typeof v !== 'boolean') throw new RehydrationError();
  return v;
}
export function currentReference(v: unknown): CurrentCaseReference {
  const x = rehydrationFields(v, ['scope', 'caseId', 'conversationId']);
  return Object.freeze({
    ...reference({ scope: x.scope, caseId: x.caseId }),
    conversationId: nativeId(x.conversationId),
  });
}
export function sameCurrentReference(a: CurrentCaseReference, b: CurrentCaseReference): boolean {
  return (
    a.scope.tenantId === b.scope.tenantId &&
    a.scope.accountId === b.scope.accountId &&
    a.caseId === b.caseId &&
    a.conversationId === b.conversationId
  );
}
export function scopeDigest(v: CurrentCaseReference): string {
  return sha256(
    JSON.stringify({ scope: v.scope, caseId: v.caseId, conversationId: v.conversationId }),
  );
}
export function sequenceCursor(v: unknown, kind: SequenceCursor['kind']): SequenceCursor | null {
  if (v === null) return null;
  const x = rehydrationFields(v, ['kind', 'scopeDigest', 'beforeSequence']);
  if (x.kind !== kind) throw new RehydrationError('invalid_query');
  return Object.freeze({
    kind,
    scopeDigest: digestValue(x.scopeDigest),
    beforeSequence: communicationSequence(x.beforeSequence),
  });
}
export function replyCursor(v: unknown): ReplyCursor | null {
  if (v === null) return null;
  const x = rehydrationFields(v, ['kind', 'scopeDigest', 'beforeAcceptedAt', 'beforeOutboundId']);
  if (x.kind !== 'replies') throw new RehydrationError('invalid_query');
  return Object.freeze({
    kind: 'replies',
    scopeDigest: digestValue(x.scopeDigest),
    beforeAcceptedAt: nativeIso(x.beforeAcceptedAt),
    beforeOutboundId: nativeUuid(x.beforeOutboundId),
  });
}
export function rehydrationQuery(v: unknown = DEFAULT_REHYDRATION_QUERY): RehydrationQuery {
  try {
    const x = rehydrationFields(v, [
        'historyCursor',
        'workCursor',
        'responseCursor',
        'replyCursor',
        'limits',
      ]),
      l = rehydrationFields(x.limits, ['history', 'work', 'responses', 'replies']);
    const limits = {
      history: intValue(l.history, 8),
      work: intValue(l.work, 8),
      responses: intValue(l.responses, 4),
      replies: intValue(l.replies, 4),
    };
    if (Object.values(limits).some((n) => n === 0)) throw Error();
    return Object.freeze({
      historyCursor: sequenceCursor(x.historyCursor, 'history'),
      workCursor: sequenceCursor(x.workCursor, 'work'),
      responseCursor: sequenceCursor(x.responseCursor, 'responses'),
      replyCursor: replyCursor(x.replyCursor),
      limits: Object.freeze(limits),
    });
  } catch {
    throw new RehydrationError('invalid_query');
  }
}
export function trustedTaskText(v: unknown): string {
  if (
    typeof v !== 'string' ||
    v.length === 0 ||
    Array.from(v).length > 128 ||
    Buffer.byteLength(v) > 512 ||
    v.trim() !== v ||
    /[\u0000-\u001f\u007f\ud800-\udfff]/u.test(v)
  )
    throw new RehydrationError();
  return v;
}
export function boundedFactText(v: unknown, maximum: number): string {
  if (
    typeof v !== 'string' ||
    v.length === 0 ||
    Buffer.byteLength(v) > maximum ||
    /[\u0000-\u001f\u007f-\u009f\ud800-\udfff]/u.test(v)
  )
    throw new RehydrationError();
  return v;
}
export function currentRequest(v: unknown): InvestigationRequest {
  const x = rehydrationFields(v, [
    'schemaVersion',
    'kind',
    'bookingReference',
    'newCheckIn',
    'investigationConsent',
  ]);
  const bookingReference = boundedFactText(x.bookingReference, 64);
  if (
    x.schemaVersion !== 1 ||
    x.kind !== 'booking_investigation' ||
    x.investigationConsent !== true ||
    bookingReference.trim().toUpperCase() !== bookingReference ||
    typeof x.newCheckIn !== 'string' ||
    !/^(?!0000)[0-9]{4}-[0-9]{2}-[0-9]{2}(?![\s\S])/.test(x.newCheckIn)
  )
    throw new RehydrationError();
  const date = new Date(x.newCheckIn + 'T00:00:00.000Z');
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== x.newCheckIn)
    throw new RehydrationError();
  return Object.freeze({
    schemaVersion: 1,
    kind: 'booking_investigation',
    bookingReference,
    newCheckIn: x.newCheckIn,
    investigationConsent: true,
  });
}
export function currentCase(v: unknown, expected: CurrentCaseReference): CurrentCase {
  try {
    const x = rehydrationFields(v, [
        'schemaVersion',
        'source',
        'scope',
        'caseId',
        'conversationId',
        'revision',
        'request',
        'workflow',
        'intent',
        'mutation',
        'supplierResult',
        'sourceRevision',
      ]),
      ref = currentReference({
        scope: x.scope,
        caseId: x.caseId,
        conversationId: x.conversationId,
      });
    if (x.schemaVersion !== 1 || !sameCurrentReference(ref, expected)) throw Error();
    const source = enumValue(x.source, ['standalone_reference_v1', 'p1_public_v4'] as const);
    const w =
        x.workflow === null ? null : rehydrationFields(x.workflow, ['taskId', 'state', 'version']),
      workflow =
        w === null
          ? null
          : Object.freeze({
              taskId: trustedTaskText(w.taskId),
              state: enumValue(w.state, [
                'ready',
                'running',
                'retry_wait',
                'inquiry_complete',
                'waiting',
                'intent_committed',
                'failed',
                'uncertain',
                'completed',
                'cancelled',
              ] as const),
              version: revision(w.version),
            });
    const i = rehydrationFields(x.intent, ['state', 'intentId']),
      intent = Object.freeze({
        state: enumValue(i.state, ['not_committed', 'committed'] as const),
        intentId: i.intentId === null ? null : canonicalUuid(i.intentId),
      });
    if ((intent.state === 'committed') !== (intent.intentId !== null)) throw Error();
    const m = rehydrationFields(x.mutation, [
        'state',
        'outcome',
        'cancellation',
        'effectId',
        'outcomeEventId',
      ]),
      mutation = Object.freeze({
        state: enumValue(m.state, [
          'not_observed',
          'pending',
          'claimed',
          'dispatched',
          'succeeded',
          'failed',
          'uncertain',
          'cancelled',
        ] as const),
        outcome: enumValue(m.outcome, [
          'not_observed',
          'succeeded',
          'failed',
          'uncertain',
          'cancelled',
        ] as const),
        cancellation: enumValue(m.cancellation, [
          'not_observed',
          'not_requested',
          'cancelled_before_commit',
          'cancelled_before_dispatch',
          'requested_best_effort',
          'already_terminal',
        ] as const),
        effectId: m.effectId === null ? null : canonicalUuid(m.effectId),
        outcomeEventId: m.outcomeEventId === null ? null : canonicalUuid(m.outcomeEventId),
      });
    let supplierResult: CurrentCase['supplierResult'] = null;
    if (x.supplierResult !== null) {
      const s = rehydrationFields(x.supplierResult, [
          'supplierId',
          'revision',
          'bookingReference',
          'newCheckIn',
        ]),
        r = currentRequest({
          schemaVersion: 1,
          kind: 'booking_investigation',
          bookingReference: s.bookingReference,
          newCheckIn: s.newCheckIn,
          investigationConsent: true,
        });
      supplierResult = Object.freeze({
        supplierId: canonicalUuid(s.supplierId),
        revision: revision(s.revision),
        bookingReference: r.bookingReference,
        newCheckIn: r.newCheckIn,
      });
      if (mutation.state !== 'succeeded' && mutation.outcome !== 'succeeded') throw Error();
    }
    if (
      (mutation.state !== 'not_observed' ||
        mutation.effectId !== null ||
        ['succeeded', 'failed', 'uncertain'].includes(mutation.outcome)) &&
      intent.state !== 'committed'
    )
      throw Error();
    if (
      (mutation.state === 'succeeded' || mutation.outcome === 'succeeded') &&
      (supplierResult === null || mutation.effectId === null)
    )
      throw Error();
    if (
      source === 'standalone_reference_v1' &&
      (workflow !== null ||
        supplierResult !== null ||
        mutation.state !== 'not_observed' ||
        mutation.outcome !== 'not_observed' ||
        mutation.effectId !== null ||
        mutation.outcomeEventId !== null ||
        mutation.cancellation !== 'not_observed')
    )
      throw Error();
    if (source === 'p1_public_v4' && workflow === null) throw Error();
    const result = Object.freeze({
      schemaVersion: 1 as const,
      source,
      ...ref,
      revision: revision(x.revision),
      request: currentRequest(x.request),
      workflow,
      intent,
      mutation,
      supplierResult,
      sourceRevision: digestValue(x.sourceRevision),
    });
    if (Buffer.byteLength(JSON.stringify(result)) > 4096) throw Error();
    return result;
  } catch {
    throw new RehydrationError();
  }
}
export function workReference(v: unknown): WorkReference {
  const x = rehydrationFields(v, [
    'receiptId',
    'operationKey',
    'acceptanceSequence',
    'state',
    'possibleExternal',
    'externalReceiptId',
    'attempts',
    'nextAttemptAt',
    'lastCode',
  ]);
  const result = Object.freeze({
    receiptId: nativeUuid(x.receiptId),
    operationKey: nativeUuid(x.operationKey),
    acceptanceSequence: communicationSequence(x.acceptanceSequence),
    state: enumValue(x.state, ['pending', 'running', 'uncertain', 'blocked', 'exhausted'] as const),
    possibleExternal: bool(x.possibleExternal),
    externalReceiptId: x.externalReceiptId === null ? null : nativeUuid(x.externalReceiptId),
    attempts: intValue(x.attempts, 5),
    nextAttemptAt: x.nextAttemptAt === null ? null : nativeIso(x.nextAttemptAt),
    lastCode: enumValue(x.lastCode, WORK_CODES),
  });
  if (result.externalReceiptId !== null) throw new RehydrationError();
  return result;
}
export function historicalResponse(v: unknown, ref: CurrentCaseReference): HistoricalResponse {
  const x = rehydrationFields(v, [
    'historical',
    'anchor',
    'receipt',
    'observationCount',
    'generated',
    'sdk',
    'browserState',
    'conflicted',
  ]);
  if (x.historical !== true) throw new RehydrationError();
  const a = rehydrationFields(x.anchor, [
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
    ]),
    r = currentReference({ scope: a.scope, caseId: a.caseId, conversationId: a.conversationId }),
    p = rehydrationFields(a.providerScope, ['tenantId', 'provider', 'providerAccountId']);
  if (
    !sameCurrentReference(ref, r) ||
    p.tenantId !== ref.scope.tenantId ||
    p.provider !== 'livekit'
  )
    throw new RehydrationError();
  const anchor = Object.freeze({
      ...responseAnchor({
        schemaVersion: a.schemaVersion,
        responseId: a.responseId,
        generationId: a.generationId,
        sdkSpeechId: a.sdkSpeechId,
        bindingId: a.bindingId,
        inputId: a.inputId,
        receiptId: a.receiptId,
        operationKey: a.operationKey,
        caseRevision: a.caseRevision,
      }),
      scope: r.scope,
      providerScope: Object.freeze({
        tenantId: nativeId(p.tenantId),
        provider: 'livekit',
        providerAccountId: nativeId(p.providerAccountId),
      }),
      caseId: r.caseId,
      conversationId: r.conversationId,
      roomId: nativeId(a.roomId),
      participantId: nativeId(a.participantId),
    }),
    receipt = responseReceipt(x.receipt);
  if (
    receipt.responseId !== anchor.responseId ||
    receipt.anchorDigest !== sha256(JSON.stringify(anchor))
  )
    throw new RehydrationError();
  function summary(value: unknown, states: readonly string[]) {
    const z = rehydrationFields(value, ['state', 'textDigest', 'textBytes']),
      state = enumValue(z.state, states),
      textDigest = z.textDigest === null ? null : digestValue(z.textDigest),
      textBytes = z.textBytes === null ? null : intValue(z.textBytes, 4096);
    if ((textDigest === null) !== (textBytes === null)) throw new RehydrationError();
    return Object.freeze({ state, textDigest, textBytes });
  }
  return Object.freeze({
    historical: true,
    anchor,
    receipt,
    observationCount: intValue(x.observationCount, 64),
    generated: summary(x.generated, [
      'not_observed',
      'complete',
      'conflicted',
    ]) as HistoricalResponse['generated'],
    sdk: summary(x.sdk, [
      'unknown',
      'completed',
      'interrupted',
      'conflicted',
    ]) as HistoricalResponse['sdk'],
    browserState: enumValue(x.browserState, [
      'unknown',
      'started',
      'partial',
      'interrupted',
      'completed_reported',
      'conflicted',
    ] as const),
    conflicted: bool(x.conflicted),
  });
}
export function replyReference(v: unknown): ReplyReference {
  const x = rehydrationFields(v, [
      'outboundId',
      'responseId',
      'receiptId',
      'acceptedAt',
      'bodyDigest',
      'attemptCount',
      'lastAttempt',
      'callbackObservations',
      'callbacksTruncated',
    ]),
    l =
      x.lastAttempt === null
        ? null
        : rehydrationFields(x.lastAttempt, [
            'attemptId',
            'providerOperationKey',
            'requestDigest',
            'result',
            'providerMessageId',
          ]),
    lastAttempt =
      l === null
        ? null
        : Object.freeze({
            attemptId: nativeUuid(l.attemptId),
            providerOperationKey: nativeUuid(l.providerOperationKey),
            requestDigest: digestValue(l.requestDigest),
            result: enumValue(l.result, [
              'unknown',
              'accepted_by_provider',
              'definitive_not_accepted',
            ] as const),
            providerMessageId: l.providerMessageId === null ? null : nativeId(l.providerMessageId),
          });
  return Object.freeze({
    outboundId: nativeUuid(x.outboundId),
    responseId: nativeId(x.responseId),
    receiptId: nativeUuid(x.receiptId),
    acceptedAt: nativeIso(x.acceptedAt),
    bodyDigest: digestValue(x.bodyDigest),
    attemptCount: intValue(x.attemptCount, 5),
    lastAttempt,
    callbackObservations: Object.freeze(
      strictArray(x.callbackObservations, 4).map((c) => {
        const a = rehydrationFields(c, ['attemptId', 'eventId', 'receiptId', 'state']);
        return Object.freeze({
          attemptId: nativeUuid(a.attemptId),
          eventId: nativeId(a.eventId),
          receiptId: nativeUuid(a.receiptId),
          state: enumValue(a.state, [
            'accepted_by_provider',
            'delivered',
            'failed',
            'unknown',
            'read_reported',
          ] as const),
        });
      }),
    ),
    callbacksTruncated: bool(x.callbacksTruncated),
  });
}
export function rehydrationContext(
  v: unknown,
  expected?: CurrentCaseReference,
): RehydrationContext {
  try {
    const x = rehydrationFields(v, [
      'schemaVersion',
      'contextId',
      'access',
      'case',
      'history',
      'work',
      'responses',
      'replies',
      'observed',
    ]);
    if (x.schemaVersion !== 1) throw Error();
    const c = x.case as CurrentCase,
      ref = currentReference({
        scope: rehydrationFields(c, [
          'schemaVersion',
          'source',
          'scope',
          'caseId',
          'conversationId',
          'revision',
          'request',
          'workflow',
          'intent',
          'mutation',
          'supplierResult',
          'sourceRevision',
        ]).scope,
        caseId: c.caseId,
        conversationId: c.conversationId,
      }),
      cas = currentCase(c, expected ?? ref);
    const accessValue = rehydrationFields(
      x.access,
      typeof x.access === 'object' &&
        x.access !== null &&
        Object.getOwnPropertyDescriptor(x.access, 'kind')?.value === 'native'
        ? ['kind', 'bindingId', 'roomId', 'participantId']
        : ['kind', 'receiptId', 'eventId', 'senderId', 'associationVersion'],
    );
    const access: RehydrationAccess =
      accessValue.kind === 'native'
        ? Object.freeze({
            kind: 'native',
            bindingId: nativeUuid(accessValue.bindingId),
            roomId: nativeId(accessValue.roomId),
            participantId: nativeId(accessValue.participantId),
          })
        : Object.freeze({
            kind: enumValue(accessValue.kind, ['sms'] as const),
            receiptId: nativeUuid(accessValue.receiptId),
            eventId: nativeId(accessValue.eventId),
            senderId: nativeId(accessValue.senderId),
            associationVersion: communicationSequence(accessValue.associationVersion),
          });
    const h = rehydrationFields(x.history, ['messages', 'nextCursor', 'hasMore']);
    const history = Object.freeze({
      messages: Object.freeze(
        strictArray(h.messages, 8).map((m) => {
          const r = rehydrationFields(m, [
              'receipt',
              'event',
              'operationKey',
              'processingState',
              'associationVersion',
            ]),
            rc = rehydrationFields(r.receipt, [
              'receiptId',
              'eventId',
              'messageId',
              'acceptanceSequence',
              'acceptedAt',
            ]);
          const checked = acceptedMessage(m, nativeUuid(rc.receiptId), [ref]);
          if (checked.event.conversationId !== ref.conversationId) throw Error();
          return Object.freeze({
            receipt: Object.freeze({
              receiptId: nativeUuid(rc.receiptId),
              eventId: nativeId(rc.eventId),
              messageId: nativeId(rc.messageId),
              acceptanceSequence: communicationSequence(rc.acceptanceSequence),
              acceptedAt: nativeIso(rc.acceptedAt),
            }),
            event: checked.event,
            operationKey: nativeUuid(r.operationKey),
            processingState: checked.processingState,
            associationVersion: communicationSequence(r.associationVersion),
          });
        }),
      ),
      nextCursor: sequenceCursor(h.nextCursor, 'history'),
      hasMore: bool(h.hasMore),
    });
    const w = rehydrationFields(x.work, ['items', 'nextCursor', 'hasMore']),
      s = rehydrationFields(x.responses, ['items', 'nextCursor', 'hasMore']),
      r = rehydrationFields(x.replies, ['items', 'nextCursor', 'hasMore']);
    const observed = rehydrationFields(x.observed, [
      'p2ObservedAt',
      'caseObservedAt',
      'disclosureAdmittedAt',
      'atomic',
    ]);
    if (observed.atomic !== false) throw Error();
    const result = Object.freeze({
      schemaVersion: 1 as const,
      contextId: nativeUuid(x.contextId),
      access,
      case: cas,
      history,
      work: Object.freeze({
        items: Object.freeze(strictArray(w.items, 8).map(workReference)),
        nextCursor: sequenceCursor(w.nextCursor, 'work'),
        hasMore: bool(w.hasMore),
      }),
      responses: Object.freeze({
        items: Object.freeze(strictArray(s.items, 4).map((v) => historicalResponse(v, ref))),
        nextCursor: sequenceCursor(s.nextCursor, 'responses'),
        hasMore: bool(s.hasMore),
      }),
      replies: Object.freeze({
        items: Object.freeze(strictArray(r.items, 4).map(replyReference)),
        nextCursor: replyCursor(r.nextCursor),
        hasMore: bool(r.hasMore),
      }),
      observed: Object.freeze({
        p2ObservedAt: nativeIso(observed.p2ObservedAt),
        caseObservedAt: nativeIso(observed.caseObservedAt),
        disclosureAdmittedAt: nativeIso(observed.disclosureAdmittedAt),
        atomic: false as const,
      }),
    });
    if (
      Buffer.byteLength(JSON.stringify({ schemaVersion: 1, status: 'known', context: result })) >
      REHYDRATION_MAX_BYTES
    )
      throw Error();
    for (const [name, max] of Object.entries(REHYDRATION_SECTION_BYTES))
      if (
        Buffer.byteLength(JSON.stringify(result[name as keyof typeof REHYDRATION_SECTION_BYTES])) >
        max
      )
        throw Error();
    const expectedDigest = scopeDigest(cas);
    for (const section of [result.history, result.work, result.responses, result.replies])
      if (
        section.hasMore !== (section.nextCursor !== null) ||
        (section.nextCursor !== null && section.nextCursor.scopeDigest !== expectedDigest)
      )
        throw Error();
    const sequences = [
      {
        values: result.history.messages.map((m) => m.receipt.acceptanceSequence),
        cursor: result.history.nextCursor,
      },
      {
        values: result.work.items.map((m) => m.acceptanceSequence),
        cursor: result.work.nextCursor,
      },
      {
        values: result.responses.items.map((m) => m.receipt.responseSequence),
        cursor: result.responses.nextCursor,
      },
    ];
    for (const section of sequences) {
      if (
        section.values.some(
          (value, n) => n > 0 && BigInt(value) >= BigInt(section.values[n - 1]!),
        ) ||
        (section.cursor !== null && section.cursor.beforeSequence !== section.values.at(-1))
      )
        throw Error();
    }
    const lastReply = result.replies.items.at(-1);
    if (
      result.replies.nextCursor !== null &&
      (!lastReply ||
        result.replies.nextCursor.beforeAcceptedAt !== lastReply.acceptedAt ||
        result.replies.nextCursor.beforeOutboundId !== lastReply.outboundId)
    )
      throw Error();

    return result;
  } catch {
    throw new RehydrationError();
  }
}
