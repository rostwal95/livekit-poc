/** Explicit process-local samples and safe read spans; never a work queue or exporter service. */
import {
  OperationsError,
  OPERATIONS_METRICS,
  operationsArray,
  operationsRecord,
  operationsMetrics,
  operationsObservation,
  operationsUuid,
  type OperationsSource,
  type OperationsMetricSnapshot,
  type OperationsMetric,
  type OperationsObservation,
  type OperationsEventCode,
  type OperationsTelemetrySnapshot,
} from './operations-types.js';

// These literals are the existing public producer envelopes, not arbitrary log labels.
const INBOX_CODES = [
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
];
const STEP_CODES = [
  'busy',
  'blocked',
  'not_due',
  'exhausted',
  'uncertain',
  'not_needed',
  'dispatched',
];
const GATEWAY_CODES = [
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
  'closed',
  'communication_known',
];
const OUTBOX_CODES = [
  'queued',
  'replayed',
  'held',
  'unknown',
  'accepted_by_provider',
  'definitive_not_accepted',
  'exhausted',
  'unavailable',
  'rejected',
  'identity_conflict',
  'route_selected',
  'suppressed',
  'unsuppressed',
  'ok',
  'recovery_known',
  'recovery_unknown',
  'recovery_held',
  'recovery_conflicted',
  'recovery_replayed',
  'lookup_started',
  'retry_started',
];
const READ_CODES = [
  'known',
  'access_denied',
  'invalid_query',
  'context_unavailable',
  'overloaded',
  'closed',
];
const INBOX_OPERATIONS = [
  'challenge',
  'associate',
  'revoke',
  'accept',
  'inspect',
  'history',
  'inspect_confirmation',
  'communication',
  'rehydration',
  'pool',
  'close',
];
const INBOX_EVENTS = {
  completed: ['ok', 'known', 'accepted', 'replayed'],
  rejected: INBOX_CODES,
  dependency_failure: ['StorageUnavailable'],
  closed: ['ok'],
};
const PRODUCER_EVENTS: Readonly<
  Record<OperationsSource, Readonly<Record<string, readonly string[]>>>
> = {
  inbox: INBOX_EVENTS,
  inbox_telemetry: INBOX_EVENTS,
  communication: INBOX_EVENTS,
  dispatch: {
    dispatch: [
      ...STEP_CODES,
      ...INBOX_CODES.filter((code) => code !== 'InvalidEvent' && code !== 'WebhookRejected'),
      'timeout',
    ],
  },
  gateway: {
    http: [...GATEWAY_CODES, 'accepted', 'replayed'],
    poll: [
      ...GATEWAY_CODES.filter(
        (code) =>
          ![
            'invalid_input',
            'forbidden',
            'idempotency_conflict',
            'capacity_exhausted',
            'dependency_unavailable',
            'closed',
            'communication_known',
          ].includes(code),
      ),
      ...STEP_CODES,
    ],
    close: ['closed'],
  },
  outbox: {
    completed: OUTBOX_CODES,
    rejected: ['identity_conflict', 'unknown', 'rejected'],
    waiter_rejected: ['unknown', 'unavailable', 'recovery_unknown'],
    closed: ['ok'],
  },
  callbacks: {
    accepted: ['ok'],
    replayed: ['ok'],
    rejected: ['identity_conflict', 'webhook_rejected', 'unknown', 'overloaded', 'rejected'],
    waiter_rejected: ['unknown', 'unavailable'],
    closed: ['ok'],
  },
  rehydration: {
    completed: ['known'],
    rejected: READ_CODES,
    waiter_rejected: ['context_unavailable', 'closed'],
    closed: ['closed'],
  },
  operations: {
    completed: ['known'],
    rejected: [
      'invalid_query',
      'access_denied',
      'cursor_stale',
      'overloaded',
      'unavailable',
      'closed',
    ],
    waiter_rejected: ['unavailable', 'closed'],
    closed: ['closed'],
  },
};
function producerObservation(source: OperationsSource, value: unknown) {
  if (!value || typeof value !== 'object') throw Error();
  const keys = Reflect.ownKeys(value),
    hasOperation = keys.includes('operation');
  const r = operationsRecord(
    value,
    hasOperation ? ['event', 'operation', 'code'] : ['event', 'code'],
  );
  if (
    hasOperation &&
    (!['inbox', 'inbox_telemetry', 'communication'].includes(source) ||
      typeof r.operation !== 'string' ||
      !INBOX_OPERATIONS.includes(r.operation))
  )
    throw Error();
  if (typeof r.event !== 'string' || typeof r.code !== 'string') throw Error();
  const events = PRODUCER_EVENTS[source];
  if (!Object.hasOwn(events, r.event) || !events[r.event]!.includes(r.code)) throw Error();
  // Public callbacks use event accepted/replayed with their common success code ok.
  // Retain that distinction; every other distinct cause remains its original literal.
  const code = (
    r.code === 'ok'
      ? r.event === 'accepted' || r.event === 'replayed'
        ? r.event
        : r.event === 'closed'
          ? 'closed'
          : 'known'
      : r.code
  ) as OperationsEventCode;
  const status: OperationsObservation['status'] =
    r.event === 'closed' || r.event === 'close' || ['closed', 'closing'].includes(code)
      ? 'closed'
      : [
            'unknown',
            'uncertain',
            'AcknowledgementUnknown',
            'acknowledgement_unknown',
            'recovery_unknown',
            'DispatchClaimLost',
          ].includes(code) ||
          r.event === 'waiter_rejected' ||
          code === 'timeout'
        ? 'unknown'
        : r.event === 'dependency_failure' ||
            [
              'StorageUnavailable',
              'storage_unavailable',
              'dependency_unavailable',
              'context_unavailable',
              'unavailable',
              'CleanupIncomplete',
              'cleanup_incomplete',
              'DispatchUnavailable',
              'InvalidConfiguration',
              'SchemaMismatch',
              'UpgradeRequired',
            ].includes(code)
          ? 'error'
          : r.event === 'rejected' ||
              [
                'blocked',
                'exhausted',
                'definitive_not_accepted',
                'recovery_conflicted',
                'AccessDenied',
                'AssociationRequired',
                'AssociationRejected',
                'IdentityConflict',
                'OperationConflict',
                'Overloaded',
                'InvalidEvent',
                'NotFound',
                'invalid_http',
                'body_limit',
                'body_timeout',
                'request_aborted',
                'capacity',
                'unauthorized',
                'not_found',
                'identity_conflict',
                'invalid_input',
                'forbidden',
                'idempotency_conflict',
                'capacity_exhausted',
              ].includes(code)
            ? 'rejected'
            : 'ok';
  return { code, status };
}

export type OperationsMetricSource = Readonly<{ source: OperationsSource; read: () => unknown }>;
export type OperationsObserver = (observation: OperationsObservation) => void | PromiseLike<void>;
type Entry = {
  source: OperationsSource;
  read: () => unknown;
  pending: boolean;
  ready: boolean;
  state: OperationsMetricSnapshot['state'];
  at: string;
  values: readonly OperationsMetric[];
};
type Stats = {
  started: number;
  known: number;
  rejected: number;
  unavailable: number;
  observerDropped: number;
  observerFailures: number;
  getterFailures: number;
  observationsDropped: number;
};
export class OperationsTelemetry {
  readonly #sources: Entry[] = [];
  readonly #observer: OperationsObserver | undefined;
  readonly #owners = new Set<Promise<void>>();
  readonly #observations: OperationsObservation[] = [];
  #closing = false;
  #closeDrain: Promise<void> | undefined;
  #closeObservation: Promise<void> | undefined;
  #exports = 0;
  #getters = 0;
  #active = 0;
  #stats: Stats = {
    started: 0,
    known: 0,
    rejected: 0,
    unavailable: 0,
    observerDropped: 0,
    observerFailures: 0,
    getterFailures: 0,
    observationsDropped: 0,
  };
  constructor(sources: readonly OperationsMetricSource[] = [], observer?: OperationsObserver) {
    if (observer !== undefined && typeof observer !== 'function')
      throw new OperationsError('invalid_query');
    this.#observer = observer;
    const seen = new Set<string>();
    for (const raw of operationsArray(sources, 8)) {
      const r = operationsRecord(raw, ['source', 'read']);
      if (
        typeof r.source !== 'string' ||
        !Object.hasOwn(OPERATIONS_METRICS, r.source) ||
        seen.has(r.source) ||
        typeof r.read !== 'function'
      )
        throw new OperationsError('invalid_query');
      seen.add(r.source);
      this.#sources.push({
        source: r.source as OperationsSource,
        read: r.read as () => unknown,
        pending: false,
        ready: false,
        state: 'unavailable',
        at: new Date().toISOString(),
        values: Object.freeze([]),
      });
    }
  }
  #increment(key: keyof Stats): void {
    this.#stats[key] = Math.min(Number.MAX_SAFE_INTEGER, this.#stats[key] + 1);
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({
      ...this.#stats,
      active: this.#active,
      observerPending: this.#exports,
      getterPending: this.#getters,
      spansRetained: this.#observations.length,
    });
  }
  #retain(work: Promise<void>): void {
    this.#owners.add(work);
    void work.finally(() => this.#owners.delete(work)).catch(() => undefined);
  }
  #completion(): () => void {
    let release: () => void = () => {};
    this.#retain(
      new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    return release;
  }
  #publish(value: OperationsObservation): void {
    if (this.#closing) return;
    const observed = operationsObservation(value);
    if (this.#observations.length === 32) {
      this.#observations.shift();
      this.#increment('observationsDropped');
    }
    this.#observations.push(observed);
    if (!this.#observer) return;
    if (this.#exports >= 8) {
      this.#increment('observerDropped');
      return;
    }
    this.#exports++;
    const complete = this.#completion();
    try {
      const returned = this.#observer(observed);
      if (returned !== undefined) {
        const work = Promise.resolve(returned)
          .then(
            () => undefined,
            () => {
              this.#increment('observerFailures');
            },
          )
          .finally(() => {
            this.#exports--;
            complete();
          });
        void work.catch(() => undefined);
      } else {
        this.#exports--;
        complete();
      }
    } catch {
      this.#exports--;
      complete();
      this.#increment('observerFailures');
    }
  }
  observer(source: OperationsSource): (value: unknown) => void {
    if (typeof source !== 'string' || !Object.hasOwn(OPERATIONS_METRICS, source))
      throw new OperationsError('invalid_query');
    return (value: unknown) => {
      if (this.#closing) return;
      try {
        const { code, status } = producerObservation(source, value);
        this.#publish({
          kind: 'producer_log',
          source,
          operation: 'producer',
          status,
          code,
          observedAt: new Date().toISOString(),
          durationMs: 0,
          requestId: null,
        });
      } catch {
        this.#increment('observationsDropped');
      }
    };
  }
  begin(
    requestId: string,
    operation: 'context' | 'telemetry',
  ): (status: OperationsObservation['status'], code: OperationsEventCode) => void {
    operationsUuid(requestId);
    if (this.#closing || this.#active >= 2) {
      this.#increment('observationsDropped');
      return () => {};
    }
    if (!['context', 'telemetry'].includes(operation)) throw new OperationsError('invalid_query');
    const began = performance.now();
    let ended = false;
    let release: () => void = () => {};
    this.#retain(
      new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    this.#active++;
    this.#increment('started');
    return (status, code) => {
      if (ended) return;
      ended = true;
      this.#active--;
      release();
      this.#increment(
        status === 'ok' ? 'known' : status === 'rejected' ? 'rejected' : 'unavailable',
      );
      try {
        this.#publish({
          kind: 'read_span',
          source: 'operations',
          operation,
          status,
          code,
          observedAt: new Date().toISOString(),
          durationMs: Math.ceil(performance.now() - began),
          requestId,
        });
      } catch {
        this.#increment('observationsDropped');
      }
    };
  }
  #sample(entry: Entry): OperationsMetricSnapshot {
    const snapshot = () =>
      Object.freeze({
        source: entry.source,
        state: entry.state,
        observedAt: entry.at,
        values: entry.state === 'observed' ? entry.values : Object.freeze([]),
      });
    if (this.#closing) return snapshot();
    if (entry.pending) {
      entry.state = 'pending';
      return snapshot();
    }
    if (entry.ready) {
      entry.ready = false;
      return snapshot();
    }
    entry.pending = true;
    this.#getters++;
    const complete = this.#completion();
    try {
      const raw = entry.read();
      const then =
        raw !== null && (typeof raw === 'object' || typeof raw === 'function')
          ? (raw as { then?: unknown }).then
          : undefined;
      if (typeof then === 'function') {
        entry.state = 'pending';
        entry.at = new Date().toISOString();
        const work = Promise.resolve(raw)
          .then(
            (value) => {
              entry.values = operationsMetrics(entry.source, value);
              entry.state = 'observed';
            },
            () => {
              entry.state = 'unavailable';
              this.#increment('getterFailures');
            },
          )
          .catch(() => {
            entry.state = 'unavailable';
            this.#increment('getterFailures');
          })
          .finally(() => {
            entry.at = new Date().toISOString();
            entry.pending = false;
            entry.ready = true;
            this.#getters--;
            complete();
          });
        void work.catch(() => undefined);
      } else {
        entry.values = operationsMetrics(entry.source, raw);
        entry.state = 'observed';
        entry.at = new Date().toISOString();
        entry.pending = false;
        this.#getters--;
        complete();
      }
    } catch {
      entry.state = 'unavailable';
      entry.at = new Date().toISOString();
      entry.pending = false;
      this.#getters--;
      complete();
      this.#increment('getterFailures');
    }
    return snapshot();
  }
  snapshot(requestId: string): OperationsTelemetrySnapshot {
    operationsUuid(requestId);
    if (this.#closing) throw new OperationsError('closed');
    return Object.freeze({
      schemaVersion: 1,
      status: 'known',
      scope: 'process',
      requestId,
      observedAt: new Date().toISOString(),
      sources: Object.freeze(this.#sources.map((entry) => this.#sample(entry))),
      observations: Object.freeze([...this.#observations]),
    });
  }
  close(): Promise<void> {
    this.#closing = true;
    if (!this.#closeDrain)
      this.#closeDrain = Promise.all([...this.#owners]).then(() => {
        if (this.#owners.size || this.#active || this.#exports || this.#getters)
          throw new OperationsError('unavailable');
      });
    if (this.#closeObservation) return this.#closeObservation;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const observation = Promise.race([
      this.#closeDrain,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new OperationsError('unavailable')), 1000);
      }),
    ]);
    this.#closeObservation = observation;
    void observation
      .finally(() => {
        clearTimeout(timer);
        if (this.#closeObservation === observation) this.#closeObservation = undefined;
      })
      .catch(() => undefined);
    return observation;
  }
}
