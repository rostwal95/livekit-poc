/** Separate synthetic callback HMAC capability. No listener or side effects on import. */
import { createHmac, timingSafeEqual } from 'node:crypto';
import { isUtf8 } from 'node:buffer';
import type { ProviderScope } from './index.js';
import type { WebhookHeaders, SignedFakeSms } from './security.js';
import {
  CallbackError,
  CALLBACK_KEYS,
  callbackObservation,
  callbackScope,
  type CallbackObservation,
} from './callback-types.js';
export type FakeSmsCallbackIntegration = Readonly<{ providerScope: ProviderScope }>;
export type VerifiedCallback = Readonly<{
  observation: CallbackObservation;
  providerScope: ProviderScope;
  raw: string;
  transportSeconds: number;
}>;
export const CALLBACK_WINDOW_SECONDS = 60;
export const CALLBACK_MAX_BYTES = 4096;
const PREFIX = 'p2.fake_sms_callback.v1\n';
const integrations = new WeakMap<
  FakeSmsCallbackIntegration,
  Readonly<{ key: Buffer; providerScope: ProviderScope }>
>();
function reject(): never {
  throw new CallbackError('WebhookRejected');
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) reject();
  return value as Record<string, unknown>;
}
function dataFields(value: unknown, keys: readonly string[]): Record<string, unknown> {
  const candidate = object(value);
  if (
    Object.getPrototypeOf(candidate) !== Object.prototype &&
    Object.getPrototypeOf(candidate) !== null
  )
    reject();
  const descriptors = Object.getOwnPropertyDescriptors(candidate);
  if (
    Object.keys(descriptors).length !== keys.length ||
    Object.getOwnPropertySymbols(candidate).length
  )
    reject();
  const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const key of keys) {
    const descriptor = descriptors[key];
    if (!descriptor || !('value' in descriptor) || !descriptor.enumerable) reject();
    result[key] = descriptor.value;
  }
  return result;
}
function keyCopy(value: unknown): Buffer {
  if (!(value instanceof Uint8Array) || value.byteLength < 32 || value.byteLength > 64) reject();
  return Buffer.from(value);
}
function seconds(value: unknown): number {
  if (
    typeof value !== 'number' ||
    !Number.isSafeInteger(value) ||
    value < 1000000000 ||
    value > 9999999999
  )
    reject();
  return value;
}
function mac(key: Buffer, scope: ProviderScope, timestamp: string, raw: Uint8Array): Buffer {
  return createHmac('sha256', key)
    .update(PREFIX)
    .update(scope.tenantId)
    .update('\n')
    .update(scope.provider)
    .update('\n')
    .update(scope.providerAccountId)
    .update('\n')
    .update(timestamp)
    .update('\n')
    .update(raw)
    .digest();
}
/** Strict flat JSON keeps duplicate evidence before projection; nested authority is forbidden. */
function messageJson(raw: string): Record<string, unknown> {
  let offset = 0;
  const whitespace = (): void => {
    while (offset < raw.length && /[\x20\t\n\r]/.test(raw[offset]!)) offset++;
  };
  const string = (): string => {
    if (raw[offset] !== '"') reject();
    const start = offset++;
    let escaped = false;
    while (offset < raw.length) {
      const character = raw[offset++]!;
      if (character === '"' && !escaped) {
        const value: unknown = JSON.parse(raw.slice(start, offset));
        if (typeof value !== 'string') reject();
        return value;
      }
      if (character === '\\' && !escaped) escaped = true;
      else escaped = false;
    }
    reject();
  };
  whitespace();
  if (raw[offset++] !== '{') reject();
  const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  let count = 0;
  while (true) {
    whitespace();
    if (++count > CALLBACK_KEYS.length) reject();
    const field = string();
    if (!(CALLBACK_KEYS as readonly string[]).includes(field) || Object.hasOwn(result, field))
      reject();
    whitespace();
    if (raw[offset++] !== ':') reject();
    whitespace();
    if (field === 'schemaVersion') {
      if (raw[offset++] !== '1') reject();
      result[field] = 1;
    } else result[field] = string();
    whitespace();
    const separator = raw[offset++];
    if (separator === '}') break;
    if (separator !== ',') reject();
  }
  whitespace();
  if (offset !== raw.length || count !== CALLBACK_KEYS.length) reject();
  return result;
}

export function createFakeSmsCallbackIntegration(
  providerScope: ProviderScope,
  key: Uint8Array,
): FakeSmsCallbackIntegration {
  try {
    const scope = callbackScope(providerScope),
      integration = Object.freeze({ providerScope: scope });
    integrations.set(integration, Object.freeze({ key: keyCopy(key), providerScope: scope }));
    return integration;
  } catch {
    reject();
  }
}
export function authenticateFakeSmsCallback(
  raw: Uint8Array,
  headers: WebhookHeaders,
  integration: FakeSmsCallbackIntegration,
  nowSeconds: number,
): VerifiedCallback {
  try {
    const configured = integrations.get(integration);
    if (
      !configured ||
      !(raw instanceof Uint8Array) ||
      !raw.byteLength ||
      raw.byteLength > CALLBACK_MAX_BYTES
    )
      reject();
    const now = seconds(nowSeconds),
      h = dataFields(headers, ['timestamp', 'signature']);
    if (
      typeof h.timestamp !== 'string' ||
      !/[1-9][0-9]{9}/.test(h.timestamp) ||
      h.timestamp.length !== 10 ||
      typeof h.signature !== 'string' ||
      !/^[a-f0-9]{64}(?![\s\S])/.test(h.signature)
    )
      reject();
    if (Math.abs(now - Number(h.timestamp)) > CALLBACK_WINDOW_SECONDS) reject();
    const snapshot = Buffer.from(raw);
    if (
      !timingSafeEqual(
        mac(configured.key, configured.providerScope, h.timestamp, snapshot),
        Buffer.from(h.signature, 'hex'),
      ) ||
      !isUtf8(snapshot)
    )
      reject();
    const observation = callbackObservation(messageJson(snapshot.toString('utf8')));
    return Object.freeze({
      observation,
      providerScope: configured.providerScope,
      raw: snapshot.toString('utf8'),
      transportSeconds: Number(h.timestamp),
    });
  } catch {
    reject();
  }
}
export function signFakeSmsCallback(
  observation: CallbackObservation,
  key: Uint8Array,
  transportTimestamp: number,
  providerScope: ProviderScope,
): SignedFakeSms {
  try {
    const timestamp = String(seconds(transportTimestamp)),
      scope = callbackScope(providerScope),
      raw = Buffer.from(JSON.stringify(callbackObservation(observation)));
    if (raw.length > CALLBACK_MAX_BYTES) reject();
    return Object.freeze({
      raw,
      headers: Object.freeze({
        timestamp,
        signature: mac(keyCopy(key), scope, timestamp, raw).toString('hex'),
      }),
    });
  } catch {
    reject();
  }
}

/** Internal capability validation; callers cannot forge a key-bearing integration. */
export function configuredCallbackScope(integration: FakeSmsCallbackIntegration): ProviderScope {
  const v = integrations.get(integration);
  if (!v) throw new CallbackError('InvalidCommand');
  return v.providerScope;
}
/** Internal persisted-wire semantic validation; historical MAC is not re-authentication. */
export function parseCallbackWire(raw: string): CallbackObservation {
  try {
    if (typeof raw !== 'string' || Buffer.byteLength(raw) > 4096) reject();
    return callbackObservation(messageJson(raw));
  } catch {
    reject();
  }
}
