/** Investigation request revisions only. Exact quote confirmation is a separate authority. */
import { produceTextEvent, type AccountScope, type TextEventInput } from './index.js';
import type { StoredMessage } from './postgres.js';

export type RoutingCode =
  | 'InvalidCommand'
  | 'AccessDenied'
  | 'RevisionConflict'
  | 'ClarificationRequired'
  | 'OutcomeUnknown'
  | 'Unavailable'
  | 'Overloaded'
  | 'Closed'
  | 'CleanupIncomplete'
  | 'InvalidAdapterResponse';
const ROUTING_CODES: readonly string[] = [
  'InvalidCommand',
  'AccessDenied',
  'RevisionConflict',
  'ClarificationRequired',
  'OutcomeUnknown',
  'Unavailable',
  'Overloaded',
  'Closed',
  'CleanupIncomplete',
  'InvalidAdapterResponse',
];
export class RoutingError extends Error {
  readonly code: RoutingCode;
  constructor(code: RoutingCode) {
    const safe = ROUTING_CODES.includes(code) ? code : 'Unavailable';
    super(safe);
    this.code = safe;
    this.name = 'RoutingError';
  }
}
export function safeRoutingCode(value: unknown): RoutingCode | undefined {
  if (!(value instanceof RoutingError)) return undefined;
  const d = Object.getOwnPropertyDescriptor(value, 'code');
  return d && 'value' in d && typeof d.value === 'string' && ROUTING_CODES.includes(d.value)
    ? (d.value as RoutingCode)
    : undefined;
}
export type CaseReference = Readonly<{ scope: AccountScope; caseId: string }>;
export type InvestigationRequest = Readonly<{
  schemaVersion: 1;
  kind: 'booking_investigation';
  bookingReference: string;
  newCheckIn: string;
  investigationConsent: true;
}>;
export type RevisionCommand = Readonly<{
  schemaVersion: 1;
  kind: 'case.revise_investigation';
  expectedRevision: string;
  request: InvestigationRequest;
}>;
export type CaseSnapshot = CaseReference &
  Readonly<{
    revision: string;
    request: InvestigationRequest;
    cancelled: boolean;
    committed: boolean;
  }>;
export type CaseRevision = CaseReference &
  Readonly<{
    expectedRevision: string;
    request: InvestigationRequest;
  }>;
/** Existing authority owns CAS; no automatic retry or command-receipt guarantee. */
export interface CaseAuthorityPort {
  inspect(reference: CaseReference, signal: AbortSignal): Promise<CaseSnapshot>;
  revise(command: CaseRevision, signal: AbortSignal): Promise<CaseSnapshot>;
}
export type AcceptedInputPort = Readonly<{
  inspect(accountToken: string, receiptId: string): Promise<StoredMessage>;
}>;
export type RoutingIdentity = Readonly<{
  receiptId: string;
  operationKey: string;
  eventId: string;
  messageId: string;
  channel: 'web_chat' | 'sms' | 'voice_transcript';
}>;
export type RoutingResult = RoutingIdentity &
  (
    | Readonly<{ status: 'revised' | 'unchanged'; case: CaseSnapshot }>
    | Readonly<{ status: 'revision_conflict' | 'clarification_required' | 'outcome_unknown' }>
  );
export type RoutingEvent = Readonly<{
  event: 'completed' | 'waiter_rejected';
  code:
    | 'revised'
    | 'unchanged'
    | 'revision_conflict'
    | 'clarification_required'
    | 'outcome_unknown'
    | 'unavailable';
}>;
export type RouterOptions = Readonly<{
  maxActive?: number;
  timeoutMs?: number;
  cleanupMs?: number;
  observer?: (event: RoutingEvent) => void | Promise<void>;
}>;
export function fields(value: unknown, expected: readonly string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw new RoutingError('InvalidCommand');
  const keys = Reflect.ownKeys(value);
  if (
    keys.length !== expected.length ||
    keys.some((k) => typeof k !== 'string' || !expected.includes(k))
  )
    throw new RoutingError('InvalidCommand');
  const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const key of expected) {
    const d = Object.getOwnPropertyDescriptor(value, key);
    if (!d || !('value' in d) || !d.enumerable) throw new RoutingError('InvalidCommand');
    result[key] = d.value;
  }
  return result;
}
export function id(value: unknown): string {
  if (
    typeof value !== 'string' ||
    value.length > 128 ||
    !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}(?![\s\S])/.test(value)
  )
    throw new RoutingError('InvalidCommand');
  return value;
}
export function revision(value: unknown): string {
  if (
    typeof value !== 'string' ||
    value.length > 19 ||
    !/^(0|[1-9][0-9]{0,18})(?![\s\S])/.test(value) ||
    BigInt(value) > 9223372036854775807n
  )
    throw new RoutingError('InvalidCommand');
  return value;
}
export function reference(value: unknown): CaseReference {
  const r = fields(value, ['scope', 'caseId']),
    s = fields(r.scope, ['tenantId', 'accountId']);
  return Object.freeze({
    scope: Object.freeze({ tenantId: id(s.tenantId), accountId: id(s.accountId) }),
    caseId: id(r.caseId),
  });
}
export function sameReference(a: CaseReference, b: CaseReference): boolean {
  return (
    a.caseId === b.caseId &&
    a.scope.tenantId === b.scope.tenantId &&
    a.scope.accountId === b.scope.accountId
  );
}
export function allowedReferences(values: readonly CaseReference[]): readonly CaseReference[] {
  if (!Array.isArray(values) || values.length < 1 || values.length > 64)
    throw new RoutingError('InvalidCommand');
  const result: CaseReference[] = [];
  for (const value of values) {
    const item = reference(value);
    if (result.some((existing) => sameReference(item, existing)))
      throw new RoutingError('InvalidCommand');
    result.push(item);
  }
  return Object.freeze(result);
}
export function investigation(value: unknown): InvestigationRequest {
  const r = fields(value, [
    'schemaVersion',
    'kind',
    'bookingReference',
    'newCheckIn',
    'investigationConsent',
  ]);
  if (
    r.schemaVersion !== 1 ||
    r.kind !== 'booking_investigation' ||
    r.investigationConsent !== true ||
    typeof r.bookingReference !== 'string' ||
    r.bookingReference.length > 64 ||
    !/^[A-Z0-9][A-Z0-9._:-]{0,63}(?![\s\S])/.test(r.bookingReference) ||
    typeof r.newCheckIn !== 'string' ||
    !/^(?!0000)[0-9]{4}-[0-9]{2}-[0-9]{2}(?![\s\S])/.test(r.newCheckIn)
  )
    throw new RoutingError('InvalidCommand');
  const date = new Date(r.newCheckIn + 'T00:00:00.000Z');
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== r.newCheckIn)
    throw new RoutingError('InvalidCommand');
  return Object.freeze({
    schemaVersion: 1,
    kind: 'booking_investigation',
    bookingReference: r.bookingReference,
    newCheckIn: r.newCheckIn,
    investigationConsent: true,
  });
}
export function caseRevision(value: unknown): CaseRevision {
  const r = fields(value, ['scope', 'caseId', 'expectedRevision', 'request']);
  return Object.freeze({
    ...reference({ scope: r.scope, caseId: r.caseId }),
    expectedRevision: revision(r.expectedRevision),
    request: investigation(r.request),
  });
}
export function snapshot(value: unknown, expected: CaseReference): CaseSnapshot {
  try {
    const r = fields(value, ['scope', 'caseId', 'revision', 'request', 'cancelled', 'committed']);
    const ref = reference({ scope: r.scope, caseId: r.caseId });
    if (
      !sameReference(ref, expected) ||
      typeof r.cancelled !== 'boolean' ||
      typeof r.committed !== 'boolean'
    )
      throw new RoutingError('InvalidAdapterResponse');
    return Object.freeze({
      ...ref,
      revision: revision(r.revision),
      request: investigation(r.request),
      cancelled: r.cancelled,
      committed: r.committed,
    });
  } catch {
    throw new RoutingError('InvalidAdapterResponse');
  }
}
export function revisedSnapshot(value: unknown, command: CaseRevision): CaseSnapshot {
  const checked = snapshot(value, command);
  if (
    checked.cancelled ||
    checked.committed ||
    JSON.stringify(checked.request) !== JSON.stringify(command.request) ||
    (checked.revision !== command.expectedRevision &&
      BigInt(checked.revision) !== BigInt(command.expectedRevision) + 1n)
  )
    throw new RoutingError('InvalidAdapterResponse');
  return checked;
}
export function encodeRevisionCommand(value: RevisionCommand): string {
  const r = fields(value, ['schemaVersion', 'kind', 'expectedRevision', 'request']);
  if (r.schemaVersion !== 1 || r.kind !== 'case.revise_investigation')
    throw new RoutingError('InvalidCommand');
  return JSON.stringify({
    schemaVersion: 1,
    kind: 'case.revise_investigation',
    expectedRevision: revision(r.expectedRevision),
    request: investigation(r.request),
  });
}
export function decodeRevisionCommand(body: string): RevisionCommand {
  try {
    if (typeof body !== 'string' || body.length > 4096 || Buffer.byteLength(body) > 4096)
      throw new RoutingError('InvalidCommand');
    const raw = JSON.parse(body) as RevisionCommand;
    const encoded = encodeRevisionCommand(raw);
    if (encoded !== body) throw new RoutingError('InvalidCommand');
    const r = fields(raw, ['schemaVersion', 'kind', 'expectedRevision', 'request']);
    return Object.freeze({
      schemaVersion: 1,
      kind: 'case.revise_investigation',
      expectedRevision: revision(r.expectedRevision),
      request: investigation(r.request),
    });
  } catch {
    throw new RoutingError('ClarificationRequired');
  }
}
export function acceptedMessage(
  value: unknown,
  receiptId: string,
  allowed: readonly CaseReference[],
): StoredMessage {
  try {
    const r = fields(value, [
      'receipt',
      'event',
      'operationKey',
      'processingState',
      'associationVersion',
    ]);
    const receipt = fields(r.receipt, [
      'receiptId',
      'eventId',
      'messageId',
      'acceptanceSequence',
      'acceptedAt',
    ]);
    const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
    if (
      receipt.receiptId !== receiptId ||
      typeof receiptId !== 'string' ||
      !uuid.test(receiptId) ||
      typeof r.operationKey !== 'string' ||
      !uuid.test(r.operationKey)
    )
      throw new Error();
    const positive = (value: unknown) =>
      typeof value === 'string' &&
      /^[1-9][0-9]{0,18}(?![\s\S])/.test(value) &&
      BigInt(value) <= 9223372036854775807n;
    if (
      !positive(receipt.acceptanceSequence) ||
      !positive(r.associationVersion) ||
      typeof receipt.acceptedAt !== 'string' ||
      new Date(receipt.acceptedAt).toISOString() !== receipt.acceptedAt ||
      typeof r.processingState !== 'string' ||
      !['pending', 'running', 'dispatched', 'blocked', 'exhausted', 'uncertain'].includes(
        r.processingState,
      )
    )
      throw new Error();
    const event = r.event;
    if (!event || typeof event !== 'object' || Array.isArray(event)) throw new Error();
    const e: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
    for (const key of Reflect.ownKeys(event)) {
      if (typeof key !== 'string') throw new Error();
      const d = Object.getOwnPropertyDescriptor(event, key);
      if (!d || !('value' in d) || !d.enumerable) throw new Error();
      e[key] = d.value;
    }
    if (e.type !== 'text.received' || e.schemaVersion !== 1 || !e.accountScope || !e.caseId)
      throw new Error();
    const ref = reference({ scope: e.accountScope, caseId: e.caseId });
    if (!allowed.some((item) => sameReference(item, ref))) throw new RoutingError('AccessDenied');
    const input = { ...e };
    delete input.type;
    delete input.schemaVersion;
    const checked = produceTextEvent(input as TextEventInput, {
      providerScope: e.providerScope as TextEventInput['providerScope'],
      accountScope: ref.scope,
    });
    if (
      checked.event.type !== 'text.received' ||
      checked.event.eventId !== receipt.eventId ||
      checked.event.messageId !== receipt.messageId
    )
      throw new Error();
    // Revalidate all event data with the public codec. The accepted-input adapter,
    // rather than this data value, is responsible for authentication/persistence.
    return Object.freeze({ ...(value as StoredMessage), event: checked.event });
  } catch (error) {
    if (error instanceof RoutingError && error.code === 'AccessDenied') throw error;
    throw new RoutingError('InvalidAdapterResponse');
  }
}

const abortedGetter = Object.getOwnPropertyDescriptor(AbortSignal.prototype, 'aborted')!.get!;
export function checkedSignal(value: unknown): AbortSignal {
  try {
    if (typeof abortedGetter.call(value) !== 'boolean') throw new Error();
  } catch {
    throw new RoutingError('InvalidCommand');
  }
  return value as AbortSignal;
}
export function isAborted(value: AbortSignal): boolean {
  return abortedGetter.call(value) as boolean;
}
export function listenAbort(value: AbortSignal, listener: () => void): void {
  EventTarget.prototype.addEventListener.call(value, 'abort', listener, { once: true });
}
export function unlistenAbort(value: AbortSignal, listener: () => void): void {
  EventTarget.prototype.removeEventListener.call(value, 'abort', listener);
}
