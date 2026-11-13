/** Explicit loopback worker transport; borrowed reads own their own actual I/O. */
import { timingSafeEqual } from 'node:crypto';
import { snapshotMethod } from './read-ports.js';
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import type { Socket } from 'node:net';
import {
  ChannelPolicySourceReader,
  SourceReadError,
  sourceReadFailure,
  DISCOVERY_BYTES,
  PREPARED_BYTES,
} from './source-reader.js';

type ReadPort = Pick<ChannelPolicySourceReader, 'discover' | 'prepared'>;
export type ReadEndpoint = Readonly<{ host: '127.0.0.1'; port: number }>;
const REQUEST_BYTES = 1024;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
function body(request: IncomingMessage, length: number): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const result = Buffer.alloc(length);
    let used = 0,
      done = false;
    const finish = (error?: SourceReadError): void => {
      if (done) return;
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
        finish(new SourceReadError('invalid_input'));
        return;
      }
      chunk.copy(result, used);
      used += chunk.length;
    };
    const end = (): void =>
      finish(used === length ? undefined : new SourceReadError('invalid_input'));
    const failed = (): void => finish(new SourceReadError('unavailable'));
    const timer = setTimeout(failed, 1000);
    request.on('data', data);
    request.once('end', end);
    request.once('error', failed);
    request.once('aborted', failed);
  });
}
function preparedRequest(
  raw: Buffer,
): Readonly<{ receiptId: string; sourceBindingId: 'native' | 'sms' }> {
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder('utf8', { fatal: true }).decode(raw));
  } catch {
    throw new SourceReadError('invalid_input');
  }
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new SourceReadError('invalid_input');
  const v = value as Record<string, unknown>;
  if (
    Object.keys(v).length !== 3 ||
    v.schemaVersion !== 1 ||
    typeof v.receiptId !== 'string' ||
    UUID.exec(v.receiptId)?.[0] !== v.receiptId ||
    (v.sourceBindingId !== 'native' && v.sourceBindingId !== 'sms')
  )
    throw new SourceReadError('invalid_input');
  const canonical = Buffer.from(
    JSON.stringify({
      schemaVersion: 1,
      receiptId: v.receiptId,
      sourceBindingId: v.sourceBindingId,
    }),
  );
  // Canonical closed requests also reject duplicate keys, alternate numeric forms and ignored bytes.
  if (!canonical.equals(raw)) throw new SourceReadError('invalid_input');
  return Object.freeze({ receiptId: v.receiptId, sourceBindingId: v.sourceBindingId });
}
/** Four full handler lifetimes, eight sockets; client abandonment does not cancel reads.
 * close() owns transport/handler drain only. The application subsequently drains
 * the supplied source reader, then its borrowed P2 owners.
 */
export class ChannelPolicyReadHttp {
  readonly #reads: ReadPort;
  readonly #authorization: Buffer;
  readonly #cleanupMs: number;
  readonly #server: Server;
  readonly #sockets = new Set<Socket>();
  readonly #headerTimers = new Map<Socket, ReturnType<typeof setTimeout>>();
  readonly #socketClosures = new Map<Socket, Promise<void>>();
  readonly #handlers = new Set<Promise<void>>();
  #starting: Promise<ReadEndpoint> | undefined;
  #closing = false;
  #serverClosed: Promise<void> | undefined;
  #completed = 0;
  #rejected = 0;
  constructor(reads: ReadPort, workerBearer: string, cleanupMs = 1000) {
    try {
      if (
        typeof workerBearer !== 'string' ||
        !/^[A-Za-z0-9_-]{43}$/.test(workerBearer) ||
        workerBearer.length !== 43 ||
        !Number.isSafeInteger(cleanupMs) ||
        cleanupMs < 20 ||
        cleanupMs > 2000
      )
        throw new SourceReadError('invalid_input');
      this.#reads = Object.freeze({
        discover: snapshotMethod<ReadPort['discover']>(reads, 'discover'),
        prepared: snapshotMethod<ReadPort['prepared']>(reads, 'prepared'),
      });
      this.#authorization = Buffer.from('Bearer ' + workerBearer, 'ascii');
      this.#cleanupMs = cleanupMs;
      this.#server = createServer(
        { maxHeaderSize: 8192, headersTimeout: 1000, requestTimeout: 2000 },
        (request, response) => {
          const timer = this.#headerTimers.get(request.socket);
          if (timer) clearTimeout(timer);
          this.#headerTimers.delete(request.socket);
          if (this.#closing || this.#handlers.size >= 4) {
            this.#error(response, new SourceReadError(this.#closing ? 'closed' : 'capacity'));
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
              this.#sockets.delete(socket);
              this.#socketClosures.delete(socket);
              resolve();
            });
          }),
        );
      });
      this.#server.on('clientError', (_error, socket) => socket.destroy());
      // Late listener errors remain finite; callers observe failed start/transport, not raw messages.
      this.#server.on('error', () => undefined);
    } catch {
      throw new SourceReadError('invalid_input');
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
  start(port = 0): Promise<ReadEndpoint> {
    if (!Number.isSafeInteger(port) || port < 0 || port > 65535)
      return Promise.reject(new SourceReadError('invalid_input'));
    if (this.#closing) return Promise.reject(new SourceReadError('closed'));
    if (this.#starting)
      return this.#starting.then((endpoint) => {
        if (port !== 0 && port !== endpoint.port) throw new SourceReadError('invalid_input');
        return endpoint;
      });
    this.#starting = new Promise((resolve, reject) => {
      const failed = (): void => {
        this.#server.off('listening', ready);
        this.#server.off('error', failed);
        reject(new SourceReadError('unavailable'));
      };
      const ready = (): void => {
        this.#server.off('error', failed);
        const address = this.#server.address();
        if (!address || typeof address === 'string') {
          reject(new SourceReadError('unavailable'));
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
  #error(response: ServerResponse, error: SourceReadError): void {
    this.#rejected++;
    const status = {
      invalid_input: 400,
      unauthorized: 403,
      not_found: 404,
      invalid_state: 503,
      capacity: 429,
      unavailable: 503,
      closed: 503,
      cleanup_incomplete: 503,
    }[error.code];
    this.#send(
      response,
      status,
      Buffer.from(JSON.stringify({ schemaVersion: 1, status: 'unavailable', code: error.code })),
    );
  }
  async #handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    // The response may close while #handle remains owned awaiting the actual port.
    response.on('error', () => undefined);
    response.setTimeout(2000, () => response.destroy());
    try {
      const route = request.url;
      if (
        request.method !== 'POST' ||
        (route !== '/v1/policy/discovery' && route !== '/v1/policy/prepared')
      )
        throw new SourceReadError('not_found');
      if (request.rawHeaders.length > 16) throw new SourceReadError('invalid_input');
      const headers: Record<string, string> = Object.create(null) as Record<string, string>;
      for (let n = 0; n < request.rawHeaders.length; n += 2) {
        const name = request.rawHeaders[n]!.toLowerCase(),
          value = request.rawHeaders[n + 1]!;
        if (
          Object.hasOwn(headers, name) ||
          ![
            'host',
            'authorization',
            'content-type',
            'content-length',
            'connection',
            'accept-encoding',
          ].includes(name)
        )
          throw new SourceReadError('invalid_input');
        headers[name] = value;
      }
      const auth = Buffer.from(headers.authorization ?? '', 'utf8');
      if (auth.length !== this.#authorization.length || !timingSafeEqual(auth, this.#authorization))
        throw new SourceReadError('unauthorized');
      if (
        headers['content-type'] !== 'application/json' ||
        !headers['content-length'] ||
        !/^[1-9][0-9]{0,3}$/.test(headers['content-length'])
      )
        throw new SourceReadError('invalid_input');
      const length = Number(headers['content-length']);
      if (length > REQUEST_BYTES) throw new SourceReadError('invalid_input');
      const raw = await body(request, length);
      if (route === '/v1/policy/discovery') {
        if (!raw.equals(Buffer.from('{"schemaVersion":1}')))
          throw new SourceReadError('invalid_input');
        const page = await this.#reads.discover();
        const encoded = Buffer.from(JSON.stringify(page), 'utf8');
        if (encoded.length > DISCOVERY_BYTES) throw new SourceReadError('invalid_state');
        this.#send(response, 200, encoded);
      } else {
        const input = preparedRequest(raw);
        const frame = await this.#reads.prepared(input.receiptId, input.sourceBindingId);
        if (
          frame !== null &&
          (!Buffer.isBuffer(frame) || frame.length < 1 || frame.length > PREPARED_BYTES)
        )
          throw new SourceReadError('invalid_state');
        this.#send(response, frame === null ? 204 : 200, frame ?? Buffer.alloc(0));
      }
      this.#completed++;
    } catch (error) {
      this.#error(response, sourceReadFailure(error));
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
              error ? reject(new SourceReadError('cleanup_incomplete')) : resolve(),
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
            () => reject(new SourceReadError('cleanup_incomplete')),
            this.#cleanupMs,
          );
        }),
      ]);
    } finally {
      clearTimeout(timer!);
    }
    if (this.#handlers.size || this.#sockets.size) throw new SourceReadError('cleanup_incomplete');
  }
}
