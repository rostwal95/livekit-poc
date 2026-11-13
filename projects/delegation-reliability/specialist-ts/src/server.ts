/** One bounded scripted HTTP attempt; P1 remains the sole durable execution owner. */
import { createServer, type IncomingMessage, type ServerResponse, type Server } from 'node:http';
import type { Socket } from 'node:net';
import { randomUUID } from 'node:crypto';
import {
  CAPABILITY,
  ContractError,
  canonical,
  decode,
  encodeError,
  fields,
  hash,
  integer,
  MAX_REQUEST_BYTES,
  parseResult,
} from './contracts.js';
import type { ErrorCode } from './contracts.js';
import { encodeCapabilityResult, parseCapabilityRequest } from './capability-codec.js';
import type { CapabilityRequest, CapabilityResult } from './capability-codec.js';
import { DOCUMENT_CAPABILITY, DocumentHandler } from './document.js';
import { FixedPolicyHandler } from './fixed-policy.js';
import type { DocumentAfterDecode } from './document.js';
import { AttemptBoundary, EvidenceRegistry, LocalTrust, verifyPolicyFacts } from './security.js';
import type { AttemptPermit } from './security.js';
import { SpecialistHttpError, httpErrorBytes } from './http-protocol.js';
import type { AttemptObservation, Endpoint, HttpCode } from './http-protocol.js';
export type SpecialistLimits = Readonly<{
  maxConnections: number;
  maxRequests: number;
  maxActive: number;
  maxPerPrincipal: number;
  headerBytes: number;
  headerFields: number;
  headerMs: number;
  bodyMs: number;
  invokeMs: number;
  responseMs: number;
  closeMs: number;
}>;
export const DEFAULT_SPECIALIST_LIMITS: SpecialistLimits = Object.freeze({
  maxConnections: 16,
  maxRequests: 16,
  maxActive: 4,
  maxPerPrincipal: 2,
  headerBytes: 8192,
  headerFields: 16,
  headerMs: 1000,
  bodyMs: 2000,
  invokeMs: 5000,
  responseMs: 1000,
  closeMs: 2000,
});
export type SpecialistEvent = Readonly<{
  event: 'request_rejected' | 'attempt_started' | 'attempt_finished' | 'observation' | 'closed';
  operation: 'invoke' | 'status' | 'cancel' | 'http';
  code: ErrorCode | HttpCode | 'ok';
}>;
export type SpecialistObserver = (event: SpecialistEvent) => void | Promise<void>;
/** Trusted harness-only barrier. Never supplied or selected by request JSON. */
export type SpecialistHarnessHooks = Readonly<{
  beforeEvaluate?: (context: Readonly<{ signal: AbortSignal }>) => void | Promise<void>;
  afterDocumentDecode?: DocumentAfterDecode;
}>;
export type SpecialistServerOptions = Readonly<{
  trust: LocalTrust;
  evidence: EvidenceRegistry;
  limits?: Partial<SpecialistLimits>;
  observer?: SpecialistObserver;
  hooks?: SpecialistHarnessHooks;
  document?: DocumentHandler;
  fixedPolicy?: FixedPolicyHandler;
}>;
type Active = {
  request: CapabilityRequest;
  permit: AttemptPermit;
  controller: AbortController;
  cancel: boolean;
  expired: boolean;
  disconnected: boolean;
  closing: boolean;
};
const requestId = (): string => 'http_' + randomUUID().replaceAll('-', '');
const key = (request: CapabilityRequest) =>
  JSON.stringify([request.scope.tenant_id, request.scope.account_id, request.attempt.attempt_id]);
function limits(input: Partial<SpecialistLimits> = {}): SpecialistLimits {
  const configured = { ...DEFAULT_SPECIALIST_LIMITS, ...input };
  if (Object.keys(configured).length !== Object.keys(DEFAULT_SPECIALIST_LIMITS).length)
    throw new SpecialistHttpError('invalid_http');
  for (const [name, value] of Object.entries(configured)) {
    const maximum = DEFAULT_SPECIALIST_LIMITS[name as keyof SpecialistLimits];
    if (!Number.isSafeInteger(value) || value < (name.endsWith('Ms') ? 20 : 1) || value > maximum)
      throw new SpecialistHttpError('invalid_http');
  }
  if (configured.maxPerPrincipal > configured.maxActive)
    throw new SpecialistHttpError('invalid_http');
  return Object.freeze(configured);
}
function defaultObserver(event: SpecialistEvent): void {
  console.info(JSON.stringify({ component: 'delegation_specialist', ...event }));
}
function status(error: unknown): number {
  if (error instanceof ContractError)
    return (
      (
        {
          unauthorized: 401,
          capacity: 429,
          unknown_attempt: 404,
          identity_conflict: 409,
          expired: 408,
        } as Partial<Record<ErrorCode, number>>
      )[error.code] ?? 400
    );
  if (error instanceof SpecialistHttpError)
    return (
      (
        {
          body_limit: 413,
          body_timeout: 408,
          deadline_exceeded: 504,
          closing: 503,
          internal_error: 500,
          cleanup_incomplete: 503,
          request_aborted: 408,
        } as Partial<Record<HttpCode, number>>
      )[error.code] ?? 400
    );
  return 500;
}
function failure(error: unknown): SpecialistHttpError | ContractError {
  return error instanceof ContractError || error instanceof SpecialistHttpError
    ? error
    : new SpecialistHttpError('internal_error');
}
function observation(active: Active): AttemptObservation {
  return Object.freeze({
    schema_version: 1,
    kind: 'specialist.attempt_observation',
    scope: active.request.scope,
    delegation_id: active.request.delegation_id,
    attempt_id: active.request.attempt.attempt_id,
    input_fingerprint: active.request.input_fingerprint,
    state: 'running',
    cancel_requested: active.cancel,
    deadline_exceeded: active.expired,
    transport_disconnected: active.disconnected,
    closing: active.closing,
    durable: false,
  });
}
function readBody(
  request: IncomingMessage,
  length: number,
  milliseconds: number,
): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const deadline = performance.now() + milliseconds;
    const bytes = Buffer.alloc(length);
    let used = 0;
    let done = false;
    const finish = (error?: SpecialistHttpError): void => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      request.off('data', data);
      request.off('end', end);
      request.off('aborted', aborted);
      request.off('error', aborted);
      if (!error && performance.now() >= deadline) error = new SpecialistHttpError('body_timeout');
      if (error) {
        request.pause();
        reject(error);
      } else resolve(bytes);
    };
    const data = (chunk: Buffer): void => {
      if (used + chunk.length > length) {
        finish(new SpecialistHttpError('body_limit'));
        return;
      }
      chunk.copy(bytes, used);
      used += chunk.length;
    };
    const end = (): void =>
      finish(used === length ? undefined : new SpecialistHttpError('request_aborted'));
    const aborted = (): void => finish(new SpecialistHttpError('request_aborted'));
    const timer = setTimeout(() => finish(new SpecialistHttpError('body_timeout')), milliseconds);
    request.on('data', data);
    request.once('end', end);
    request.once('aborted', aborted);
    request.once('error', aborted);
  });
}
export class SpecialistServer {
  readonly #trust: LocalTrust;
  readonly #evidence: EvidenceRegistry;
  readonly #limits: SpecialistLimits;
  readonly #boundary: AttemptBoundary;
  readonly #observer: SpecialistObserver;
  readonly #hooks: SpecialistHarnessHooks;
  readonly #document: DocumentHandler | undefined;
  readonly #fixedPolicy: FixedPolicyHandler | undefined;
  readonly #server: Server;
  readonly #sockets = new Set<Socket>();
  readonly #socketClosed = new Map<Socket, Promise<void>>();
  readonly #headers = new Map<Socket, ReturnType<typeof setTimeout>>();
  readonly #headerDeadlines = new Map<Socket, number>();
  readonly #handlers = new Set<Promise<void>>();
  readonly #seen = new WeakSet<Socket>();
  readonly #active = new Map<string, Active>();
  readonly #work = new Set<Promise<void>>();
  #requests = 0;
  #closing = false;
  #endpoint: Endpoint | undefined;
  #starting: Promise<Endpoint> | undefined;
  #close: Promise<void> | undefined;
  #observing = 0;
  readonly #counts = {
    invoked: 0,
    completed: 0,
    rejected: 0,
    cancellations: 0,
    expirations: 0,
    disconnects: 0,
    observerFailures: 0,
    observerDropped: 0,
  };
  constructor(options: SpecialistServerOptions) {
    if (!(options.trust instanceof LocalTrust) || !(options.evidence instanceof EvidenceRegistry))
      throw new SpecialistHttpError('invalid_http');
    this.#trust = options.trust;
    this.#evidence = options.evidence;
    this.#limits = limits(options.limits);
    this.#observer = options.observer ?? defaultObserver;
    this.#hooks = Object.freeze({ ...options.hooks });
    this.#document = options.document;
    this.#fixedPolicy = options.fixedPolicy;
    if (this.#fixedPolicy !== undefined && !(this.#fixedPolicy instanceof FixedPolicyHandler))
      throw new SpecialistHttpError('invalid_http');
    if (this.#document !== undefined && !(this.#document instanceof DocumentHandler))
      throw new SpecialistHttpError('invalid_http');
    if (
      typeof this.#observer !== 'function' ||
      (this.#hooks.beforeEvaluate !== undefined &&
        typeof this.#hooks.beforeEvaluate !== 'function') ||
      (this.#hooks.afterDocumentDecode !== undefined &&
        typeof this.#hooks.afterDocumentDecode !== 'function')
    )
      throw new SpecialistHttpError('invalid_http');
    this.#boundary = new AttemptBoundary(
      this.#trust,
      this.#evidence,
      this.#limits.maxActive,
      this.#limits.maxPerPrincipal,
    );
    this.#server = createServer(
      {
        maxHeaderSize: this.#limits.headerBytes,
        requestTimeout: 0,
        headersTimeout: 0,
        keepAliveTimeout: 1,
      },
      (request, response) => {
        const handled = this.#handle(request, response).catch(() => {
          this.#counts.rejected++;
          response.destroy();
        });
        this.#handlers.add(handled);
        void handled.then(() => this.#handlers.delete(handled));
      },
    );
    this.#server.maxConnections = this.#limits.maxConnections;
    this.#server.maxHeadersCount = 0; // Keep every raw header under the byte cap.
    this.#server.maxRequestsPerSocket = 1;
    this.#server.on('connection', (socket) => {
      if (this.#closing || this.#sockets.size >= this.#limits.maxConnections) {
        socket.destroy();
        return;
      }
      this.#sockets.add(socket);
      this.#headerDeadlines.set(socket, performance.now() + this.#limits.headerMs);
      let observedClose!: () => void;
      this.#socketClosed.set(
        socket,
        new Promise<void>((resolve) => {
          observedClose = resolve;
        }),
      );
      socket.setNoDelay(true);
      this.#headers.set(
        socket,
        setTimeout(() => {
          this.#counts.rejected++;
          this.#emit({ event: 'request_rejected', operation: 'http', code: 'invalid_http' });
          socket.destroy();
        }, this.#limits.headerMs),
      );
      socket.once('close', () => {
        const timer = this.#headers.get(socket);
        if (timer) clearTimeout(timer);
        this.#headers.delete(socket);
        this.#headerDeadlines.delete(socket);
        this.#sockets.delete(socket);
        this.#socketClosed.delete(socket);
        observedClose();
      });
    });
    this.#server.on('dropRequest', (_request, socket) => {
      this.#counts.rejected++;
      this.#emit({ event: 'request_rejected', operation: 'http', code: 'capacity' });
      socket.destroy();
    });
    this.#server.on('clientError', (_error, socket) => this.#rawError(socket as Socket));
    this.#server.on('checkContinue', (_request, response) => {
      void this.#send(response, 417, httpErrorBytes('invalid_http', requestId()));
    });
    this.#server.on('checkExpectation', (_request, response) => {
      void this.#send(response, 417, httpErrorBytes('invalid_http', requestId()));
    });
    this.#server.on('upgrade', (_request, socket) => this.#rawError(socket as Socket));
    this.#server.on('connect', (_request, socket) => this.#rawError(socket as Socket));
    this.#server.on('error', () => {
      this.#counts.rejected++;
    });
  }
  #emit(event: SpecialistEvent): void {
    if (this.#observing >= 8) {
      this.#counts.observerDropped++;
      return;
    }
    try {
      this.#observing++;
      const result = this.#observer(Object.freeze(event));
      void Promise.resolve(result)
        .catch(() => {
          this.#counts.observerFailures++;
        })
        .finally(() => {
          this.#observing--;
        });
    } catch {
      this.#observing--;
      this.#counts.observerFailures++;
    }
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({
      ...this.#counts,
      active: this.#boundary.active,
      requests: this.#requests,
      sockets: this.#sockets.size,
      observerPending: this.#observing,
    });
  }
  listen(port = 0): Promise<Endpoint> {
    if (this.#closing || this.#endpoint || this.#starting)
      return Promise.reject(new SpecialistHttpError('closing'));
    if (typeof port !== 'number' || !Number.isSafeInteger(port) || port < 0 || port > 65535)
      return Promise.reject(new SpecialistHttpError('invalid_http'));
    const pending = new Promise<Endpoint>((resolve, reject) => {
      const failed = (): void => {
        this.#server.off('error', failed);
        this.#server.off('listening', ready);
        reject(new SpecialistHttpError('connection_failed'));
      };
      const ready = (): void => {
        this.#server.off('error', failed);
        this.#server.off('listening', ready);
        if (this.#closing) {
          this.#server.close(() => reject(new SpecialistHttpError('closing')));
          return;
        }
        const address = this.#server.address();
        if (!address || typeof address === 'string') {
          reject(new SpecialistHttpError('connection_failed'));
          return;
        }
        this.#endpoint = Object.freeze({ host: '127.0.0.1', port: address.port });
        resolve(this.#endpoint);
      };
      this.#server.once('error', failed);
      this.#server.once('listening', ready);
      try {
        this.#server.listen(port, '127.0.0.1');
      } catch {
        failed();
      }
    });
    this.#starting = pending;
    void pending.then(
      () => {
        this.#starting = undefined;
      },
      () => {
        this.#starting = undefined;
      },
    );
    return pending;
  }
  #rawError(socket: Socket): void {
    this.#counts.rejected++;
    this.#emit({ event: 'request_rejected', operation: 'http', code: 'invalid_http' });
    if (!socket.writable || socket.destroyed) {
      socket.destroy();
      return;
    }
    const body = Buffer.from(httpErrorBytes('invalid_http', requestId()));
    socket.end(
      `HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: ${body.length}\r\nConnection: close\r\n\r\n${body.toString('utf8')}`,
    );
    const timer = setTimeout(() => socket.destroy(), this.#limits.responseMs);
    socket.once('close', () => clearTimeout(timer));
  }
  async #send(response: ServerResponse, code: number, bytes: Uint8Array): Promise<void> {
    if (response.destroyed || response.socket?.destroyed) return;
    await new Promise<void>((resolve) => {
      let done = false;
      const finish = (): void => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        response.off('finish', finish);
        response.off('close', finish);
        response.off('error', finish);
        response.socket?.destroy();
        resolve();
      };
      const timer = setTimeout(() => {
        response.destroy();
        finish();
      }, this.#limits.responseMs);
      response.once('finish', finish);
      response.once('close', finish);
      response.once('error', finish);
      response.writeHead(code, {
        'content-type': 'application/json',
        'content-length': bytes.byteLength,
        connection: 'close',
        'cache-control': 'no-store',
      });
      response.end(bytes);
    });
  }
  #headersFor(request: IncomingMessage): { authorization: string; length: number } {
    if (request.httpVersion !== '1.1' || request.rawHeaders.length > this.#limits.headerFields * 2)
      throw new SpecialistHttpError('invalid_http');
    const seen = new Set<string>();
    const allowed = new Set([
      'host',
      'authorization',
      'content-type',
      'content-length',
      'connection',
    ]);
    for (let index = 0; index < request.rawHeaders.length; index += 2) {
      const name = request.rawHeaders[index]!.toLowerCase();
      if (seen.has(name) || !allowed.has(name)) throw new SpecialistHttpError('invalid_http');
      seen.add(name);
    }
    const length = request.headers['content-length'];
    if (
      request.headers['content-type'] !== 'application/json' ||
      typeof length !== 'string' ||
      !/^(0|[1-9][0-9]{0,5})(?![\s\S])/.test(length)
    )
      throw new SpecialistHttpError('invalid_http');
    const size = Number(length);
    if (size > MAX_REQUEST_BYTES) throw new SpecialistHttpError('body_limit');
    const authorization = request.headers.authorization;
    if (typeof authorization !== 'string') throw new ContractError('unauthorized');
    this.#trust.authenticate(authorization);
    return { authorization, length: size };
  }
  async #handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    const headerExpired =
      performance.now() >= (this.#headerDeadlines.get(request.socket) ?? Infinity);
    this.#headerDeadlines.delete(request.socket);
    const header = this.#headers.get(request.socket);
    if (header) clearTimeout(header);
    this.#headers.delete(request.socket);
    if (this.#seen.has(request.socket)) {
      request.socket.destroy();
      return;
    }
    this.#seen.add(request.socket);
    if (this.#requests >= this.#limits.maxRequests) {
      await this.#send(response, 429, encodeError('capacity', requestId()));
      return;
    }
    this.#requests++;
    let operation: SpecialistEvent['operation'] = 'http';
    try {
      if (this.#closing) throw new SpecialistHttpError('closing');
      if (headerExpired) throw new SpecialistHttpError('invalid_http');
      if (
        request.method !== 'POST' ||
        !['/v1/invoke', '/v1/status', '/v1/cancel'].includes(request.url ?? '')
      )
        throw new SpecialistHttpError('invalid_http');
      operation = request.url!.slice(4) as 'invoke' | 'status' | 'cancel';
      const { authorization, length } = this.#headersFor(request);
      const input = parseCapabilityRequest(await readBody(request, length, this.#limits.bodyMs));
      if (input.capability === DOCUMENT_CAPABILITY && this.#document === undefined)
        throw new ContractError('unknown_capability');
      if (this.#closing) throw new SpecialistHttpError('closing');
      if (operation === 'invoke') {
        await this.#invoke(input, authorization, response);
        return;
      }
      this.#boundary.inspect(authorization, input, operation === 'status' ? 'result' : 'cancel');
      const active = this.#active.get(key(input));
      if (!active) throw new ContractError('unknown_attempt');
      if (operation === 'cancel') {
        active.cancel = true;
        active.controller.abort(new SpecialistHttpError('request_aborted'));
        this.#counts.cancellations++;
      }
      await this.#send(
        response,
        operation === 'cancel' ? 202 : 200,
        canonical(observation(active)),
      );
      this.#emit({ event: 'observation', operation, code: 'ok' });
    } catch (error) {
      const safe = failure(error);
      this.#counts.rejected++;
      this.#emit({ event: 'request_rejected', operation, code: safe.code });
      await this.#send(
        response,
        status(safe),
        safe instanceof ContractError
          ? encodeError(safe.code, requestId())
          : httpErrorBytes(safe.code, requestId()),
      );
    } finally {
      this.#requests--;
    }
  }
  async #invoke(
    input: CapabilityRequest,
    authorization: string,
    response: ServerResponse,
  ): Promise<void> {
    this.#trust.authorize(authorization, 'result', input);
    if (this.#closing) throw new SpecialistHttpError('closing');
    if (
      input.capability === CAPABILITY &&
      input.input_schema_version === 2 &&
      this.#fixedPolicy === undefined
    )
      throw new ContractError('unknown_capability');
    const permit = this.#boundary.acquire(authorization, input, Date.now());
    const maximumMs = Math.min(
      this.#limits.invokeMs,
      Math.max(1, input.deadline_at_ms - Date.now()),
    );
    const invokeDeadline = performance.now() + maximumMs;
    const active: Active = {
      request: input,
      permit,
      controller: new AbortController(),
      cancel: false,
      expired: false,
      disconnected: false,
      closing: false,
    };
    this.#active.set(key(input), active);
    this.#counts.invoked++;
    this.#emit({ event: 'attempt_started', operation: 'invoke', code: 'ok' });
    const disconnect = (): void => {
      if (!response.writableFinished && !active.controller.signal.aborted) {
        active.disconnected = true;
        this.#counts.disconnects++;
        active.controller.abort(new SpecialistHttpError('request_aborted'));
      }
    };
    response.once('close', disconnect);
    const timer = setTimeout(
      () => {
        active.expired = true;
        this.#counts.expirations++;
        active.controller.abort(new SpecialistHttpError('deadline_exceeded'));
      },
      Math.min(this.#limits.invokeMs, Math.max(1, input.deadline_at_ms - Date.now())),
    );
    let rejectAbort!: (reason: unknown) => void;
    const aborted = new Promise<never>((_resolve, reject) => {
      rejectAbort = reject;
    });
    const abort = (): void =>
      rejectAbort(
        active.controller.signal.reason instanceof SpecialistHttpError
          ? active.controller.signal.reason
          : new SpecialistHttpError('request_aborted'),
      );
    active.controller.signal.addEventListener('abort', abort, { once: true });
    if (active.controller.signal.aborted) abort();
    const evaluation = (async (): Promise<CapabilityResult> => {
      if (active.controller.signal.aborted || this.#closing)
        throw new SpecialistHttpError('closing');
      if (performance.now() >= invokeDeadline) throw new SpecialistHttpError('deadline_exceeded');
      await this.#hooks.beforeEvaluate?.(Object.freeze({ signal: active.controller.signal }));
      if (performance.now() >= invokeDeadline || Date.now() >= input.deadline_at_ms) {
        if (!active.expired) this.#counts.expirations++;
        active.expired = true;
        active.controller.abort(new SpecialistHttpError('deadline_exceeded'));
        throw new SpecialistHttpError('deadline_exceeded');
      }
      if (active.controller.signal.aborted) throw new SpecialistHttpError('request_aborted');
      const records = this.#evidence.resolve(authorization, input, this.#trust);
      if (input.capability === DOCUMENT_CAPABILITY) {
        if (this.#document === undefined || records.length !== 1)
          throw new ContractError('unknown_capability');
        return this.#document.evaluate(
          input,
          records[0]!,
          active.controller.signal,
          invokeDeadline,
          this.#hooks.afterDocumentDecode,
        );
      }
      if (input.input_schema_version === 2) {
        if (this.#fixedPolicy === undefined) throw new ContractError('unknown_capability');
        const result = this.#fixedPolicy.evaluate(input, records, Date.now());
        if (performance.now() >= invokeDeadline || Date.now() >= input.deadline_at_ms)
          throw new SpecialistHttpError('deadline_exceeded');
        return result;
      }
      const policy = records.find(
        (record) => record.reference.source_id === input.context_snapshot.policy_source_id,
      );
      if (!policy) throw new ContractError('evidence_mismatch');
      const facts = fields(decode(policy.body, 4096), ['policy_version', 'minimum_notice_days']);
      if (facts.policy_version !== input.context_snapshot.policy_version)
        throw new ContractError('unsupported_facts');
      const days = integer(facts.minimum_notice_days, 0, 3650);
      const result = parseResult(
        canonical({
          schema_version: 1,
          kind: 'delegation.result',
          capability: CAPABILITY,
          result_schema_version: 1,
          scope: input.scope,
          delegation_id: input.delegation_id,
          case_id: input.case_id,
          request_revision: input.request_revision,
          attempt_id: input.attempt.attempt_id,
          input_fingerprint: input.input_fingerprint,
          eligible: input.context_snapshot.days_before_arrival >= days,
          uncertainty: 'none',
          evidence_refs: [
            {
              source_id: policy.reference.source_id,
              version: policy.reference.version,
              sha256: policy.reference.sha256,
              rule_id: 'notice_minimum_days',
            },
          ],
          producer: {
            producer_id: 'scripted_policy_http_v1',
            model_id: null,
            model_version: null,
            config_fingerprint: hash(Buffer.from('scripted_policy_http_v1')),
          },
          completed_at_ms: Date.now(),
        }),
      );
      if (verifyPolicyFacts(input, result, records, Date.now()) !== 'candidate')
        throw new ContractError('expired');
      if (performance.now() >= invokeDeadline || Date.now() >= input.deadline_at_ms) {
        if (!active.expired) this.#counts.expirations++;
        active.expired = true;
        active.controller.abort(new SpecialistHttpError('deadline_exceeded'));
        throw new SpecialistHttpError('deadline_exceeded');
      }
      return result;
    })();
    const lifetime = evaluation
      .then(
        () => {
          this.#counts.completed++;
          this.#emit({ event: 'attempt_finished', operation: 'invoke', code: 'ok' });
        },
        (error) => {
          this.#emit({ event: 'attempt_finished', operation: 'invoke', code: failure(error).code });
        },
      )
      .finally(() => {
        clearTimeout(timer);
        this.#active.delete(key(input));
        this.#boundary.release(permit);
      });
    this.#work.add(lifetime);
    void lifetime.then(
      () => this.#work.delete(lifetime),
      () => this.#work.delete(lifetime),
    );
    try {
      const result = await Promise.race([evaluation, aborted]);
      await this.#send(response, 200, encodeCapabilityResult(result));
    } finally {
      response.off('close', disconnect);
      active.controller.signal.removeEventListener('abort', abort);
    }
  }
  close(): Promise<void> {
    if (this.#close) return this.#close;
    let resolve!: () => void;
    let reject!: (error: unknown) => void;
    // Publish before abort callbacks or observers can synchronously reenter close.
    const pending = new Promise<void>((yes, no) => {
      resolve = yes;
      reject = no;
    });
    this.#close = pending;
    void this.#finishClose().then(resolve, (error) => {
      this.#close = undefined;
      reject(error);
    });
    return pending;
  }
  async #finishClose(): Promise<void> {
    this.#closing = true;
    const closeDeadline = performance.now() + this.#limits.closeMs;
    const starting = this.#starting;
    for (const active of this.#active.values()) {
      active.closing = true;
      active.controller.abort(new SpecialistHttpError('closing'));
    }
    const socketClosed = [...this.#socketClosed.values()];
    for (const socket of this.#sockets) socket.destroy();
    const stopped = (async (): Promise<void> => {
      if (starting) await starting.catch(() => undefined);
      await new Promise<void>((resolve) => {
        if (!this.#server.listening) resolve();
        else this.#server.close(() => resolve());
      });
    })();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all([
          stopped,
          this.#document?.close(),
          ...this.#work,
          ...this.#handlers,
          ...socketClosed,
        ]),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(
            () => reject(new SpecialistHttpError('cleanup_incomplete')),
            this.#limits.closeMs,
          );
        }),
      ]);
    } finally {
      if (timer) clearTimeout(timer);
    }
    if (
      this.#boundary.active !== 0 ||
      this.#sockets.size !== 0 ||
      this.#requests !== 0 ||
      performance.now() > closeDeadline
    )
      throw new SpecialistHttpError('cleanup_incomplete');
    this.#emit({ event: 'closed', operation: 'http', code: 'ok' });
  }
}
