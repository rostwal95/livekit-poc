/** Node-side exact P1 ASCII canonical wire. Neither source content nor a hash grants authority. */
import { createHash } from 'node:crypto';
import {
  RESULT_BODY_BYTES,
  RESULT_INTENT_BYTES,
  ResultReceiverError,
  type P1ResultIntent,
  type P1ResultReceipt,
  type ResultRouteBinding,
} from './result-receiver-types.js';
export function resultFields(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw new ResultReceiverError('InvalidCommand');
  const names = Reflect.ownKeys(value);
  if (names.length !== keys.length || names.some((k) => typeof k !== 'string' || !keys.includes(k)))
    throw new ResultReceiverError('InvalidCommand');
  const copy: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const key of keys) {
    const d = Object.getOwnPropertyDescriptor(value, key);
    if (!d || !('value' in d) || !d.enumerable) throw new ResultReceiverError('InvalidCommand');
    copy[key] = d.value;
  }
  return copy;
}
export function resultUuid(v: unknown): string {
  if (
    typeof v !== 'string' ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/u.test(v)
  )
    throw new ResultReceiverError('InvalidCommand');
  return v;
}
export function resultId(v: unknown): string {
  if (typeof v !== 'string' || !/^[a-z][a-z0-9_-]{0,63}(?![\s\S])/u.test(v))
    throw new ResultReceiverError('InvalidCommand');
  return v;
}
function milliseconds(v: unknown): number {
  if (typeof v !== 'number' || !Number.isSafeInteger(v) || v < 0 || v > 4102444800000)
    throw new ResultReceiverError('InvalidCommand');
  return v;
}
function digest(v: unknown): string {
  if (typeof v !== 'string' || !/^[0-9a-f]{64}(?![\s\S])/u.test(v))
    throw new ResultReceiverError('InvalidCommand');
  return v;
}
export function resultIntent(value: unknown): P1ResultIntent {
  const v = resultFields(value, [
    'delivery_id',
    'scope',
    'work_id',
    'attempt_id',
    'result_sha256',
    'receiver_id',
    'recipient_id',
    'body',
    'prepared_at_ms',
  ]);
  const s = resultFields(v.scope, ['tenant_id', 'account_id']);
  if (
    typeof v.body !== 'string' ||
    v.body.length > 10924 ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?(?![\s\S])/u.test(v.body)
  )
    throw new ResultReceiverError('InvalidCommand');
  const body = Buffer.from(v.body, 'base64');
  if (
    body.length < 1 ||
    body.length > RESULT_BODY_BYTES ||
    body.toString('base64') !== v.body ||
    createHash('sha256').update(body).digest('hex') !== digest(v.result_sha256)
  )
    throw new ResultReceiverError('InvalidCommand');
  return Object.freeze({
    delivery_id: resultUuid(v.delivery_id),
    scope: Object.freeze({ tenant_id: resultId(s.tenant_id), account_id: resultId(s.account_id) }),
    work_id: resultUuid(v.work_id),
    attempt_id: resultUuid(v.attempt_id),
    result_sha256: digest(v.result_sha256),
    receiver_id: resultUuid(v.receiver_id),
    recipient_id: resultId(v.recipient_id),
    body: v.body,
    prepared_at_ms: milliseconds(v.prepared_at_ms),
  });
}
export function encodeResultIntent(value: P1ResultIntent): string {
  const v = resultIntent(value);
  const text = JSON.stringify({
    attempt_id: v.attempt_id,
    body: v.body,
    delivery_id: v.delivery_id,
    prepared_at_ms: v.prepared_at_ms,
    receiver_id: v.receiver_id,
    recipient_id: v.recipient_id,
    result_sha256: v.result_sha256,
    scope: { account_id: v.scope.account_id, tenant_id: v.scope.tenant_id },
    work_id: v.work_id,
  });
  if (Buffer.byteLength(text, 'ascii') > RESULT_INTENT_BYTES)
    throw new ResultReceiverError('InvalidCommand');
  return text;
}
export function parseResultIntent(canonical: string): P1ResultIntent {
  if (
    typeof canonical !== 'string' ||
    canonical.length < 1 ||
    canonical.length > RESULT_INTENT_BYTES ||
    /[^\x20-\x7e]/u.test(canonical)
  )
    throw new ResultReceiverError('InvalidCommand');
  let parsed: unknown;
  try {
    parsed = JSON.parse(canonical) as unknown;
  } catch {
    throw new ResultReceiverError('InvalidCommand');
  }
  const v = resultIntent(parsed);
  if (encodeResultIntent(v) !== canonical) throw new ResultReceiverError('InvalidCommand');
  return v;
}
export function resultReceipt(value: unknown): P1ResultReceipt {
  const v = resultFields(value, [
    'delivery_id',
    'receipt_id',
    'receiver_id',
    'recipient_id',
    'result_sha256',
    'accepted_at_ms',
  ]);
  return Object.freeze({
    delivery_id: resultUuid(v.delivery_id),
    receipt_id: resultUuid(v.receipt_id),
    receiver_id: resultUuid(v.receiver_id),
    recipient_id: resultId(v.recipient_id),
    result_sha256: digest(v.result_sha256),
    accepted_at_ms: milliseconds(v.accepted_at_ms),
  });
}
export function matchResultReceipt(intent: P1ResultIntent, receipt: P1ResultReceipt): void {
  const i = resultIntent(intent),
    r = resultReceipt(receipt);
  if (
    i.delivery_id !== r.delivery_id ||
    i.receiver_id !== r.receiver_id ||
    i.recipient_id !== r.recipient_id ||
    i.result_sha256 !== r.result_sha256
  )
    throw new ResultReceiverError('IdentityConflict');
}
export function resultRoute(value: unknown): ResultRouteBinding {
  const v = resultFields(value, ['scope', 'caseId', 'conversationId', 'recipientId']),
    s = resultFields(v.scope, ['tenantId', 'accountId']);
  // P1's smaller vocabulary is intentional for this explicit receiver integration.
  return Object.freeze({
    scope: Object.freeze({ tenantId: resultId(s.tenantId), accountId: resultId(s.accountId) }),
    caseId: resultId(v.caseId),
    conversationId: resultId(v.conversationId),
    recipientId: resultId(v.recipientId),
  });
}
export function receiverToken(value: unknown): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{32,128}(?![\s\S])/u.test(value))
    throw new ResultReceiverError('AccessDenied');
  return value;
}
export function safeResultError(error: unknown): ResultReceiverError {
  if (error instanceof ResultReceiverError) return new ResultReceiverError(error.code);
  if (error && typeof error === 'object') {
    const d = Object.getOwnPropertyDescriptor(error, 'code');
    if (d && 'value' in d && typeof d.value === 'string') {
      const code = new ResultReceiverError(d.value as ResultReceiverError['code']);
      if (code.code === d.value) return code;
    }
  }
  return new ResultReceiverError('Unavailable');
}
