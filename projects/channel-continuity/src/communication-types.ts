/** Immutable communication evidence. Source claims never grant business authority. */
import {
  createNativeIntegration,
  nativeConfig,
  nativeFields,
  nativeId,
  nativeIso,
  nativeToken,
  nativeUuid,
  nativeSha,
  type NativeIntegration,
} from './native-types.js';
import type { AccountScope, ProviderScope } from './index.js';
import { ChannelError } from './public-types.js';
export type CommunicationGrant = Readonly<{
  scope: AccountScope;
  caseId: string;
  conversationId: string;
  publisherToken: string;
  sdkToken: string;
  browserToken: string;
}>;
export type CommunicationIntegration = NativeIntegration;
export type CommunicationLimits = Readonly<{
  maxResponses: number;
  maxObservations: number;
  maxObservationsPerResponse: number;
}>;
export const DEFAULT_COMMUNICATION_LIMITS: CommunicationLimits = Object.freeze({
  maxResponses: 1024,
  maxObservations: 8192,
  maxObservationsPerResponse: 16,
});
export type ResponseAnchor = Readonly<{
  schemaVersion: 1;
  responseId: string;
  generationId: string;
  sdkSpeechId: string;
  bindingId: string;
  inputId: string;
  receiptId: string;
  operationKey: string;
  caseRevision: string;
}>;
export type ResponseReceipt = Readonly<{
  responseId: string;
  receiptId: string;
  anchorDigest: string;
  responseSequence: string;
  acceptedAt: string;
}>;
export type SdkFact =
  | Readonly<{ type: 'generated_complete'; text: string }>
  | Readonly<{
      type: 'speech_settled';
      state: 'completed' | 'interrupted' | 'unknown';
      sdkText: string | null;
    }>;
export type SdkObservation = Readonly<{
  schemaVersion: 1;
  eventId: string;
  responseId: string;
  generationId: string;
  sdkSpeechId: string;
  fact: SdkFact;
}>;
export type BrowserObservation = Readonly<{
  schemaVersion: 1;
  eventId: string;
  responseId: string;
  state: 'started' | 'partial' | 'interrupted' | 'completed';
  observedAudioMs: number;
}>;
export type ObservationReceipt = Readonly<{
  responseId: string;
  eventId: string;
  receiptId: string;
  payloadDigest: string;
  observationSequence: string;
  acceptedAt: string;
}>;
export type StoredObservation =
  | Readonly<{ source: 'agent_sdk'; payload: SdkObservation; receipt: ObservationReceipt }>
  | Readonly<{
      source: 'browser_client';
      payload: BrowserObservation;
      receipt: ObservationReceipt;
    }>;
export type CommunicationProjection = Readonly<{
  generatedText: string | null;
  sdkState: 'unknown' | 'completed' | 'interrupted' | 'conflicted';
  sdkText: string | null;
  browserState:
    'unknown' | 'started' | 'partial' | 'interrupted' | 'completed_reported' | 'conflicted';
  conflicted: boolean;
}>;
export type BoundResponseAnchor = ResponseAnchor &
  Readonly<{
    scope: AccountScope;
    providerScope: ProviderScope;
    caseId: string;
    conversationId: string;
    roomId: string;
    participantId: string;
  }>;
export type ResponseView = CommunicationProjection &
  Readonly<{ anchor: BoundResponseAnchor; receipt: ResponseReceipt; observationCount: number }>;
export type CommunicationSource = 'publisher' | 'agent_sdk' | 'browser_client';
type Grant = Readonly<{
  scope: AccountScope;
  caseId: string;
  conversationId: string;
  tokens: Readonly<Record<CommunicationSource, string>>;
}>;
type Configuration = Readonly<{
  providerScope: ProviderScope;
  grants: readonly Grant[];
  rawTokens: readonly string[];
}>;
const registry = new WeakMap<CommunicationIntegration, Configuration>();
export function communicationFields(v: unknown, keys: readonly string[]): Record<string, unknown> {
  try {
    return nativeFields(v, keys);
  } catch {
    throw new ChannelError('InvalidEvent');
  }
}
export function communicationText(v: unknown): string {
  if (
    typeof v !== 'string' ||
    !v ||
    Buffer.byteLength(v, 'utf8') > 4096 ||
    Buffer.from(v, 'utf8').toString('utf8') !== v
  )
    throw new ChannelError('InvalidEvent');
  return v;
}
export function communicationRevision(v: unknown): string {
  if (
    typeof v !== 'string' ||
    !/^[1-9][0-9]{0,18}(?![\s\S])/.test(v) ||
    BigInt(v) > 9223372036854775807n
  )
    throw new ChannelError('InvalidEvent');
  return v;
}
export function communicationSequence(v: unknown): string {
  return communicationRevision(v);
}
function bounded(v: unknown, max: number): number {
  if (!Number.isSafeInteger(v) || (v as number) < 1 || (v as number) > max)
    throw new ChannelError('InvalidEvent');
  return v as number;
}
export function communicationLimits(v: unknown): CommunicationLimits {
  const r = communicationFields(v, [
    'maxResponses',
    'maxObservations',
    'maxObservationsPerResponse',
  ]);
  return Object.freeze({
    maxResponses: bounded(r.maxResponses, 10000),
    maxObservations: bounded(r.maxObservations, 100000),
    maxObservationsPerResponse: bounded(r.maxObservationsPerResponse, 64),
  });
}
function normalArray(v: unknown, max: number): readonly unknown[] {
  if (!Array.isArray(v) || Object.getPrototypeOf(v) !== Array.prototype || v.length > max)
    throw new ChannelError('InvalidEvent');
  const d = Object.getOwnPropertyDescriptors(v);
  if (Reflect.ownKeys(d).length !== v.length + 1) throw new ChannelError('InvalidEvent');
  const result: unknown[] = [];
  for (let i = 0; i < v.length; i++) {
    const x = d[String(i)];
    if (!x || !('value' in x) || !x.enumerable) throw new ChannelError('InvalidEvent');
    result.push(x.value);
  }
  return result;
}
export function createCommunicationIntegration(
  native: NativeIntegration,
  values: readonly CommunicationGrant[],
): CommunicationIntegration {
  try {
    const original = nativeConfig(native),
      items = normalArray(values, 64);
    if (!items.length) throw Error();
    const grants: Grant[] = [],
      tokens: string[] = [];
    for (const value of items) {
      const r = communicationFields(value, [
          'scope',
          'caseId',
          'conversationId',
          'publisherToken',
          'sdkToken',
          'browserToken',
        ]),
        s = communicationFields(r.scope, ['tenantId', 'accountId']);
      const scope = Object.freeze({
        tenantId: nativeId(s.tenantId),
        accountId: nativeId(s.accountId),
      });
      if (scope.tenantId !== original.providerScope.tenantId) throw Error();
      const raw = {
        publisher: nativeToken(r.publisherToken),
        agent_sdk: nativeToken(r.sdkToken),
        browser_client: nativeToken(r.browserToken),
      };
      tokens.push(...Object.values(raw));
      grants.push(
        Object.freeze({
          scope,
          caseId: nativeId(r.caseId),
          conversationId: nativeId(r.conversationId),
          tokens: Object.freeze({
            publisher: nativeSha(raw.publisher),
            agent_sdk: nativeSha(raw.agent_sdk),
            browser_client: nativeSha(raw.browser_client),
          }),
        }),
      );
    }
    if (
      new Set(tokens).size !== tokens.length ||
      tokens.some((x) => original.rawPublishers.some((y) => y.token === x))
    )
      throw Error();
    const integration = createNativeIntegration(original.providerScope, original.rawPublishers);
    registry.set(
      integration,
      Object.freeze({
        providerScope: original.providerScope,
        grants: Object.freeze(grants),
        rawTokens: Object.freeze(tokens),
      }),
    );
    return integration;
  } catch {
    throw new ChannelError('InvalidConfiguration');
  }
}
export function communicationConfig(v: object): Configuration {
  const c = registry.get(v as CommunicationIntegration);
  if (!c) throw new ChannelError('AccessDenied');
  return c;
}
export function hasCommunicationIntegration(v: object): boolean {
  return registry.has(v as CommunicationIntegration);
}
export function responseAnchor(value: unknown): ResponseAnchor {
  try {
    const r = communicationFields(value, [
      'schemaVersion',
      'responseId',
      'generationId',
      'sdkSpeechId',
      'bindingId',
      'inputId',
      'receiptId',
      'operationKey',
      'caseRevision',
    ]);
    if (r.schemaVersion !== 1) throw Error();
    return Object.freeze({
      schemaVersion: 1,
      responseId: nativeUuid(r.responseId),
      generationId: nativeUuid(r.generationId),
      sdkSpeechId: nativeId(r.sdkSpeechId),
      bindingId: nativeUuid(r.bindingId),
      inputId: nativeUuid(r.inputId),
      receiptId: nativeUuid(r.receiptId),
      operationKey: nativeUuid(r.operationKey),
      caseRevision: communicationRevision(r.caseRevision),
    });
  } catch {
    throw new ChannelError('InvalidEvent');
  }
}
export function sdkObservation(value: unknown): SdkObservation {
  try {
    const r = communicationFields(value, [
      'schemaVersion',
      'eventId',
      'responseId',
      'generationId',
      'sdkSpeechId',
      'fact',
    ]);
    if (r.schemaVersion !== 1) throw Error();
    const f = communicationFields(r.fact, Object.keys(r.fact as object));
    let fact: SdkFact;
    if (f.type === 'generated_complete') {
      communicationFields(f, ['type', 'text']);
      fact = Object.freeze({ type: 'generated_complete', text: communicationText(f.text) });
    } else {
      communicationFields(f, ['type', 'state', 'sdkText']);
      if (
        f.type !== 'speech_settled' ||
        typeof f.state !== 'string' ||
        !['completed', 'interrupted', 'unknown'].includes(f.state)
      )
        throw Error();
      fact = Object.freeze({
        type: 'speech_settled',
        state: f.state as 'completed' | 'interrupted' | 'unknown',
        sdkText: f.sdkText === null ? null : communicationText(f.sdkText),
      });
    }
    return Object.freeze({
      schemaVersion: 1,
      eventId: nativeUuid(r.eventId),
      responseId: nativeUuid(r.responseId),
      generationId: nativeUuid(r.generationId),
      sdkSpeechId: nativeId(r.sdkSpeechId),
      fact,
    });
  } catch {
    throw new ChannelError('InvalidEvent');
  }
}
export function browserObservation(value: unknown): BrowserObservation {
  try {
    const r = communicationFields(value, [
      'schemaVersion',
      'eventId',
      'responseId',
      'state',
      'observedAudioMs',
    ]);
    if (
      r.schemaVersion !== 1 ||
      typeof r.state !== 'string' ||
      !['started', 'partial', 'interrupted', 'completed'].includes(r.state) ||
      !Number.isSafeInteger(r.observedAudioMs) ||
      (r.observedAudioMs as number) < 0 ||
      (r.observedAudioMs as number) > 180000
    )
      throw Error();
    return Object.freeze({
      schemaVersion: 1,
      eventId: nativeUuid(r.eventId),
      responseId: nativeUuid(r.responseId),
      state: r.state as BrowserObservation['state'],
      observedAudioMs: r.observedAudioMs as number,
    });
  } catch {
    throw new ChannelError('InvalidEvent');
  }
}
export function responseReceipt(value: unknown): ResponseReceipt {
  const r = communicationFields(value, [
    'responseId',
    'receiptId',
    'anchorDigest',
    'responseSequence',
    'acceptedAt',
  ]);
  if (typeof r.anchorDigest !== 'string' || !/^[0-9a-f]{64}(?![\s\S])/.test(r.anchorDigest))
    throw new ChannelError('InvalidEvent');
  return Object.freeze({
    responseId: nativeUuid(r.responseId),
    receiptId: nativeUuid(r.receiptId),
    anchorDigest: r.anchorDigest,
    responseSequence: communicationSequence(r.responseSequence),
    acceptedAt: nativeIso(r.acceptedAt),
  });
}
export function observationReceipt(value: unknown): ObservationReceipt {
  const r = communicationFields(value, [
    'responseId',
    'eventId',
    'receiptId',
    'payloadDigest',
    'observationSequence',
    'acceptedAt',
  ]);
  if (typeof r.payloadDigest !== 'string' || !/^[0-9a-f]{64}(?![\s\S])/.test(r.payloadDigest))
    throw new ChannelError('InvalidEvent');
  return Object.freeze({
    responseId: nativeUuid(r.responseId),
    eventId: nativeUuid(r.eventId),
    receiptId: nativeUuid(r.receiptId),
    payloadDigest: r.payloadDigest,
    observationSequence: communicationSequence(r.observationSequence),
    acceptedAt: nativeIso(r.acceptedAt),
  });
}
export function reduceCommunicationEvidence(
  values: readonly StoredObservation[],
): CommunicationProjection {
  try {
    let responseId: string | undefined,
      generationId: string | undefined,
      speechId: string | undefined;
    const generated = new Set<string>(),
      sdk = new Set<string>(),
      texts = new Set<string>(),
      browser = new Set<string>();
    for (const value of normalArray(values, 64)) {
      const r = communicationFields(value, ['source', 'payload', 'receipt']);
      const receipt = observationReceipt(r.receipt);
      if (r.source === 'agent_sdk') {
        const o = sdkObservation(r.payload);
        if (
          receipt.responseId !== o.responseId ||
          receipt.eventId !== o.eventId ||
          (responseId !== undefined && responseId !== o.responseId) ||
          (generationId !== undefined && generationId !== o.generationId) ||
          (speechId !== undefined && speechId !== o.sdkSpeechId)
        )
          throw Error();
        responseId = o.responseId;
        generationId = o.generationId;
        speechId = o.sdkSpeechId;
        if (o.fact.type === 'generated_complete') generated.add(o.fact.text);
        else {
          sdk.add(o.fact.state);
          if (o.fact.sdkText !== null) texts.add(o.fact.sdkText);
        }
      } else if (r.source === 'browser_client') {
        const o = browserObservation(r.payload);
        if (
          receipt.responseId !== o.responseId ||
          receipt.eventId !== o.eventId ||
          (responseId !== undefined && responseId !== o.responseId)
        )
          throw Error();
        responseId = o.responseId;
        browser.add(o.state);
      } else throw Error();
    }
    const sdkConflict = (sdk.has('completed') && sdk.has('interrupted')) || texts.size > 1;
    const browserConflict =
      browser.has('completed') && (browser.has('interrupted') || sdk.has('interrupted'));
    return Object.freeze({
      generatedText: generated.size === 1 ? [...generated][0]! : null,
      sdkState: sdkConflict
        ? 'conflicted'
        : sdk.has('interrupted')
          ? 'interrupted'
          : sdk.has('completed')
            ? 'completed'
            : 'unknown',
      sdkText: texts.size === 1 ? [...texts][0]! : null,
      browserState: browserConflict
        ? 'conflicted'
        : browser.has('completed')
          ? 'completed_reported'
          : browser.has('interrupted')
            ? 'interrupted'
            : browser.has('partial')
              ? 'partial'
              : browser.has('started')
                ? 'started'
                : 'unknown',
      conflicted: generated.size > 1 || sdkConflict || browserConflict,
    });
  } catch {
    throw new ChannelError('InvalidEvent');
  }
}
