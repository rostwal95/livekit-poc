/** Current-grant context observations. Restoring history grants no execution or consent. */
import { parseBusinessJson } from './business';
import { NativeUiError } from './p2-native-policy';
import type { NativeSession } from './p2-native-policy';

const utf8 = new TextEncoder();
const textDecoder = new TextDecoder('utf-8', { fatal: true });
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![\s\S])/u;
const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/u;
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}(?![\s\S])/u;
const HASH = /^[0-9a-f]{64}(?![\s\S])/u;
const PROCESSING = [
  'pending',
  'running',
  'dispatched',
  'blocked',
  'exhausted',
  'uncertain',
] as const;
const BROWSER = [
  'unknown',
  'started',
  'partial',
  'interrupted',
  'completed_reported',
  'conflicted',
] as const;
const SDK = ['unknown', 'completed', 'interrupted', 'conflicted'] as const;
const CALLBACK = [
  'accepted_by_provider',
  'delivered',
  'failed',
  'unknown',
  'read_reported',
] as const;
const LAST_CODE = [
  'none',
  'association_required',
  'adapter_invalid',
  'adapter_unavailable',
  'operation_conflict',
  'claim_lost',
  'accepted',
  'lookup_absent',
] as const;
const SECTION_LIMITS = { history: 8, work: 8, responses: 4, replies: 4 } as const;

function invalid(): never {
  throw new NativeUiError('invalid', 'Current case context could not be verified.');
}
function record(
  value: unknown,
  required: readonly string[],
  optional: readonly string[] = [],
): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  )
    return invalid();
  const descriptors = Object.getOwnPropertyDescriptors(value);
  const keys = Reflect.ownKeys(descriptors);
  if (
    required.some((key) => !Object.hasOwn(descriptors, key)) ||
    keys.some(
      (key) =>
        typeof key !== 'string' ||
        ![...required, ...optional].includes(key) ||
        !Object.hasOwn(descriptors[key]!, 'value'),
    )
  )
    return invalid();
  return Object.fromEntries(keys.map((key) => [key, descriptors[key as string]!.value as unknown]));
}
function string(value: unknown, maximum = 128, empty = false): string {
  if (
    typeof value !== 'string' ||
    (!empty && !value) ||
    utf8.encode(value).byteLength > maximum ||
    textDecoder.decode(utf8.encode(value)) !== value
  )
    return invalid();
  return value;
}
function id(value: unknown): string {
  const v = string(value);
  if (!IDENTIFIER.test(v)) return invalid();
  return v;
}
function trustedIdentity(value: unknown): string {
  const v = string(value, 512);
  const boundaryWhitespace =
    /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000](?![\s\S])/u;
  if (Array.from(v).length > 128 || /[\u0000-\u001f\u007f]/u.test(v) || boundaryWhitespace.test(v))
    return invalid();
  return v;
}
function booking(value: unknown): string {
  const v = trustedIdentity(value);
  if (utf8.encode(v).byteLength > 64 || v.toUpperCase() !== v) return invalid();
  return v;
}
function uuid(value: unknown, version4 = true): string {
  const v = string(value, 36);
  if (!(version4 ? UUID4 : UUID).test(v)) return invalid();
  return v;
}
function hash(value: unknown): string {
  const v = string(value, 64);
  if (!HASH.test(v)) return invalid();
  return v;
}
function decimal(value: unknown, zero = false): string {
  const v = string(value, 19);
  if (
    !/^(0|[1-9][0-9]{0,18})(?![\s\S])/u.test(v) ||
    BigInt(v) > 9223372036854775807n ||
    (!zero && v === '0')
  )
    return invalid();
  return v;
}
function integer(value: unknown, maximum: number): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0 || value > maximum)
    return invalid();
  return value;
}
function boolean(value: unknown): boolean {
  if (typeof value !== 'boolean') return invalid();
  return value;
}
function oneOf<const T extends readonly string[]>(value: unknown, values: T): T[number] {
  if (typeof value !== 'string' || !values.includes(value)) return invalid();
  return value as T[number];
}
function iso(value: unknown): string {
  const v = string(value, 24);
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z(?![\s\S])/u.test(v) ||
    v.startsWith('0000-') ||
    !Number.isFinite(Date.parse(v)) ||
    new Date(v).toISOString() !== v
  )
    return invalid();
  return v;
}
function date(value: unknown): string {
  const v = string(value, 10);
  if (
    !/^\d{4}-\d{2}-\d{2}(?![\s\S])/u.test(v) ||
    v.startsWith('0000-') ||
    !Number.isFinite(Date.parse(v)) ||
    new Date(v).toISOString().slice(0, 10) !== v
  )
    return invalid();
  return v;
}
function list(value: unknown, maximum: number): unknown[] {
  if (!Array.isArray(value) || value.length > maximum) return invalid();
  return value;
}
function scope(value: unknown): ContextScope {
  const r = record(value, ['tenantId', 'accountId']);
  return { tenantId: id(r.tenantId), accountId: id(r.accountId) };
}
function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
  if (Array.isArray(a) || Array.isArray(b))
    return (
      Array.isArray(a) &&
      Array.isArray(b) &&
      a.length === b.length &&
      a.every((v, i) => same(v, b[i]))
    );
  const x = Object.keys(a).sort(),
    y = Object.keys(b).sort();
  return (
    x.length === y.length &&
    x.every(
      (key, i) =>
        key === y[i] &&
        same((a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key]),
    )
  );
}
function nullable(value: unknown, check: (v: unknown) => unknown): void {
  if (value !== null) check(value);
}
function freeze<T>(value: T): T {
  if (value && typeof value === 'object') {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}

export interface ContextScope {
  readonly tenantId: string;
  readonly accountId: string;
}
export interface ContextIdentity {
  readonly scope: ContextScope;
  readonly caseId: string;
  readonly conversationId: string;
}
export interface ContextCase extends ContextIdentity {
  readonly schemaVersion: 1;
  readonly source: 'standalone_reference_v1' | 'p1_public_v4';
  readonly revision: string;
  readonly sourceRevision: string;
  readonly request: {
    readonly schemaVersion: 1;
    readonly kind: 'booking_investigation';
    readonly bookingReference: string;
    readonly newCheckIn: string;
    readonly investigationConsent: true;
  };
  readonly workflow: {
    readonly taskId: string;
    readonly state: string;
    readonly version: string;
  } | null;
  readonly intent: {
    readonly state: 'not_committed' | 'committed';
    readonly intentId: string | null;
  };
  readonly mutation: {
    readonly state: string;
    readonly outcome: string;
    readonly cancellation: string;
    readonly effectId: string | null;
    readonly outcomeEventId: string | null;
  };
  readonly supplierResult: {
    readonly supplierId: string;
    readonly revision: string;
    readonly bookingReference: string;
    readonly newCheckIn: string;
  } | null;
}
export interface ContextCursor {
  readonly kind: 'history' | 'work' | 'responses' | 'replies';
  readonly scopeDigest: string;
  readonly beforeSequence?: string;
  readonly beforeAcceptedAt?: string;
  readonly beforeOutboundId?: string;
}
export interface ContextPage<T> {
  readonly items: readonly T[];
  readonly nextCursor: ContextCursor | null;
  readonly hasMore: boolean;
}
export interface ContextMessage {
  readonly receipt: {
    readonly receiptId: string;
    readonly eventId: string;
    readonly messageId: string;
    readonly acceptanceSequence: string;
    readonly acceptedAt: string;
  };
  readonly event: {
    readonly schemaVersion: 1;
    readonly type: string;
    readonly eventId: string;
    readonly providerScope: {
      readonly tenantId: string;
      readonly provider: string;
      readonly providerAccountId: string;
    };
    readonly accountScope?: ContextScope;
    readonly caseId?: string;
    readonly conversationId: string;
    readonly channel?: string;
    readonly messageId?: string;
    readonly senderId?: string;
    readonly body?: string;
    readonly receivedAt: string;
  };
  readonly operationKey: string;
  readonly processingState: string;
  readonly associationVersion: string;
}
export interface ContextWork {
  readonly receiptId: string;
  readonly operationKey: string;
  readonly acceptanceSequence: string;
  readonly state: string;
  readonly possibleExternal: boolean;
  readonly externalReceiptId: string | null;
  readonly attempts: number;
  readonly nextAttemptAt: string | null;
  readonly lastCode: string;
}
export interface ContextResponse {
  readonly historical: true;
  readonly anchor: {
    readonly schemaVersion: 1;
    readonly responseId: string;
    readonly generationId: string;
    readonly sdkSpeechId: string;
    readonly bindingId: string;
    readonly inputId: string;
    readonly receiptId: string;
    readonly operationKey: string;
    readonly caseRevision: string;
    readonly scope: ContextScope;
    readonly providerScope: {
      readonly tenantId: string;
      readonly provider: string;
      readonly providerAccountId: string;
    };
    readonly caseId: string;
    readonly conversationId: string;
    readonly roomId: string;
    readonly participantId: string;
  };
  readonly receipt: {
    readonly responseId: string;
    readonly receiptId: string;
    readonly anchorDigest: string;
    readonly responseSequence: string;
    readonly acceptedAt: string;
  };
  readonly observationCount: number;
  readonly generated: {
    readonly state: string;
    readonly textDigest: string | null;
    readonly textBytes: number | null;
  };
  readonly sdk: {
    readonly state: string;
    readonly textDigest: string | null;
    readonly textBytes: number | null;
  };
  readonly browserState: string;
  readonly conflicted: boolean;
}
export interface ContextReply {
  readonly outboundId: string;
  readonly responseId: string;
  readonly receiptId: string;
  readonly acceptedAt: string;
  readonly bodyDigest: string;
  readonly attemptCount: number;
  readonly lastAttempt: {
    readonly attemptId: string;
    readonly providerOperationKey: string;
    readonly requestDigest: string;
    readonly result: string;
    readonly providerMessageId: string | null;
  } | null;
  readonly callbackObservations: readonly {
    readonly attemptId: string;
    readonly eventId: string;
    readonly receiptId: string;
    readonly state: string;
  }[];
  readonly callbacksTruncated: boolean;
}
export interface RehydrationContext {
  readonly schemaVersion: 1;
  readonly contextId: string;
  readonly access: {
    readonly kind: 'native';
    readonly bindingId: string;
    readonly roomId: string;
    readonly participantId: string;
  };
  readonly case: ContextCase;
  readonly history: {
    readonly messages: readonly ContextMessage[];
    readonly nextCursor: ContextCursor | null;
    readonly hasMore: boolean;
  };
  readonly work: ContextPage<ContextWork>;
  readonly responses: ContextPage<ContextResponse>;
  readonly replies: ContextPage<ContextReply>;
  readonly observed: {
    readonly p2ObservedAt: string;
    readonly caseObservedAt: string;
    readonly disclosureAdmittedAt: string;
    readonly atomic: false;
  };
}
export const DEFAULT_CONTEXT_QUERY = freeze({
  historyCursor: null,
  workCursor: null,
  responseCursor: null,
  replyCursor: null,
  limits: { history: 8, work: 8, responses: 4, replies: 4 },
});

function caseFacts(value: unknown): ContextCase {
  const r = record(value, [
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
  ]);
  if (r.schemaVersion !== 1) return invalid();
  oneOf(r.source, ['standalone_reference_v1', 'p1_public_v4']);
  scope(r.scope);
  id(r.caseId);
  id(r.conversationId);
  decimal(r.revision, true);
  hash(r.sourceRevision);
  const request = record(r.request, [
    'schemaVersion',
    'kind',
    'bookingReference',
    'newCheckIn',
    'investigationConsent',
  ]);
  if (
    request.schemaVersion !== 1 ||
    request.kind !== 'booking_investigation' ||
    request.investigationConsent !== true
  )
    return invalid();
  booking(request.bookingReference);
  date(request.newCheckIn);
  if (r.workflow !== null) {
    const w = record(r.workflow, ['taskId', 'state', 'version']);
    trustedIdentity(w.taskId);
    decimal(w.version, true);
    oneOf(w.state, [
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
    ]);
  }
  const intent = record(r.intent, ['state', 'intentId']);
  oneOf(intent.state, ['not_committed', 'committed']);
  nullable(intent.intentId, (v) => uuid(v, false));
  if ((intent.state === 'committed') !== (intent.intentId !== null)) return invalid();
  const m = record(r.mutation, ['state', 'outcome', 'cancellation', 'effectId', 'outcomeEventId']);
  oneOf(m.state, [
    'not_observed',
    'pending',
    'claimed',
    'dispatched',
    'succeeded',
    'failed',
    'uncertain',
    'cancelled',
  ]);
  oneOf(m.outcome, ['not_observed', 'succeeded', 'failed', 'uncertain', 'cancelled']);
  oneOf(m.cancellation, [
    'not_observed',
    'not_requested',
    'cancelled_before_commit',
    'cancelled_before_dispatch',
    'requested_best_effort',
    'already_terminal',
  ]);
  nullable(m.effectId, (v) => uuid(v, false));
  nullable(m.outcomeEventId, (v) => uuid(v, false));
  if (r.supplierResult !== null) {
    const result = record(r.supplierResult, [
      'supplierId',
      'revision',
      'bookingReference',
      'newCheckIn',
    ]);
    uuid(result.supplierId, false);
    decimal(result.revision, true);
    booking(result.bookingReference);
    date(result.newCheckIn);
    if (intent.state !== 'committed' || (m.state !== 'succeeded' && m.outcome !== 'succeeded'))
      return invalid();
    if (
      result.bookingReference !== request.bookingReference ||
      result.newCheckIn !== request.newCheckIn
    )
      return invalid();
  }
  if (
    (m.state !== 'not_observed' ||
      m.effectId !== null ||
      ['succeeded', 'failed', 'uncertain'].includes(m.outcome as string)) &&
    intent.state !== 'committed'
  )
    return invalid();
  if (
    (m.state === 'succeeded' || m.outcome === 'succeeded') &&
    (r.supplierResult === null || m.effectId === null)
  )
    return invalid();
  if (r.source === 'p1_public_v4' && r.workflow === null) return invalid();
  if (
    r.source === 'standalone_reference_v1' &&
    (r.workflow !== null ||
      r.supplierResult !== null ||
      m.state !== 'not_observed' ||
      m.outcome !== 'not_observed' ||
      m.effectId !== null ||
      m.outcomeEventId !== null ||
      m.cancellation !== 'not_observed')
  )
    return invalid();
  // All fields and nested values have been validated; the caller deep-freezes the wire copy.
  return value as ContextCase;
}
function event(value: unknown, current: ContextCase): void {
  const base = [
    'schemaVersion',
    'type',
    'eventId',
    'providerScope',
    'conversationId',
    'receivedAt',
  ];
  const optional = [
    'accountScope',
    'caseId',
    'occurredAt',
    'causationId',
    'retryCount',
    'signature',
  ];
  const initial = record(value, base, [
    ...optional,
    'channel',
    'messageId',
    'senderId',
    'body',
    'expectedCaseRevision',
    'replyToResponseId',
    'responseId',
    'source',
    'state',
    'playedText',
  ]);
  const kind = oneOf(initial.type, [
    'text.received',
    'response.generated',
    'playback.reported',
    'delivery.reported',
    'user.acknowledged',
  ]);
  const specs = {
    'text.received': [
      ['channel', 'messageId', 'senderId', 'body'],
      ['expectedCaseRevision', 'replyToResponseId'],
    ],
    'response.generated': [['responseId', 'body'], []],
    'playback.reported': [['responseId', 'source', 'state'], ['playedText']],
    'delivery.reported': [['messageId', 'state'], []],
    'user.acknowledged': [['responseId', 'messageId'], []],
  } as const;
  const [required, extra] = specs[kind];
  const r = record(value, [...base, ...required], [...optional, ...extra]);
  if (r.schemaVersion !== 1 || id(r.conversationId) !== current.conversationId) return invalid();
  id(r.eventId);
  iso(r.receivedAt);
  const provider = record(r.providerScope, ['tenantId', 'provider', 'providerAccountId']);
  if (id(provider.tenantId) !== current.scope.tenantId) return invalid();
  id(provider.provider);
  id(provider.providerAccountId);
  if (Object.hasOwn(r, 'accountScope') && !same(scope(r.accountScope), current.scope))
    return invalid();
  if (Object.hasOwn(r, 'caseId') && id(r.caseId) !== current.caseId) return invalid();
  for (const k of ['messageId', 'senderId', 'responseId', 'replyToResponseId', 'causationId'])
    if (Object.hasOwn(r, k)) id(r[k]);
  if (Object.hasOwn(r, 'occurredAt')) iso(r.occurredAt);
  if (Object.hasOwn(r, 'retryCount')) integer(r.retryCount, 1000000);
  if (Object.hasOwn(r, 'expectedCaseRevision')) integer(r.expectedCaseRevision, 9007199254740991);
  for (const k of ['body', 'playedText']) if (Object.hasOwn(r, k)) string(r[k], 4096);
  if (Object.hasOwn(r, 'signature')) string(r.signature, 256);
  if (kind === 'text.received') oneOf(r.channel, ['sms', 'web_chat', 'voice_transcript']);
  if (kind === 'playback.reported') {
    oneOf(r.source, ['agent_sdk', 'browser_client']);
    oneOf(r.state, ['started', 'partial', 'completed', 'interrupted']);
  }
  if (kind === 'delivery.reported') oneOf(r.state, CALLBACK);
}
function cursor(value: unknown, section: keyof typeof SECTION_LIMITS): void {
  if (value === null) return;
  const r = record(
    value,
    section === 'replies'
      ? ['kind', 'scopeDigest', 'beforeAcceptedAt', 'beforeOutboundId']
      : ['kind', 'scopeDigest', 'beforeSequence'],
  );
  if (r.kind !== section) return invalid();
  hash(r.scopeDigest);
  if (section === 'replies') {
    iso(r.beforeAcceptedAt);
    uuid(r.beforeOutboundId);
  } else decimal(r.beforeSequence);
}
function page(value: unknown, section: keyof typeof SECTION_LIMITS): unknown[] {
  const key = section === 'history' ? 'messages' : 'items';
  const r = record(value, [key, 'nextCursor', 'hasMore']);
  const rows = list(r[key], SECTION_LIMITS[section]);
  cursor(r.nextCursor, section);
  const more = boolean(r.hasMore);
  if (more !== (r.nextCursor !== null) || (more && rows.length === 0)) return invalid();
  return rows;
}
function message(value: unknown, current: ContextCase): void {
  const r = record(value, [
    'receipt',
    'event',
    'operationKey',
    'processingState',
    'associationVersion',
  ]);
  const receipt = record(r.receipt, [
    'receiptId',
    'eventId',
    'messageId',
    'acceptanceSequence',
    'acceptedAt',
  ]);
  uuid(receipt.receiptId);
  id(receipt.eventId);
  id(receipt.messageId);
  decimal(receipt.acceptanceSequence);
  iso(receipt.acceptedAt);
  uuid(r.operationKey);
  oneOf(r.processingState, PROCESSING);
  decimal(r.associationVersion);
  event(r.event, current);
  const ev = r.event as Record<string, unknown>;
  if (
    receipt.eventId !== ev.eventId ||
    (Object.hasOwn(ev, 'messageId') && receipt.messageId !== ev.messageId)
  )
    return invalid();
}
function work(value: unknown): void {
  const r = record(value, [
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
  uuid(r.receiptId);
  uuid(r.operationKey);
  decimal(r.acceptanceSequence);
  oneOf(
    r.state,
    PROCESSING.filter((v) => v !== 'dispatched'),
  );
  boolean(r.possibleExternal);
  nullable(r.externalReceiptId, uuid);
  integer(r.attempts, 5);
  nullable(r.nextAttemptAt, iso);
  oneOf(r.lastCode, LAST_CODE);
}
function response(value: unknown, current: ContextCase): void {
  const r = record(value, [
    'historical',
    'anchor',
    'receipt',
    'observationCount',
    'generated',
    'sdk',
    'browserState',
    'conflicted',
  ]);
  if (r.historical !== true) return invalid();
  const a = record(r.anchor, [
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
  if (
    a.schemaVersion !== 1 ||
    !same(scope(a.scope), current.scope) ||
    a.caseId !== current.caseId ||
    a.conversationId !== current.conversationId
  )
    return invalid();
  for (const k of [
    'responseId',
    'generationId',
    'bindingId',
    'inputId',
    'receiptId',
    'operationKey',
  ])
    uuid(a[k]);
  for (const k of ['sdkSpeechId', 'roomId', 'participantId']) id(a[k]);
  decimal(a.caseRevision, true);
  const provider = record(a.providerScope, ['tenantId', 'provider', 'providerAccountId']);
  if (provider.tenantId !== current.scope.tenantId || provider.provider !== 'livekit')
    return invalid();
  id(provider.providerAccountId);
  const receipt = record(r.receipt, [
    'responseId',
    'receiptId',
    'anchorDigest',
    'responseSequence',
    'acceptedAt',
  ]);
  if (receipt.responseId !== a.responseId) return invalid();
  uuid(receipt.receiptId);
  hash(receipt.anchorDigest);
  decimal(receipt.responseSequence);
  iso(receipt.acceptedAt);
  integer(r.observationCount, 64);
  oneOf(r.browserState, BROWSER);
  boolean(r.conflicted);
  for (const section of ['generated', 'sdk']) {
    const fact = record(r[section], ['state', 'textDigest', 'textBytes']);
    if (section === 'generated') oneOf(fact.state, ['not_observed', 'complete', 'conflicted']);
    else oneOf(fact.state, SDK);
    nullable(fact.textDigest, hash);
    nullable(fact.textBytes, (v) => integer(v, 4096));
    if (
      (fact.textDigest === null) !== (fact.textBytes === null) ||
      (section === 'generated' && fact.state === 'complete' && fact.textDigest === null)
    )
      return invalid();
  }
}
function reply(value: unknown): void {
  const r = record(value, [
    'outboundId',
    'responseId',
    'receiptId',
    'acceptedAt',
    'bodyDigest',
    'attemptCount',
    'lastAttempt',
    'callbackObservations',
    'callbacksTruncated',
  ]);
  uuid(r.outboundId);
  id(r.responseId);
  uuid(r.receiptId);
  iso(r.acceptedAt);
  hash(r.bodyDigest);
  integer(r.attemptCount, 5);
  boolean(r.callbacksTruncated);
  if (r.lastAttempt !== null) {
    const a = record(r.lastAttempt, [
      'attemptId',
      'providerOperationKey',
      'requestDigest',
      'result',
      'providerMessageId',
    ]);
    uuid(a.attemptId);
    uuid(a.providerOperationKey);
    hash(a.requestDigest);
    oneOf(a.result, ['unknown', 'accepted_by_provider', 'definitive_not_accepted']);
    nullable(a.providerMessageId, id);
  }
  const callbacks = list(r.callbackObservations, 4);
  for (const v of callbacks) {
    const c = record(v, ['attemptId', 'eventId', 'receiptId', 'state']);
    uuid(c.attemptId);
    id(c.eventId);
    uuid(c.receiptId);
    oneOf(c.state, CALLBACK);
  }
  if (
    new Set(callbacks.map((v) => (v as Record<string, unknown>).receiptId)).size !==
    callbacks.length
  )
    return invalid();
}
function descending(values: readonly unknown[], key: (v: unknown) => string): void {
  let previous: bigint | null = null;
  for (const row of values) {
    const next = BigInt(key(row));
    if (previous !== null && next >= previous) return invalid();
    previous = next;
  }
}

export function parseRehydrationContext(
  raw: Uint8Array,
  session: Pick<NativeSession, 'bindingId' | 'roomId' | 'participantId'>,
  expectedCase?: ContextIdentity,
): RehydrationContext {
  try {
    if (!(raw instanceof Uint8Array) || raw.byteLength < 1 || raw.byteLength > 65536)
      return invalid();
    const envelope = record(parseBusinessJson(textDecoder.decode(raw)), [
      'schemaVersion',
      'status',
      'context',
    ]);
    if (envelope.schemaVersion !== 1 || envelope.status !== 'known') return invalid();
    const c = record(envelope.context, [
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
    if (c.schemaVersion !== 1) return invalid();
    uuid(c.contextId);
    const access = record(c.access, ['kind', 'bindingId', 'roomId', 'participantId']);
    if (
      access.kind !== 'native' ||
      access.bindingId !== session.bindingId ||
      access.roomId !== session.roomId ||
      access.participantId !== session.participantId
    )
      return invalid();
    const current = caseFacts(c.case);
    for (const [name, maximum] of Object.entries({
      case: 4096,
      history: 28672,
      work: 4096,
      responses: 12288,
      replies: 8192,
    })) {
      if (utf8.encode(JSON.stringify(c[name])).byteLength > maximum) return invalid();
    }
    if (
      expectedCase &&
      (!same(current.scope, expectedCase.scope) ||
        current.caseId !== expectedCase.caseId ||
        current.conversationId !== expectedCase.conversationId)
    )
      return invalid();
    const history = page(c.history, 'history');
    for (const v of history) message(v, current);
    descending(history, (v) => (v as ContextMessage).receipt.acceptanceSequence);
    const works = page(c.work, 'work');
    for (const v of works) work(v);
    descending(works, (v) => (v as ContextWork).acceptanceSequence);
    const responses = page(c.responses, 'responses');
    for (const v of responses) response(v, current);
    descending(responses, (v) => (v as ContextResponse).receipt.responseSequence);
    const replies = page(c.replies, 'replies');
    for (const v of replies) reply(v);
    for (const [rows, key] of [
      [history, (v: unknown) => (v as ContextMessage).receipt.receiptId],
      [works, (v: unknown) => (v as ContextWork).receiptId],
      [responses, (v: unknown) => (v as ContextResponse).anchor.responseId],
      [replies, (v: unknown) => (v as ContextReply).outboundId],
    ] as const)
      if (new Set(rows.map(key)).size !== rows.length) return invalid();
    const observed = record(c.observed, [
      'p2ObservedAt',
      'caseObservedAt',
      'disclosureAdmittedAt',
      'atomic',
    ]);
    if (observed.atomic !== false) return invalid();
    for (const key of ['p2ObservedAt', 'caseObservedAt', 'disclosureAdmittedAt'])
      iso(observed[key]);
    // No supplied object survives parsing; recursive freeze protects nested source facts/cursors.
    return freeze(envelope.context as RehydrationContext);
  } catch {
    return invalid();
  }
}

export interface ContextRead {
  readonly bindingId: string;
  readonly nonce: symbol;
}
export type ContextPhase = 'empty' | 'loading' | 'ready' | 'unavailable' | 'ended';
export class CurrentContext {
  #session: NativeSession | null = null;
  #ticket: ContextRead | null = null;
  #last: RehydrationContext | null = null;
  #phase: ContextPhase = 'empty';
  get phase(): ContextPhase {
    return this.#phase;
  }
  get value(): RehydrationContext | null {
    return this.#last;
  }
  get ready(): boolean {
    return this.#phase === 'ready' && this.#last?.access.bindingId === this.#session?.bindingId;
  }
  get identity(): ContextIdentity | undefined {
    return this.#last
      ? {
          scope: this.#last.case.scope,
          caseId: this.#last.case.caseId,
          conversationId: this.#last.case.conversationId,
        }
      : undefined;
  }
  bind(session: NativeSession): void {
    this.#session = Object.freeze({ ...session });
    this.#ticket = null;
    this.#phase = 'loading';
  }
  begin(): ContextRead | null {
    if (!this.#session) return null;
    const ticket = Object.freeze({
      bindingId: this.#session.bindingId,
      nonce: Symbol('context-read'),
    });
    this.#ticket = ticket;
    this.#phase = 'loading';
    return ticket;
  }
  accept(ticket: ContextRead, context: RehydrationContext): boolean {
    if (ticket !== this.#ticket || !this.#session || ticket.bindingId !== this.#session.bindingId)
      return false;
    if (
      context.access.bindingId !== this.#session.bindingId ||
      context.access.roomId !== this.#session.roomId ||
      context.access.participantId !== this.#session.participantId
    )
      return invalid();
    if (
      this.#last &&
      (!same(this.#last.case.scope, context.case.scope) ||
        this.#last.case.caseId !== context.case.caseId ||
        this.#last.case.conversationId !== context.case.conversationId)
    )
      return invalid();
    this.#last = context;
    this.#ticket = null;
    this.#phase = 'ready';
    return true;
  }
  unavailable(ticket: ContextRead): boolean {
    if (ticket !== this.#ticket || !this.#session) return false;
    this.#ticket = null;
    this.#phase = 'unavailable';
    return true;
  }
  end(): void {
    this.#session = null;
    this.#ticket = null;
    this.#phase = this.#last ? 'ended' : 'empty';
  }
  forget(): void {
    this.#session = null;
    this.#ticket = null;
    this.#last = null;
    this.#phase = 'empty';
  }
}
