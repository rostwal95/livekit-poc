/** Fixed operator read projection. This module starts no listener or background worker. */
import { randomUUID, timingSafeEqual } from 'node:crypto';
import {
  createServer,
  request as httpRequest,
  type IncomingMessage,
  type ServerResponse,
  type Server,
  type ClientRequest,
} from 'node:http';
import type { Socket } from 'node:net';
import { OperationsTelemetry } from './operations-telemetry.js';
import type { ChannelInbox } from './postgres.js';
import type { FakeSmsIntegration } from './security.js';
import { ChannelError } from './public-types.js';
import { rehydrationInbox } from './rehydration-access.js';
import { RehydrationStore } from './rehydration-store.js';
import {
  currentCase,
  currentReference,
  rehydrationContext,
  RehydrationError,
  type CurrentCasePort,
  type CurrentCaseReference,
} from './rehydration-types.js';
import { checkedSignal, isAborted, listenAbort, unlistenAbort } from './routing-types.js';
import { OperationsCursorStore } from './operations-store.js';
import {
  OperationsError,
  operationsUuid,
  operationsQuery,
  operationsRecord,
  operationsJson,
  operationsFailure,
  operationsTelemetrySnapshot,
  OPERATIONS_SECTIONS,
  type OperationsCode,
  type OperationsCursors,
  type OperationsTelemetrySnapshot,
  DEFAULT_OPERATIONS_QUERY,
  type OperationsContext,
  type OperationsQuery,
} from './operations-types.js';
export type OperationsProfile = Readonly<{
  profileId: string;
  sourceId: string;
  reference: CurrentCaseReference;
  bindingId: string;
  nativeToken: string;
  cursorKey: Uint8Array;
}>;
export * from './operations-types.js';
export {
  OperationsTelemetry,
  type OperationsMetricSource,
  type OperationsObserver,
} from './operations-telemetry.js';

type ReadTask = { controller: AbortController; settled: Promise<void>; abandon: () => void };
function inspectMethod(port: CurrentCasePort): CurrentCasePort['inspect'] {
  try {
    let current: object | null = port;
    for (let n = 0; current && n < 4; n++, current = Object.getPrototypeOf(current)) {
      const d = Object.getOwnPropertyDescriptor(current, 'inspect');
      if (d) {
        if ('value' in d && typeof d.value === 'function')
          return d.value.bind(port) as CurrentCasePort['inspect'];
        break;
      }
    }
  } catch {
    /* closed failure below */
  }
  throw new OperationsError('invalid_query');
}
function safeOperations(error: unknown): OperationsError {
  let code: unknown;
  try {
    if (error !== null && (typeof error === 'object' || typeof error === 'function')) {
      const d = Object.getOwnPropertyDescriptor(error, 'code');
      if (d && 'value' in d) code = d.value;
    }
  } catch {
    return new OperationsError('unavailable');
  }
  if (error instanceof OperationsError) return new OperationsError(code as OperationsError['code']);
  if (error instanceof RehydrationError)
    return new OperationsError(
      code === 'access_denied'
        ? 'access_denied'
        : code === 'overloaded'
          ? 'overloaded'
          : 'unavailable',
    );
  if (
    error instanceof ChannelError &&
    typeof code === 'string' &&
    ['AccessDenied', 'AssociationRequired', 'AssociationRejected', 'NotFound'].includes(code)
  )
    return new OperationsError('access_denied');
  return new OperationsError('unavailable');
}
const readers = new WeakSet<object>();
export class OperationsReader {
  readonly #store: RehydrationStore;
  readonly #cursors: OperationsCursorStore;
  readonly #inspect: CurrentCasePort['inspect'];
  readonly #tasks = new Set<ReadTask>();
  #closing = false;
  #closeDrain: Promise<void> | undefined;
  #closeObservation: Promise<void> | undefined;
  #counts = {
    started: 0,
    known: 0,
    denied: 0,
    invalid: 0,
    unavailable: 0,
    overloaded: 0,
    waiterRejected: 0,
  };
  constructor(
    inbox: ChannelInbox,
    cases: CurrentCasePort,
    sms: FakeSmsIntegration,
    profile: OperationsProfile,
  ) {
    const access = rehydrationInbox(inbox);
    if (!access) throw new OperationsError('invalid_query');
    this.#cursors = new OperationsCursorStore(access, profile);
    this.#store = new RehydrationStore(access, sms);
    this.#inspect = inspectMethod(cases);
    readers.add(this);
  }
  get reference(): CurrentCaseReference {
    return this.#cursors.reference;
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({ ...this.#counts, active: this.#tasks.size });
  }
  assertDistinctOperator(authorization: string): void {
    this.#cursors.distinctOperator(authorization);
  }
  read(
    requestId: string,
    query: OperationsQuery = DEFAULT_OPERATIONS_QUERY,
    external?: AbortSignal,
  ): Promise<OperationsContext> {
    let copied: OperationsQuery;
    try {
      operationsUuid(requestId);
      copied = operationsQuery(query);
      if (external !== undefined) checkedSignal(external);
    } catch {
      this.#counts.invalid++;
      return Promise.reject(new OperationsError('invalid_query'));
    }
    if (this.#closing) return Promise.reject(new OperationsError('closed'));
    if (this.#tasks.size >= 2) {
      this.#counts.overloaded++;
      return Promise.reject(new OperationsError('overloaded'));
    }
    if (external !== undefined && isAborted(external))
      return Promise.reject(new OperationsError('unavailable'));
    this.#counts.started++;
    const controller = new AbortController(),
      deadline = performance.now() + 3000;
    let timer: ReturnType<typeof setTimeout> | undefined, onAbort: (() => void) | undefined;
    let failed = false;
    let fail: (closed?: boolean) => void = () => undefined;
    const waiter = new Promise<never>((_, reject) => {
      fail = (closed = false) => {
        if (failed) return;
        failed = true;
        this.#counts.waiterRejected++;
        controller.abort();
        reject(new OperationsError(closed ? 'closed' : 'unavailable'));
      };
      timer = setTimeout(() => fail(), 3000);
      if (external !== undefined) {
        onAbort = () => fail();
        listenAbort(external, onAbort);
      }
    });
    const task: ReadTask = { controller, settled: Promise.resolve(), abandon: () => fail(true) };
    this.#tasks.add(task);
    const check = () => {
      if (this.#closing || controller.signal.aborted || performance.now() >= deadline)
        throw new OperationsError(this.#closing ? 'closed' : 'unavailable');
    };
    const work = Promise.resolve().then(async () => {
      check();
      const prepared = await this.#cursors.prepare(copied);
      check();
      const source = Object.freeze({ kind: 'native' as const, bearer: this.#cursors.nativeToken });
      const snapshot = await this.#store.snapshot(source, prepared.query);
      check();
      const authority = currentCase(
          await this.#inspect(snapshot.ref, controller.signal),
          snapshot.ref,
        ),
        caseObservedAt = new Date().toISOString();
      check();
      const disclosureAdmittedAt = await this.#store.disclose(source, snapshot);
      check();
      const context = rehydrationContext(
        {
          schemaVersion: 1,
          contextId: randomUUID(),
          access: snapshot.access,
          case: authority,
          history: snapshot.history,
          work: snapshot.work,
          responses: snapshot.responses,
          replies: snapshot.replies,
          observed: {
            p2ObservedAt: snapshot.p2ObservedAt,
            caseObservedAt,
            disclosureAdmittedAt,
            atomic: false,
          },
        },
        snapshot.ref,
      );
      const cursors = this.#cursors.finish(context, prepared);
      check();
      const result: OperationsContext = Object.freeze({
        schemaVersion: 1,
        status: 'known',
        requestId,
        context,
        cursors,
      });
      const legacy = Buffer.byteLength(
          JSON.stringify({ schemaVersion: 1, status: 'known', context }),
        ),
        bytes = Buffer.byteLength(JSON.stringify(result));
      if (legacy > 65536 || bytes - legacy > 8192 || bytes > 73728)
        throw new OperationsError('unavailable');
      check();
      return result;
    });
    const settled = () => {
      this.#tasks.delete(task);
      clearTimeout(timer);
      if (external !== undefined && onAbort) unlistenAbort(external, onAbort);
    };
    task.settled = work.then(settled, settled);
    return Promise.race([work, waiter])
      .then((value) => {
        check();
        this.#counts.known++;
        return value;
      })
      .catch((error: unknown) => {
        const safe = safeOperations(error);
        this.#counts[
          safe.code === 'access_denied'
            ? 'denied'
            : safe.code === 'invalid_query' || safe.code === 'cursor_stale'
              ? 'invalid'
              : safe.code === 'overloaded'
                ? 'overloaded'
                : 'unavailable'
        ]++;
        throw safe;
      });
  }
  close(): Promise<void> {
    this.#closing = true;
    for (const task of this.#tasks) task.abandon();
    if (!this.#closeDrain)
      this.#closeDrain = Promise.all([...this.#tasks].map((task) => task.settled)).then(() => {
        if (this.#tasks.size) throw new OperationsError('unavailable');
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
export function isOperationsReader(value: unknown): value is OperationsReader {
  return typeof value === 'object' && value !== null && readers.has(value);
}

/** An operator capability exposes reads only; application owns reader and telemetry drains. */
export type OperationsEndpoint = Readonly<{ host: '127.0.0.1'; port: number }>;
export const OPERATIONS_HTTP_STATUS = Object.freeze({
  invalid_query: 400,
  access_denied: 403,
  cursor_stale: 409,
  overloaded: 429,
  unavailable: 503,
  closed: 503,
} as const);
function operatorAuthorization(value: unknown): string {
  if (typeof value !== 'string' || !/^Bearer [A-Za-z0-9_-]{43}(?![\s\S])/.test(value))
    throw new OperationsError('invalid_query');
  return value;
}
function responseStatus(code: OperationsCode): number {
  return OPERATIONS_HTTP_STATUS[code];
}
function onceCloseObservation(
  drain: Promise<void>,
  previous: Promise<void> | undefined,
  save: (value: Promise<void> | undefined) => void,
): Promise<void> {
  if (previous) return previous;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const observed = Promise.race([
    drain,
    new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new OperationsError('unavailable')), 1000);
    }),
  ]);
  save(observed);
  void observed
    .finally(() => {
      clearTimeout(timer);
      save(undefined);
    })
    .catch(() => undefined);
  return observed;
}
export class OperationsReadServer {
  readonly #server: Server;
  readonly #reader: OperationsReader;
  readonly #telemetry: OperationsTelemetry;
  readonly #authorization: Buffer;
  readonly #sockets = new Set<Socket>();
  readonly #handlers = new Set<Promise<void>>();
  #closing = false;
  #started = false;
  #bind: Promise<void> | undefined;
  #drain: Promise<void> | undefined;
  #observation: Promise<void> | undefined;
  readonly #counts = { started: 0, known: 0, rejected: 0 };
  constructor(reader: OperationsReader, telemetry: OperationsTelemetry, authorization: string) {
    if (!isOperationsReader(reader) || !(telemetry instanceof OperationsTelemetry))
      throw new OperationsError('invalid_query');
    this.#reader = reader;
    this.#telemetry = telemetry;
    this.#authorization = Buffer.from(operatorAuthorization(authorization));
    OperationsReader.prototype.assertDistinctOperator.call(reader, authorization);
    this.#server = createServer(
      { maxHeaderSize: 4096, insecureHTTPParser: false, connectionsCheckingInterval: 100 },
      (req, res) => {
        if (this.#closing || this.#handlers.size >= 2) {
          req.socket.destroy();
          return;
        }
        const work = this.#handle(req, res);
        this.#handlers.add(work);
        void work.finally(() => this.#handlers.delete(work)).catch(() => undefined);
      },
    );
    this.#server.headersTimeout = 1000;
    this.#server.requestTimeout = 4000;
    this.#server.keepAliveTimeout = 1;
    this.#server.maxRequestsPerSocket = 1;
    this.#server.maxConnections = 16;
    this.#server.on('connection', (socket) => {
      if (this.#closing || this.#sockets.size >= 16) {
        socket.destroy();
        return;
      }
      this.#sockets.add(socket);
      socket.once('close', () => this.#sockets.delete(socket));
    });
    this.#server.on('clientError', (_, socket) => socket.destroy());
    for (const event of ['upgrade', 'connect'] as const)
      this.#server.on(event, (_req, socket) => socket.destroy());
    this.#server.on('checkContinue', (req) => req.socket.destroy());
    this.#server.on('checkExpectation', (req) => req.socket.destroy());
    this.#server.on('error', () => undefined);
  }
  metrics() {
    return Object.freeze({
      ...this.#counts,
      sockets: this.#sockets.size,
      handlers: this.#handlers.size,
    });
  }
  async start(port = 0): Promise<OperationsEndpoint> {
    if (this.#closing || this.#started || !Number.isInteger(port) || port < 0 || port > 65535)
      throw new OperationsError('invalid_query');
    this.#started = true;
    this.#bind = new Promise<void>((resolve, reject) => {
      const failed = () => {
        this.#server.off('listening', ready);
        reject(new OperationsError());
      };
      const ready = () => {
        this.#server.off('error', failed);
        resolve();
      };
      this.#server.once('error', failed);
      this.#server.once('listening', ready);
      this.#server.listen(port, '127.0.0.1');
    });
    await this.#bind;
    if (this.#closing) {
      await this.close();
      throw new OperationsError('closed');
    }
    const address = this.#server.address();
    if (!address || typeof address === 'string') throw new OperationsError();
    return Object.freeze({ host: '127.0.0.1', port: address.port });
  }
  #headers(req: IncomingMessage): Record<string, string> {
    const headers: Record<string, string> = Object.create(null) as Record<string, string>;
    let bytes = 2;
    for (let n = 0; n < req.rawHeaders.length; n += 2) {
      const key = req.rawHeaders[n]!.toLowerCase(),
        value = req.rawHeaders[n + 1]!;
      bytes += Buffer.byteLength(key) + Buffer.byteLength(value) + 4;
      if (bytes > 4096 || Object.hasOwn(headers, key)) throw new OperationsError('invalid_query');
      headers[key] = value;
    }
    return headers;
  }
  #query(req: IncomingMessage, h: Record<string, string>): OperationsQuery | null {
    const address = this.#server.address();
    if (
      req.method !== 'GET' ||
      !req.url ||
      Buffer.byteLength(req.url) > 4096 ||
      !address ||
      typeof address === 'string' ||
      h.host !== `127.0.0.1:${address.port}` ||
      h['transfer-encoding'] !== undefined ||
      h['content-encoding'] !== undefined ||
      h.expect !== undefined ||
      (h['content-length'] !== undefined && h['content-length'] !== '0')
    )
      throw new OperationsError('invalid_query');
    const question = req.url.indexOf('?'),
      path = question < 0 ? req.url : req.url.slice(0, question),
      search = question < 0 ? '' : req.url.slice(question + 1);
    if (path === '/v1/operations/telemetry') {
      if (question >= 0) throw new OperationsError('invalid_query');
      return null;
    }
    if (path !== '/v1/operations/context' || /%(?![0-9a-f]{2})/i.test(search))
      throw new OperationsError('invalid_query');
    const params = new URLSearchParams(search),
      values: Record<string, string> = {};
    for (const [key, value] of params) {
      if (!['section', 'cursor'].includes(key) || Object.hasOwn(values, key))
        throw new OperationsError('invalid_query');
      values[key] = value;
    }
    return operationsQuery({ section: values.section ?? 'history', cursor: values.cursor ?? null });
  }
  async #send(
    res: ServerResponse,
    status: number,
    requestId: string,
    value: unknown,
    maximum: number,
  ): Promise<void> {
    const raw = Buffer.from(JSON.stringify(value));
    if (raw.length > maximum) throw new OperationsError('unavailable');
    if (res.destroyed) throw new OperationsError('unavailable');
    await new Promise<void>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      const clean = () => {
        clearTimeout(timer);
        res.off('finish', finished);
        res.off('close', closed);
        res.off('error', closed);
      };
      const finished = () => {
        clean();
        resolve();
      };
      const closed = () => {
        clean();
        reject(new OperationsError());
      };
      res.once('finish', finished);
      res.once('close', closed);
      res.once('error', closed);
      timer = setTimeout(() => {
        closed();
        res.socket?.destroy();
      }, 1000);
      try {
        res.writeHead(status, {
          'Content-Type': 'application/json',
          'Content-Length': String(raw.length),
          'Cache-Control': 'no-store',
          Connection: 'close',
          'x-p2-request-id': requestId,
        });
        res.end(raw);
      } catch {
        closed();
        res.socket?.destroy();
      }
    });
  }
  async #handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    this.#counts.started++;
    let requestId: string = randomUUID(),
      timer: ReturnType<typeof setTimeout> | undefined;
    const abort = new AbortController();
    const stopped = () => {
      if (!res.writableFinished) abort.abort();
    };
    res.once('close', stopped);
    let end: ReturnType<OperationsTelemetry['begin']> = () => {};
    try {
      const h = this.#headers(req);
      requestId = operationsUuid(h['x-p2-request-id']);
      const provided = Buffer.from(h.authorization ?? '');
      if (
        provided.length !== this.#authorization.length ||
        !timingSafeEqual(provided, this.#authorization)
      )
        throw new OperationsError('access_denied');
      const query = this.#query(req, h);
      end = OperationsTelemetry.prototype.begin.call(
        this.#telemetry,
        requestId,
        query === null ? 'telemetry' : 'context',
      );
      timer = setTimeout(() => {
        abort.abort();
        req.socket.destroy();
      }, 4000);
      // All accepted GETs must reach the actual end-of-body event before disclosure.
      await new Promise<void>((resolve, reject) => {
        req.on('data', () => {
          reject(new OperationsError('invalid_query'));
          req.socket.destroy();
        });
        req.once('end', resolve);
        req.once('error', () => reject(new OperationsError()));
        req.once('aborted', () => reject(new OperationsError()));
      });
      const value =
        query === null
          ? OperationsTelemetry.prototype.snapshot.call(this.#telemetry, requestId)
          : await OperationsReader.prototype.read.call(
              this.#reader,
              requestId,
              query,
              abort.signal,
            );
      if (abort.signal.aborted || this.#closing) throw new OperationsError('closed');
      await this.#send(res, 200, requestId, value, query === null ? 16384 : 73728);
      this.#counts.known++;
      end('ok', 'known');
    } catch (error) {
      this.#counts.rejected++;
      const safe = safeOperations(error);
      end(safe.code === 'closed' ? 'closed' : 'error', safe.code);
      try {
        if (!res.headersSent)
          await this.#send(
            res,
            responseStatus(safe.code),
            requestId,
            operationsFailure(safe.code, requestId),
            1024,
          );
        else req.socket.destroy();
      } catch {
        req.socket.destroy();
      }
    } finally {
      clearTimeout(timer);
      res.off('close', stopped);
    }
  }
  close(): Promise<void> {
    this.#closing = true;
    for (const socket of this.#sockets) socket.destroy();
    if (!this.#drain)
      this.#drain = (async () => {
        if (this.#bind) await this.#bind.catch(() => undefined);
        await new Promise<void>((resolve) => {
          if (!this.#server.listening) resolve();
          else this.#server.close(() => resolve());
        });
        await Promise.all([...this.#handlers]);
        if (this.#sockets.size || this.#handlers.size) {
          await new Promise<void>((resolve) => setImmediate(resolve));
          if (this.#sockets.size || this.#handlers.size) throw new OperationsError();
        }
      })();
    return onceCloseObservation(this.#drain, this.#observation, (value) => {
      this.#observation = value;
    });
  }
}

type HttpCall = {
  request: ClientRequest | undefined;
  socket: Socket | undefined;
  releaseWaiter: () => void;
  settled: Promise<void>;
};
export class OperationsHttpClient {
  readonly #endpoint: OperationsEndpoint;
  readonly #authorization: string;
  readonly #reference: CurrentCaseReference;
  readonly #bindingId: string;
  readonly #calls = new Set<HttpCall>();
  #closing = false;
  #drain: Promise<void> | undefined;
  #observation: Promise<void> | undefined;
  readonly #counts = { started: 0, known: 0, rejected: 0, unavailable: 0, overloaded: 0 };
  constructor(
    endpoint: OperationsEndpoint,
    authorization: string,
    expected: Readonly<{ reference: CurrentCaseReference; bindingId: string }>,
  ) {
    const e = operationsRecord(endpoint, ['host', 'port']),
      x = operationsRecord(expected, ['reference', 'bindingId']);
    if (
      e.host !== '127.0.0.1' ||
      !Number.isInteger(e.port) ||
      (e.port as number) < 1 ||
      (e.port as number) > 65535
    )
      throw new OperationsError('invalid_query');
    this.#endpoint = Object.freeze({ host: '127.0.0.1', port: e.port as number });
    this.#authorization = operatorAuthorization(authorization);
    this.#reference = currentReference(x.reference);
    this.#bindingId = operationsUuid(x.bindingId);
  }
  metrics() {
    return Object.freeze({ ...this.#counts, active: this.#calls.size });
  }
  context(
    query: OperationsQuery = DEFAULT_OPERATIONS_QUERY,
    signal?: AbortSignal,
  ): Promise<OperationsContext> {
    let copied: OperationsQuery;
    try {
      copied = operationsQuery(query);
    } catch {
      return Promise.reject(new OperationsError('invalid_query'));
    }
    const search = new URLSearchParams({ section: copied.section });
    if (copied.cursor !== null) search.set('cursor', copied.cursor);
    return this.#get('/v1/operations/context?' + search.toString(), 73728, signal, (value, id) => {
      const v = operationsRecord(value, [
        'schemaVersion',
        'status',
        'requestId',
        'context',
        'cursors',
      ]);
      if (v.schemaVersion !== 1 || v.status !== 'known' || v.requestId !== id) throw Error();
      const context = rehydrationContext(v.context, this.#reference);
      if (context.access.kind !== 'native' || context.access.bindingId !== this.#bindingId)
        throw Error();
      const c = operationsRecord(v.cursors, ['history', 'work', 'responses', 'replies']);
      const cursors = Object.freeze(
        Object.fromEntries(
          OPERATIONS_SECTIONS.map((section) => [
            section,
            operationsQuery({ section, cursor: c[section] }).cursor,
          ]),
        ),
      ) as OperationsCursors;
      const result: OperationsContext = Object.freeze({
        schemaVersion: 1,
        status: 'known',
        requestId: id,
        context,
        cursors,
      });
      const legacy = Buffer.byteLength(
          JSON.stringify({ schemaVersion: 1, status: 'known', context }),
        ),
        bytes = Buffer.byteLength(JSON.stringify(result));
      if (legacy > 65536 || bytes - legacy > 8192 || bytes > 73728) throw Error();
      return result;
    });
  }
  telemetry(signal?: AbortSignal): Promise<OperationsTelemetrySnapshot> {
    return this.#get('/v1/operations/telemetry', 16384, signal, (value, id) =>
      operationsTelemetrySnapshot(value, id),
    );
  }
  #get<T>(
    path: string,
    maximum: number,
    signal: AbortSignal | undefined,
    decode: (value: unknown, requestId: string) => T,
  ): Promise<T> {
    try {
      if (signal !== undefined) checkedSignal(signal);
    } catch {
      return Promise.reject(new OperationsError('invalid_query'));
    }
    if (this.#closing) return Promise.reject(new OperationsError('closed'));
    if (signal !== undefined && isAborted(signal)) return Promise.reject(new OperationsError());
    if (this.#calls.size >= 2) {
      this.#counts.overloaded++;
      return Promise.reject(new OperationsError('overloaded'));
    }
    this.#counts.started++;
    const requestId = randomUUID();
    let finish: () => void = () => {},
      rejectWaiter: (error: OperationsError) => void = () => {};
    let timer: ReturnType<typeof setTimeout> | undefined, onAbort: (() => void) | undefined;
    let requestClosed = false,
      socketClosed = false,
      waiterDone = false;
    const call: HttpCall = {
      request: undefined,
      socket: undefined,
      releaseWaiter: () => {},
      settled: new Promise<void>((resolve) => {
        finish = resolve;
      }),
    };
    this.#calls.add(call);
    const settle = () => {
      if (!requestClosed || !socketClosed) return;
      this.#calls.delete(call);
      clearTimeout(timer);
      if (signal !== undefined && onAbort) unlistenAbort(signal, onAbort);
      finish();
    };
    const result = new Promise<T>((resolve, reject) => {
      const fail = (error: OperationsError) => {
        if (!waiterDone) {
          waiterDone = true;
          this.#counts[error.code === 'unavailable' ? 'unavailable' : 'rejected']++;
          reject(error);
        }
        call.request?.destroy();
      };
      rejectWaiter = fail;
      call.releaseWaiter = () => fail(new OperationsError('closed'));
      try {
        const req = httpRequest(
          {
            host: this.#endpoint.host,
            port: this.#endpoint.port,
            path,
            method: 'GET',
            agent: false,
            maxHeaderSize: 4096,
            headers: {
              Host: `127.0.0.1:${this.#endpoint.port}`,
              Authorization: this.#authorization,
              Connection: 'close',
              'x-p2-request-id': requestId,
            },
          },
          (res) => {
            const chunks: Buffer[] = [];
            let size = 0;
            const limit = res.statusCode === 200 ? maximum : 1024;
            try {
              const h: Record<string, string> = {};
              let headerBytes = 2;
              for (let n = 0; n < res.rawHeaders.length; n += 2) {
                const key = res.rawHeaders[n]!.toLowerCase(),
                  value = res.rawHeaders[n + 1]!;
                headerBytes += Buffer.byteLength(key) + Buffer.byteLength(value) + 4;
                if (headerBytes > 4096 || Object.hasOwn(h, key)) throw Error();
                h[key] = value;
              }
              if (
                h['x-p2-request-id'] !== requestId ||
                h['content-type'] !== 'application/json' ||
                h['content-encoding'] !== undefined ||
                h['transfer-encoding'] !== undefined ||
                h.connection !== 'close' ||
                h['cache-control'] !== 'no-store' ||
                !/^[1-9][0-9]{0,5}(?![\s\S])/.test(h['content-length'] ?? '') ||
                Number(h['content-length']) > limit
              )
                throw Error();
              res.on('data', (chunk: Buffer) => {
                size += chunk.length;
                if (size > limit || size > Number(h['content-length'])) {
                  fail(new OperationsError());
                  res.destroy();
                } else chunks.push(Buffer.from(chunk));
              });
              res.once('end', () => {
                if (waiterDone) return;
                try {
                  if (size !== Number(h['content-length'])) throw Error();
                  const value = operationsJson(Buffer.concat(chunks), limit);
                  if (res.statusCode === 200) {
                    const decoded = decode(value, requestId);
                    waiterDone = true;
                    this.#counts.known++;
                    resolve(decoded);
                  } else {
                    const r = operationsRecord(value, [
                      'schemaVersion',
                      'status',
                      'requestId',
                      'code',
                      'retry',
                    ]);
                    const expected = operationsFailure(r.code as OperationsCode, requestId);
                    if (
                      r.schemaVersion !== 1 ||
                      r.status !== 'unavailable' ||
                      r.requestId !== requestId ||
                      r.code !== expected.code ||
                      r.retry !== expected.retry ||
                      res.statusCode !== responseStatus(expected.code)
                    )
                      throw Error();
                    fail(new OperationsError(expected.code));
                  }
                } catch {
                  fail(new OperationsError());
                }
              });
            } catch {
              fail(new OperationsError());
              res.destroy();
            }
            res.once('error', () => fail(new OperationsError()));
            res.once('aborted', () => fail(new OperationsError()));
          },
        );
        call.request = req;
        req.once('socket', (socket) => {
          call.socket = socket;
          socket.once('close', () => {
            socketClosed = true;
            settle();
          });
        });
        req.once('close', () => {
          requestClosed = true;
          if (!call.socket) socketClosed = true;
          settle();
        });
        req.once('error', () => fail(new OperationsError()));
        req.end();
      } catch {
        if (!call.request) requestClosed = socketClosed = true;
        fail(new OperationsError());
        settle();
      }
    });
    if (this.#calls.has(call)) timer = setTimeout(() => rejectWaiter(new OperationsError()), 4000);
    if (signal !== undefined && this.#calls.has(call)) {
      onAbort = () => rejectWaiter(new OperationsError());
      listenAbort(signal, onAbort);
      if (isAborted(signal)) onAbort();
    }
    return result;
  }
  close(): Promise<void> {
    this.#closing = true;
    for (const call of this.#calls) call.releaseWaiter();
    if (!this.#drain)
      this.#drain = Promise.all([...this.#calls].map((call) => call.settled)).then(() => {
        if (this.#calls.size) throw new OperationsError();
      });
    return onceCloseObservation(this.#drain, this.#observation, (value) => {
      this.#observation = value;
    });
  }
}
