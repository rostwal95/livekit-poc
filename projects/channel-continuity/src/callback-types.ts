/** Authenticated provider reports are retained evidence, never recipient consent or resend authority. */
import type { ProviderScope } from './index.js';
import type { CarrierResult } from './outbox-types.js';
import { record, identifier, uuid, sha } from './outbox-types.js';
export const CALLBACK_STATES = [
  'accepted_by_provider',
  'delivered',
  'failed',
  'unknown',
  'read_reported',
] as const;
export type CallbackState = (typeof CALLBACK_STATES)[number];
export type CallbackObservation = Readonly<{
  schemaVersion: 1;
  eventId: string;
  attemptId: string;
  providerOperationKey: string;
  requestDigest: string;
  providerMessageId: string;
  state: CallbackState;
  occurredAt: string;
}>;
export type CallbackReceipt = Readonly<{
  receiptId: string;
  eventId: string;
  attemptId: string;
  payloadDigest: string;
  acceptedAt: string;
}>;
export type RetainedCallback = Readonly<{
  observation: CallbackObservation;
  receipt: CallbackReceipt;
}>;
export type CallbackEvidence = Readonly<{
  rule: 'fake_sms_delivery_evidence_v1';
  strongestReported: CallbackState | 'none';
  assessment: 'none' | 'reported' | 'conflicted';
  reportedFailure: boolean;
  reportedUnknown: boolean;
  providerMessageIds: readonly string[];
  conflicts: readonly ('terminal_reports' | 'provider_identity' | 'send_result')[];
  sendResult: CarrierResult | null;
}>;
export type CallbackAttempt = Readonly<{
  outboundId: string;
  attemptId: string;
  requestDigest: string;
  providerOperationKey: string;
  observations: readonly RetainedCallback[];
  evidence: CallbackEvidence;
}>;
export type CallbackLimits = Readonly<{ maxGlobal: number; maxPerAttempt: number }>;
export const DEFAULT_CALLBACK_LIMITS: CallbackLimits = Object.freeze({
  maxGlobal: 10000,
  maxPerAttempt: 8,
});
export type CallbackCode =
  | 'InvalidCommand'
  | 'WebhookRejected'
  | 'AccessDenied'
  | 'NotFound'
  | 'IdentityConflict'
  | 'Overloaded'
  | 'UpgradeRequired'
  | 'Unavailable'
  | 'AcknowledgementUnknown'
  | 'CleanupIncomplete'
  | 'Closed';
const CODES: readonly string[] = [
  'InvalidCommand',
  'WebhookRejected',
  'AccessDenied',
  'NotFound',
  'IdentityConflict',
  'Overloaded',
  'UpgradeRequired',
  'Unavailable',
  'AcknowledgementUnknown',
  'CleanupIncomplete',
  'Closed',
];
export class CallbackError extends Error {
  constructor(readonly code: CallbackCode) {
    super(code);
    this.name = 'CallbackError';
  }
}
export function safeCallback(
  error: unknown,
  fallback: CallbackCode = 'Unavailable',
): CallbackError {
  const d =
    error instanceof CallbackError ? Object.getOwnPropertyDescriptor(error, 'code') : undefined;
  return new CallbackError(
    d && 'value' in d && typeof d.value === 'string' && CODES.includes(d.value)
      ? (d.value as CallbackCode)
      : fallback,
  );
}
export function callbackLimits(value: unknown): CallbackLimits {
  try {
    const p = record(value, ['maxGlobal', 'maxPerAttempt']);
    for (const [k, max] of [
      ['maxGlobal', 100000],
      ['maxPerAttempt', 32],
    ] as const)
      if (!Number.isSafeInteger(p[k]) || (p[k] as number) < 1 || (p[k] as number) > max)
        throw Error();
    return Object.freeze({
      maxGlobal: p.maxGlobal as number,
      maxPerAttempt: p.maxPerAttempt as number,
    });
  } catch {
    throw new CallbackError('InvalidCommand');
  }
}
export const CALLBACK_KEYS = [
  'schemaVersion',
  'eventId',
  'attemptId',
  'providerOperationKey',
  'requestDigest',
  'providerMessageId',
  'state',
  'occurredAt',
] as const;
export function callbackObservation(value: unknown): CallbackObservation {
  try {
    const p = record(value, CALLBACK_KEYS);
    if (
      p.schemaVersion !== 1 ||
      typeof p.requestDigest !== 'string' ||
      !/^[a-f0-9]{64}(?![\s\S])/.test(p.requestDigest) ||
      typeof p.state !== 'string' ||
      !(CALLBACK_STATES as readonly string[]).includes(p.state) ||
      typeof p.occurredAt !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z(?![\s\S])/.test(p.occurredAt) ||
      !Number.isFinite(Date.parse(p.occurredAt)) ||
      new Date(p.occurredAt).toISOString() !== p.occurredAt
    )
      throw Error();
    return Object.freeze({
      schemaVersion: 1,
      eventId: identifier(p.eventId),
      attemptId: uuid(p.attemptId),
      providerOperationKey: uuid(p.providerOperationKey),
      requestDigest: p.requestDigest,
      providerMessageId: identifier(p.providerMessageId),
      state: p.state as CallbackState,
      occurredAt: p.occurredAt,
    });
  } catch {
    throw new CallbackError('InvalidCommand');
  }
}
export function callbackScope(value: unknown): ProviderScope {
  try {
    const p = record(value, ['tenantId', 'provider', 'providerAccountId']);
    if (p.provider !== 'fake_sms') throw Error();
    return Object.freeze({
      tenantId: identifier(p.tenantId),
      provider: 'fake_sms',
      providerAccountId: identifier(p.providerAccountId),
    });
  } catch {
    throw new CallbackError('InvalidCommand');
  }
}
export function callbackDigest(value: CallbackObservation): string {
  return sha(JSON.stringify(callbackObservation(value)));
}
/** Commutative provider rule: timestamps and arrival order never select a winner. */
export function reduceCallbackEvidence(
  observations: readonly CallbackObservation[],
  sendResult: CarrierResult | null,
): CallbackEvidence {
  let normalized: CallbackObservation[] = [];
  try {
    if (
      !Array.isArray(observations) ||
      Object.getPrototypeOf(observations) !== Array.prototype ||
      Object.getOwnPropertySymbols(observations).length
    )
      throw Error();
    const d = Object.getOwnPropertyDescriptors(observations) as unknown as Record<
        string,
        PropertyDescriptor
      >,
      length = d.length?.value;
    if (
      !Number.isSafeInteger(length) ||
      length < 0 ||
      length > 32 ||
      Object.keys(d).length !== length + 1
    )
      throw Error();
    for (let i = 0; i < length; i++) {
      const entry = d[String(i)];
      if (!entry || !('value' in entry) || !entry.enumerable) throw Error();
      normalized.push(callbackObservation(entry.value));
    }
  } catch {
    throw new CallbackError('InvalidCommand');
  }
  const original = normalized[0];
  if (
    normalized.some(
      (x) =>
        x.attemptId !== original?.attemptId ||
        x.providerOperationKey !== original?.providerOperationKey ||
        x.requestDigest !== original?.requestDigest,
    )
  )
    throw new CallbackError('InvalidCommand');
  let result: CarrierResult | null = null;
  if (sendResult !== null) {
    try {
      const d = Object.getOwnPropertyDescriptor(sendResult, 'status'),
        p = record(
          sendResult,
          d?.value === 'accepted_by_provider'
            ? ['schemaVersion', 'attemptId', 'requestDigest', 'status', 'providerMessageId']
            : ['schemaVersion', 'attemptId', 'requestDigest', 'status'],
        );
      if (
        p.schemaVersion !== 1 ||
        typeof p.requestDigest !== 'string' ||
        !/^[a-f0-9]{64}(?![\s\S])/.test(p.requestDigest) ||
        !['accepted_by_provider', 'definitive_not_accepted'].includes(p.status as string)
      )
        throw Error();
      const attemptId = uuid(p.attemptId);
      if (
        original &&
        (attemptId !== original.attemptId || p.requestDigest !== original.requestDigest)
      )
        throw Error();
      result = Object.freeze(
        p.status === 'accepted_by_provider'
          ? {
              schemaVersion: 1,
              attemptId,
              requestDigest: p.requestDigest,
              status: 'accepted_by_provider',
              providerMessageId: identifier(p.providerMessageId),
            }
          : {
              schemaVersion: 1,
              attemptId,
              requestDigest: p.requestDigest,
              status: 'definitive_not_accepted',
            },
      );
    } catch {
      throw new CallbackError('InvalidCommand');
    }
  }
  sendResult = result;
  const states = new Set(normalized.map((x) => x.state)),
    ids = [...new Set(normalized.map((x) => x.providerMessageId))].sort(),
    conflicts: ('terminal_reports' | 'provider_identity' | 'send_result')[] = [];
  if (states.has('failed') && (states.has('delivered') || states.has('read_reported')))
    conflicts.push('terminal_reports');
  if (
    ids.length > 1 ||
    (sendResult?.status === 'accepted_by_provider' &&
      ids.some((x) => x !== sendResult.providerMessageId))
  )
    conflicts.push('provider_identity');
  if (
    sendResult?.status === 'definitive_not_accepted' &&
    normalized.some((x) => ['accepted_by_provider', 'delivered', 'read_reported'].includes(x.state))
  )
    conflicts.push('send_result');
  const strongest =
    (['read_reported', 'delivered', 'failed', 'accepted_by_provider', 'unknown'] as const).find(
      (x) => states.has(x),
    ) ?? 'none';
  return Object.freeze({
    rule: 'fake_sms_delivery_evidence_v1',
    strongestReported: strongest,
    assessment: conflicts.length ? 'conflicted' : normalized.length ? 'reported' : 'none',
    reportedFailure: states.has('failed'),
    reportedUnknown: states.has('unknown'),
    providerMessageIds: Object.freeze(ids),
    conflicts: Object.freeze(conflicts),
    sendResult,
  });
}
export type CallbackEvent = Readonly<{
  event: 'accepted' | 'replayed' | 'rejected' | 'waiter_rejected' | 'closed';
  code:
    | 'ok'
    | 'identity_conflict'
    | 'webhook_rejected'
    | 'overloaded'
    | 'unknown'
    | 'unavailable'
    | 'rejected';
}>;
export type CallbackOptions = Readonly<{
  timeoutMs?: number;
  cleanupMs?: number;
  observer?: (event: CallbackEvent) => void | Promise<void>;
}>;
