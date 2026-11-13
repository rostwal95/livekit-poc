/** Closed browser-only Parent v1 wire. Never accepts internal service capabilities. */
import { parseBusinessJson } from './business';
import { JoinedUiError } from './channel-policy-contract';
import type { PolicySummary } from './channel-policy-contract';
export const UI_LIMITS = Object.freeze({
  responseBytes: 16384,
  requestBytes: 32768,
  httpMs: 15000,
  closeMs: 5000,
});
export const PURPOSES = ['status', 'start', 'end', 'current', 'case', 'progress', 'sms'] as const;
export type Purpose = (typeof PURPOSES)[number];
export type Code =
  | 'invalid_input'
  | 'unauthorized'
  | 'conflict'
  | 'closed'
  | 'recovery_required'
  | 'capacity'
  | 'unavailable'
  | 'outcome_unknown'
  | 'cleanup_incomplete';
export interface StartCommand {
  readonly schemaVersion: 1;
  readonly ownerEpoch: string;
  readonly expectedGeneration: string;
  readonly commandId: string;
}
export interface EndCommand {
  readonly schemaVersion: 1;
  readonly ownerEpoch: string;
  readonly generation: string;
  readonly originalStartCommandId: string;
}
export interface SmsCommand {
  readonly schemaVersion: 1;
  readonly commandId: string;
  readonly occurredAt: string;
  readonly body: string;
}
export interface RoomStatus {
  readonly schemaVersion: 1;
  readonly ownerEpoch: string;
  readonly generation: string;
  readonly originalStartCommandId: string | null;
  readonly stage:
    'idle' | 'preparing' | 'waiting_browser' | 'ready' | 'closing' | 'closed' | 'recovery_required';
  readonly asOf: string;
  readonly nodeCursor: Readonly<{
    nodeEpoch: string;
    generation: string;
    recoveryRequired: boolean;
    endpoint: Readonly<{ host: '127.0.0.1'; port: number }>;
  }>;
  readonly sdkReady: boolean;
  readonly workerRunning: boolean;
  readonly expiresAt: string | null;
}
export interface RoomGrant extends Omit<EndCommand, 'schemaVersion'> {
  readonly schemaVersion: 1;
  readonly mode: 'scripted' | 'provider_real';
  readonly stage: 'waiting_browser';
  readonly rtc: Readonly<{
    url: string;
    token: string;
    roomId: string;
    participantId: string;
    agentId: string;
    bindingId: string;
    expiresAt: string;
  }>;
}
export interface CurrentView extends EndCommand {
  readonly fact: PolicySummary;
}
export interface CaseView {
  readonly schemaVersion: 1;
  readonly case: Readonly<{ revision: string; observedAt: string }>;
}
export interface ProgressView {
  readonly schemaVersion: 1;
  readonly asOf: string;
  readonly counts: Readonly<
    Record<
      | 'native'
      | 'sms'
      | 'pending'
      | 'running'
      | 'dispatched'
      | 'blocked'
      | 'exhausted'
      | 'uncertain'
      | 'workKnown',
      number
    >
  >;
}
export interface SmsReceipt {
  readonly schemaVersion: 1;
  readonly commandId: string;
  readonly replayed: boolean;
  readonly receipt: Readonly<{
    receiptId: string;
    eventId: string;
    messageId: string;
    acceptanceSequence: string;
    acceptedAt: string;
  }>;
}
const UTF8 = new TextEncoder();
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
function invalid(): never {
  throw new JoinedUiError('invalid');
}
export function closed(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    return invalid();
  const own = Object.getOwnPropertyDescriptors(value);
  const names = Reflect.ownKeys(own);
  if (
    names.length !== keys.length ||
    names.some((k) => typeof k !== 'string' || !keys.includes(k)) ||
    keys.some((k) => !Object.hasOwn(own, k) || !Object.hasOwn(own[k]!, 'value'))
  )
    return invalid();
  return Object.fromEntries(keys.map((k) => [k, own[k]!.value as unknown]));
}
export function uuid(value: unknown): string {
  if (typeof value !== 'string' || !UUID.test(value)) return invalid();
  return value;
}
export function decimal(value: unknown, max = 9223372036854775807n, zero = true): string {
  if (
    typeof value !== 'string' ||
    !/^(0|[1-9][0-9]{0,18})$/u.test(value) ||
    BigInt(value) > max ||
    (!zero && value === '0')
  )
    return invalid();
  return value;
}
export function instant(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/u.test(value) ||
    !Number.isFinite(Date.parse(value)) ||
    new Date(value).toISOString() !== value
  )
    return invalid();
  return value;
}
function boolean(value: unknown): boolean {
  if (typeof value !== 'boolean') return invalid();
  return value;
}
function rtcUrl(value: unknown): string {
  if (typeof value !== 'string') return invalid();
  const match = /^ws:\/\/127\.0\.0\.1:([1-9][0-9]{0,4})$/u.exec(value);
  if (!match || Number(match[1]) > 65535) return invalid();
  return value;
}
function identity(value: unknown): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u.test(value))
    return invalid();
  return value;
}
function schema(row: Record<string, unknown>): void {
  if (row.schemaVersion !== 1) return invalid();
}
export function json(text: string): unknown {
  try {
    if (UTF8.encode(text).length > UI_LIMITS.responseBytes) return invalid();
    return parseBusinessJson(text);
  } catch {
    return invalid();
  }
}
export function startCommand(value: unknown): StartCommand {
  const row = closed(value, ['schemaVersion', 'ownerEpoch', 'expectedGeneration', 'commandId']);
  schema(row);
  return Object.freeze({
    schemaVersion: 1,
    ownerEpoch: uuid(row.ownerEpoch),
    expectedGeneration: decimal(row.expectedGeneration, 1000000n),
    commandId: uuid(row.commandId),
  });
}
export function endCommand(value: unknown): EndCommand {
  const row = closed(value, [
    'schemaVersion',
    'ownerEpoch',
    'generation',
    'originalStartCommandId',
  ]);
  schema(row);
  return Object.freeze({
    schemaVersion: 1,
    ownerEpoch: uuid(row.ownerEpoch),
    generation: decimal(row.generation, 1000000n, false),
    originalStartCommandId: uuid(row.originalStartCommandId),
  });
}
export function smsCommand(value: unknown): SmsCommand {
  const row = closed(value, ['schemaVersion', 'commandId', 'occurredAt', 'body']);
  schema(row);
  if (
    typeof row.body !== 'string' ||
    !row.body.trim() ||
    row.body.length > 4096 ||
    UTF8.encode(row.body).length > 4096 ||
    new TextDecoder().decode(UTF8.encode(row.body)) !== row.body
  )
    return invalid();
  return Object.freeze({
    schemaVersion: 1,
    commandId: uuid(row.commandId),
    occurredAt: instant(row.occurredAt),
    body: row.body,
  });
}
export function parseStatus(value: unknown): RoomStatus {
  const r = closed(value, [
    'schemaVersion',
    'ownerEpoch',
    'generation',
    'originalStartCommandId',
    'stage',
    'asOf',
    'nodeCursor',
    'sdkReady',
    'workerRunning',
    'expiresAt',
  ]);
  schema(r);
  const stage = r.stage;
  if (
    typeof stage !== 'string' ||
    ![
      'idle',
      'preparing',
      'waiting_browser',
      'ready',
      'closing',
      'closed',
      'recovery_required',
    ].includes(stage)
  )
    return invalid();
  const n = closed(r.nodeCursor, ['nodeEpoch', 'generation', 'recoveryRequired', 'endpoint']);
  const ep = closed(n.endpoint, ['host', 'port']);
  if (
    ep.host !== '127.0.0.1' ||
    typeof ep.port !== 'number' ||
    !Number.isInteger(ep.port) ||
    ep.port < 1 ||
    ep.port > 65535
  )
    return invalid();
  const generation = decimal(r.generation, 1000000n),
    command = r.originalStartCommandId === null ? null : uuid(r.originalStartCommandId),
    sdkReady = boolean(r.sdkReady),
    workerRunning = boolean(r.workerRunning);
  if (
    (generation === '0') !== (command === null) ||
    (sdkReady && (stage !== 'ready' || !workerRunning)) ||
    (['idle', 'closed'].includes(stage) && (sdkReady || workerRunning))
  )
    return invalid();
  return Object.freeze({
    schemaVersion: 1,
    ownerEpoch: uuid(r.ownerEpoch),
    generation,
    originalStartCommandId: command,
    stage: stage as RoomStatus['stage'],
    asOf: instant(r.asOf),
    nodeCursor: Object.freeze({
      nodeEpoch: uuid(n.nodeEpoch),
      generation: decimal(n.generation, 1000000n),
      recoveryRequired: boolean(n.recoveryRequired),
      endpoint: Object.freeze({ host: '127.0.0.1', port: ep.port }),
    }),
    sdkReady,
    workerRunning,
    expiresAt: r.expiresAt === null ? null : instant(r.expiresAt),
  });
}
export function parseGrant(value: unknown, expected: StartCommand): RoomGrant {
  const r = closed(value, [
    'schemaVersion',
    'ownerEpoch',
    'generation',
    'originalStartCommandId',
    'mode',
    'stage',
    'rtc',
  ]);
  schema(r);
  const rtc = closed(r.rtc, [
    'url',
    'token',
    'roomId',
    'participantId',
    'agentId',
    'bindingId',
    'expiresAt',
  ]);
  const generation = decimal(r.generation, 1000000n, false);
  if (
    r.ownerEpoch !== expected.ownerEpoch ||
    r.originalStartCommandId !== expected.commandId ||
    BigInt(generation) !== BigInt(expected.expectedGeneration) + 1n ||
    (r.mode !== 'scripted' && r.mode !== 'provider_real') ||
    r.stage !== 'waiting_browser' ||
    typeof rtc.token !== 'string' ||
    rtc.token.length > 8192 ||
    !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/u.test(rtc.token) ||
    rtc.participantId === rtc.agentId
  )
    return invalid();
  return Object.freeze({
    schemaVersion: 1,
    ownerEpoch: uuid(r.ownerEpoch),
    generation,
    originalStartCommandId: uuid(r.originalStartCommandId),
    mode: r.mode,
    stage: 'waiting_browser',
    rtc: Object.freeze({
      url: rtcUrl(rtc.url),
      token: rtc.token,
      roomId: identity(rtc.roomId),
      participantId: identity(rtc.participantId),
      agentId: identity(rtc.agentId),
      bindingId: uuid(rtc.bindingId),
      expiresAt: instant(rtc.expiresAt),
    }),
  });
}
export function parseFact(value: unknown): PolicySummary {
  const r = closed(value, ['state', 'eligible', 'uncertainty', 'revision', 'asOf']);
  if (r.state === 'unavailable') {
    if (r.eligible !== null || r.uncertainty !== null || r.revision !== null || r.asOf !== null)
      return invalid();
    return Object.freeze({
      state: 'unavailable',
      eligible: null,
      uncertainty: null,
      revision: null,
      asOf: null,
    });
  }
  if (r.state === 'no_delivery' || r.state === 'not_applicable') {
    if (r.eligible !== null || r.uncertainty !== null || r.revision !== null) return invalid();
    return Object.freeze({
      state: r.state,
      eligible: null,
      uncertainty: null,
      revision: null,
      asOf: instant(r.asOf),
    });
  }
  if (
    r.state !== 'current' ||
    !['none', 'missing', 'conflicting'].includes(r.uncertainty as string) ||
    (r.eligible !== null && typeof r.eligible !== 'boolean') ||
    (r.uncertainty === 'none') !== (r.eligible !== null)
  )
    return invalid();
  return Object.freeze({
    state: 'current',
    eligible: r.eligible as boolean | null,
    uncertainty: r.uncertainty as 'none' | 'missing' | 'conflicting',
    revision: decimal(r.revision, 9223372036854775807n, false),
    asOf: instant(r.asOf),
  });
}
export function parseCurrent(value: unknown, expected: EndCommand): CurrentView {
  const r = closed(value, [
    'schemaVersion',
    'ownerEpoch',
    'generation',
    'originalStartCommandId',
    'fact',
  ]);
  const binding = endCommand(Object.fromEntries(Object.entries(r).filter(([k]) => k !== 'fact')));
  if (
    binding.ownerEpoch !== expected.ownerEpoch ||
    binding.generation !== expected.generation ||
    binding.originalStartCommandId !== expected.originalStartCommandId
  )
    return invalid();
  return Object.freeze({ ...binding, fact: parseFact(r.fact) });
}
export function parseCase(value: unknown): CaseView {
  const r = closed(value, ['schemaVersion', 'case']);
  schema(r);
  const c = closed(r.case, ['revision', 'observedAt']);
  return Object.freeze({
    schemaVersion: 1,
    case: Object.freeze({
      revision: decimal(c.revision),
      observedAt: instant(c.observedAt),
    }),
  });
}
export function parseProgress(value: unknown): ProgressView {
  const r = closed(value, ['schemaVersion', 'asOf', 'counts']);
  schema(r);
  const names = [
    'native',
    'sms',
    'pending',
    'running',
    'dispatched',
    'blocked',
    'exhausted',
    'uncertain',
    'workKnown',
  ] as const;
  const c = closed(r.counts, names);
  for (const key of names)
    if (
      typeof c[key] !== 'number' ||
      !Number.isInteger(c[key]) ||
      (c[key] as number) < 0 ||
      (c[key] as number) > 16
    )
      return invalid();
  const counts = c as Record<(typeof names)[number], number>;
  if (
    counts.native + counts.sms > 16 ||
    counts.native + counts.sms !==
      counts.pending +
        counts.running +
        counts.dispatched +
        counts.blocked +
        counts.exhausted +
        counts.uncertain ||
    counts.workKnown > counts.dispatched + counts.uncertain
  )
    return invalid();
  return Object.freeze({
    schemaVersion: 1,
    asOf: instant(r.asOf),
    counts: Object.freeze({ ...counts }),
  });
}
export function parseSms(value: unknown, expected: SmsCommand): SmsReceipt {
  const r = closed(value, ['schemaVersion', 'commandId', 'replayed', 'receipt']);
  schema(r);
  const q = closed(r.receipt, [
    'receiptId',
    'eventId',
    'messageId',
    'acceptanceSequence',
    'acceptedAt',
  ]);
  const event = 'cp_sms_' + expected.commandId.replaceAll('-', '');
  if (r.commandId !== expected.commandId || q.eventId !== event || q.messageId !== event)
    return invalid();
  return Object.freeze({
    schemaVersion: 1,
    commandId: uuid(r.commandId),
    replayed: boolean(r.replayed),
    receipt: Object.freeze({
      receiptId: uuid(q.receiptId),
      eventId: event,
      messageId: event,
      acceptanceSequence: decimal(q.acceptanceSequence, 9223372036854775807n, false),
      acceptedAt: instant(q.acceptedAt),
    }),
  });
}
export function errorCode(value: unknown, status: number): Code {
  const r = closed(value, ['schemaVersion', 'status', 'code']);
  schema(r);
  const codes: Record<number, readonly string[]> = {
    400: ['invalid_input'],
    403: ['unauthorized'],
    409: ['conflict', 'closed', 'recovery_required'],
    429: ['capacity'],
    503: ['unavailable', 'outcome_unknown', 'cleanup_incomplete'],
  };
  if (r.status !== 'unavailable' || typeof r.code !== 'string' || !codes[status]?.includes(r.code))
    return invalid();
  return r.code as Code;
}
export function safeCode(
  error: unknown,
  fallback: 'unknown' | 'unavailable' = 'unavailable',
): JoinedUiError {
  let descriptor: PropertyDescriptor | undefined;
  try {
    descriptor =
      error && typeof error === 'object'
        ? Object.getOwnPropertyDescriptor(error, 'code')
        : undefined;
  } catch {
    return new JoinedUiError(fallback);
  }
  const code =
    descriptor && Object.hasOwn(descriptor, 'value') ? (descriptor.value as unknown) : null;
  const mapped: Record<string, import('./channel-policy-contract').UiCode> = {
    invalid: 'invalid',
    invalid_input: 'invalid',
    unauthorized: 'denied',
    denied: 'denied',
    conflict: 'conflict',
    closed: 'conflict',
    recovery_required: 'conflict',
    capacity: 'capacity',
    unavailable: 'unavailable',
    unknown: 'unknown',
    outcome_unknown: 'unknown',
    cleanup_incomplete: 'cleanup_incomplete',
  };
  return new JoinedUiError(
    typeof code === 'string' && Object.hasOwn(mapped, code) ? mapped[code]! : fallback,
  );
}

export function encodeRequest(purpose: Purpose, value: unknown): string {
  let payload: unknown;
  if (purpose === 'start') payload = startCommand(value);
  else if (purpose === 'end' || purpose === 'current') payload = endCommand(value);
  else if (purpose === 'sms') payload = smsCommand(value);
  else {
    const row = closed(value, ['schemaVersion']);
    schema(row);
    payload = Object.freeze({ schemaVersion: 1 });
  }
  const raw = JSON.stringify(payload);
  if (UTF8.encode(raw).length > UI_LIMITS.requestBytes) return invalid();
  return raw;
}
