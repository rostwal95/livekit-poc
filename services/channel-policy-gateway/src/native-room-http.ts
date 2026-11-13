import { parseRoomAttach, type RoomAttach, type RoomAttachment } from './native-bridge-contract.js';
/** One loopback control/read transport. Parent manager owns grant calls and borrowed P2 waiters. */
import { timingSafeEqual } from 'node:crypto';
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import type { Socket } from 'node:net';
import type { NativeRoomManager } from './native-room-manager.js';
import { snapshotMethod } from './read-ports.js';
import {
  NativeRoomError,
  roomFailure,
  roomJson,
  parseRoomOpen,
  parseRoomCommand,
  parseRoomRecover,
  parseRoomRead,
  type RoomEndpoint,
  type RoomRead,
} from './native-room-contract.js';
type Ports = Pick<
  NativeRoomManager,
  'open' | 'observe' | 'closeRoom' | 'recover' | 'nativeResult' | 'assertDisclosure'
>;
const ROOT = '/v1/channel-policy/rooms/';
const ROUTES = new Set(
  ['open', 'observe', 'close', 'recover-revoke', 'native-result'].map((v) => ROOT + v),
);
export class NativeRoomHttp {
  readonly #ports: Ports;
  readonly #authorization: Buffer;
  readonly #attach: ((value: RoomAttach) => Promise<RoomAttachment>) | undefined;
  readonly #server: Server;
  readonly #sockets = new Set<Socket>();
  readonly #socketClosed = new Map<Socket, Promise<void>>();
  readonly #headers = new Map<Socket, ReturnType<typeof setTimeout>>();
  readonly #headerDeadlines = new Map<Socket, number>();
  readonly #seen = new WeakSet<Socket>();
  readonly #handlers = new Set<Promise<void>>();
  #starting: Promise<RoomEndpoint> | undefined;
  #endpoint: RoomEndpoint | undefined;
  #closeTask: Promise<void> | undefined;
  #closing = false;
  #closed = false;
  #completed = 0;
  #rejected = 0;
  constructor(
    ports: Ports,
    publisherToken: string,
    attach?: (value: RoomAttach) => Promise<RoomAttachment>,
  ) {
    if (
      typeof publisherToken !== 'string' ||
      publisherToken.length !== 43 ||
      !/^[A-Za-z0-9_-]+$/.test(publisherToken)
    )
      throw new NativeRoomError('invalid_input');
    try {
      this.#ports = Object.freeze({
        open: snapshotMethod<Ports['open']>(ports, 'open'),
        observe: snapshotMethod<Ports['observe']>(ports, 'observe'),
        closeRoom: snapshotMethod<Ports['closeRoom']>(ports, 'closeRoom'),
        recover: snapshotMethod<Ports['recover']>(ports, 'recover'),
        nativeResult: snapshotMethod<Ports['nativeResult']>(ports, 'nativeResult'),
        assertDisclosure: snapshotMethod<Ports['assertDisclosure']>(ports, 'assertDisclosure'),
      });
    } catch {
      throw new NativeRoomError('invalid_input');
    }
    this.#attach =
      attach === undefined
        ? undefined
        : snapshotMethod<{ attach: (value: RoomAttach) => Promise<RoomAttachment> }['attach']>(
            { attach },
            'attach',
          );
    this.#authorization = Buffer.from('Bearer ' + publisherToken, 'ascii');
    this.#server = createServer(
      { maxHeaderSize: 4096, requestTimeout: 0, headersTimeout: 0, keepAliveTimeout: 1 },
      (request, response) => {
        if (this.#closing || this.#handlers.size >= 4) {
          this.#rejected++;
          request.socket.destroy();
          return;
        }
        const actual = this.#handle(request, response).catch(() => {
          this.#rejected++;
          response.destroy();
        });
        this.#handlers.add(actual);
        void actual.then(() => this.#handlers.delete(actual));
      },
    );
    this.#server.maxConnections = 8;
    this.#server.maxRequestsPerSocket = 1;
    this.#server.maxHeadersCount = 0;
    this.#server.on('connection', (socket) => {
      if (this.#closing || this.#sockets.size >= 8) {
        socket.destroy();
        return;
      }
      this.#sockets.add(socket);
      let finish!: () => void;
      this.#socketClosed.set(
        socket,
        new Promise<void>((r) => {
          finish = r;
        }),
      );
      this.#headerDeadlines.set(socket, performance.now() + 1000);
      this.#headers.set(
        socket,
        setTimeout(() => {
          this.#rejected++;
          socket.destroy();
        }, 1000),
      );
      socket.once('close', () => {
        const timer = this.#headers.get(socket);
        if (timer) clearTimeout(timer);
        this.#headers.delete(socket);
        this.#headerDeadlines.delete(socket);
        this.#sockets.delete(socket);
        this.#socketClosed.delete(socket);
        finish();
      });
    });
    this.#server.on('clientError', (_error, socket) => {
      this.#rejected++;
      socket.destroy();
    });
    for (const name of ['upgrade', 'connect'] as const)
      this.#server.on(name, (_request, socket) => {
        this.#rejected++;
        socket.destroy();
      });
    for (const name of ['checkContinue', 'checkExpectation'] as const)
      this.#server.on(name, (request) => {
        this.#rejected++;
        request.socket.destroy();
      });
    this.#server.on('dropRequest', (_request, socket) => {
      this.#rejected++;
      socket.destroy();
    });
    this.#server.on('error', () => {
      this.#rejected++;
    });
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({
      httpSockets: this.#sockets.size,
      httpHandlers: this.#handlers.size,
      httpHandled: this.#completed,
      httpRejected: this.#rejected,
    });
  }
  start(port: number): Promise<RoomEndpoint> {
    if (this.#closing || this.#starting || this.#endpoint)
      return Promise.reject(new NativeRoomError('closed'));
    if (typeof port !== 'number' || !Number.isSafeInteger(port) || port < 1 || port > 65535)
      return Promise.reject(new NativeRoomError('invalid_input'));
    const actual = new Promise<RoomEndpoint>((resolve, reject) => {
      const failed = () => {
        this.#server.off('error', failed);
        this.#server.off('listening', ready);
        reject(new NativeRoomError('unavailable'));
      };
      const ready = () => {
        this.#server.off('error', failed);
        this.#server.off('listening', ready);
        if (this.#closing) {
          this.#server.close(() => reject(new NativeRoomError('closed')));
          return;
        }
        const a = this.#server.address();
        if (!a || typeof a === 'string' || a.port !== port) {
          reject(new NativeRoomError('unavailable'));
          return;
        }
        this.#endpoint = Object.freeze({ host: '127.0.0.1', port: a.port });
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
    this.#starting = actual;
    void actual.catch(() => {});
    return actual;
  }
  #header(request: IncomingMessage): Readonly<{ authorization: string; length: number }> {
    if (
      request.httpVersion !== '1.1' ||
      request.method !== 'POST' ||
      !(ROUTES.has(request.url ?? '') || (request.url === ROOT + 'attach-agent' && this.#attach)) ||
      request.rawHeaders.length > 16
    )
      throw new NativeRoomError('invalid_input');
    const seen = new Set<string>(),
      allowed = new Set(['host', 'authorization', 'content-type', 'content-length', 'connection']);
    for (let i = 0; i < request.rawHeaders.length; i += 2) {
      const name = request.rawHeaders[i]!.toLowerCase();
      if (seen.has(name) || !allowed.has(name)) throw new NativeRoomError('invalid_input');
      seen.add(name);
    }
    const length = request.headers['content-length'],
      authorization = request.headers.authorization;
    if (
      seen.size !== 5 ||
      request.headers.host !== '127.0.0.1:' + String(this.#endpoint?.port) ||
      request.headers['content-type'] !== 'application/json' ||
      request.headers.connection !== 'close' ||
      typeof length !== 'string' ||
      !/^[1-9][0-9]{0,3}$/.test(length) ||
      Number(length) > 1024
    )
      throw new NativeRoomError('invalid_input');
    if (
      typeof authorization !== 'string' ||
      authorization.length !== 50 ||
      !/^Bearer [A-Za-z0-9_-]{43}$/.test(authorization)
    )
      throw new NativeRoomError('unauthorized');
    if (
      request.url !== ROOT + 'native-result' &&
      !timingSafeEqual(Buffer.from(authorization, 'ascii'), this.#authorization)
    )
      throw new NativeRoomError('unauthorized');
    return Object.freeze({ authorization, length: Number(length) });
  }
  #body(request: IncomingMessage, length: number): Promise<Buffer> {
    return new Promise((resolve, reject) => {
      const raw = Buffer.alloc(length);
      let used = 0,
        done = false;
      const finish = (error?: NativeRoomError) => {
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
        } else resolve(raw);
      };
      const data = (part: Buffer) => {
        if (used + part.length > length) {
          finish(new NativeRoomError('invalid_input'));
          return;
        }
        part.copy(raw, used);
        used += part.length;
      };
      const end = () => finish(used === length ? undefined : new NativeRoomError('invalid_input')),
        failed = () => finish(new NativeRoomError('unavailable'));
      const timer = setTimeout(failed, 1000);
      request.on('data', data);
      request.once('end', end);
      request.once('error', failed);
      request.once('aborted', failed);
    });
  }
  #send(response: ServerResponse, status: number, bytes: Buffer): Promise<void> {
    if (response.destroyed || response.socket?.destroyed) return Promise.resolve();
    return new Promise((resolve) => {
      let done = false;
      const finish = () => {
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
      }, 1000);
      response.once('finish', finish);
      response.once('close', finish);
      response.once('error', finish);
      try {
        response.writeHead(status, {
          'content-type': 'application/json',
          'content-length': bytes.length,
          connection: 'close',
          'cache-control': 'no-store',
        });
        response.end(bytes);
      } catch {
        response.destroy();
        finish();
      }
    });
  }
  async #handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    const late = performance.now() >= (this.#headerDeadlines.get(request.socket) ?? Infinity);
    this.#headerDeadlines.delete(request.socket);
    const timer = this.#headers.get(request.socket);
    if (timer) clearTimeout(timer);
    this.#headers.delete(request.socket);
    if (this.#seen.has(request.socket)) {
      request.socket.destroy();
      return;
    }
    this.#seen.add(request.socket);
    try {
      if (this.#closing || late)
        throw new NativeRoomError(this.#closing ? 'closed' : 'invalid_input');
      const h = this.#header(request),
        value = roomJson(await this.#body(request, h.length));
      if (this.#closing) throw new NativeRoomError('closed');
      let result: unknown, read: RoomRead | undefined;
      if (request.url === ROOT + 'open') result = await this.#ports.open(parseRoomOpen(value));
      else if (request.url === ROOT + 'attach-agent' && this.#attach)
        result = await this.#attach(parseRoomAttach(value));
      else if (request.url === ROOT + 'observe')
        result = this.#ports.observe(parseRoomCommand(value));
      else if (request.url === ROOT + 'close')
        result = await this.#ports.closeRoom(parseRoomCommand(value));
      else if (request.url === ROOT + 'recover-revoke')
        result = await this.#ports.recover(parseRoomRecover(value));
      else {
        read = parseRoomRead(value);
        result = await this.#ports.nativeResult(read, h.authorization.slice(7));
      }
      if (this.#closing) throw new NativeRoomError('closed');
      const bytes = Buffer.from(JSON.stringify(result));
      if (bytes.length > (read ? 32768 : 4096)) throw new NativeRoomError('unavailable');
      // No await between final same-generation disclosure admission and initiating output.
      if (read) this.#ports.assertDisclosure(read, h.authorization.slice(7));
      await this.#send(response, 200, bytes);
      this.#completed++;
    } catch (error) {
      this.#rejected++;
      if (response.headersSent) {
        response.destroy();
        return;
      }
      const failure = roomFailure(error),
        status = (
          {
            invalid_input: 400,
            unauthorized: 401,
            conflict: 409,
            capacity: 429,
            recovery_required: 409,
            closed: 503,
            unavailable: 503,
            outcome_unknown: 503,
            cleanup_incomplete: 503,
          } as const
        )[failure.code];
      await this.#send(
        response,
        status,
        Buffer.from(
          JSON.stringify({ schemaVersion: 1, status: 'unavailable', code: failure.code }),
        ),
      );
    }
  }
  close(): Promise<void> {
    this.#closing = true;
    if (this.#closed) return Promise.resolve();
    if (!this.#closeTask) {
      const actual = Promise.resolve().then(async () => {
        const sockets = [...this.#socketClosed.values()];
        for (const socket of this.#sockets) socket.destroy();
        if (this.#starting) await this.#starting.catch(() => {});
        if (this.#server.listening) await new Promise<void>((r) => this.#server.close(() => r()));
        await Promise.all([...this.#handlers, ...sockets]);
        if (this.#sockets.size || this.#handlers.size)
          throw new NativeRoomError('cleanup_incomplete');
        this.#closed = true;
      });
      this.#closeTask = actual;
      void actual.then(
        () => {
          this.#closeTask = undefined;
        },
        () => {
          this.#closeTask = undefined;
        },
      );
    }
    const actual = this.#closeTask;
    return (async () => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([
          actual,
          new Promise<never>((_r, reject) => {
            timer = setTimeout(() => reject(new NativeRoomError('cleanup_incomplete')), 1000);
          }),
        ]);
      } finally {
        if (timer) clearTimeout(timer);
      }
    })();
  }
}
