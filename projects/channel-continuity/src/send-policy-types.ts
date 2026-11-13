/** Explicit same-operation recovery; provider acceptance is not physical delivery or consent. */
import type { ProviderScope, AccountScope } from './index.js';
import {
  OutboxError,
  record,
  identifier,
  uuid,
  sha,
  text,
  sendRequest,
  type SendRequest,
  type OutboxPublisher,
} from './outbox-types.js';
export type SendCapability = 'ordinary_fake_sms_v1' | 'idempotent_fake_sms_v1';
export type ProviderOperation = Readonly<{
  schemaVersion: 1;
  capability: SendCapability;
  providerScope: ProviderScope;
  scope: AccountScope;
  caseId: string;
  conversationId: string;
  outboundId: string;
  responseId: string;
  providerOperationKey: string;
  senderId: string;
  body: string;
}>;
export type ProviderLookup = Readonly<{
  schemaVersion: 1;
  providerScope: ProviderScope;
  providerOperationKey: string;
  operationDigest: string;
  state: 'accepted_by_provider' | 'definitive_not_accepted' | 'absent' | 'unknown';
  providerMessageId: string | null;
}>;
export type RecoveryController = OutboxPublisher;
export type SendPolicyLimits = Readonly<{ maxRecoveryCommands: number; maxPerOperation: number }>;
export const DEFAULT_SEND_POLICY_LIMITS: SendPolicyLimits = Object.freeze({
  maxRecoveryCommands: 10000,
  maxPerOperation: 8,
});
export type RecoveryCode =
  | 'lookup'
  | 'retry_reserved'
  | 'known_accepted'
  | 'known_not_accepted'
  | 'ordinary_no_resend'
  | 'callback_veto'
  | 'route_missing'
  | 'association_required'
  | 'suppressed'
  | 'route_changed'
  | 'attempt_exhausted'
  | 'conflicted'
  | 'prior_operation_evidence';
export type RecoveryKind = 'reconcile' | 'retry';
export type RecoveryReceipt = Readonly<{
  schemaVersion: 1;
  receiptId: string;
  commandId: string;
  kind: RecoveryKind;
  outboundId: string;
  sourceAttemptId: string;
  providerOperationKey: string;
  operationDigest: string;
  decision: 'lookup_authorized' | 'retry_reserved' | 'held' | 'terminal';
  code: RecoveryCode;
  newAttemptId: string | null;
  acceptedAt: string;
}>;
export type RecoveryObservation = Readonly<{
  schemaVersion: 1;
  commandId: string;
  providerOperationKey: string;
  operationDigest: string;
  source: 'lookup' | 'send' | 'policy';
  state: ProviderLookup['state'];
  assessment: 'reported' | 'conflicted';
  providerMessageId: string | null;
  observedAt: string;
}>;
export type RecoveryCommandView = Readonly<{
  receipt: RecoveryReceipt;
  observation: RecoveryObservation | null;
}>;
export type RecoverySummary = Readonly<{
  outboundId: string;
  operations: readonly Readonly<{
    providerOperationKey: string;
    operationDigest: string;
    capability: SendCapability;
    firstAttemptId: string;
    state: 'accepted_by_provider' | 'definitive_not_accepted' | 'unknown' | 'conflicted';
    providerMessageIdsSample: readonly string[];
    providerMessageIdCount: number;
    callbackVeto: boolean;
    commandCount: number;
    latestCommandId: string | null;
  }>[];
}>;
export function capability(value: unknown): SendCapability {
  if (value !== 'ordinary_fake_sms_v1' && value !== 'idempotent_fake_sms_v1')
    throw new OutboxError('InvalidCommand');
  return value;
}
export function sendPolicyLimits(value: unknown): SendPolicyLimits {
  const p = record(value, ['maxRecoveryCommands', 'maxPerOperation']);
  for (const [k, max] of [
    ['maxRecoveryCommands', 100000],
    ['maxPerOperation', 32],
  ] as const)
    if (!Number.isSafeInteger(p[k]) || (p[k] as number) < 1 || (p[k] as number) > max)
      throw new OutboxError('InvalidCommand');
  return Object.freeze({
    maxRecoveryCommands: p.maxRecoveryCommands as number,
    maxPerOperation: p.maxPerOperation as number,
  });
}
export function hashValue(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-f0-9]{64}(?![\s\S])/.test(value))
    throw new OutboxError('InvalidCommand');
  return value;
}
export function iso(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z(?![\s\S])/.test(value) ||
    !Number.isFinite(Date.parse(value)) ||
    new Date(value).toISOString() !== value
  )
    throw new OutboxError('InvalidCommand');
  return value;
}
export function operation(value: unknown): ProviderOperation {
  const p = record(value, [
      'schemaVersion',
      'capability',
      'providerScope',
      'scope',
      'caseId',
      'conversationId',
      'outboundId',
      'responseId',
      'providerOperationKey',
      'senderId',
      'body',
    ]),
    s = record(p.scope, ['tenantId', 'accountId']),
    provider = record(p.providerScope, ['tenantId', 'provider', 'providerAccountId']);
  if (p.schemaVersion !== 1 || s.tenantId !== provider.tenantId || provider.provider !== 'fake_sms')
    throw new OutboxError('InvalidCommand');
  return Object.freeze({
    schemaVersion: 1,
    capability: capability(p.capability),
    providerScope: Object.freeze({
      tenantId: identifier(provider.tenantId),
      provider: identifier(provider.provider),
      providerAccountId: identifier(provider.providerAccountId),
    }),
    scope: Object.freeze({ tenantId: identifier(s.tenantId), accountId: identifier(s.accountId) }),
    caseId: identifier(p.caseId),
    conversationId: identifier(p.conversationId),
    outboundId: uuid(p.outboundId),
    responseId: identifier(p.responseId),
    providerOperationKey: uuid(p.providerOperationKey),
    senderId: identifier(p.senderId),
    body: text(p.body),
  });
}
export function operationFrom(request: SendRequest, mode: SendCapability): ProviderOperation {
  const r = sendRequest(request);
  return operation({
    schemaVersion: 1,
    capability: mode,
    providerScope: r.providerScope,
    scope: r.scope,
    caseId: r.caseId,
    conversationId: r.conversationId,
    outboundId: r.outboundId,
    responseId: r.responseId,
    providerOperationKey: r.providerOperationKey,
    senderId: r.senderId,
    body: r.body,
  });
}
export function operationDigest(value: ProviderOperation): string {
  return sha(JSON.stringify(operation(value)));
}
export function lookup(value: unknown, expected: ProviderOperation): ProviderLookup {
  const p = record(value, [
      'schemaVersion',
      'providerScope',
      'providerOperationKey',
      'operationDigest',
      'state',
      'providerMessageId',
    ]),
    s = record(p.providerScope, ['tenantId', 'provider', 'providerAccountId']);
  if (
    p.schemaVersion !== 1 ||
    JSON.stringify(s) !== JSON.stringify(expected.providerScope) ||
    p.providerOperationKey !== expected.providerOperationKey ||
    p.operationDigest !== operationDigest(expected) ||
    typeof p.state !== 'string' ||
    !['accepted_by_provider', 'definitive_not_accepted', 'absent', 'unknown'].includes(p.state) ||
    (p.state === 'accepted_by_provider') !== (p.providerMessageId !== null)
  )
    throw new OutboxError('OutcomeUnknown');
  return Object.freeze({
    schemaVersion: 1,
    providerScope: expected.providerScope,
    providerOperationKey: expected.providerOperationKey,
    operationDigest: operationDigest(expected),
    state: p.state as ProviderLookup['state'],
    providerMessageId: p.providerMessageId === null ? null : identifier(p.providerMessageId),
  });
}
export function recoveryReceipt(value: unknown): RecoveryReceipt {
  const p = record(value, [
    'schemaVersion',
    'receiptId',
    'commandId',
    'kind',
    'outboundId',
    'sourceAttemptId',
    'providerOperationKey',
    'operationDigest',
    'decision',
    'code',
    'newAttemptId',
    'acceptedAt',
  ]);
  if (
    p.schemaVersion !== 1 ||
    !['reconcile', 'retry'].includes(p.kind as string) ||
    !['lookup_authorized', 'retry_reserved', 'held', 'terminal'].includes(p.decision as string) ||
    ![
      'lookup',
      'retry_reserved',
      'known_accepted',
      'known_not_accepted',
      'ordinary_no_resend',
      'callback_veto',
      'route_missing',
      'association_required',
      'suppressed',
      'route_changed',
      'attempt_exhausted',
      'conflicted',
      'prior_operation_evidence',
    ].includes(p.code as string) ||
    (p.decision === 'retry_reserved') !== (p.newAttemptId !== null)
  )
    throw new OutboxError('InvalidCommand');
  const terminal =
    p.decision === 'terminal' &&
    ['known_accepted', 'known_not_accepted'].includes(p.code as string);
  const held =
    p.decision === 'held' &&
    [
      'ordinary_no_resend',
      'callback_veto',
      'route_missing',
      'association_required',
      'suppressed',
      'route_changed',
      'attempt_exhausted',
      'conflicted',
      'prior_operation_evidence',
    ].includes(p.code as string);
  const lookupAllowed =
    p.kind === 'reconcile' && p.decision === 'lookup_authorized' && p.code === 'lookup';
  const retryAllowed =
    p.kind === 'retry' &&
    p.decision === 'retry_reserved' &&
    p.code === 'retry_reserved' &&
    p.newAttemptId !== p.sourceAttemptId;
  if (!terminal && !held && !lookupAllowed && !retryAllowed)
    throw new OutboxError('InvalidCommand');
  if (
    p.kind === 'reconcile' &&
    held &&
    !['ordinary_no_resend', 'conflicted', 'prior_operation_evidence'].includes(p.code as string)
  )
    throw new OutboxError('InvalidCommand');
  return Object.freeze({
    schemaVersion: 1,
    receiptId: uuid(p.receiptId),
    commandId: uuid(p.commandId),
    kind: p.kind as RecoveryKind,
    outboundId: uuid(p.outboundId),
    sourceAttemptId: uuid(p.sourceAttemptId),
    providerOperationKey: uuid(p.providerOperationKey),
    operationDigest: hashValue(p.operationDigest),
    decision: p.decision as RecoveryReceipt['decision'],
    code: p.code as RecoveryCode,
    newAttemptId: p.newAttemptId === null ? null : uuid(p.newAttemptId),
    acceptedAt: iso(p.acceptedAt),
  });
}
export function recoveryObservation(value: unknown, receipt: RecoveryReceipt): RecoveryObservation {
  receipt = recoveryReceipt(receipt);
  const p = record(value, [
    'schemaVersion',
    'commandId',
    'providerOperationKey',
    'operationDigest',
    'source',
    'state',
    'assessment',
    'providerMessageId',
    'observedAt',
  ]);
  if (
    p.schemaVersion !== 1 ||
    p.commandId !== receipt.commandId ||
    p.providerOperationKey !== receipt.providerOperationKey ||
    p.operationDigest !== receipt.operationDigest ||
    typeof p.source !== 'string' ||
    !['lookup', 'send', 'policy'].includes(p.source) ||
    typeof p.state !== 'string' ||
    !['accepted_by_provider', 'definitive_not_accepted', 'absent', 'unknown'].includes(p.state) ||
    !['reported', 'conflicted'].includes(p.assessment as string) ||
    (p.state === 'accepted_by_provider') !== (p.providerMessageId !== null)
  )
    throw new OutboxError('InvalidCommand');
  if (
    p.source === 'lookup' &&
    (receipt.kind !== 'reconcile' || receipt.decision !== 'lookup_authorized')
  )
    throw new OutboxError('InvalidCommand');
  if (p.source === 'send' && (receipt.kind !== 'retry' || receipt.decision !== 'retry_reserved'))
    throw new OutboxError('InvalidCommand');
  if (
    p.source === 'policy' &&
    (!['held', 'terminal'].includes(receipt.decision) ||
      (receipt.code === 'known_accepted' &&
        (p.state !== 'accepted_by_provider' || p.assessment !== 'reported')) ||
      (receipt.code === 'known_not_accepted' &&
        (p.state !== 'definitive_not_accepted' || p.assessment !== 'reported')) ||
      (receipt.decision === 'held' && p.state !== 'unknown') ||
      (receipt.code === 'conflicted' && p.assessment !== 'conflicted'))
  )
    throw new OutboxError('InvalidCommand');
  return Object.freeze({
    schemaVersion: 1,
    commandId: receipt.commandId,
    providerOperationKey: receipt.providerOperationKey,
    operationDigest: receipt.operationDigest,
    source: p.source as RecoveryObservation['source'],
    state: p.state as RecoveryObservation['state'],
    assessment: p.assessment as RecoveryObservation['assessment'],
    providerMessageId: p.providerMessageId === null ? null : identifier(p.providerMessageId),
    observedAt: iso(p.observedAt),
  });
}

/** Immutable local admission witness. Later provider facts cannot rewrite history. */
export type OperationAdmission =
  | Readonly<{ schemaVersion: 1; kind: 'first_operation' }>
  | Readonly<{
      schemaVersion: 1;
      kind: 'prior_send_nonacceptance';
      predecessorAttemptId: string;
      predecessorOperationKey: string;
      evidenceAttemptId: string;
      evidenceDigest: string;
    }>
  | Readonly<{
      schemaVersion: 1;
      kind: 'prior_lookup_nonacceptance';
      predecessorAttemptId: string;
      predecessorOperationKey: string;
      commandId: string;
      evidenceDigest: string;
    }>;
export function admission(value: unknown): OperationAdmission {
  const kind = Object.getOwnPropertyDescriptor(Object(value), 'kind')?.value,
    keys =
      kind === 'first_operation'
        ? ['schemaVersion', 'kind']
        : kind === 'prior_send_nonacceptance'
          ? [
              'schemaVersion',
              'kind',
              'predecessorAttemptId',
              'predecessorOperationKey',
              'evidenceAttemptId',
              'evidenceDigest',
            ]
          : [
              'schemaVersion',
              'kind',
              'predecessorAttemptId',
              'predecessorOperationKey',
              'commandId',
              'evidenceDigest',
            ],
    p = record(value, keys);
  if (
    p.schemaVersion !== 1 ||
    !['first_operation', 'prior_send_nonacceptance', 'prior_lookup_nonacceptance'].includes(
      p.kind as string,
    )
  )
    throw new OutboxError('InvalidCommand');
  if (p.kind === 'first_operation')
    return Object.freeze({ schemaVersion: 1, kind: 'first_operation' });
  const common = {
    schemaVersion: 1 as const,
    predecessorAttemptId: uuid(p.predecessorAttemptId),
    predecessorOperationKey: uuid(p.predecessorOperationKey),
    evidenceDigest: hashValue(p.evidenceDigest),
  };
  return p.kind === 'prior_send_nonacceptance'
    ? Object.freeze({
        ...common,
        kind: 'prior_send_nonacceptance',
        evidenceAttemptId: uuid(p.evidenceAttemptId),
      })
    : Object.freeze({
        ...common,
        kind: 'prior_lookup_nonacceptance',
        commandId: uuid(p.commandId),
      });
}
