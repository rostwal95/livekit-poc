/** Read-only operations observations and one retained browser owner. Reviewed 12 November 2026. */
import { parseBusinessJson } from './business';
import { parseRehydrationContext } from './p2-context-policy';
import type {
  ContextMessage,
  ContextWork,
  ContextResponse,
  ContextReply,
  RehydrationContext,
} from './p2-context-policy';
import {
  DEFAULT_OPERATIONS_QUERY,
  operationsQuery,
  operationsRecord,
  operationsText,
  operationsUuid,
  operationsTelemetrySnapshot,
} from '@livekit-ecosystem/channel-continuity/operations-types';
import type {
  OperationsSection,
  OperationsQuery,
  OperationsCursors,
  OperationsTelemetrySnapshot,
  OperationsCode,
  OperationsRetry,
} from '@livekit-ecosystem/channel-continuity/operations-types';

export type { OperationsSection, OperationsQuery, OperationsTelemetrySnapshot };
export const SECTIONS = ['history', 'work', 'responses', 'replies'] as const;
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });
const retryCodes = {
  invalid_query: 'none',
  access_denied: 'authenticate',
  cursor_stale: 'refresh_first_page',
  overloaded: 'same_read',
  unavailable: 'same_read',
  closed: 'none',
} as const;
export type UiCode = OperationsCode | 'invalid_response' | 'cleanup_incomplete';
export class OperationsUiError extends Error {
  readonly retry: OperationsRetry;
  constructor(
    readonly code: UiCode,
    retry?: OperationsRetry,
  ) {
    super(code);
    this.retry =
      retry ??
      (code === 'invalid_response'
        ? 'same_read'
        : code === 'cleanup_incomplete'
          ? 'none'
          : retryCodes[code]);
    this.name = 'OperationsUiError';
  }
}
function invalid(): never {
  throw new OperationsUiError('invalid_response');
}
function countBytes(value: unknown): number {
  return encoder.encode(JSON.stringify(value)).length;
}
function stable(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if (value && typeof value === 'object')
    return (
      '{' +
      Object.keys(value)
        .sort()
        .map((k) => JSON.stringify(k) + ':' + stable((value as Record<string, unknown>)[k]))
        .join(',') +
      '}'
    );
  return JSON.stringify(value);
}
export type ReadBinding = Readonly<{
  bindingId: string;
  roomId: string;
  participantId: string;
  scope: Readonly<{ tenantId: string; accountId: string }>;
  caseId: string;
  conversationId: string;
}>;
export type OperationsView = Readonly<{
  schemaVersion: 1;
  status: 'known';
  requestId: string;
  context: RehydrationContext;
  cursors: OperationsCursors;
}>;
function readBinding(context: RehydrationContext): ReadBinding {
  return Object.freeze({
    bindingId: context.access.bindingId,
    roomId: context.access.roomId,
    participantId: context.access.participantId,
    scope: Object.freeze({ ...context.case.scope }),
    caseId: context.case.caseId,
    conversationId: context.case.conversationId,
  });
}
export function parseOperationsContext(
  raw: Uint8Array,
  requestId: string,
  expected?: ReadBinding,
): OperationsView {
  try {
    if (!(raw instanceof Uint8Array) || raw.length < 1 || raw.length > 73728) return invalid();
    const v = operationsRecord(parseBusinessJson(decoder.decode(raw)), [
      'schemaVersion',
      'status',
      'requestId',
      'context',
      'cursors',
    ]);
    if (v.schemaVersion !== 1 || v.status !== 'known' || v.requestId !== operationsUuid(requestId))
      return invalid();
    const c = operationsRecord(v.context, [
      'schemaVersion',
      'contextId',
      'access',
      'case',
      'history',
      'work',
      'responses',
      'replies',
      'observed',
    ]);
    const access = operationsRecord(c.access, ['kind', 'bindingId', 'roomId', 'participantId']);
    if (access.kind !== 'native') return invalid();
    const identity = {
      bindingId: operationsUuid(access.bindingId),
      roomId: operationsText(access.roomId, 128, true),
      participantId: operationsText(access.participantId, 128, true),
    };
    const legacy = { schemaVersion: 1, status: 'known', context: v.context };
    const full = {
      schemaVersion: 1,
      status: 'known',
      requestId: v.requestId,
      context: v.context,
      cursors: v.cursors,
    };
    if (
      countBytes(legacy) > 65536 ||
      countBytes(full) > 73728 ||
      countBytes(full) - countBytes(legacy) > 8192
    )
      return invalid();
    const context = parseRehydrationContext(
      encoder.encode(JSON.stringify(legacy)),
      identity,
      expected
        ? {
            scope: expected.scope,
            caseId: expected.caseId,
            conversationId: expected.conversationId,
          }
        : undefined,
    );
    const binding = readBinding(context);
    if (expected && stable(binding) !== stable(expected)) return invalid();
    const cursorValues = operationsRecord(v.cursors, [...SECTIONS]);
    const cursors = {} as Record<OperationsSection, string | null>;
    for (const section of SECTIONS)
      cursors[section] = operationsQuery({ section, cursor: cursorValues[section] }).cursor;
    return Object.freeze({
      schemaVersion: 1,
      status: 'known',
      requestId,
      context,
      cursors: Object.freeze(cursors),
    });
  } catch {
    return invalid();
  }
}
export function parseOperationsTelemetry(
  raw: Uint8Array,
  requestId: string,
): OperationsTelemetrySnapshot {
  try {
    if (!(raw instanceof Uint8Array) || raw.length < 1 || raw.length > 16384) return invalid();
    return operationsTelemetrySnapshot(parseBusinessJson(decoder.decode(raw)), requestId);
  } catch {
    return invalid();
  }
}
export function parseOperationsFailure(raw: Uint8Array, requestId: string): OperationsUiError {
  try {
    if (!(raw instanceof Uint8Array) || raw.length < 1 || raw.length > 1024) return invalid();
    const v = operationsRecord(parseBusinessJson(decoder.decode(raw)), [
      'schemaVersion',
      'status',
      'requestId',
      'code',
      'retry',
    ]);
    if (
      v.schemaVersion !== 1 ||
      v.status !== 'unavailable' ||
      v.requestId !== operationsUuid(requestId) ||
      typeof v.code !== 'string' ||
      !Object.hasOwn(retryCodes, v.code)
    )
      return invalid();
    const code = v.code as OperationsCode;
    if (v.retry !== retryCodes[code]) return invalid();
    return new OperationsUiError(code, retryCodes[code]);
  } catch {
    return new OperationsUiError('unavailable');
  }
}
export interface ClientMetrics {
  readonly active: number;
  readonly started: number;
  readonly settled: number;
  readonly contextStarted: number;
  readonly telemetryStarted: number;
  readonly abandoned: number;
}
export interface OperationsClient {
  context(query: OperationsQuery, signal?: AbortSignal): Promise<OperationsView>;
  telemetry(signal?: AbortSignal): Promise<OperationsTelemetrySnapshot>;
  metrics(): ClientMetrics;
  close(): Promise<void>;
}
interface HttpOwner {
  kind: 'context' | 'telemetry';
  controller: AbortController;
  settled: Promise<void>;
}
async function responseBytes(response: Response, maximum: number): Promise<Uint8Array> {
  if (!response.body) return invalid();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    const length = response.headers.get('content-length');
    if (length !== null && (!/^(0|[1-9][0-9]*)$/.test(length) || Number(length) > maximum))
      return invalid();
    const contentType = response.headers.get('content-type')?.toLowerCase();
    if (contentType !== 'application/json' && contentType !== 'application/json; charset=utf-8')
      return invalid();
    for (;;) {
      const item = await reader.read();
      if (item.done) break;
      total += item.value.length;
      if (total > maximum) return invalid();
      chunks.push(item.value);
    }
    if (!total || (length !== null && total !== Number(length))) return invalid();
    const result = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      result.set(chunk, offset);
      offset += chunk.length;
    }
    return result;
  } catch (error) {
    try {
      await reader.cancel();
    } catch {
      /* Preserve the validation/transport failure. */
    }
    throw error;
  } finally {
    reader.releaseLock();
  }
}
export class BrowserOperationsClient implements OperationsClient {
  #token: string;
  #closed = false;
  #closing: Promise<void> | null = null;
  #binding: ReadBinding | undefined;
  #owners = new Set<HttpOwner>();
  #counts = { started: 0, settled: 0, contextStarted: 0, telemetryStarted: 0, abandoned: 0 };
  constructor(
    token: string,
    readonly changed: () => void = () => {},
    readonly fetcher: typeof fetch = fetch,
    readonly requestId: () => string = () => crypto.randomUUID(),
  ) {
    if (!/^[A-Za-z0-9_-]{43}(?![\s\S])/.test(token)) throw new OperationsUiError('invalid_query');
    this.#token = token;
  }
  #notify(): void {
    try {
      this.changed();
    } catch {
      /* Rendering cannot release or strand HTTP ownership. */
    }
  }
  metrics(): ClientMetrics {
    return Object.freeze({ active: this.#owners.size, ...this.#counts });
  }
  context(query: OperationsQuery, signal?: AbortSignal): Promise<OperationsView> {
    const q = operationsQuery(query);
    return this.#read('context', q, signal) as Promise<OperationsView>;
  }
  telemetry(signal?: AbortSignal): Promise<OperationsTelemetrySnapshot> {
    return this.#read('telemetry', undefined, signal) as Promise<OperationsTelemetrySnapshot>;
  }
  #read(
    kind: 'context' | 'telemetry',
    query: OperationsQuery | undefined,
    external?: AbortSignal,
  ): Promise<OperationsView | OperationsTelemetrySnapshot> {
    if (this.#closed) return Promise.reject(new OperationsUiError('closed'));
    if (this.#owners.size >= 2 || [...this.#owners].some((x) => x.kind === kind))
      return Promise.reject(new OperationsUiError('overloaded'));
    if (external?.aborted) return Promise.reject(new OperationsUiError('unavailable'));
    const requestId = operationsUuid(this.requestId());
    const owner: HttpOwner = {
      kind,
      controller: new AbortController(),
      settled: Promise.resolve(),
    };
    this.#owners.add(owner);
    const authorization = 'Bearer ' + this.#token;
    const work = Promise.resolve().then(async () => {
      if (this.#closed || owner.controller.signal.aborted) throw new OperationsUiError('closed');
      this.#counts.started++;
      this.#counts[kind === 'context' ? 'contextStarted' : 'telemetryStarted']++;
      const search = query
        ? '?' +
          new URLSearchParams({
            section: query.section,
            ...(query.cursor ? { cursor: query.cursor } : {}),
          }).toString()
        : '';
      // Native browser fetch rejects a client instance as its WebIDL receiver.
      const fetcher = this.fetcher;
      const response = await fetcher('/p2-operations/' + kind + search, {
        method: 'GET',
        headers: { authorization, 'x-p2-request-id': requestId },
        credentials: 'omit',
        cache: 'no-store',
        redirect: 'error',
        mode: 'same-origin',
        signal: owner.controller.signal,
      });
      const raw = await responseBytes(
        response,
        response.status === 200 ? (kind === 'context' ? 73728 : 16384) : 1024,
      );
      if (response.headers.get('x-p2-request-id') !== requestId || response.redirected)
        return invalid();
      if (response.status !== 200) {
        const failure = parseOperationsFailure(raw, requestId);
        const status = {
          access_denied: 403,
          invalid_query: 400,
          cursor_stale: 409,
          overloaded: 429,
          unavailable: 503,
          closed: 503,
        } as const;
        if (
          !Object.hasOwn(status, failure.code) ||
          status[failure.code as OperationsCode] !== response.status
        )
          return invalid();
        throw failure;
      }
      if (kind === 'telemetry') return parseOperationsTelemetry(raw, requestId);
      const value = parseOperationsContext(raw, requestId, this.#binding);
      this.#binding ??= readBinding(value.context);
      return value;
    });
    owner.settled = work.then(
      () => {
        this.#owners.delete(owner);
        this.#counts.settled++;
        this.#notify();
      },
      () => {
        this.#owners.delete(owner);
        this.#counts.settled++;
        this.#notify();
      },
    );
    let timer: ReturnType<typeof setTimeout> | undefined;
    let abandon: (() => void) | undefined;
    const waiter = new Promise<never>((_resolve, reject) => {
      abandon = () => {
        this.#counts.abandoned++;
        reject(new OperationsUiError('unavailable'));
      };
      timer = setTimeout(abandon, 4000);
      external?.addEventListener('abort', abandon, { once: true });
    });
    return Promise.race([work, waiter])
      .catch((error: unknown) => {
        throw error instanceof OperationsUiError ? error : new OperationsUiError('unavailable');
      })
      .finally(() => {
        clearTimeout(timer);
        if (abandon) external?.removeEventListener('abort', abandon);
      });
  }
  close(): Promise<void> {
    this.#closed = true;
    this.#token = '';
    for (const owner of this.#owners) owner.controller.abort();
    if (!this.#closing)
      this.#closing = Promise.all([...this.#owners].map((x) => x.settled)).then(() => undefined);
    const actual = this.#closing;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const wait = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new OperationsUiError('cleanup_incomplete')), 1000);
    });
    return Promise.race([actual, wait]).finally(() => clearTimeout(timer));
  }
}

export interface ObservedRow<T> {
  readonly value: T;
  readonly observedAt: string;
}
export interface OperationsRows {
  readonly history: readonly ObservedRow<ContextMessage>[];
  readonly work: readonly ObservedRow<ContextWork>[];
  readonly responses: readonly ObservedRow<ContextResponse>[];
  readonly replies: readonly ObservedRow<ContextReply>[];
}
const emptyRows = (): OperationsRows => ({ history: [], work: [], responses: [], replies: [] });
const emptyCursors = (): OperationsCursors => ({
  history: null,
  work: null,
  responses: null,
  replies: null,
});
export type OperationsPhase =
  'idle' | 'connecting' | 'ready' | 'unavailable' | 'denied' | 'closing';
export interface OperationsState {
  readonly phase: OperationsPhase;
  readonly view: OperationsView | null;
  readonly telemetry: OperationsTelemetrySnapshot | null;
  readonly rows: OperationsRows;
  readonly cursors: OperationsCursors;
  readonly contextHistorical: boolean;
  readonly diagnosticsHistorical: boolean;
  readonly error: Readonly<{ code: UiCode; retry: OperationsRetry }> | null;
  readonly telemetryError: UiCode | null;
  readonly contextPending: boolean;
  readonly telemetryPending: boolean;
  readonly ownedClient: 0 | 1;
  readonly actualRequests: number;
  readonly cleanupComplete: boolean;
  readonly polling: boolean;
  readonly ticksRemaining: number;
  readonly ticks: number;
  readonly clientMetrics: ClientMetrics;
  readonly lastSection: OperationsSection;
}
interface ControllerOwner {
  client: OperationsClient;
  epoch: number;
  retiring: boolean;
  close: Promise<void> | null;
}
export type ClientFactory = (token: string, changed: () => void) => OperationsClient;
function safeError(error: unknown): OperationsUiError {
  return error instanceof OperationsUiError ? error : new OperationsUiError('unavailable');
}
function cache<T>(items: readonly T[], stamp: string): readonly ObservedRow<T>[] {
  return Object.freeze(
    items.slice(0, 32).map((value) => Object.freeze({ value, observedAt: stamp })),
  );
}
function joinRows<T>(
  old: readonly ObservedRow<T>[],
  items: readonly T[],
  stamp: string,
  key: (value: T) => string,
  immutable: (value: T) => unknown,
): readonly ObservedRow<T>[] {
  const result = [...old];
  for (const value of items) {
    const index = result.findIndex((x) => key(x.value) === key(value));
    if (index >= 0) {
      if (stable(immutable(result[index]!.value)) !== stable(immutable(value))) return invalid();
      result[index] = Object.freeze({ value, observedAt: stamp });
    } else result.push(Object.freeze({ value, observedAt: stamp }));
  }
  return Object.freeze(result.slice(0, 32));
}
export class OperationsController {
  #owner: ControllerOwner | null = null;
  #epoch = 0;
  #view: OperationsView | null = null;
  #telemetry: OperationsTelemetrySnapshot | null = null;
  #rows: OperationsRows = emptyRows();
  #cursors: OperationsCursors = emptyCursors();
  #failure: OperationsUiError | null = null;
  #telemetryError: UiCode | null = null;
  #contextHistorical = false;
  #diagnosticsHistorical = false;
  #contextPending = false;
  #telemetryPending = false;
  #denied = false;
  #polling = false;
  #remaining = 0;
  #ticks = 0;
  #timer: ReturnType<typeof setTimeout> | undefined;
  #lastQuery: OperationsQuery = DEFAULT_OPERATIONS_QUERY;
  constructor(
    readonly changed: (state: OperationsState) => void,
    readonly factory: ClientFactory = (token, update) => new BrowserOperationsClient(token, update),
  ) {}
  snapshot(): OperationsState {
    const owner = this.#owner;
    const clientMetrics = owner?.client.metrics() ?? {
      active: 0,
      started: 0,
      settled: 0,
      contextStarted: 0,
      telemetryStarted: 0,
      abandoned: 0,
    };
    const phase: OperationsPhase = owner?.retiring
      ? 'closing'
      : !owner
        ? 'idle'
        : this.#denied
          ? 'denied'
          : this.#failure
            ? 'unavailable'
            : this.#view
              ? 'ready'
              : this.#contextPending
                ? 'connecting'
                : 'unavailable';
    return Object.freeze({
      phase,
      view: this.#view,
      telemetry: this.#telemetry,
      rows: this.#rows,
      cursors: this.#cursors,
      contextHistorical: this.#contextHistorical,
      diagnosticsHistorical: this.#diagnosticsHistorical,
      error: this.#failure
        ? Object.freeze({ code: this.#failure.code, retry: this.#failure.retry })
        : null,
      telemetryError: this.#telemetryError,
      contextPending: this.#contextPending,
      telemetryPending: this.#telemetryPending,
      ownedClient: owner ? 1 : 0,
      actualRequests: clientMetrics.active,
      cleanupComplete: !owner,
      polling: this.#polling,
      ticksRemaining: this.#remaining,
      ticks: this.#ticks,
      clientMetrics,
      lastSection: this.#lastQuery.section,
    });
  }
  #emit(): void {
    try {
      this.changed(this.snapshot());
    } catch {
      /* View callbacks do not own lifecycle work. */
    }
  }
  #valid(owner: ControllerOwner): boolean {
    return this.#owner === owner && owner.epoch === this.#epoch && !owner.retiring;
  }
  async connect(token: string): Promise<void> {
    if (this.#owner) throw new OperationsUiError('overloaded');
    if (!/^[A-Za-z0-9_-]{43}(?![\s\S])/.test(token)) throw new OperationsUiError('invalid_query');
    let owner: ControllerOwner | null = null;
    const client = this.factory(token, () => {
      if (owner && this.#owner === owner) this.#emit();
    });
    owner = { client, epoch: ++this.#epoch, retiring: false, close: null };
    this.#owner = owner;
    this.#failure = null;
    this.#telemetryError = null;
    this.#denied = false;
    this.#remaining = 30;
    this.#ticks = 0;
    await Promise.allSettled([
      this.#context(owner, DEFAULT_OPERATIONS_QUERY, false),
      this.#diagnostics(owner),
    ]);
    if (this.#valid(owner) && !this.#failure && !this.#telemetryError) {
      this.#polling = true;
      this.#schedule();
    }
    this.#emit();
  }
  async refresh(): Promise<void> {
    const owner = this.#current();
    await Promise.allSettled([
      this.#context(owner, DEFAULT_OPERATIONS_QUERY, false),
      this.#diagnostics(owner),
    ]);
  }
  async retry(): Promise<void> {
    const owner = this.#current();
    if (this.#failure?.retry === 'same_read')
      await this.#context(owner, this.#lastQuery, this.#lastQuery.cursor !== null);
    else if (this.#telemetryError) await this.#diagnostics(owner);
    else throw new OperationsUiError('invalid_query');
  }
  async older(section: OperationsSection): Promise<void> {
    const owner = this.#current();
    const cursor = this.#cursors[section];
    if (!cursor || this.#rows[section].length >= 32) throw new OperationsUiError('invalid_query');
    this.pause();
    await this.#context(owner, { section, cursor }, true);
  }
  #current(): ControllerOwner {
    const owner = this.#owner;
    if (!owner || owner.retiring) throw new OperationsUiError('closed');
    if (this.#denied) throw new OperationsUiError('access_denied');
    return owner;
  }
  pause(): void {
    this.#polling = false;
    clearTimeout(this.#timer);
    this.#timer = undefined;
    this.#emit();
  }
  resume(): void {
    const owner = this.#current();
    if (this.#failure || this.#telemetryError || !this.#view) return;
    this.#remaining = 30;
    this.#polling = true;
    this.#schedule();
    if (this.#valid(owner)) this.#emit();
  }
  hidden(): void {
    this.pause();
  }
  #schedule(): void {
    clearTimeout(this.#timer);
    this.#timer = undefined;
    if (!this.#polling || this.#remaining <= 0) return;
    this.#timer = setTimeout(() => {
      this.#timer = undefined;
      void this.#tick();
    }, 2000);
  }
  async #tick(): Promise<void> {
    const owner = this.#owner;
    if (!owner || !this.#valid(owner) || !this.#polling) return;
    this.#remaining--;
    this.#ticks++;
    if (this.#contextPending || this.#telemetryPending) {
      if (this.#remaining === 0) this.#polling = false;
      else this.#schedule();
      this.#emit();
      return;
    }
    await Promise.allSettled([
      this.#context(owner, DEFAULT_OPERATIONS_QUERY, false),
      this.#diagnostics(owner),
    ]);
    if (this.#valid(owner) && this.#polling && this.#remaining > 0) this.#schedule();
    else if (this.#remaining === 0) this.#polling = false;
    this.#emit();
  }
  async #context(owner: ControllerOwner, query: OperationsQuery, older: boolean): Promise<void> {
    if (!this.#valid(owner) || this.#contextPending) return;
    this.#contextPending = true;
    this.#lastQuery = Object.freeze({ ...query });
    this.#emit();
    try {
      const view = await owner.client.context(query);
      if (!this.#valid(owner)) return;
      const context = view.context;
      if (
        older &&
        this.#view &&
        (context.case.source !== this.#view.context.case.source ||
          context.case.sourceRevision !== this.#view.context.case.sourceRevision)
      )
        throw new OperationsUiError('cursor_stale');
      const stamp = context.observed.p2ObservedAt;
      if (!older) {
        this.#rows = Object.freeze({
          history: cache(context.history.messages, stamp),
          work: cache(context.work.items, stamp),
          responses: cache(context.responses.items, stamp),
          replies: cache(context.replies.items, stamp),
        });
        this.#cursors = view.cursors;
      } else {
        const rows = { ...this.#rows };
        if (query.section === 'history')
          rows.history = joinRows(
            rows.history,
            context.history.messages,
            stamp,
            (x) => x.receipt.receiptId,
            (x) => ({
              receipt: x.receipt,
              event: x.event,
              operationKey: x.operationKey,
              associationVersion: x.associationVersion,
            }),
          );
        if (query.section === 'work')
          rows.work = joinRows(
            rows.work,
            context.work.items,
            stamp,
            (x) => x.receiptId,
            (x) => ({
              receiptId: x.receiptId,
              operationKey: x.operationKey,
              acceptanceSequence: x.acceptanceSequence,
            }),
          );
        if (query.section === 'responses')
          rows.responses = joinRows(
            rows.responses,
            context.responses.items,
            stamp,
            (x) => x.anchor.responseId,
            (x) => ({ anchor: x.anchor, receipt: x.receipt }),
          );
        if (query.section === 'replies')
          rows.replies = joinRows(
            rows.replies,
            context.replies.items,
            stamp,
            (x) => x.outboundId,
            (x) => ({
              outboundId: x.outboundId,
              responseId: x.responseId,
              receiptId: x.receiptId,
              acceptedAt: x.acceptedAt,
              bodyDigest: x.bodyDigest,
            }),
          );
        this.#rows = Object.freeze(rows);
        this.#cursors = Object.freeze({
          ...this.#cursors,
          [query.section]: view.cursors[query.section],
        });
      }
      this.#view = view;
      this.#failure = null;
      this.#contextHistorical = false;
    } catch (error) {
      if (this.#valid(owner)) {
        this.#failure = safeError(error);
        this.#contextHistorical = !!this.#view;
        this.#diagnosticsHistorical = !!this.#telemetry;
        this.pause();
        if (this.#failure.code === 'access_denied') this.#denied = true;
      }
    } finally {
      if (this.#owner === owner && owner.epoch === this.#epoch) this.#contextPending = false;
      this.#emit();
    }
  }
  async #diagnostics(owner: ControllerOwner): Promise<void> {
    if (!this.#valid(owner) || this.#telemetryPending || this.#denied) return;
    this.#telemetryPending = true;
    this.#emit();
    try {
      const value = await owner.client.telemetry();
      if (!this.#valid(owner) || this.#denied) return;
      this.#telemetry = value;
      this.#telemetryError = null;
      this.#diagnosticsHistorical = false;
    } catch (error) {
      if (this.#valid(owner)) {
        this.#telemetryError = safeError(error).code;
        this.#diagnosticsHistorical = !!this.#telemetry;
        this.pause();
      }
    } finally {
      if (this.#owner === owner && owner.epoch === this.#epoch) this.#telemetryPending = false;
      this.#emit();
    }
  }
  forget(): Promise<void> {
    this.pause();
    this.#epoch++;
    this.#view = null;
    this.#telemetry = null;
    this.#rows = emptyRows();
    this.#cursors = emptyCursors();
    this.#failure = null;
    this.#telemetryError = null;
    this.#contextHistorical = false;
    this.#diagnosticsHistorical = false;
    this.#contextPending = false;
    this.#telemetryPending = false;
    this.#denied = false;
    const owner = this.#owner;
    if (!owner) {
      this.#emit();
      return Promise.resolve();
    }
    owner.retiring = true;
    if (!owner.close) {
      const closing = Promise.resolve()
        .then(() => owner.client.close())
        .then(
          () => {
            if (this.#owner === owner) this.#owner = null;
            this.#emit();
          },
          () => {
            owner.close = null;
            this.#emit();
            throw new OperationsUiError('cleanup_incomplete');
          },
        );
      owner.close = closing;
      void closing.catch(() => {});
    }
    this.#emit();
    return owner.close;
  }
}
