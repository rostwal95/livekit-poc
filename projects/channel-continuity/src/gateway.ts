import { registerRehydrationProxy } from './rehydration-access.js';
/** Bounded loopback fake-SMS gateway. PostgreSQL owns acceptance and due work. */
import { createServer, type IncomingMessage, type ServerResponse, type Server } from 'node:http';
import type { Socket } from 'node:net';
import {
  ChannelInbox,
  SeededAccounts,
  type AccountSeed,
  type DatabaseSettings,
} from './postgres.js';
import { ChannelDispatcher, type DispatchPorts } from './dispatch.js';
import {
  dispatchFields,
  type DispatchObservation,
  type PreparedDispatch,
} from './dispatch-types.js';
import {
  hasCommunicationIntegration,
  responseAnchor,
  sdkObservation,
  browserObservation,
} from './communication-types.js';
import { ChannelError } from './public-types.js';
import {
  NativeError,
  isNativeIntegration,
  nativeInput,
  NATIVE_INPUT_BYTES,
} from './native-types.js';
import { FAKE_SMS_MAX_BYTES, WebhookError, type FakeSmsIntegration } from './security.js';
export type GatewayCode =
  | 'invalid_http'
  | 'body_limit'
  | 'body_timeout'
  | 'request_aborted'
  | 'capacity'
  | 'unauthorized'
  | 'not_found'
  | 'identity_conflict'
  | 'storage_unavailable'
  | 'acknowledgement_unknown'
  | 'closing'
  | 'cleanup_incomplete';
export class GatewayError extends Error {
  readonly code: GatewayCode;
  constructor(code: GatewayCode) {
    super(code);
    this.code = code;
  }
}
export type GatewayOptions = Readonly<{
  pollMs?: number;
  /** Longest pause an idle dispatch loop backs off to; defaults to pollMs (no backoff). */
  idlePollMs?: number;
  batchSize?: number;
  cleanupMs?: number;
  startupMs?: number;
  observer?: (
    event: Readonly<{ event: 'http' | 'poll' | 'close'; code: string }>,
  ) => void | Promise<void>;
  /** Trusted test-only pause after a successful flushed ACK, not chosen by input. */
  harnessAfterAcknowledgement?: () => void | Promise<void>;
}>;
export type ChannelGatewayOptions = Readonly<{
  inputMode?: 'native_livekit';
  database: DatabaseSettings;
  integration: FakeSmsIntegration;
  accounts: readonly AccountSeed[];
  ports: DispatchPorts;
  options?: GatewayOptions;
}>;
export type GatewayEndpoint = Readonly<{ host: '127.0.0.1'; port: number }>;
const LIMITS = Object.freeze({
  sockets: 16,
  requests: 4,
  headers: 16,
  headerBytes: 8192,
  headerMs: 1000,
  bodyMs: 2000,
  responseMs: 1000,
});
const ERRORS = new Set<GatewayCode>([
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
]);
function failure(error: unknown): GatewayError {
  if (error instanceof WebhookError) return new GatewayError('unauthorized');
  if (error instanceof GatewayError && ERRORS.has(error.code)) return new GatewayError(error.code);
  if (error instanceof ChannelError) {
    const descriptor = Object.getOwnPropertyDescriptor(error, 'code');
    const code = descriptor && 'value' in descriptor ? descriptor.value : undefined;
    const mapped: Record<string, GatewayCode> = {
      AccessDenied: 'unauthorized',
      AssociationRequired: 'unauthorized',
      AssociationRejected: 'unauthorized',
      NotFound: 'not_found',
      IdentityConflict: 'identity_conflict',
      Overloaded: 'capacity',
      AcknowledgementUnknown: 'acknowledgement_unknown',
      CleanupIncomplete: 'cleanup_incomplete',
    };
    if (typeof code === 'string' && Object.hasOwn(mapped, code))
      return new GatewayError(mapped[code]!);
  }
  return new GatewayError('storage_unavailable');
}
function httpStatus(code: GatewayCode): number {
  return {
    invalid_http: 400,
    body_limit: 413,
    body_timeout: 408,
    request_aborted: 408,
    capacity: 429,
    unauthorized: 401,
    not_found: 404,
    identity_conflict: 409,
    storage_unavailable: 503,
    acknowledgement_unknown: 503,
    closing: 503,
    cleanup_incomplete: 503,
  }[code];
}
function positive(value: unknown, fallback: number, maximum: number, minimum = 1): number {
  if (value === undefined) return fallback;
  if (
    typeof value !== 'number' ||
    !Number.isSafeInteger(value) ||
    value < minimum ||
    value > maximum
  )
    throw new GatewayError('invalid_http');
  return value;
}
function headers(request: IncomingMessage): Record<string, string> {
  if (request.rawHeaders.length > LIMITS.headers * 2) throw new GatewayError('invalid_http');
  const result: Record<string, string> = Object.create(null) as Record<string, string>;
  for (let i = 0; i < request.rawHeaders.length; i += 2) {
    const name = request.rawHeaders[i]!.toLowerCase(),
      value = request.rawHeaders[i + 1]!;
    if (Object.hasOwn(result, name) || name === 'transfer-encoding' || name === 'expect')
      throw new GatewayError('invalid_http');
    result[name] = value;
  }
  return result;
}
function body(request: IncomingMessage, length: number): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const bytes = Buffer.alloc(length),
      deadline = performance.now() + LIMITS.bodyMs;
    let used = 0,
      done = false;
    const finish = (error?: GatewayError): void => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      request.off('data', data);
      request.off('end', end);
      request.off('aborted', aborted);
      request.off('error', aborted);
      if (!error && performance.now() >= deadline) error = new GatewayError('body_timeout');
      if (error) {
        request.pause();
        reject(error);
      } else resolve(bytes);
    };
    const data = (chunk: Buffer): void => {
      if (used + chunk.length > length) {
        finish(new GatewayError('body_limit'));
        return;
      }
      chunk.copy(bytes, used);
      used += chunk.length;
    };
    const end = (): void =>
      finish(used === length ? undefined : new GatewayError('request_aborted'));
    const aborted = (): void => finish(new GatewayError('request_aborted'));
    const timer = setTimeout(() => finish(new GatewayError('body_timeout')), LIMITS.bodyMs);
    request.on('data', data);
    request.once('end', end);
    request.once('aborted', aborted);
    request.once('error', aborted);
  });
}
export class ChannelGateway {
  readonly #native: boolean;
  readonly #communication: boolean;
  readonly #inbox: ChannelInbox;
  readonly #dispatcher: ChannelDispatcher;
  readonly #tokens: readonly string[];
  readonly #pollMs: number;
  readonly #idlePollMs: number;
  readonly #batchSize: number;
  readonly #cleanupMs: number;
  readonly #startupMs: number;
  readonly #observer: NonNullable<GatewayOptions['observer']>;
  readonly #hook: GatewayOptions['harnessAfterAcknowledgement'];
  readonly #server: Server;
  readonly #sockets = new Set<Socket>();
  readonly #socketClosed = new Map<Socket, Promise<void>>();
  readonly #headers = new Map<Socket, ReturnType<typeof setTimeout>>();
  readonly #deadlines = new Map<Socket, number>();
  readonly #seen = new WeakSet<Socket>();
  readonly #handlers = new Set<Promise<void>>();
  #notifications = 0;
  #active = 0;
  #intakes = 0;
  #nudged = false;
  #cursor = 0;
  #closing = false;
  #binding: Promise<GatewayEndpoint> | undefined;
  #endpoint: GatewayEndpoint | undefined;
  #loop: Promise<void> | undefined;
  #driverFault = false;
  #wake: (() => void) | undefined;
  #cleanup: Promise<void> | undefined;
  #counts: Record<string, number> = {
    accepted: 0,
    replayed: 0,
    dispatched: 0,
    pollErrors: 0,
    telemetryFailures: 0,
  };
  constructor(configuration: ChannelGatewayOptions) {
    const input = dispatchFields(configuration, [
      'database',
      'integration',
      'accounts',
      'ports',
      ...(Object.hasOwn(configuration, 'inputMode') ? ['inputMode'] : []),
      ...(Object.hasOwn(configuration, 'options') ? ['options'] : []),
    ]);
    this.#native = input.inputMode === 'native_livekit';
    this.#communication = hasCommunicationIntegration(configuration.integration);
    if (
      (input.inputMode !== undefined && !this.#native) ||
      (this.#native && !isNativeIntegration(configuration.integration))
    )
      throw new GatewayError('unauthorized');
    const options = (input.options ?? {}) as GatewayOptions;
    const fields = dispatchFields(options, Object.keys(options));
    if (
      Object.keys(fields).some(
        (k) =>
          ![
            'pollMs',
            'idlePollMs',
            'batchSize',
            'cleanupMs',
            'startupMs',
            'observer',
            'harnessAfterAcknowledgement',
          ].includes(k),
      )
    )
      throw new GatewayError('invalid_http');
    this.#pollMs = positive(fields.pollMs, 100, 1000, 20);
    this.#idlePollMs = positive(fields.idlePollMs, this.#pollMs, 5000, this.#pollMs);
    this.#batchSize = positive(fields.batchSize, 4, 16);
    this.#cleanupMs = positive(fields.cleanupMs, 2000, 5000, 20);
    this.#startupMs = positive(fields.startupMs, 5000, 10000, 20);
    if (
      (fields.observer !== undefined && typeof fields.observer !== 'function') ||
      (fields.harnessAfterAcknowledgement !== undefined &&
        typeof fields.harnessAfterAcknowledgement !== 'function')
    )
      throw new GatewayError('invalid_http');
    this.#observer =
      options.observer ??
      ((event) => {
        console.info(JSON.stringify({ component: 'channel_gateway', ...event }));
      });
    this.#hook = options.harnessAfterAcknowledgement;
    const accounts = new SeededAccounts(configuration.accounts);
    if (
      configuration.accounts.some(
        (seed) => seed.tenantId !== configuration.integration.providerScope.tenantId,
      )
    )
      throw new GatewayError('unauthorized');
    this.#tokens = Object.freeze(configuration.accounts.map((seed) => seed.token));
    this.#inbox = new ChannelInbox(
      configuration.database,
      configuration.integration,
      accounts,
      {},
      () => undefined,
    );
    registerRehydrationProxy(this, this.#inbox);
    this.#dispatcher = new ChannelDispatcher(
      configuration.database,
      configuration.integration,
      accounts,
      configuration.ports,
      this.#native ? { timeoutMs: 5000, cleanupTimeoutMs: 2000 } : undefined,
    );
    this.#server = createServer(
      { maxHeaderSize: this.#native ? 4096 : LIMITS.headerBytes, joinDuplicateHeaders: false },
      (request, response) => this.#request(request, response),
    );
    this.#server.headersTimeout = LIMITS.headerMs;
    this.#server.requestTimeout = LIMITS.bodyMs;
    this.#server.maxHeadersCount = 0;
    this.#server.maxConnections = LIMITS.sockets;
    this.#server.timeout = 0;
    this.#server.keepAliveTimeout = 1;
    this.#server.maxRequestsPerSocket = 1;
    this.#server.on('connection', (socket) => {
      socket.on('error', () => undefined);
      if (this.#closing || this.#sockets.size >= LIMITS.sockets) {
        socket.destroy();
        return;
      }
      this.#sockets.add(socket);
      let closed!: () => void;
      this.#socketClosed.set(
        socket,
        new Promise<void>((resolve) => {
          closed = resolve;
        }),
      );
      this.#deadlines.set(socket, performance.now() + LIMITS.headerMs);
      this.#headers.set(
        socket,
        setTimeout(() => socket.destroy(), LIMITS.headerMs),
      );
      socket.once('close', () => {
        clearTimeout(this.#headers.get(socket));
        this.#headers.delete(socket);
        this.#deadlines.delete(socket);
        this.#sockets.delete(socket);
        this.#socketClosed.delete(socket);
        closed();
      });
    });
    this.#server.on('clientError', (_error, socket) => socket.destroy());
    this.#server.on('checkContinue', (request) => request.socket.destroy());
    this.#server.on('checkExpectation', (request) => request.socket.destroy());
    this.#server.on('upgrade', (_request, socket) => socket.destroy());
    this.#server.on('connect', (_request, socket) => socket.destroy());
    this.#server.on('dropRequest', (_request, socket) => socket.destroy());
    this.#server.on('error', () => this.#emit('http', 'storage_unavailable'));
  }
  #increment(name: string): void {
    this.#counts[name] = Math.min(Number.MAX_SAFE_INTEGER, (this.#counts[name] ?? 0) + 1);
  }
  #emit(event: 'http' | 'poll' | 'close', code: string): void {
    if (this.#notifications >= 8) {
      this.#increment('observerDropped');
      return;
    }
    try {
      const observed = this.#observer(Object.freeze({ event, code }));
      if (observed && typeof observed.then === 'function') {
        this.#notifications++;
        void Promise.resolve(observed)
          .catch(() => this.#increment('telemetryFailures'))
          .finally(() => {
            this.#notifications--;
          });
      }
    } catch {
      this.#increment('telemetryFailures');
    }
  }
  communicationMetrics() {
    return this.#inbox.communicationMetrics();
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({
      ...this.#counts,
      active: this.#active,
      intakes: this.#intakes,
      sockets: this.#sockets.size,
      handlers: this.#handlers.size,
      driver: this.#loop ? 1 : 0,
      observerPending: this.#notifications,
    });
  }
  /** Read the owned integration-scoped dispatch observation without creating work. */
  inspectDispatch(accountToken: string, receiptId: string): Promise<DispatchObservation> {
    if (this.#closing) return Promise.reject(new ChannelError('StorageUnavailable'));
    return this.#dispatcher.inspect(accountToken, receiptId);
  }
  /** Reuse the owned integration-scoped dispatcher; no intake or driver admission. */
  readPrepared(accountToken: string, receiptId: string): Promise<PreparedDispatch | null> {
    if (this.#closing) return Promise.reject(new ChannelError('StorageUnavailable'));
    return this.#dispatcher.readPrepared(accountToken, receiptId);
  }
  async listen(port = 0): Promise<GatewayEndpoint> {
    if (this.#closing || this.#binding || this.#endpoint) throw new GatewayError('closing');
    positive(port, 0, 65535, 0);
    const deadline = performance.now() + this.#startupMs;
    const binding = this.#bind(port, deadline);
    this.#binding = binding;
    void binding.then(
      () => {
        this.#binding = undefined;
      },
      () => {
        this.#binding = undefined;
      },
    );
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        binding,
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(
            () => {
              void this.close().catch(() => undefined);
              reject(new GatewayError('storage_unavailable'));
            },
            Math.max(0, deadline - performance.now()),
          );
        }),
      ]);
    } catch (error) {
      // A rejected/late bind may already own a socket or pending SQL; close observes it.
      void this.close().catch(() => undefined);
      throw error;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  #starting(deadline: number): void {
    if (this.#closing) throw new GatewayError('closing');
    if (performance.now() >= deadline) throw new GatewayError('storage_unavailable');
  }
  async #bind(port: number, deadline: number): Promise<GatewayEndpoint> {
    // Preflight existing v2 schema; caller timeout retains actual owned I/O until settlement.
    for (const token of this.#tokens) {
      this.#starting(deadline);
      await this.#dispatcher.eligible(token, 1);
      this.#starting(deadline);
      if (this.#communication) {
        await this.#inbox.communicationResponses(token, { limit: 1 });
        this.#starting(deadline);
      }
    }
    await new Promise<void>((resolve, reject) => {
      const failed = (): void => {
        this.#server.off('listening', ready);
        reject(new GatewayError('storage_unavailable'));
      };
      const ready = (): void => {
        this.#server.off('error', failed);
        resolve();
      };
      this.#server.once('error', failed);
      this.#server.once('listening', ready);
      this.#server.listen(port, '127.0.0.1');
    });
    this.#starting(deadline);
    const address = this.#server.address();
    if (!address || typeof address === 'string') throw new GatewayError('storage_unavailable');
    this.#endpoint = Object.freeze({ host: '127.0.0.1', port: address.port });
    this.#loop = this.#drive()
      .catch(() => {
        this.#driverFault = true;
        this.#increment('pollErrors');
        this.#emit('poll', 'storage_unavailable');
      })
      .finally(() => {
        this.#loop = undefined;
      });
    return this.#endpoint;
  }
  #request(request: IncomingMessage, response: ServerResponse): void {
    response.on('error', () => undefined);
    const socket = request.socket,
      deadline = this.#deadlines.get(socket);
    clearTimeout(this.#headers.get(socket));
    this.#headers.delete(socket);
    this.#deadlines.delete(socket);
    if (this.#seen.has(socket) || deadline === undefined || performance.now() >= deadline) {
      socket.destroy();
      return;
    }
    this.#seen.add(socket);
    const accepted = !this.#closing && this.#active < LIMITS.requests;
    if (accepted) this.#active++;
    const work = this.#handle(request, response, accepted)
      .catch(() => {
        socket.destroy();
      })
      .finally(() => {
        if (accepted) this.#active--;
        this.#handlers.delete(work);
      });
    this.#handlers.add(work);
  }
  async #reply(
    response: ServerResponse,
    status: number,
    value: unknown,
    maximum = 16384,
  ): Promise<boolean> {
    if (response.destroyed) return false;
    const raw = Buffer.from(JSON.stringify(value));
    if (raw.length > maximum) throw new GatewayError('storage_unavailable');
    return await new Promise((resolve) => {
      const deadline = performance.now() + LIMITS.responseMs;
      let done = false;
      const finish = (success: boolean): void => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        response.off('finish', finished);
        response.off('close', closed);
        response.off('error', closed);
        if (!success || performance.now() >= deadline) {
          response.destroy();
          resolve(false);
        } else resolve(true);
      };
      const finished = (): void => finish(true),
        closed = (): void => finish(false);
      const timer = setTimeout(() => finish(false), LIMITS.responseMs);
      response.once('finish', finished);
      response.once('close', closed);
      response.once('error', closed);
      response.writeHead(status, {
        'Content-Type': 'application/json',
        'Content-Length': raw.length,
        Connection: 'close',
        'Cache-Control': 'no-store',
      });
      response.end(raw);
    });
  }
  async #handle(
    request: IncomingMessage,
    response: ServerResponse,
    admitted: boolean,
  ): Promise<void> {
    let intake = false;
    try {
      if (!admitted) throw new GatewayError(this.#closing ? 'closing' : 'capacity');
      const fields = headers(request);
      if (request.method === 'GET' && request.url === '/health') {
        if (fields['content-length'] !== undefined && fields['content-length'] !== '0')
          throw new GatewayError('invalid_http');
        await this.#reply(response, this.#driverFault || !this.#loop ? 503 : 200, {
          status: this.#driverFault || !this.#loop ? 'degraded' : 'listening',
          processing: this.#loop ? 'persisted_poll' : 'stopped',
          business_execution: false,
        });
        return;
      }
      if (request.method === 'GET' && /^\/receipts\/[0-9a-f-]{36}$/.test(request.url ?? '')) {
        if (fields['content-length'] !== undefined && fields['content-length'] !== '0')
          throw new GatewayError('invalid_http');
        const auth = fields.authorization;
        if (!auth || !/^Bearer [A-Za-z0-9_-]{32,128}$/.test(auth))
          throw new GatewayError('unauthorized');
        const observed = await this.#dispatcher.inspect(
          auth.slice(7),
          request.url!.slice('/receipts/'.length),
        );
        await this.#reply(response, 200, {
          schemaVersion: 1,
          kind: 'channel.processing_observation',
          ...observed,
        });
        return;
      }
      if (
        this.#communication &&
        request.method === 'POST' &&
        [
          '/v1/native/responses',
          '/v1/native/sdk-observations',
          '/v1/native/browser-observations',
          '/v1/native/response-inspect',
        ].includes(request.url ?? '')
      ) {
        if (
          fields['content-type'] !== 'application/json' ||
          !fields['content-length'] ||
          !/^[1-9][0-9]{0,5}(?![\s\S])/.test(fields['content-length']) ||
          Number(fields['content-length']) > 32768
        )
          throw new NativeError('invalid_input');
        if (
          !fields.authorization ||
          !/^Bearer [A-Za-z0-9_-]{32,128}(?![\s\S])/.test(fields.authorization)
        )
          throw new NativeError('forbidden');
        this.#intakes++;
        intake = true;
        const raw = await body(request, Number(fields['content-length']));
        let value: unknown;
        try {
          const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
          value = JSON.parse(text);
          if (JSON.stringify(value) !== text) throw Error();
        } catch {
          throw new NativeError('invalid_input');
        }
        const token = fields.authorization.slice(7);
        let result: unknown;
        if (request.url === '/v1/native/responses')
          result = await this.#inbox.communicationBegin(token, responseAnchor(value));
        else if (request.url === '/v1/native/sdk-observations')
          result = await this.#inbox.communicationSdk(token, sdkObservation(value));
        else if (request.url === '/v1/native/browser-observations')
          result = await this.#inbox.communicationBrowser(token, browserObservation(value));
        else {
          const v = dispatchFields(value, ['schemaVersion', 'responseId']);
          if (v.schemaVersion !== 1 || typeof v.responseId !== 'string')
            throw new NativeError('invalid_input');
          result = await this.#inbox.communicationInspect(token, v.responseId);
        }
        await this.#reply(
          response,
          200,
          { schemaVersion: 1, status: 'known', result },
          request.url === '/v1/native/response-inspect' ? 65536 : 2048,
        );
        this.#emit('http', 'communication_known');
        return;
      }
      if (this.#native) {
        if (request.method !== 'POST' || request.url !== '/v1/native/accept')
          throw new GatewayError('not_found');
        if (
          fields['content-type'] !== 'application/json' ||
          !fields['content-length'] ||
          !/^[1-9][0-9]{0,5}(?![\s\S])/.test(fields['content-length']) ||
          Number(fields['content-length']) > NATIVE_INPUT_BYTES
        )
          throw new NativeError('invalid_input');
        if (
          !fields.authorization ||
          !/^Bearer [A-Za-z0-9_-]{32,128}(?![\s\S])/.test(fields.authorization)
        )
          throw new NativeError('forbidden');
        this.#intakes++;
        intake = true;
        const raw = await body(request, Number(fields['content-length']));
        let value: unknown;
        try {
          const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
          value = JSON.parse(text);
          if (JSON.stringify(value) !== text) throw Error();
        } catch {
          throw new NativeError('invalid_input');
        }
        const accepted = await this.#inbox.acceptNative(
          fields.authorization.slice(7),
          nativeInput(value),
        );
        this.#increment(accepted.status === 'replayed' ? 'replayed' : 'accepted');
        if (accepted.status !== 'replayed') this.#nudge();
        const flushed = await this.#reply(response, 200, accepted);
        this.#emit('http', accepted.status);
        if (flushed) await this.#hook?.();
        return;
      }
      if (request.method !== 'POST' || request.url !== '/webhooks/fake-sms')
        throw new GatewayError('not_found');
      if (
        fields['content-type'] !== 'application/json' ||
        !fields['content-length'] ||
        !/^[1-9][0-9]{0,5}$/.test(fields['content-length'])
      )
        throw new GatewayError('invalid_http');
      const length = Number(fields['content-length']);
      if (length > FAKE_SMS_MAX_BYTES) throw new GatewayError('body_limit');
      if (!fields['x-p2-timestamp'] || !fields['x-p2-signature'])
        throw new GatewayError('unauthorized');
      this.#intakes++;
      intake = true;
      const raw = await body(request, length);
      if (this.#closing) throw new GatewayError('closing');
      const result = await this.#inbox.acceptSms(raw, {
        timestamp: fields['x-p2-timestamp'],
        signature: fields['x-p2-signature'],
      });
      this.#increment(result.replayed ? 'replayed' : 'accepted');
      if (!result.replayed) this.#nudge();
      const flushed = await this.#reply(response, 200, {
        schemaVersion: 1,
        kind: 'channel.receipt',
        ...result,
      });
      this.#emit('http', result.replayed ? 'replayed' : 'accepted');
      if (flushed) await this.#hook?.();
    } catch (error) {
      if (this.#native) {
        let code: import('./native-types.js').NativeCode = 'acknowledgement_unknown';
        if (error instanceof NativeError) code = error.code;
        else if (error instanceof ChannelError) {
          if (error.code === 'AccessDenied' || error.code === 'AssociationRequired')
            code = 'forbidden';
          else if (error.code === 'IdentityConflict') code = 'idempotency_conflict';
          else if (error.code === 'Overloaded') code = 'capacity_exhausted';
          else if (this.#communication && error.code === 'InvalidEvent') code = 'invalid_input';
          else if (this.#communication && error.code === 'NotFound') code = 'forbidden';
          else if (
            this.#communication &&
            ['UpgradeRequired', 'SchemaMismatch'].includes(error.code)
          )
            code = 'dependency_unavailable';
        } else if (error instanceof GatewayError) {
          if (error.code === 'closing') code = 'closed';
          else if (error.code === 'capacity') code = 'capacity_exhausted';
          else if (
            ['invalid_http', 'body_limit', 'body_timeout', 'not_found', 'unauthorized'].includes(
              error.code,
            )
          )
            code = error.code === 'unauthorized' ? 'forbidden' : 'invalid_input';
        }
        this.#increment('httpRejected');
        this.#emit('http', code);
        await this.#reply(
          response,
          code === 'acknowledgement_unknown'
            ? 503
            : code === 'forbidden'
              ? 403
              : code === 'idempotency_conflict'
                ? 409
                : code === 'capacity_exhausted'
                  ? 429
                  : 400,
          {
            schemaVersion: 1,
            status: code === 'acknowledgement_unknown' ? 'unknown' : 'rejected',
            code,
          },
        );
        return;
      }
      const checked = failure(error);
      this.#increment('httpRejected');
      this.#emit('http', checked.code);
      await this.#reply(response, httpStatus(checked.code), {
        schemaVersion: 1,
        kind: 'channel.gateway_error',
        code: checked.code,
        retryable: false,
      });
    } finally {
      if (intake) this.#intakes--;
    }
  }
  /** New local intake resets idle backoff and ends a pause early. */
  #nudge(): void {
    this.#nudged = true;
    this.#wake?.();
  }
  async #pause(delayMs: number): Promise<void> {
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        this.#wake = undefined;
        resolve();
      }, delayMs);
      this.#wake = () => {
        clearTimeout(timer);
        this.#wake = undefined;
        resolve();
      };
    });
  }
  async #drive(): Promise<void> {
    let delayMs = this.#pollMs;
    while (!this.#closing) {
      const start = this.#cursor,
        deadline = performance.now() + 2000;
      this.#cursor = (this.#cursor + 1) % this.#tokens.length;
      let remaining = this.#batchSize;
      let found = false;
      for (
        let offset = 0;
        offset < this.#tokens.length &&
        performance.now() < deadline &&
        remaining > 0 &&
        !this.#closing &&
        (this.#hook === undefined || this.#intakes === 0);
        offset++
      ) {
        const token = this.#tokens[(start + offset) % this.#tokens.length]!;
        try {
          const eligible = await this.#dispatcher.eligible(token, remaining);
          if (eligible.length > 0) found = true;
          for (const id of eligible) {
            if (
              this.#closing ||
              (this.#hook !== undefined && this.#intakes > 0) ||
              performance.now() >= deadline
            )
              break;
            remaining--;
            const result = await this.#dispatcher.step(token, id);
            if (result.status === 'dispatched') this.#increment('dispatched');
            this.#emit('poll', result.status);
          }
        } catch (error) {
          this.#increment('pollErrors');
          this.#emit('poll', failure(error).code);
        }
      }
      // Work that appears without local intake waits at most idlePollMs.
      delayMs = found || this.#nudged ? this.#pollMs : Math.min(delayMs * 2, this.#idlePollMs);
      this.#nudged = false;
      if (!this.#closing) await this.#pause(delayMs);
    }
  }
  async close(): Promise<void> {
    const deadline = performance.now() + this.#cleanupMs;
    this.#closing = true;
    this.#wake?.();
    if (!this.#cleanup) {
      this.#cleanup = this.#closeOwned();
      void this.#cleanup.catch(() => undefined);
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        this.#cleanup,
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(
            () => reject(new GatewayError('cleanup_incomplete')),
            Math.max(0, deadline - performance.now()),
          );
        }),
      ]);
      if (performance.now() >= deadline) throw new GatewayError('cleanup_incomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  async #closeOwned(): Promise<void> {
    if (this.#binding) await this.#binding.catch(() => undefined);
    const stopped = new Promise<void>((resolve) => {
      if (!this.#server.listening) {
        resolve();
        return;
      }
      this.#server.close(() => resolve());
    });
    const socketClosed = [...this.#socketClosed.values()];
    for (const socket of this.#sockets) socket.destroy();
    await stopped;
    await Promise.all([...socketClosed, ...this.#handlers, this.#loop]);
    const results = await Promise.allSettled([this.#dispatcher.close(), this.#inbox.close()]);
    if (results.some((result) => result.status === 'rejected'))
      throw new GatewayError('cleanup_incomplete');
    this.#endpoint = undefined;
    this.#emit('close', 'closed');
  }
}
