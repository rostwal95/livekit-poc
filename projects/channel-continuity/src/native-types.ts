/** Native room capability and immutable input values. No transport label authenticates a caller. */
import { createHash } from 'node:crypto';
import type { AccountScope, ProviderScope } from './index.js';
import { dispatchFields, dispatchId } from './dispatch-types.js';
export const NATIVE_TEXT_BYTES = 2048;
export const NATIVE_INPUT_BYTES = 16384;
export const NATIVE_ACK_BYTES = 2048;
export type NativeCode =
  | 'invalid_input'
  | 'forbidden'
  | 'idempotency_conflict'
  | 'capacity_exhausted'
  | 'dependency_unavailable'
  | 'acknowledgement_unknown'
  | 'closed';
export class NativeError extends Error {
  constructor(readonly code: NativeCode) {
    super(code);
    this.name = 'NativeError';
  }
}
export type NativePublisher = Readonly<{
  token: string;
  scope: AccountScope;
  caseId: string;
  conversationId: string;
}>;
export type NativeIntegration = Readonly<{ providerScope: ProviderScope }>;
type Grant = Readonly<{
  tokenDigest: string;
  scope: AccountScope;
  caseId: string;
  conversationId: string;
}>;
type Config = Readonly<{
  providerScope: ProviderScope;
  publishers: readonly Grant[];
  rawPublishers: readonly NativePublisher[];
}>;
const registry = new WeakMap<NativeIntegration, Config>();
export const nativeSha = (value: string): string =>
  createHash('sha256').update(value).digest('hex');
export function nativeFields(value: unknown, keys: readonly string[]): Record<string, unknown> {
  try {
    return dispatchFields(value, keys);
  } catch {
    throw new NativeError('invalid_input');
  }
}
export function nativeId(value: unknown): string {
  try {
    return dispatchId(value);
  } catch {
    throw new NativeError('invalid_input');
  }
}
export function nativeUuid(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/.test(value)
  )
    throw new NativeError('invalid_input');
  return value;
}
export function nativeToken(value: unknown): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{32,128}(?![\s\S])/.test(value))
    throw new NativeError('forbidden');
  return value;
}
export function nativeIso(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z(?![\s\S])/.test(value) ||
    !Number.isFinite(Date.parse(value)) ||
    new Date(value).toISOString() !== value
  )
    throw new NativeError('invalid_input');
  return value;
}
export function nativeBody(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !value ||
    Buffer.byteLength(value, 'utf8') > NATIVE_TEXT_BYTES ||
    Buffer.from(value, 'utf8').toString('utf8') !== value
  )
    throw new NativeError('invalid_input');
  return value;
}
export function createNativeIntegration(
  scope: ProviderScope,
  publishers: readonly NativePublisher[],
): NativeIntegration {
  try {
    const p = nativeFields(scope, ['tenantId', 'provider', 'providerAccountId']),
      providerScope = Object.freeze({
        tenantId: nativeId(p.tenantId),
        provider: nativeId(p.provider),
        providerAccountId: nativeId(p.providerAccountId),
      });
    if (
      providerScope.provider !== 'livekit' ||
      !Array.isArray(publishers) ||
      Object.getPrototypeOf(publishers) !== Array.prototype ||
      publishers.length < 1 ||
      publishers.length > 64
    )
      throw Error();
    const descriptors = Object.getOwnPropertyDescriptors(publishers);
    if (Reflect.ownKeys(descriptors).length !== publishers.length + 1) throw Error();
    const raw: NativePublisher[] = [],
      grants: Grant[] = [];
    for (let i = 0; i < publishers.length; i++) {
      const d = descriptors[String(i)];
      if (!d || !('value' in d) || !d.enumerable) throw Error();
      const v = nativeFields(d.value, ['token', 'scope', 'caseId', 'conversationId']),
        s = nativeFields(v.scope, ['tenantId', 'accountId']),
        account = Object.freeze({
          tenantId: nativeId(s.tenantId),
          accountId: nativeId(s.accountId),
        }),
        token = nativeToken(v.token);
      if (account.tenantId !== providerScope.tenantId) throw Error();
      const grant = Object.freeze({
        token,
        scope: account,
        caseId: nativeId(v.caseId),
        conversationId: nativeId(v.conversationId),
      });
      raw.push(grant);
      grants.push(
        Object.freeze({
          tokenDigest: nativeSha(token),
          scope: account,
          caseId: grant.caseId,
          conversationId: grant.conversationId,
        }),
      );
    }
    if (new Set(grants.map((g) => g.tokenDigest)).size !== grants.length) throw Error();
    const integration = Object.freeze({ providerScope });
    registry.set(
      integration,
      Object.freeze({
        providerScope,
        publishers: Object.freeze(grants),
        rawPublishers: Object.freeze(raw),
      }),
    );
    return integration;
  } catch {
    throw new NativeError('invalid_input');
  }
}
/** Package-private capability lookup. A structurally similar object gains no native authority. */
export function nativeConfig(integration: object): Config {
  const c = registry.get(integration as NativeIntegration);
  if (!c) throw new NativeError('forbidden');
  return c;
}
export function isNativeIntegration(integration: object): boolean {
  return registry.has(integration as NativeIntegration);
}
export type NativePublication = Readonly<{
  bindingId: string;
  bearer: string;
  roomId: string;
  participantId: string;
  expiresAt: string;
}>;
export function publication(value: unknown): NativePublication {
  const v = nativeFields(value, ['bindingId', 'bearer', 'roomId', 'participantId', 'expiresAt']);
  return Object.freeze({
    bindingId: nativeUuid(v.bindingId),
    bearer: nativeToken(v.bearer),
    roomId: nativeId(v.roomId),
    participantId: nativeId(v.participantId),
    expiresAt: nativeIso(v.expiresAt),
  });
}
export type NativeInput = Readonly<{
  schemaVersion: 1;
  inputId: string;
  channel: 'web_chat' | 'voice_transcript';
  body: string;
  roomId: string;
  participantId: string;
}>;
export function nativeInput(value: unknown): NativeInput {
  const v = nativeFields(value, [
    'schemaVersion',
    'inputId',
    'channel',
    'body',
    'roomId',
    'participantId',
  ]);
  if (v.schemaVersion !== 1 || (v.channel !== 'web_chat' && v.channel !== 'voice_transcript'))
    throw new NativeError('invalid_input');
  return Object.freeze({
    schemaVersion: 1,
    inputId: nativeUuid(v.inputId),
    channel: v.channel,
    body: nativeBody(v.body),
    roomId: nativeId(v.roomId),
    participantId: nativeId(v.participantId),
  });
}
export type NativeBindingReceipt = Readonly<{
  bindingId: string;
  bindingDigest: string;
  publishedAt: string;
  expiresAt: string;
}>;
export type NativeAcceptance = Readonly<{
  schemaVersion: 1;
  bindingId: string;
  inputId: string;
  channel: NativeInput['channel'];
  status: 'accepted' | 'replayed';
  receiptId: string;
  operationKey: string;
  acceptanceSequence: string;
  code: null;
}>;
export type NativeAcknowledgement =
  | NativeAcceptance
  | Readonly<{
      schemaVersion: 1;
      bindingId: string;
      inputId: string;
      channel: NativeInput['channel'];
      status: 'unknown';
      receiptId: null;
      operationKey: null;
      acceptanceSequence: null;
      code: 'acknowledgement_unknown';
    }>
  | Readonly<{
      schemaVersion: 1;
      bindingId: string;
      inputId: string;
      channel: NativeInput['channel'];
      status: 'rejected';
      receiptId: null;
      operationKey: null;
      acceptanceSequence: null;
      code: Exclude<NativeCode, 'acknowledgement_unknown'>;
    }>;
export type NativeLimits = Readonly<{ maxBindings: number }>;
export const DEFAULT_NATIVE_LIMITS: NativeLimits = Object.freeze({ maxBindings: 64 });
export function nativeLimits(value: unknown): NativeLimits {
  const v = nativeFields(value, ['maxBindings']);
  if (
    !Number.isSafeInteger(v.maxBindings) ||
    (v.maxBindings as number) < 1 ||
    (v.maxBindings as number) > 1024
  )
    throw new NativeError('invalid_input');
  return Object.freeze({ maxBindings: v.maxBindings as number });
}
