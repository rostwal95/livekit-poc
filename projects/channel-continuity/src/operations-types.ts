/** Browser-safe operations data. Process observations never grant case authority. */
import type { RehydrationContext } from './rehydration-types.js';

export const OPERATIONS_CODES = Object.freeze([
  'invalid_query',
  'access_denied',
  'cursor_stale',
  'overloaded',
  'unavailable',
  'closed',
] as const);
export type OperationsCode = (typeof OPERATIONS_CODES)[number];
export type OperationsRetry = 'none' | 'authenticate' | 'same_read' | 'refresh_first_page';
export class OperationsError extends Error {
  readonly code: OperationsCode;
  constructor(code: OperationsCode = 'unavailable') {
    super('The operations read could not be completed');
    this.name = 'OperationsError';
    this.code =
      typeof code === 'string' && (OPERATIONS_CODES as readonly string[]).includes(code)
        ? code
        : 'unavailable';
    Object.defineProperty(this, 'code', {
      value: this.code,
      enumerable: true,
      writable: false,
      configurable: false,
    });
  }
}
export function operationsRecord(value: unknown, keys: readonly string[]): Record<string, unknown> {
  try {
    if (
      !value ||
      typeof value !== 'object' ||
      ![Object.prototype, null].includes(Object.getPrototypeOf(value))
    )
      throw Error();
    const names = Reflect.ownKeys(value);
    if (
      names.length !== keys.length ||
      names.some((n) => typeof n !== 'string' || !keys.includes(n))
    )
      throw Error();
    const copy: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
    for (const name of keys) {
      const descriptor = Object.getOwnPropertyDescriptor(value, name);
      if (!descriptor || !('value' in descriptor) || !descriptor.enumerable) throw Error();
      copy[name] = descriptor.value;
    }
    return copy;
  } catch {
    throw new OperationsError('invalid_query');
  }
}
export function operationsArray(value: unknown, maximum: number): readonly unknown[] {
  try {
    if (!Array.isArray(value) || value.length > maximum) throw Error();
    const names = Reflect.ownKeys(value);
    if (
      names.length !== value.length + 1 ||
      names.some(
        (n) =>
          n !== 'length' &&
          (typeof n !== 'string' ||
            !/^(0|[1-9][0-9]*)(?![\s\S])/.test(n) ||
            Number(n) >= value.length),
      )
    )
      throw Error();
    return Object.freeze(
      Array.from({ length: value.length }, (_, n) => {
        const d = Object.getOwnPropertyDescriptor(value, String(n));
        if (!d || !('value' in d)) throw Error();
        return d.value as unknown;
      }),
    );
  } catch {
    throw new OperationsError('invalid_query');
  }
}
export function operationsUuid(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/.test(value)
  )
    throw new OperationsError('invalid_query');
  return value;
}
export function operationsText(value: unknown, maximum: number, ascii = false): string {
  if (
    typeof value !== 'string' ||
    !value.length ||
    value.trim() !== value ||
    /[\u0000-\u001f\u007f]/.test(value) ||
    (ascii && !/^[A-Za-z0-9_.:-]+(?![\s\S])/.test(value))
  )
    throw new OperationsError('invalid_query');
  for (let n = 0; n < value.length; n++) {
    const c = value.charCodeAt(n);
    if (c >= 0xd800 && c <= 0xdbff) {
      const d = value.charCodeAt(++n);
      if (!(d >= 0xdc00 && d <= 0xdfff)) throw new OperationsError('invalid_query');
    } else if (c >= 0xdc00 && c <= 0xdfff) throw new OperationsError('invalid_query');
  }
  if (new TextEncoder().encode(value).length > maximum) throw new OperationsError('invalid_query');
  return value;
}
export function operationsCount(value: unknown): number {
  if (
    typeof value !== 'number' ||
    !Number.isSafeInteger(value) ||
    value < 0 ||
    Object.is(value, -0)
  )
    throw new OperationsError('invalid_query');
  return value;
}
export function operationsIso(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z(?![\s\S])/.test(value) ||
    !Number.isFinite(Date.parse(value)) ||
    new Date(value).toISOString() !== value
  )
    throw new OperationsError('invalid_query');
  return value;
}
export const OPERATIONS_SECTIONS = Object.freeze([
  'history',
  'work',
  'responses',
  'replies',
] as const);
export type OperationsSection = (typeof OPERATIONS_SECTIONS)[number];
export type OperationsQuery = Readonly<{ section: OperationsSection; cursor: string | null }>;
export const DEFAULT_OPERATIONS_QUERY: OperationsQuery = Object.freeze({
  section: 'history',
  cursor: null,
});
export function operationsQuery(value: unknown = DEFAULT_OPERATIONS_QUERY): OperationsQuery {
  const r = operationsRecord(value, ['section', 'cursor']);
  if (
    typeof r.section !== 'string' ||
    !(OPERATIONS_SECTIONS as readonly string[]).includes(r.section)
  )
    throw new OperationsError('invalid_query');
  const cursor = r.cursor === null ? null : operationsText(r.cursor, 2048, true);
  if (cursor !== null && !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}(?![\s\S])/.test(cursor))
    throw new OperationsError('invalid_query');
  return Object.freeze({ section: r.section as OperationsSection, cursor });
}
export type OperationsCursors = Readonly<Record<OperationsSection, string | null>>;
export type OperationsContext = Readonly<{
  schemaVersion: 1;
  status: 'known';
  requestId: string;
  context: RehydrationContext;
  cursors: OperationsCursors;
}>;
export type OperationsFailure = Readonly<{
  schemaVersion: 1;
  status: 'unavailable';
  requestId: string;
  code: OperationsCode;
  retry: OperationsRetry;
}>;
export function operationsFailure(code: OperationsCode, requestId: string): OperationsFailure {
  const safe = new OperationsError(code).code;
  return Object.freeze({
    schemaVersion: 1,
    status: 'unavailable',
    requestId: operationsUuid(requestId),
    code: safe,
    retry:
      safe === 'access_denied'
        ? 'authenticate'
        : safe === 'cursor_stale'
          ? 'refresh_first_page'
          : safe === 'overloaded' || safe === 'unavailable'
            ? 'same_read'
            : 'none',
  });
}
const METRIC_KEYS = {
  inbox: [
    'accepted',
    'replayed',
    'rejected',
    'dependencyErrors',
    'overloaded',
    'telemetryFailures',
    'active',
  ],
  inbox_telemetry: ['observerPending', 'observerDropped', 'observerFailures'],
  dispatch: [
    'dispatch:dispatched',
    'dispatch:blocked',
    'dispatch:uncertain',
    'dispatch:pending',
    'dispatch:not_eligible',
    'dispatch:exhausted',
    'dispatch:timeout',
    'dispatch:DispatchClaimLost',
    'dispatch:StorageUnavailable',
    'dispatch:AccessDenied',
    'dispatch:OperationConflict',
    'dispatch:Overloaded',
    'dispatch:UpgradeRequired',
    'dispatch:SchemaMismatch',
    'dispatch:AdapterUnavailable',
    'dispatch:InvalidConfiguration',
  ],
  gateway: [
    'accepted',
    'replayed',
    'dispatched',
    'pollErrors',
    'telemetryFailures',
    'active',
    'intakes',
    'sockets',
    'handlers',
    'driver',
    'observerPending',
  ],
  outbox: [
    'enqueued',
    'enqueueReplayed',
    'enqueueConflicts',
    'started',
    'accepted',
    'definitiveFailure',
    'unknown',
    'held',
    'rejected',
    'retryInvocations',
    'lookupInvocations',
    'recoveryAcknowledgementUnknown',
    'active',
    'observerPending',
    'observerDropped',
    'telemetryFailures',
  ],
  callbacks: [
    'accepted',
    'replayed',
    'rejected',
    'conflicts',
    'webhookRejected',
    'waiterRejected',
    'telemetryFailures',
    'observerDropped',
    'active',
    'observerPending',
  ],
  communication: [
    'responsesAccepted',
    'responsesReplayed',
    'observationsAccepted',
    'observationsReplayed',
    'identityConflicts',
    'rejected',
    'unknownAcknowledgements',
    'capacityRejected',
    'telemetryFailures',
    'observerPending',
    'observerDropped',
  ],
  rehydration: [
    'started',
    'known',
    'denied',
    'invalid',
    'unavailable',
    'overloaded',
    'waiterRejected',
    'telemetryFailures',
    'observerDropped',
    'active',
    'observerPending',
  ],
  operations: [
    'started',
    'known',
    'rejected',
    'unavailable',
    'active',
    'observerPending',
    'observerDropped',
    'observerFailures',
    'getterPending',
    'getterFailures',
    'spansRetained',
    'observationsDropped',
    'readerActive',
    'readerStarted',
    'readerKnown',
    'readerWaiterRejected',
  ],
} as const;
export const OPERATIONS_METRICS = Object.freeze(
  Object.fromEntries(
    Object.entries(METRIC_KEYS).map(([name, values]) => [name, Object.freeze([...values])]),
  ),
) as typeof METRIC_KEYS;
export type OperationsSource = keyof typeof OPERATIONS_METRICS;
export type OperationsMetric = Readonly<{ name: string; value: number }>;
export type OperationsMetricSnapshot = Readonly<{
  source: OperationsSource;
  state: 'observed' | 'pending' | 'unavailable';
  observedAt: string;
  values: readonly OperationsMetric[];
}>;
export const OPERATIONS_EVENT_CODES = Object.freeze([
  'known',
  'invalid_query',
  'access_denied',
  'cursor_stale',
  'overloaded',
  'unavailable',
  'closed',
  'waiter_abandoned',
  'accepted',
  'replayed',
  'rejected',
  'dependency_failure',
  'started',
  'dispatched',
  'uncertain',
  'pending',
  'blocked',
  'exhausted',
  'observer_failed',
  'observer_dropped',
  'InvalidConfiguration',
  'InvalidEvent',
  'AccessDenied',
  'AssociationRequired',
  'AssociationRejected',
  'IdentityConflict',
  'Overloaded',
  'NotFound',
  'StorageUnavailable',
  'AcknowledgementUnknown',
  'SchemaMismatch',
  'CleanupIncomplete',
  'UpgradeRequired',
  'DispatchClaimLost',
  'DispatchUnavailable',
  'OperationConflict',
  'WebhookRejected',
  'invalid_http',
  'body_limit',
  'body_timeout',
  'request_aborted',
  'capacity',
  'unauthorized',
  'not_found',
  'identity_conflict',
  'storage_unavailable',
  'acknowledgement_unknown',
  'closing',
  'cleanup_incomplete',
  'invalid_input',
  'forbidden',
  'idempotency_conflict',
  'capacity_exhausted',
  'dependency_unavailable',
  'communication_known',
  'queued',
  'held',
  'unknown',
  'accepted_by_provider',
  'definitive_not_accepted',
  'route_selected',
  'suppressed',
  'unsuppressed',
  'recovery_known',
  'recovery_unknown',
  'recovery_held',
  'recovery_conflicted',
  'recovery_replayed',
  'lookup_started',
  'retry_started',
  'busy',
  'not_due',
  'not_needed',
  'timeout',
  'context_unavailable',
  'webhook_rejected',
] as const);
export type OperationsEventCode = (typeof OPERATIONS_EVENT_CODES)[number];
export type OperationsObservation = Readonly<{
  kind: 'read_span' | 'producer_log';
  source: OperationsSource;
  operation: 'context' | 'telemetry' | 'producer';
  status: 'ok' | 'error' | 'unknown' | 'rejected' | 'closed';
  code: OperationsEventCode;
  observedAt: string;
  durationMs: number;
  requestId: string | null;
}>;
export type OperationsTelemetrySnapshot = Readonly<{
  schemaVersion: 1;
  status: 'known';
  scope: 'process';
  requestId: string;
  observedAt: string;
  sources: readonly OperationsMetricSnapshot[];
  observations: readonly OperationsObservation[];
}>;
export function operationsMetrics(
  source: OperationsSource,
  value: unknown,
): readonly OperationsMetric[] {
  if (typeof source !== 'string' || !Object.hasOwn(OPERATIONS_METRICS, source))
    throw new OperationsError('invalid_query');
  if (!value || typeof value !== 'object') throw new OperationsError('invalid_query');
  const names = Reflect.ownKeys(value);
  if (
    names.length > 16 ||
    names.some(
      (n) =>
        typeof n !== 'string' || !(OPERATIONS_METRICS[source] as readonly string[]).includes(n),
    )
  )
    throw new OperationsError('invalid_query');
  const r = operationsRecord(value, names as string[]);
  return Object.freeze(
    (names as string[])
      .sort()
      .map((name) => Object.freeze({ name, value: operationsCount(r[name]) })),
  );
}
export function operationsObservation(value: unknown): OperationsObservation {
  const r = operationsRecord(value, [
    'kind',
    'source',
    'operation',
    'status',
    'code',
    'observedAt',
    'durationMs',
    'requestId',
  ]);
  if (
    !['read_span', 'producer_log'].includes(r.kind as string) ||
    typeof r.source !== 'string' ||
    !Object.hasOwn(OPERATIONS_METRICS, r.source) ||
    !['context', 'telemetry', 'producer'].includes(r.operation as string) ||
    !['ok', 'error', 'unknown', 'rejected', 'closed'].includes(r.status as string) ||
    typeof r.code !== 'string' ||
    !(OPERATIONS_EVENT_CODES as readonly string[]).includes(r.code)
  )
    throw new OperationsError('invalid_query');
  if (
    (r.kind === 'read_span') !== (r.requestId !== null) ||
    (r.kind === 'read_span' && r.operation === 'producer') ||
    (r.kind === 'producer_log' && r.operation !== 'producer')
  )
    throw new OperationsError('invalid_query');
  return Object.freeze({
    kind: r.kind as OperationsObservation['kind'],
    source: r.source as OperationsSource,
    operation: r.operation as OperationsObservation['operation'],
    status: r.status as OperationsObservation['status'],
    code: r.code as OperationsEventCode,
    observedAt: operationsIso(r.observedAt),
    durationMs: operationsCount(r.durationMs),
    requestId: r.requestId === null ? null : operationsUuid(r.requestId),
  });
}
export function operationsTelemetrySnapshot(
  value: unknown,
  requestId: string,
): OperationsTelemetrySnapshot {
  const r = operationsRecord(value, [
    'schemaVersion',
    'status',
    'scope',
    'requestId',
    'observedAt',
    'sources',
    'observations',
  ]);
  if (
    r.schemaVersion !== 1 ||
    r.status !== 'known' ||
    r.scope !== 'process' ||
    r.requestId !== operationsUuid(requestId)
  )
    throw new OperationsError('unavailable');
  const seen = new Set<string>();
  const sources = Object.freeze(
    operationsArray(r.sources, 8).map((value) => {
      const x = operationsRecord(value, ['source', 'state', 'observedAt', 'values']);
      if (
        typeof x.source !== 'string' ||
        !Object.hasOwn(OPERATIONS_METRICS, x.source) ||
        seen.has(x.source) ||
        !['observed', 'pending', 'unavailable'].includes(x.state as string)
      )
        throw new OperationsError('unavailable');
      seen.add(x.source);
      const entries = operationsArray(x.values, 16);
      const raw: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
      for (const item of entries) {
        const m = operationsRecord(item, ['name', 'value']);
        if (typeof m.name !== 'string' || Object.hasOwn(raw, m.name))
          throw new OperationsError('unavailable');
        raw[m.name] = m.value;
      }
      const values = operationsMetrics(x.source as OperationsSource, raw);
      if (x.state !== 'observed' && values.length) throw new OperationsError('unavailable');
      return Object.freeze({
        source: x.source as OperationsSource,
        state: x.state as OperationsMetricSnapshot['state'],
        observedAt: operationsIso(x.observedAt),
        values,
      });
    }),
  );
  return Object.freeze({
    schemaVersion: 1,
    status: 'known',
    scope: 'process',
    requestId,
    observedAt: operationsIso(r.observedAt),
    sources,
    observations: Object.freeze(operationsArray(r.observations, 32).map(operationsObservation)),
  });
}

/** Bounded UTF-8 JSON with duplicate object keys rejected before ordinary schema decoding. */
export function operationsJson(raw: Uint8Array, maximum: number): unknown {
  try {
    if (!(raw instanceof Uint8Array) || raw.byteLength < 1 || raw.byteLength > maximum)
      throw Error();
    const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
    let offset = 0;
    const space = () => {
      while (offset < text.length && /[\x20\x09\x0a\x0d]/.test(text[offset]!)) offset++;
    };
    const string = () => {
      const start = offset;
      if (text[offset++] !== '"') throw Error();
      while (offset < text.length) {
        const ch = text[offset++]!;
        if (ch === '"') return JSON.parse(text.slice(start, offset)) as string;
        if (ch === '\\') {
          if (offset >= text.length) throw Error();
          offset++;
        } else if (ch < ' ') throw Error();
      }
      throw Error();
    };
    const value = (depth: number): void => {
      if (depth > 32) throw Error();
      space();
      const ch = text[offset];
      if (ch === '{') {
        offset++;
        space();
        const keys = new Set<string>();
        if (text[offset] === '}') {
          offset++;
          return;
        }
        while (true) {
          space();
          const key = string();
          if (keys.has(key)) throw Error();
          keys.add(key);
          space();
          if (text[offset++] !== ':') throw Error();
          value(depth + 1);
          space();
          const next = text[offset++];
          if (next === '}') return;
          if (next !== ',') throw Error();
        }
      }
      if (ch === '[') {
        offset++;
        space();
        if (text[offset] === ']') {
          offset++;
          return;
        }
        while (true) {
          value(depth + 1);
          space();
          const next = text[offset++];
          if (next === ']') return;
          if (next !== ',') throw Error();
        }
      }
      if (ch === '"') {
        string();
        return;
      }
      const match =
        /^(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/.exec(
          text.slice(offset),
        );
      if (!match) throw Error();
      offset += match[0].length;
    };
    value(0);
    space();
    if (offset !== text.length) throw Error();
    return JSON.parse(text, (_key: string, item: unknown) => {
      if (typeof item === 'number' && !Number.isFinite(item)) throw Error();
      if (typeof item === 'string')
        for (let n = 0; n < item.length; n++) {
          const c = item.charCodeAt(n);
          if (c >= 0xd800 && c <= 0xdbff) {
            const d = item.charCodeAt(++n);
            if (!(d >= 0xdc00 && d <= 0xdfff)) throw Error();
          } else if (c >= 0xdc00 && c <= 0xdfff) throw Error();
        }
      return item;
    }) as unknown;
  } catch {
    throw new OperationsError('unavailable');
  }
}
