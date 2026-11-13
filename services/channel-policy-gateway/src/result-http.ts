/** Explicit P3 result-receiver wire; publisher and route are fixed by trusted construction. */
import { timingSafeEqual } from 'node:crypto';
import { snapshotMethod } from './read-ports.js';
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import type { Socket } from 'node:net';
import {
  ResultReceiverError,
  parseResultIntent,
  resultReceipt,
  matchResultReceipt,
  type ChannelResultReceiver,
} from '@livekit-ecosystem/channel-continuity/result-receiver';
type ReceiverPort = Pick<ChannelResultReceiver, 'accept' | 'find'>;
export type ReceiverEndpoint = Readonly<{ host: '127.0.0.1'; port: number }>;
const REQUEST_BYTES = 16384;
const RESPONSE_BYTES = 4096;
const CODES = new Set([
  'InvalidCommand',
  'AccessDenied',
  'NotFound',
  'IdentityConflict',
  'Overloaded',
  'UpgradeRequired',
  'Unavailable',
  'AcknowledgementUnknown',
  'CleanupIncomplete',
  'Closed',
]);
function failure(error: unknown): ResultReceiverError {
  try {
    if (error instanceof ResultReceiverError) {
      const d = Object.getOwnPropertyDescriptor(error, 'code');
      if (d && 'value' in d && typeof d.value === 'string' && CODES.has(d.value))
        return new ResultReceiverError(d.value as ResultReceiverError['code']);
    }
  } catch {
    /* no dependency getters or exception text */
  }
  return new ResultReceiverError('Unavailable');
}
function body(request: IncomingMessage, length: number): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const result = Buffer.alloc(length),
      deadline = performance.now() + 1000;
    let used = 0,
      done = false;
    const finish = (error?: ResultReceiverError): void => {
      if (done) return;
      if (!error && performance.now() >= deadline) error = new ResultReceiverError('Unavailable');
      done = true;
      clearTimeout(timer);
      request.off('data', data);
      request.off('end', end);
      request.off('error', failed);
      request.off('aborted', failed);
      if (error) {
        request.pause();
        reject(error);
      } else resolve(result);
    };
    const data = (chunk: Buffer): void => {
      if (used + chunk.length > length) {
        finish(new ResultReceiverError('InvalidCommand'));
        return;
      }
      chunk.copy(result, used);
      used += chunk.length;
    };
    const end = (): void =>
      finish(used === length ? undefined : new ResultReceiverError('InvalidCommand'));
    const failed = (): void => finish(new ResultReceiverError('Unavailable'));
    const timer = setTimeout(failed, 1000);
    request.on('data', data);
    request.once('end', end);
    request.once('error', failed);
    request.once('aborted', failed);
  });
}
/** Four full handler lifetimes, eight sockets; client abandonment does not cancel receiver calls.
 * close() owns transport/handler drain only. The application subsequently drains
 * the supplied result receiver, then its borrowed outbox owner.
 */
export class ChannelPolicyResultHttp {
  readonly #receiver: ReceiverPort;
  readonly #publisher: string;
  readonly #authorization: Buffer;
  readonly #cleanupMs: number;
  readonly #server: Server;
  readonly #sockets = new Set<Socket>();
  readonly #headerTimers = new Map<Socket, ReturnType<typeof setTimeout>>();
  readonly #headerDeadlines = new Map<Socket, number>();
  readonly #socketClosures = new Map<Socket, Promise<void>>();
  readonly #handlers = new Set<Promise<void>>();
  #starting: Promise<ReceiverEndpoint> | undefined;
  #closing = false;
  #serverClosed: Promise<void> | undefined;
  #completed = 0;
  #rejected = 0;
  constructor(receiver: ReceiverPort, publisherToken: string, cleanupMs = 1000) {
    try {
      if (
        typeof publisherToken !== 'string' ||
        !/^[A-Za-z0-9_-]{43}$/.test(publisherToken) ||
        publisherToken.length !== 43 ||
        !Number.isSafeInteger(cleanupMs) ||
        cleanupMs < 20 ||
        cleanupMs > 2000
      )
        throw new ResultReceiverError('InvalidCommand');
      this.#receiver = Object.freeze({
        accept: snapshotMethod<ReceiverPort['accept']>(receiver, 'accept'),
        find: snapshotMethod<ReceiverPort['find']>(receiver, 'find'),
      });
      this.#publisher = publisherToken;
      this.#authorization = Buffer.from('Bearer ' + publisherToken, 'ascii');
      this.#cleanupMs = cleanupMs;
      this.#server = createServer(
        { maxHeaderSize: 8192, headersTimeout: 1000, requestTimeout: 2000 },
        (request, response) => {
          response.on('error', () => undefined);
          response.setTimeout(2000, () => response.destroy());
          const deadline = this.#headerDeadlines.get(request.socket);
          this.#headerDeadlines.delete(request.socket);
          if (deadline === undefined || performance.now() >= deadline) {
            request.socket.destroy();
            return;
          }
          const timer = this.#headerTimers.get(request.socket);
          if (timer) clearTimeout(timer);
          this.#headerTimers.delete(request.socket);
          if (this.#closing || this.#handlers.size >= 4) {
            this.#error(response, new ResultReceiverError(this.#closing ? 'Closed' : 'Overloaded'));
            return;
          }
          const handler = this.#handle(request, response);
          this.#handlers.add(handler);
          void handler.then(
            () => this.#handlers.delete(handler),
            () => this.#handlers.delete(handler),
          );
        },
      );
      this.#server.maxConnections = 8;
      this.#server.maxHeadersCount = 8;
      this.#server.maxRequestsPerSocket = 1;
      this.#server.keepAliveTimeout = 1;
      this.#server.on('connection', (socket) => {
        if (this.#closing || this.#sockets.size >= 8) {
          socket.destroy();
          return;
        }
        this.#sockets.add(socket);
        this.#headerDeadlines.set(socket, performance.now() + 1000);
        this.#headerTimers.set(
          socket,
          setTimeout(() => socket.destroy(), 1000),
        );
        this.#socketClosures.set(
          socket,
          new Promise<void>((resolve) => {
            socket.once('close', () => {
              const timer = this.#headerTimers.get(socket);
              if (timer) clearTimeout(timer);
              this.#headerTimers.delete(socket);
              this.#headerDeadlines.delete(socket);
              this.#sockets.delete(socket);
              this.#socketClosures.delete(socket);
              resolve();
            });
          }),
        );
      });
      this.#server.on('clientError', (_error, socket) => socket.destroy());
      this.#server.on('checkContinue', (request) => request.socket.destroy());
      this.#server.on('checkExpectation', (request) => request.socket.destroy());
      this.#server.on('upgrade', (_request, socket) => socket.destroy());
      this.#server.on('connect', (_request, socket) => socket.destroy());
      // Late listener errors remain finite; callers observe failed start/transport, not raw messages.
      this.#server.on('error', () => undefined);
    } catch {
      throw new ResultReceiverError('InvalidCommand');
    }
  }
  metrics(): Readonly<{
    handlers: number;
    sockets: number;
    completed: number;
    rejected: number;
    closing: boolean;
  }> {
    return Object.freeze({
      handlers: this.#handlers.size,
      sockets: this.#sockets.size,
      completed: this.#completed,
      rejected: this.#rejected,
      closing: this.#closing,
    });
  }
  start(port = 0): Promise<ReceiverEndpoint> {
    if (!Number.isSafeInteger(port) || port < 0 || port > 65535)
      return Promise.reject(new ResultReceiverError('InvalidCommand'));
    if (this.#closing) return Promise.reject(new ResultReceiverError('Closed'));
    if (this.#starting)
      return this.#starting.then((endpoint) => {
        if (port !== 0 && port !== endpoint.port) throw new ResultReceiverError('InvalidCommand');
        return endpoint;
      });
    this.#starting = new Promise((resolve, reject) => {
      const failed = (): void => {
        this.#server.off('listening', ready);
        this.#server.off('error', failed);
        reject(new ResultReceiverError('Unavailable'));
      };
      const ready = (): void => {
        this.#server.off('error', failed);
        const address = this.#server.address();
        if (!address || typeof address === 'string') {
          reject(new ResultReceiverError('Unavailable'));
          return;
        }
        resolve(Object.freeze({ host: '127.0.0.1', port: address.port }));
      };
      this.#server.once('error', failed);
      this.#server.once('listening', ready);
      try {
        this.#server.listen({ host: '127.0.0.1', port, backlog: 8 });
      } catch {
        failed();
      }
    });
    const starting = this.#starting;
    void starting.catch(() => {
      if (this.#starting === starting) this.#starting = undefined;
    });
    return starting;
  }
  #send(response: ServerResponse, status: number, payload: Buffer): void {
    if (response.destroyed || response.writableEnded || response.headersSent) return;
    response.writeHead(status, {
      'content-type': 'application/json',
      'content-length': String(payload.length),
      'cache-control': 'no-store',
      connection: 'close',
    });
    response.end(payload);
  }
  #error(response: ServerResponse, error: ResultReceiverError): void {
    this.#rejected++;
    const status =
      error.code === 'AccessDenied'
        ? 403
        : error.code === 'IdentityConflict'
          ? 409
          : error.code === 'Overloaded'
            ? 429
            : error.code === 'InvalidCommand'
              ? 400
              : 503;
    this.#send(
      response,
      status,
      Buffer.from(JSON.stringify({ schemaVersion: 1, status: 'error', error: error.code })),
    );
  }
  async #handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    try {
      const route = request.url;
      if (
        request.method !== 'POST' ||
        (route !== '/v1/p2-result-receiver/accept' && route !== '/v1/p2-result-receiver/find')
      )
        throw new ResultReceiverError('InvalidCommand');
      if (request.rawHeaders.length > 16) throw new ResultReceiverError('InvalidCommand');
      const headers: Record<string, string> = Object.create(null) as Record<string, string>;
      for (let n = 0; n < request.rawHeaders.length; n += 2) {
        const key = request.rawHeaders[n]!.toLowerCase(),
          value = request.rawHeaders[n + 1]!;
        if (
          Object.hasOwn(headers, key) ||
          ![
            'host',
            'authorization',
            'content-type',
            'content-length',
            'connection',
            'accept',
            'accept-encoding',
          ].includes(key)
        )
          throw new ResultReceiverError('InvalidCommand');
        headers[key] = value;
      }
      const auth = Buffer.from(headers.authorization ?? '', 'utf8');
      if (auth.length !== this.#authorization.length || !timingSafeEqual(auth, this.#authorization))
        throw new ResultReceiverError('AccessDenied');
      if (
        headers['content-type'] !== 'application/json' ||
        headers['content-length'] === undefined ||
        !/^[1-9][0-9]{0,4}$/.test(headers['content-length'])
      )
        throw new ResultReceiverError('InvalidCommand');
      const length = Number(headers['content-length']);
      if (length > REQUEST_BYTES) throw new ResultReceiverError('InvalidCommand');
      const raw = await body(request, length);
      let canonical: string;
      try {
        canonical = new TextDecoder('utf8', { fatal: true }).decode(raw);
      } catch {
        throw new ResultReceiverError('InvalidCommand');
      }
      const intent = parseResultIntent(canonical);
      const value = route.endsWith('/accept')
        ? await this.#receiver.accept(this.#publisher, intent)
        : await this.#receiver.find(this.#publisher, intent);
      if (value === null && route.endsWith('/accept')) throw new ResultReceiverError('Unavailable');
      let receipt = null;
      try {
        receipt = value === null ? null : resultReceipt(value);
        if (receipt !== null) matchResultReceipt(intent, receipt);
      } catch {
        throw new ResultReceiverError('Unavailable');
      }
      const encoded = Buffer.from(
        JSON.stringify({
          schemaVersion: 1,
          status: receipt === null ? 'missing' : 'accepted',
          receipt,
        }),
      );
      if (encoded.length > RESPONSE_BYTES) throw new ResultReceiverError('Unavailable');
      this.#send(response, 200, encoded);
      this.#completed++;
    } catch (error) {
      this.#error(response, failure(error));
    }
  }
  async close(): Promise<void> {
    this.#closing = true;
    if (!this.#serverClosed) {
      this.#serverClosed = (async () => {
        if (this.#starting) await this.#starting.catch(() => undefined);
        if (this.#server.listening)
          await new Promise<void>((resolve, reject) =>
            this.#server.close((error) =>
              error ? reject(new ResultReceiverError('CleanupIncomplete')) : resolve(),
            ),
          );
      })();
      void this.#serverClosed.catch(() => undefined);
    }
    const socketClosures = [...this.#socketClosures.values()];
    for (const socket of this.#sockets) socket.destroy();
    let timer: ReturnType<typeof setTimeout>;
    try {
      await Promise.race([
        Promise.all([
          this.#serverClosed,
          Promise.allSettled([...this.#handlers]),
          Promise.all(socketClosures),
        ]),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(
            () => reject(new ResultReceiverError('CleanupIncomplete')),
            this.#cleanupMs,
          );
        }),
      ]);
    } finally {
      clearTimeout(timer!);
    }
    if (this.#handlers.size || this.#sockets.size)
      throw new ResultReceiverError('CleanupIncomplete');
  }
}
