/** Synthetic carrier authentication, separate from customer association and durable intake. */
import { createHmac, timingSafeEqual } from 'node:crypto';
import { isUtf8 } from 'node:buffer';
import { produceTextEvent, type ProviderScope } from './index.js';

export const FAKE_SMS_WINDOW_SECONDS = 60;
export const FAKE_SMS_MAX_BYTES = 32768;
const PREFIX = 'p2.fake_sms.v1\n';
const MESSAGE_KEYS = [
  'schemaVersion',
  'eventId',
  'messageId',
  'senderId',
  'body',
  'occurredAt',
] as const;
export type WebhookHeaders = Readonly<{ timestamp: string; signature: string }>;
export type FakeSmsMessage = Readonly<{
  schemaVersion: 1;
  eventId: string;
  messageId: string;
  senderId: string;
  body: string;
  occurredAt: string;
}>;
export type VerifiedProviderObservation = FakeSmsMessage &
  Readonly<{
    providerScope: ProviderScope;
    authenticatedAtSeconds: number;
  }>;
/** Created only by createFakeSmsIntegration; key material lives outside this object. */
export type FakeSmsIntegration = Readonly<{ providerScope: ProviderScope }>;
export type SignedFakeSms = Readonly<{ raw: Uint8Array; headers: WebhookHeaders }>;
export class WebhookError extends Error {
  readonly code = 'WebhookRejected';
  constructor() {
    super('WebhookRejected');
    this.name = 'WebhookError';
  }
}
const integrations = new WeakMap<
  FakeSmsIntegration,
  Readonly<{ key: Buffer; providerScope: ProviderScope }>
>();

function reject(): never {
  throw new WebhookError();
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
    if (++count > MESSAGE_KEYS.length) reject();
    const field = string();
    if (!(MESSAGE_KEYS as readonly string[]).includes(field) || Object.hasOwn(result, field))
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
  if (offset !== raw.length || count !== MESSAGE_KEYS.length) reject();
  return result;
}
function validateMessage(value: unknown, providerScope: ProviderScope): FakeSmsMessage {
  const fields = dataFields(value, MESSAGE_KEYS);
  if (fields.schemaVersion !== 1) reject();
  const normalized = produceTextEvent(
    {
      providerScope,
      eventId: fields.eventId as string,
      messageId: fields.messageId as string,
      senderId: fields.senderId as string,
      body: fields.body as string,
      occurredAt: fields.occurredAt as string,
      receivedAt: fields.occurredAt as string,
      conversationId: 'unassociated-validation-only',
      channel: 'sms',
    },
    { providerScope },
  );
  if (normalized.event.type !== 'text.received') reject();
  return Object.freeze({
    schemaVersion: 1,
    eventId: normalized.event.eventId,
    messageId: normalized.event.messageId,
    senderId: normalized.event.senderId,
    body: normalized.event.body,
    occurredAt: normalized.event.occurredAt!,
  });
}

function validatedScope(providerScope: ProviderScope): ProviderScope {
  const scopeFields = dataFields(providerScope, ['tenantId', 'provider', 'providerAccountId']);
  const scope = Object.freeze({
    tenantId: scopeFields.tenantId as string,
    provider: scopeFields.provider as string,
    providerAccountId: scopeFields.providerAccountId as string,
  });
  // Exercise the same public codec restrictions without inventing an account or acceptance.
  validateMessage(
    {
      schemaVersion: 1,
      eventId: 'configuration-check',
      messageId: 'configuration-check',
      senderId: 'configuration-check',
      body: '',
      occurredAt: '2030-01-01T00:00:00.000Z',
    },
    scope,
  );
  if (scope.provider !== 'fake_sms') reject();
  return scope;
}
export function createFakeSmsIntegration(
  providerScope: ProviderScope,
  hmacKey: Uint8Array,
): FakeSmsIntegration {
  try {
    const scope = validatedScope(providerScope);
    const key = keyCopy(hmacKey);
    const integration = Object.freeze({ providerScope: scope });
    integrations.set(integration, Object.freeze({ key, providerScope: scope }));
    return integration;
  } catch {
    reject();
  }
}

export function authenticateFakeSms(
  raw: Uint8Array,
  headers: WebhookHeaders,
  integration: FakeSmsIntegration,
  nowSeconds: number,
): VerifiedProviderObservation {
  try {
    const configured = integrations.get(integration);
    if (
      !configured ||
      !(raw instanceof Uint8Array) ||
      raw.byteLength === 0 ||
      raw.byteLength > FAKE_SMS_MAX_BYTES
    )
      reject();
    const current = seconds(nowSeconds);
    const selectedHeaders = dataFields(headers, ['timestamp', 'signature']);
    if (
      typeof selectedHeaders.timestamp !== 'string' ||
      !/^[1-9][0-9]{9}(?![\s\S])/.test(selectedHeaders.timestamp)
    )
      reject();
    if (
      typeof selectedHeaders.signature !== 'string' ||
      !/^[a-f0-9]{64}(?![\s\S])/.test(selectedHeaders.signature)
    )
      reject();
    const timestamp = Number(selectedHeaders.timestamp);
    if (Math.abs(current - timestamp) > FAKE_SMS_WINDOW_SECONDS) reject();
    // Snapshot caller-owned bytes before MAC/parse; post-check mutation cannot alter the observation.
    const snapshot = Buffer.from(raw);
    const supplied = Buffer.from(selectedHeaders.signature, 'hex');
    if (
      !timingSafeEqual(
        mac(configured.key, configured.providerScope, selectedHeaders.timestamp, snapshot),
        supplied,
      )
    )
      reject();
    if (!isUtf8(snapshot)) reject();
    const message = validateMessage(
      messageJson(snapshot.toString('utf8')),
      configured.providerScope,
    );
    return Object.freeze({
      ...message,
      providerScope: configured.providerScope,
      authenticatedAtSeconds: current,
    });
  } catch {
    reject();
  }
}

/** Synthetic carrier producer. The returned bytes are mutable transport, not a durable receipt. */
export function signFakeSms(
  message: FakeSmsMessage,
  hmacKey: Uint8Array,
  timestampSeconds: number,
  providerScope: ProviderScope,
): SignedFakeSms {
  try {
    const current = seconds(timestampSeconds);
    const scope = validatedScope(providerScope);
    const validated = validateMessage(message, scope);
    const raw = Buffer.from(JSON.stringify(validated), 'utf8');
    if (raw.length > FAKE_SMS_MAX_BYTES) reject();
    const timestamp = String(current);
    const headers = Object.freeze({
      timestamp,
      signature: mac(keyCopy(hmacKey), scope, timestamp, raw).toString('hex'),
    });
    return Object.freeze({ raw, headers });
  } catch {
    reject();
  }
}
