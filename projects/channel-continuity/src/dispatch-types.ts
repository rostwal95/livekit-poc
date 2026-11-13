/** Investigation-only dispatch contracts. No case commitment or business execution authority. */
import { createHash } from 'node:crypto';
import type { AccountScope } from './index.js';
import type { StoredMessage } from './postgres.js';
import { ChannelError, type ProcessingState } from './public-types.js';
export type { DispatchLimits } from './migrations.js';
export type DispatchCase = Readonly<{
  scope: AccountScope;
  caseId: string;
  revision: string;
  source: 'synthetic_read_only';
}>;
export type DispatchDecision = Readonly<{
  kind: 'investigation';
  source: 'scripted';
  caseRevision: string;
}>;
export type InvestigationSubmission = Readonly<{
  schemaVersion: 1;
  kind: 'investigation';
  operationKey: string;
  scope: AccountScope;
  caseId: string;
  caseRevision: string;
  conversationId: string;
  message: Readonly<{
    receiptId: string;
    eventId: string;
    messageId: string;
    senderId: string;
    body: string;
  }>;
}>;
export type PreparedDispatch = Readonly<{
  submission: InvestigationSubmission;
  canonicalPayload: string;
  payloadDigest: string;
}>;
export type OperationLookup = Readonly<{
  operationKey: string;
  scope: AccountScope;
  payloadDigest: string;
}>;
export type OperationReceipt = OperationLookup & Readonly<{ receiptId: string }>;
export type DispatchPorts = Readonly<{
  cases: {
    inspect(
      reference: Readonly<{ scope: AccountScope; caseId: string }>,
      signal: AbortSignal,
    ): Promise<DispatchCase>;
  };
  agent: {
    prepare(
      input: Readonly<{ message: StoredMessage; currentCase: DispatchCase }>,
      signal: AbortSignal,
    ): Promise<DispatchDecision>;
  };
  operations: {
    capabilities: 'stable_idempotency_and_lookup';
    lookup(
      input: OperationLookup,
      signal: AbortSignal,
    ): Promise<
      Readonly<{ status: 'absent' }> | Readonly<{ status: 'accepted'; receipt: OperationReceipt }>
    >;
    accept(input: PreparedDispatch, signal: AbortSignal): Promise<OperationReceipt>;
  };
}>;
export type DispatchObservation = Readonly<{
  receiptId: string;
  operationKey: string;
  state: ProcessingState;
  epoch: string;
  attempts: number;
  possibleExternal: boolean;
  externalReceiptId: string | null;
  nextAttemptAt: string | null;
  lastCode: string;
  history: readonly Readonly<{
    epoch: string;
    startedAt: string;
    finishedAt: string | null;
    disposition: string;
  }>[];
}>;
export type DispatchStepResult =
  | Readonly<{
      status: 'busy' | 'blocked' | 'not_due' | 'exhausted' | 'uncertain' | 'not_needed';
      receiptId: string;
      operationKey: string;
    }>
  | Readonly<{
      status: 'dispatched';
      receiptId: string;
      operationKey: string;
      externalReceiptId: string;
      reconciled: boolean;
    }>;
export type DispatchOptions = Readonly<{
  timeoutMs?: number;
  cleanupTimeoutMs?: number;
  observer?: (event: Readonly<{ event: string; code: string }>) => void | Promise<void>;
}>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/;
export function dispatchUuid(value: unknown): string {
  if (typeof value !== 'string' || value.length !== 36 || !UUID.test(value))
    throw new ChannelError('OperationConflict');
  return value;
}
export function dispatchId(value: unknown): string {
  if (
    typeof value !== 'string' ||
    value.length > 128 ||
    !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}(?![\s\S])/.test(value)
  )
    throw new ChannelError('OperationConflict');
  return value;
}
export function dispatchFields(
  value: unknown,
  expected: readonly string[],
): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw new ChannelError('OperationConflict');
  const keys = Reflect.ownKeys(value);
  if (
    keys.length !== expected.length ||
    keys.some((key) => typeof key !== 'string' || !expected.includes(key))
  )
    throw new ChannelError('OperationConflict');
  const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const key of expected) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor || !('value' in descriptor) || !descriptor.enumerable)
      throw new ChannelError('OperationConflict');
    result[key] = descriptor.value;
  }
  return result;
}
export function dispatchScope(value: unknown): AccountScope {
  const fields = dispatchFields(value, ['tenantId', 'accountId']);
  return Object.freeze({
    tenantId: dispatchId(fields.tenantId),
    accountId: dispatchId(fields.accountId),
  });
}
export function sameDispatchScope(a: AccountScope, b: AccountScope): boolean {
  return a.tenantId === b.tenantId && a.accountId === b.accountId;
}
export function dispatchRevision(value: unknown): string {
  if (
    typeof value !== 'string' ||
    value.length > 19 ||
    !/^[1-9][0-9]{0,18}(?![\s\S])/.test(value) ||
    BigInt(value) > 9223372036854775807n
  )
    throw new ChannelError('OperationConflict');
  return value;
}
export function validateDispatchCase(value: unknown, message: StoredMessage): DispatchCase {
  const fields = dispatchFields(value, ['scope', 'caseId', 'revision', 'source']);
  const scope = dispatchScope(fields.scope);
  if (
    !message.event.accountScope ||
    !sameDispatchScope(scope, message.event.accountScope) ||
    fields.caseId !== message.event.caseId ||
    fields.source !== 'synthetic_read_only'
  )
    throw new ChannelError('OperationConflict');
  return Object.freeze({
    scope,
    caseId: dispatchId(fields.caseId),
    revision: dispatchRevision(fields.revision),
    source: 'synthetic_read_only',
  });
}
export function prepareDispatch(
  message: StoredMessage,
  currentCase: DispatchCase,
  decision: unknown,
): PreparedDispatch {
  const checked = validateDispatchCase(currentCase, message),
    fields = dispatchFields(decision, ['kind', 'source', 'caseRevision']);
  if (
    fields.kind !== 'investigation' ||
    fields.source !== 'scripted' ||
    fields.caseRevision !== checked.revision ||
    message.event.type !== 'text.received'
  )
    throw new ChannelError('OperationConflict');
  return preparedSubmission({
    schemaVersion: 1,
    kind: 'investigation',
    operationKey: message.operationKey,
    scope: checked.scope,
    caseId: checked.caseId,
    caseRevision: checked.revision,
    conversationId: message.event.conversationId,
    message: {
      receiptId: message.receipt.receiptId,
      eventId: message.event.eventId,
      messageId: message.event.messageId,
      senderId: message.event.senderId,
      body: message.event.body,
    },
  });
}
export function preparedSubmission(value: unknown): PreparedDispatch {
  const fields = dispatchFields(value, [
    'schemaVersion',
    'kind',
    'operationKey',
    'scope',
    'caseId',
    'caseRevision',
    'conversationId',
    'message',
  ]);
  const message = dispatchFields(fields.message, [
    'receiptId',
    'eventId',
    'messageId',
    'senderId',
    'body',
  ]);
  if (
    fields.schemaVersion !== 1 ||
    fields.kind !== 'investigation' ||
    typeof message.body !== 'string' ||
    message.body.length > 4096
  )
    throw new ChannelError('OperationConflict');
  for (let index = 0; index < message.body.length; index++) {
    const c = message.body.charCodeAt(index);
    if (c >= 0xd800 && c <= 0xdbff) {
      const d = message.body.charCodeAt(++index);
      if (!(d >= 0xdc00 && d <= 0xdfff)) throw new ChannelError('OperationConflict');
    } else if (c >= 0xdc00 && c <= 0xdfff) throw new ChannelError('OperationConflict');
  }
  if (Buffer.byteLength(message.body, 'utf8') > 4096) throw new ChannelError('OperationConflict');
  const normalized: InvestigationSubmission = Object.freeze({
    schemaVersion: 1,
    kind: 'investigation',
    operationKey: dispatchUuid(fields.operationKey),
    scope: dispatchScope(fields.scope),
    caseId: dispatchId(fields.caseId),
    caseRevision: dispatchRevision(fields.caseRevision),
    conversationId: dispatchId(fields.conversationId),
    message: Object.freeze({
      receiptId: dispatchUuid(message.receiptId),
      eventId: dispatchId(message.eventId),
      messageId: dispatchId(message.messageId),
      senderId: dispatchId(message.senderId),
      body: message.body,
    }),
  });
  const canonicalPayload = JSON.stringify(normalized);
  if (Buffer.byteLength(canonicalPayload, 'utf8') > 32768)
    throw new ChannelError('OperationConflict');
  return Object.freeze({
    submission: normalized,
    canonicalPayload,
    payloadDigest: createHash('sha256').update(canonicalPayload).digest('hex'),
  });
}
export function parsePreparedDispatch(payload: unknown, digest: unknown): PreparedDispatch {
  if (
    typeof payload !== 'string' ||
    payload.length > 32768 ||
    Buffer.byteLength(payload, 'utf8') > 32768 ||
    typeof digest !== 'string' ||
    !/^[0-9a-f]{64}(?![\s\S])/.test(digest)
  )
    throw new ChannelError('SchemaMismatch');
  try {
    const prepared = preparedSubmission(JSON.parse(payload) as unknown);
    if (prepared.canonicalPayload !== payload || prepared.payloadDigest !== digest)
      throw new ChannelError('SchemaMismatch');
    return prepared;
  } catch {
    throw new ChannelError('SchemaMismatch');
  }
}
export function operationLookup(prepared: PreparedDispatch): OperationLookup {
  return Object.freeze({
    operationKey: prepared.submission.operationKey,
    scope: prepared.submission.scope,
    payloadDigest: prepared.payloadDigest,
  });
}
export function validateOperationReceipt(
  value: unknown,
  prepared: PreparedDispatch,
): OperationReceipt {
  const fields = dispatchFields(value, ['operationKey', 'scope', 'payloadDigest', 'receiptId']);
  const scope = dispatchScope(fields.scope);
  if (
    fields.operationKey !== prepared.submission.operationKey ||
    fields.payloadDigest !== prepared.payloadDigest ||
    !sameDispatchScope(scope, prepared.submission.scope)
  )
    throw new ChannelError('OperationConflict');
  return Object.freeze({
    operationKey: prepared.submission.operationKey,
    scope,
    payloadDigest: prepared.payloadDigest,
    receiptId: dispatchUuid(fields.receiptId),
  });
}
