import type { ProviderOperation, ProviderLookup, RecoveryController } from './send-policy-types.js';
/** Reply acceptance and ordinary send observations; never delivery, playback or consent. */
import { createHash } from 'node:crypto';
import type { AccountScope, ProviderScope } from './index.js';
import { fields, id, revision } from './routing-types.js';
export type OutboxCode =
  | 'InvalidCommand'
  | 'AccessDenied'
  | 'NotFound'
  | 'IdentityConflict'
  | 'RevisionConflict'
  | 'Overloaded'
  | 'UpgradeRequired'
  | 'Unavailable'
  | 'AcknowledgementUnknown'
  | 'OutcomeUnknown'
  | 'CleanupIncomplete'
  | 'Closed';
export class OutboxError extends Error {
  constructor(readonly code: OutboxCode) {
    super(code);
    this.name = 'OutboxError';
  }
}
export type OutboxPublisher = Readonly<{
  token: string;
  scope: AccountScope;
  caseId: string;
  conversationId: string;
}>;
export type ReplyDraft = Readonly<{
  schemaVersion: 1;
  outboundId: string;
  responseId: string;
  body: string;
}>;
export type ReplyEnvelope = ReplyDraft &
  Readonly<{ scope: AccountScope; caseId: string; conversationId: string }>;
export type OutboxReceipt = Readonly<{
  receiverId: string;
  receiptId: string;
  outboundId: string;
  intentDigest: string;
  bodyDigest: string;
  acceptedAt: string;
}>;
export type OutboundRoute = Readonly<{
  version: string;
  senderId: string | null;
  associationVersion: string | null;
  suppressed: boolean;
}>;
export type SendRequest = Readonly<{
  schemaVersion: 1;
  outboundId: string;
  attemptId: string;
  providerOperationKey: string;
  providerScope: ProviderScope;
  scope: AccountScope;
  caseId: string;
  conversationId: string;
  responseId: string;
  senderId: string;
  associationVersion: string;
  routeVersion: string;
  body: string;
}>;
export type CarrierResult =
  | Readonly<{
      schemaVersion: 1;
      attemptId: string;
      requestDigest: string;
      status: 'accepted_by_provider';
      providerMessageId: string;
    }>
  | Readonly<{
      schemaVersion: 1;
      attemptId: string;
      requestDigest: string;
      status: 'definitive_not_accepted';
    }>;
export type OrdinaryCarrierSendPort = Readonly<{
  capabilities: 'ordinary_fake_sms_v1';
  send(request: SendRequest, signal: AbortSignal): Promise<CarrierResult>;
}>;
export type IdempotentCarrierSendPort = Readonly<{
  capabilities: 'idempotent_fake_sms_v1';
  send(request: SendRequest, signal: AbortSignal): Promise<CarrierResult>;
  lookup(operation: ProviderOperation, signal: AbortSignal): Promise<ProviderLookup>;
}>;
export type CarrierSendPort = OrdinaryCarrierSendPort | IdempotentCarrierSendPort;
export type SendAttempt = Readonly<{
  request: SendRequest;
  requestDigest: string;
  reservedAt: string;
  result: CarrierResult | null;
  observedAt: string | null;
}>;
export type OutboxObservation = Readonly<{
  receipt: OutboxReceipt;
  reply: ReplyEnvelope;
  state: 'queued' | 'unknown' | 'accepted_by_provider' | 'definitive_not_accepted' | 'exhausted';
  attempts: readonly SendAttempt[];
}>;
export type SendOutcome =
  | Readonly<{
      status: 'held';
      reason: 'route_missing' | 'association_required' | 'suppressed';
      outboundId: string;
    }>
  | Readonly<{
      status: 'unknown' | 'accepted_by_provider' | 'definitive_not_accepted' | 'exhausted';
      outboundId: string;
      attemptId: string | null;
    }>;
export type OutboxEvent = Readonly<{
  event: 'completed' | 'rejected' | 'waiter_rejected' | 'closed';
  code:
    | 'queued'
    | 'replayed'
    | 'held'
    | 'unknown'
    | 'accepted_by_provider'
    | 'definitive_not_accepted'
    | 'exhausted'
    | 'unavailable'
    | 'rejected'
    | 'identity_conflict'
    | 'route_selected'
    | 'suppressed'
    | 'unsuppressed'
    | 'ok'
    | 'recovery_known'
    | 'recovery_unknown'
    | 'recovery_held'
    | 'recovery_conflicted'
    | 'recovery_replayed'
    | 'lookup_started'
    | 'retry_started';
}>;
export type OutboxOptions = Readonly<{
  maxActive?: number;
  timeoutMs?: number;
  cleanupMs?: number;
  recoveryControllers?: readonly RecoveryController[];
  observer?: (event: OutboxEvent) => void | Promise<void>;
}>;
export type OutboxLimits = Readonly<{ maxReplies: number; maxRoutes: number; maxAttempts: number }>;
export const DEFAULT_OUTBOX_LIMITS: OutboxLimits = Object.freeze({
  maxReplies: 1000,
  maxRoutes: 256,
  maxAttempts: 3,
});
export function outboxLimits(value: unknown): OutboxLimits {
  const p = record(value, ['maxReplies', 'maxRoutes', 'maxAttempts']);
  for (const [key, maximum] of [
    ['maxReplies', 10000],
    ['maxRoutes', 10000],
    ['maxAttempts', 5],
  ] as const)
    if (!Number.isSafeInteger(p[key]) || (p[key] as number) < 1 || (p[key] as number) > maximum)
      throw new OutboxError('InvalidCommand');
  return Object.freeze({
    maxReplies: p.maxReplies as number,
    maxRoutes: p.maxRoutes as number,
    maxAttempts: p.maxAttempts as number,
  });
}
export function record(value: unknown, keys: readonly string[]): Record<string, unknown> {
  try {
    return fields(value, keys);
  } catch {
    throw new OutboxError('InvalidCommand');
  }
}
export function identifier(value: unknown): string {
  try {
    return id(value);
  } catch {
    throw new OutboxError('InvalidCommand');
  }
}
export function decimal(value: unknown): string {
  try {
    return revision(value);
  } catch {
    throw new OutboxError('InvalidCommand');
  }
}
export function uuid(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/.test(value)
  )
    throw new OutboxError('InvalidCommand');
  return value;
}
export function sha(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}
export function text(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !value.length ||
    value.length > 4096 ||
    Buffer.byteLength(value, 'utf8') > 4096
  )
    throw new OutboxError('InvalidCommand');
  for (const c of value) {
    const n = c.codePointAt(0)!;
    if (n >= 0xd800 && n <= 0xdfff) throw new OutboxError('InvalidCommand');
  }
  return value;
}
export function draft(value: unknown): ReplyDraft {
  const p = record(value, ['schemaVersion', 'outboundId', 'responseId', 'body']);
  if (p.schemaVersion !== 1) throw new OutboxError('InvalidCommand');
  return Object.freeze({
    schemaVersion: 1,
    outboundId: uuid(p.outboundId),
    responseId: identifier(p.responseId),
    body: text(p.body),
  });
}
export function recipient(value: unknown): Omit<OutboxPublisher, 'token'> {
  const p = record(value, ['scope', 'caseId', 'conversationId']),
    s = record(p.scope, ['tenantId', 'accountId']);
  return Object.freeze({
    scope: Object.freeze({ tenantId: identifier(s.tenantId), accountId: identifier(s.accountId) }),
    caseId: identifier(p.caseId),
    conversationId: identifier(p.conversationId),
  });
}
export function envelope(value: unknown): ReplyEnvelope {
  const p = record(value, [
    'schemaVersion',
    'outboundId',
    'responseId',
    'body',
    'scope',
    'caseId',
    'conversationId',
  ]);
  return Object.freeze({
    ...draft({
      schemaVersion: p.schemaVersion,
      outboundId: p.outboundId,
      responseId: p.responseId,
      body: p.body,
    }),
    ...recipient({ scope: p.scope, caseId: p.caseId, conversationId: p.conversationId }),
  });
}
export function route(value: unknown): OutboundRoute {
  const p = record(value, ['version', 'senderId', 'associationVersion', 'suppressed']);
  if (
    typeof p.suppressed !== 'boolean' ||
    (p.senderId === null) !== (p.associationVersion === null)
  )
    throw new OutboxError('InvalidCommand');
  return Object.freeze({
    version: decimal(p.version),
    senderId: p.senderId === null ? null : identifier(p.senderId),
    associationVersion: p.associationVersion === null ? null : decimal(p.associationVersion),
    suppressed: p.suppressed,
  });
}
export function sendRequest(value: unknown): SendRequest {
  const p = record(value, [
      'schemaVersion',
      'outboundId',
      'attemptId',
      'providerOperationKey',
      'providerScope',
      'scope',
      'caseId',
      'conversationId',
      'responseId',
      'senderId',
      'associationVersion',
      'routeVersion',
      'body',
    ]),
    provider = record(p.providerScope, ['tenantId', 'provider', 'providerAccountId']),
    e = envelope({
      schemaVersion: p.schemaVersion,
      outboundId: p.outboundId,
      responseId: p.responseId,
      body: p.body,
      scope: p.scope,
      caseId: p.caseId,
      conversationId: p.conversationId,
    });
  if (
    provider.tenantId !== e.scope.tenantId ||
    decimal(p.associationVersion) === '0' ||
    decimal(p.routeVersion) === '0'
  )
    throw new OutboxError('InvalidCommand');
  return Object.freeze({
    ...e,
    attemptId: uuid(p.attemptId),
    providerOperationKey: uuid(p.providerOperationKey),
    providerScope: Object.freeze({
      tenantId: e.scope.tenantId,
      provider: identifier(provider.provider),
      providerAccountId: identifier(provider.providerAccountId),
    }),
    senderId: identifier(p.senderId),
    associationVersion: decimal(p.associationVersion),
    routeVersion: decimal(p.routeVersion),
  });
}
export function carrierResult(value: unknown, request: SendRequest): CarrierResult {
  const head = record(
    value,
    Object.getOwnPropertyDescriptor(Object(value), 'status')?.value === 'accepted_by_provider'
      ? ['schemaVersion', 'attemptId', 'requestDigest', 'status', 'providerMessageId']
      : ['schemaVersion', 'attemptId', 'requestDigest', 'status'],
  );
  if (
    head.schemaVersion !== 1 ||
    head.attemptId !== request.attemptId ||
    head.requestDigest !== sha(JSON.stringify(request))
  )
    throw new OutboxError('OutcomeUnknown');
  if (head.status === 'accepted_by_provider')
    return Object.freeze({
      schemaVersion: 1,
      attemptId: request.attemptId,
      requestDigest: head.requestDigest as string,
      status: 'accepted_by_provider',
      providerMessageId: identifier(head.providerMessageId),
    });
  if (head.status !== 'definitive_not_accepted') throw new OutboxError('OutcomeUnknown');
  return Object.freeze({
    schemaVersion: 1,
    attemptId: request.attemptId,
    requestDigest: head.requestDigest as string,
    status: 'definitive_not_accepted',
  });
}
export function timestamp(value: unknown): string {
  if (!(value instanceof Date) || !Number.isFinite(value.getTime()))
    throw new OutboxError('Unavailable');
  return value.toISOString();
}
export function safe(error: unknown, fallback: OutboxCode = 'Unavailable'): OutboxError {
  const p =
    error instanceof OutboxError ? Object.getOwnPropertyDescriptor(error, 'code') : undefined;
  return new OutboxError(
    p &&
      'value' in p &&
      typeof p.value === 'string' &&
      [
        'InvalidCommand',
        'AccessDenied',
        'NotFound',
        'IdentityConflict',
        'RevisionConflict',
        'Overloaded',
        'UpgradeRequired',
        'Unavailable',
        'AcknowledgementUnknown',
        'OutcomeUnknown',
        'CleanupIncomplete',
        'Closed',
      ].includes(p.value)
      ? (p.value as OutboxCode)
      : fallback,
  );
}
