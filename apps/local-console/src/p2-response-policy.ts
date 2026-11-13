/** Source-qualified response facts. No fact here supplies consent or human ACK. */
import { parseBusinessJson } from './business';
import { NativeUiError } from './p2-native-policy';
import type { NativeInputs, NativeSession } from './p2-native-policy';
import type { PlaybackSample } from './p2-playback-meter';
const utf8 = new TextEncoder();
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/;
const ID = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}(?![\s\S])/;
const DECIMAL = /^[1-9][0-9]{0,18}(?![\s\S])/;
function invalid(): never {
  throw new NativeUiError('invalid', 'The response evidence could not be verified.');
}
function row(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  )
    return invalid();
  const own = Object.getOwnPropertyDescriptors(value);
  if (
    Reflect.ownKeys(own).length !== keys.length ||
    keys.some((key) => !Object.hasOwn(own, key) || !Object.hasOwn(own[key]!, 'value'))
  )
    return invalid();
  return Object.fromEntries(keys.map((key) => [key, own[key]!.value as unknown]));
}
function uuid(value: unknown): string {
  if (typeof value !== 'string' || !UUID.test(value)) return invalid();
  return value;
}
function id(value: unknown): string {
  if (typeof value !== 'string' || !ID.test(value)) return invalid();
  return value;
}
function decimal(value: unknown): string {
  if (typeof value !== 'string' || !DECIMAL.test(value) || BigInt(value) > 9223372036854775807n)
    return invalid();
  return value;
}
function count(value: unknown): number {
  if (!Number.isInteger(value) || (value as number) < 0 || (value as number) > 64) return invalid();
  return value as number;
}
function text(value: unknown): string | null {
  if (value === null) return null;
  if (
    typeof value !== 'string' ||
    !value ||
    /[\ud800-\udfff]/u.test(value) ||
    utf8.encode(value).length > 4096
  )
    return invalid();
  return value;
}
function decode(raw: Uint8Array | string, maximum: number): unknown {
  try {
    if (typeof raw === 'string') {
      if (!raw || utf8.encode(raw).length > maximum) return invalid();
      return parseBusinessJson(raw);
    }
    if (!raw.byteLength || raw.byteLength > maximum) return invalid();
    return parseBusinessJson(new TextDecoder('utf-8', { fatal: true }).decode(raw));
  } catch {
    return invalid();
  }
}
export interface ResponseMapping {
  readonly schemaVersion: 1;
  readonly bindingId: string;
  readonly generationId: string;
  readonly inputId: string;
  readonly operationKey: string;
  readonly responseId: string;
  readonly sdkSpeechId: string;
  readonly observationCount: number;
}
export function parseResponseMapping(raw: Uint8Array, bindingId: string): ResponseMapping {
  const r = row(decode(raw, 2048), [
    'schemaVersion',
    'bindingId',
    'generationId',
    'inputId',
    'operationKey',
    'responseId',
    'sdkSpeechId',
    'observationCount',
  ]);
  if (r.schemaVersion !== 1 || r.bindingId !== bindingId) return invalid();
  return Object.freeze({
    schemaVersion: 1,
    bindingId: uuid(r.bindingId),
    generationId: uuid(r.generationId),
    inputId: uuid(r.inputId),
    operationKey: uuid(r.operationKey),
    responseId: uuid(r.responseId),
    sdkSpeechId: id(r.sdkSpeechId),
    observationCount: count(r.observationCount),
  });
}
export interface ResponseAnchor extends Omit<ResponseMapping, 'observationCount'> {
  readonly receiptId: string;
  readonly caseRevision: string;
  readonly scope: Readonly<{ tenantId: string; accountId: string }>;
  readonly providerScope: Readonly<{
    tenantId: string;
    provider: 'livekit';
    providerAccountId: string;
  }>;
  readonly caseId: string;
  readonly conversationId: string;
  readonly roomId: string;
  readonly participantId: string;
}
export interface ResponseView {
  readonly anchor: ResponseAnchor;
  readonly receipt: Readonly<{
    responseId: string;
    receiptId: string;
    anchorDigest: string;
    responseSequence: string;
    acceptedAt: string;
  }>;
  readonly observationCount: number;
  readonly generatedText: string | null;
  readonly sdkState: 'unknown' | 'completed' | 'interrupted' | 'conflicted';
  readonly sdkText: string | null;
  readonly browserState:
    'unknown' | 'started' | 'partial' | 'interrupted' | 'completed_reported' | 'conflicted';
  readonly conflicted: boolean;
}
export function parseResponseView(
  raw: Uint8Array,
  mapping: ResponseMapping,
  session: NativeSession,
  inputs: NativeInputs,
): ResponseView {
  const envelope = row(decode(raw, 65536), ['schemaVersion', 'status', 'result']);
  if (envelope.schemaVersion !== 1 || envelope.status !== 'known') return invalid();
  const v = row(envelope.result, [
    'anchor',
    'receipt',
    'observationCount',
    'generatedText',
    'sdkState',
    'sdkText',
    'browserState',
    'conflicted',
  ]);
  const a = row(v.anchor, [
    'schemaVersion',
    'responseId',
    'generationId',
    'sdkSpeechId',
    'bindingId',
    'inputId',
    'receiptId',
    'operationKey',
    'caseRevision',
    'scope',
    'providerScope',
    'caseId',
    'conversationId',
    'roomId',
    'participantId',
  ]);
  const scope = row(a.scope, ['tenantId', 'accountId']),
    provider = row(a.providerScope, ['tenantId', 'provider', 'providerAccountId']);
  const receipt = row(v.receipt, [
    'responseId',
    'receiptId',
    'anchorDigest',
    'responseSequence',
    'acceptedAt',
  ]);
  const input = inputs.values().find((input) => input.inputId === mapping.inputId);
  if (
    !input?.receiptId ||
    input.operationKey !== mapping.operationKey ||
    a.schemaVersion !== 1 ||
    a.receiptId !== input.receiptId ||
    a.roomId !== session.roomId ||
    a.participantId !== session.participantId ||
    a.bindingId !== session.bindingId ||
    provider.provider !== 'livekit' ||
    provider.tenantId !== scope.tenantId ||
    typeof v.conflicted !== 'boolean'
  )
    return invalid();
  for (const key of [
    'responseId',
    'generationId',
    'sdkSpeechId',
    'bindingId',
    'inputId',
    'operationKey',
  ] as const)
    if (a[key] !== mapping[key]) return invalid();
  if (
    receipt.responseId !== mapping.responseId ||
    typeof receipt.anchorDigest !== 'string' ||
    !/^[0-9a-f]{64}(?![\s\S])/.test(receipt.anchorDigest) ||
    typeof receipt.acceptedAt !== 'string' ||
    !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z(?![\s\S])/.test(receipt.acceptedAt) ||
    !Number.isFinite(Date.parse(receipt.acceptedAt)) ||
    new Date(receipt.acceptedAt).toISOString() !== receipt.acceptedAt
  )
    return invalid();
  if (
    !['unknown', 'completed', 'interrupted', 'conflicted'].includes(v.sdkState as string) ||
    !['unknown', 'started', 'partial', 'interrupted', 'completed_reported', 'conflicted'].includes(
      v.browserState as string,
    )
  )
    return invalid();
  const conflicted = v.conflicted;
  if (
    (v.sdkState === 'conflicted' ||
      v.browserState === 'conflicted' ||
      (v.sdkState === 'interrupted' && v.browserState === 'completed_reported')) &&
    !conflicted
  )
    return invalid();
  const anchor: ResponseAnchor = Object.freeze({
    schemaVersion: 1,
    responseId: uuid(a.responseId),
    generationId: uuid(a.generationId),
    sdkSpeechId: id(a.sdkSpeechId),
    bindingId: uuid(a.bindingId),
    inputId: uuid(a.inputId),
    receiptId: uuid(a.receiptId),
    operationKey: uuid(a.operationKey),
    caseRevision: decimal(a.caseRevision),
    scope: Object.freeze({ tenantId: id(scope.tenantId), accountId: id(scope.accountId) }),
    providerScope: Object.freeze({
      tenantId: id(provider.tenantId),
      provider: 'livekit',
      providerAccountId: id(provider.providerAccountId),
    }),
    caseId: id(a.caseId),
    conversationId: id(a.conversationId),
    roomId: id(a.roomId),
    participantId: id(a.participantId),
  });
  return Object.freeze({
    anchor,
    receipt: Object.freeze({
      responseId: uuid(receipt.responseId),
      receiptId: uuid(receipt.receiptId),
      anchorDigest: receipt.anchorDigest,
      responseSequence: decimal(receipt.responseSequence),
      acceptedAt: receipt.acceptedAt,
    }),
    observationCount: count(v.observationCount),
    generatedText: text(v.generatedText),
    sdkState: v.sdkState as ResponseView['sdkState'],
    sdkText: text(v.sdkText),
    browserState: v.browserState as ResponseView['browserState'],
    conflicted,
  });
}
export interface ResponseRow {
  readonly mapping: ResponseMapping;
  readonly view: ResponseView | null;
  readonly sample: PlaybackSample | null;
}
export class NativeResponses {
  readonly #rows = new Map<string, ResponseRow>();
  apply(mapping: ResponseMapping, inputs: NativeInputs): boolean {
    const candidate = row(mapping, [
      'schemaVersion',
      'bindingId',
      'generationId',
      'inputId',
      'operationKey',
      'responseId',
      'sdkSpeechId',
      'observationCount',
    ]);
    mapping = parseResponseMapping(
      utf8.encode(JSON.stringify(candidate)),
      candidate.bindingId as string,
    );
    const input = inputs.values().find((input) => input.inputId === mapping.inputId);
    if (!input?.receiptId || input.operationKey !== mapping.operationKey) return false;
    const previous = this.#rows.get(mapping.responseId);
    if (previous) {
      for (const key of [
        'bindingId',
        'generationId',
        'inputId',
        'operationKey',
        'sdkSpeechId',
      ] as const)
        if (previous.mapping[key] !== mapping[key]) return invalid();
      if (mapping.observationCount <= previous.mapping.observationCount) return false;
    } else {
      if (this.#rows.size >= 64)
        throw new NativeUiError('capacity', 'The response history limit was reached.');
      if (this.values().some((r) => r.mapping.generationId === mapping.generationId))
        return invalid();
    }
    this.#rows.set(
      mapping.responseId,
      Object.freeze({ mapping, view: previous?.view ?? null, sample: previous?.sample ?? null }),
    );
    return true;
  }
  inspect(view: ResponseView): boolean {
    const previous = this.#rows.get(view.anchor.responseId);
    if (
      !previous ||
      view.observationCount < previous.mapping.observationCount ||
      view.observationCount < (previous.view?.observationCount ?? 0)
    )
      return false;
    for (const key of [
      'responseId',
      'generationId',
      'sdkSpeechId',
      'bindingId',
      'inputId',
      'operationKey',
    ] as const)
      if (view.anchor[key] !== previous.mapping[key]) return invalid();
    if (
      previous.view &&
      view.observationCount === previous.view.observationCount &&
      JSON.stringify(view) !== JSON.stringify(previous.view)
    )
      return invalid();
    view = Object.freeze({
      ...view,
      anchor: Object.freeze({
        ...view.anchor,
        scope: Object.freeze({ ...view.anchor.scope }),
        providerScope: Object.freeze({ ...view.anchor.providerScope }),
      }),
      receipt: Object.freeze({ ...view.receipt }),
    });
    if (previous.view && JSON.stringify(previous.view.anchor) !== JSON.stringify(view.anchor))
      return invalid();
    if (previous.view && JSON.stringify(previous.view.receipt) !== JSON.stringify(view.receipt))
      return invalid();
    this.#rows.set(view.anchor.responseId, Object.freeze({ ...previous, view }));
    return true;
  }
  sample(sample: PlaybackSample): boolean {
    const previous = this.#rows.get(sample.responseId);
    if (
      !previous ||
      !Number.isInteger(sample.observedAudioMs) ||
      !Number.isInteger(sample.sampledAudioMs) ||
      sample.observedAudioMs < 0 ||
      sample.sampledAudioMs < sample.observedAudioMs ||
      sample.sampledAudioMs > 180000 ||
      sample.observedAudioMs < (previous.sample?.observedAudioMs ?? 0) ||
      sample.sampledAudioMs < (previous.sample?.sampledAudioMs ?? 0)
    )
      return false;
    this.#rows.set(
      sample.responseId,
      Object.freeze({ ...previous, sample: Object.freeze({ ...sample }) }),
    );
    return true;
  }
  values(): readonly ResponseRow[] {
    return Object.freeze([...this.#rows.values()]);
  }
}
export function playbackPayload(
  eventId: string,
  responseId: string,
  state: 'started' | 'partial' | 'interrupted' | 'completed',
  observedAudioMs: number,
): string {
  uuid(eventId);
  uuid(responseId);
  if (
    !['started', 'partial', 'interrupted', 'completed'].includes(state) ||
    !Number.isInteger(observedAudioMs) ||
    observedAudioMs < 0 ||
    observedAudioMs > 180000
  )
    return invalid();
  return JSON.stringify({ schemaVersion: 1, eventId, responseId, state, observedAudioMs });
}
export function interruptPayload(responseId: string): string {
  return JSON.stringify({ schemaVersion: 1, responseId: uuid(responseId) });
}
export function validateInterruptReply(raw: string, responseId: string): void {
  const r = row(decode(raw, 512), ['schemaVersion', 'status', 'responseId']);
  if (
    r.schemaVersion !== 1 ||
    r.status !== 'interruption_requested' ||
    r.responseId !== uuid(responseId)
  )
    return invalid();
}
export function validatePlaybackReply(raw: string, responseId: string, eventId: string): void {
  const r = row(decode(raw, 2048), ['schemaVersion', 'status', 'result']);
  if (r.schemaVersion !== 1 || r.status !== 'known') return invalid();
  const receipt = row(r.result, [
    'acceptedAt',
    'eventId',
    'observationSequence',
    'payloadDigest',
    'receiptId',
    'responseId',
  ]);
  if (
    receipt.responseId !== uuid(responseId) ||
    receipt.eventId !== uuid(eventId) ||
    typeof receipt.payloadDigest !== 'string' ||
    !/^[0-9a-f]{64}(?![\s\S])/.test(receipt.payloadDigest) ||
    typeof receipt.acceptedAt !== 'string' ||
    !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z(?![\s\S])/.test(receipt.acceptedAt) ||
    !Number.isFinite(Date.parse(receipt.acceptedAt)) ||
    new Date(receipt.acceptedAt).toISOString() !== receipt.acceptedAt
  )
    return invalid();
  decimal(receipt.observationSequence);
  uuid(receipt.receiptId);
}
