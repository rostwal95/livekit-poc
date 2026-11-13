/** Explicit literal-loopback read service. Application separately owns facade, inbox and case port. */
import { createServer, type IncomingMessage, type ServerResponse, type Server } from 'node:http';
import type { Socket } from 'node:net';
import type { ChannelRehydrator } from './rehydration.js';
import {
  RehydrationError,
  rehydrationFields,
  rehydrationQuery,
  type RehydrationContext,
} from './rehydration-types.js';
export class RehydrationHttpServer {
  readonly #server: Server;
  readonly #sockets = new Set<Socket>();
  readonly #handlers = new Set<Promise<void>>();
  #closing = false;
  #started = false;
  #bind: Promise<void> | undefined;
  readonly #native: ChannelRehydrator['native'];
  readonly #sms: ChannelRehydrator['sms'];
  readonly #counts = { started: 0, known: 0, rejected: 0 };
  constructor(readonly rehydrator: ChannelRehydrator) {
    const method = (name: 'native' | 'sms') => {
      let current: object | null = rehydrator;
      for (let n = 0; current && n < 4; n++, current = Object.getPrototypeOf(current)) {
        const d = Object.getOwnPropertyDescriptor(current, name);
        if (d) {
          if (!('value' in d) || typeof d.value !== 'function') break;
          return d.value.bind(rehydrator);
        }
      }
      throw new RehydrationError('invalid_query');
    };
    try {
      this.#native = method('native') as ChannelRehydrator['native'];
      this.#sms = method('sms') as ChannelRehydrator['sms'];
    } catch {
      throw new RehydrationError('invalid_query');
    }
    this.#server = createServer(
      { maxHeaderSize: 4096, insecureHTTPParser: false, connectionsCheckingInterval: 100 },
      (req, res) => {
        if (this.#closing || this.#handlers.size >= 2) {
          req.socket.destroy();
          return;
        }
        const task = this.#handle(req, res);
        this.#handlers.add(task);
        void task.finally(() => this.#handlers.delete(task)).catch(() => undefined);
      },
    );
    this.#server.headersTimeout = 1000;
    this.#server.requestTimeout = 2000;
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
  async start(port = 0): Promise<Readonly<{ host: '127.0.0.1'; port: number }>> {
    if (this.#closing || this.#started || !Number.isInteger(port) || port < 0 || port > 65535)
      throw new RehydrationError('invalid_query');
    this.#started = true;
    this.#bind = new Promise<void>((resolve, reject) => {
      const failed = () => {
        this.#server.off('listening', ready);
        reject(new RehydrationError());
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
      throw new RehydrationError('closed');
    }
    const address = this.#server.address();
    if (!address || typeof address === 'string') throw new RehydrationError();
    return Object.freeze({ host: '127.0.0.1', port: address.port });
  }
  #reply(res: ServerResponse, value: unknown) {
    const raw = Buffer.from(JSON.stringify(value));
    if (raw.length > 65536) throw new RehydrationError();
    if (res.destroyed) return;
    res.writeHead(200, {
      'Content-Type': 'application/json',
      'Content-Length': String(raw.length),
      Connection: 'close',
    });
    res.end(raw);
  }
  async #handle(req: IncomingMessage, res: ServerResponse) {
    this.#counts.started++;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const headers: Record<string, string> = Object.create(null) as Record<string, string>;
      for (let n = 0; n < req.rawHeaders.length; n += 2) {
        const key = req.rawHeaders[n]!.toLowerCase();
        if (
          Object.hasOwn(headers, key) ||
          !['host', 'authorization', 'content-type', 'content-length', 'connection'].includes(key)
        )
          throw new RehydrationError('invalid_query');
        headers[key] = req.rawHeaders[n + 1]!;
      }
      if (
        req.method !== 'POST' ||
        !['/v1/rehydration/native', '/v1/rehydration/sms'].includes(req.url ?? '') ||
        headers['content-type'] !== 'application/json' ||
        headers.connection !== 'close' ||
        headers.host !==
          '127.0.0.1:' + String((this.#server.address() as { port: number } | null)?.port) ||
        !/^[1-9][0-9]{0,4}(?![\s\S])/.test(headers['content-length'] ?? '')
      )
        throw new RehydrationError('invalid_query');
      const maximum = req.url === '/v1/rehydration/native' ? 4096 : 49152,
        size = Number(headers['content-length']);
      if (size > maximum) throw new RehydrationError('invalid_query');
      let count = 0;
      const chunks: Buffer[] = [];
      const raw = await new Promise<Buffer>((resolve, reject) => {
        timer = setTimeout(() => {
          req.destroy();
          reject(new RehydrationError());
        }, 2000);
        req.on('data', (chunk: Buffer) => {
          count += chunk.length;
          if (count > size) {
            req.destroy();
            reject(new RehydrationError('invalid_query'));
          } else chunks.push(Buffer.from(chunk));
        });
        req.once('end', () => {
          if (count === size) resolve(Buffer.concat(chunks));
          else reject(new RehydrationError('invalid_query'));
        });
        req.once('error', () => reject(new RehydrationError()));
        req.once('aborted', () => reject(new RehydrationError()));
      });
      if (timer) {
        clearTimeout(timer);
        timer = undefined;
      }
      const string = new TextDecoder('utf-8', { fatal: true }).decode(raw),
        value: unknown = JSON.parse(string);
      if (JSON.stringify(value) !== string) throw new RehydrationError('invalid_query');
      let context: RehydrationContext;
      if (req.url === '/v1/rehydration/native') {
        const x = rehydrationFields(value, ['schemaVersion', 'query']);
        if (
          x.schemaVersion !== 1 ||
          !/^Bearer [A-Za-z0-9_-]{32,128}(?![\s\S])/.test(headers.authorization ?? '')
        )
          throw new RehydrationError('access_denied');
        context = await this.#native(headers.authorization!.slice(7), rehydrationQuery(x.query));
      } else {
        const x = rehydrationFields(value, ['schemaVersion', 'rawSms', 'headers', 'query']);
        if (x.schemaVersion !== 1 || typeof x.rawSms !== 'string' || x.rawSms.length > 43692)
          throw new RehydrationError('invalid_query');
        const bytes = Buffer.from(x.rawSms, 'base64');
        if (bytes.toString('base64') !== x.rawSms) throw new RehydrationError('invalid_query');
        const h = rehydrationFields(x.headers, ['timestamp', 'signature']);
        context = await this.#sms(
          bytes,
          { timestamp: h.timestamp as string, signature: h.signature as string },
          rehydrationQuery(x.query),
        );
      }
      this.#reply(res, { schemaVersion: 1, status: 'known', context });
      this.#counts.known++;
    } catch (error) {
      this.#counts.rejected++;
      try {
        this.#reply(res, {
          schemaVersion: 1,
          status: 'unavailable',
          code: error instanceof RehydrationError ? error.code : 'context_unavailable',
        });
      } catch {
        req.socket.destroy();
      }
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  async close() {
    this.#closing = true;
    for (const socket of this.#sockets) socket.destroy();
    const listener = (async () => {
      if (this.#bind) await this.#bind.catch(() => undefined);
      await new Promise<void>((resolve) => {
        if (!this.#server.listening) resolve();
        else this.#server.close(() => resolve());
      });
    })();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all([listener, ...this.#handlers]),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new RehydrationError()), 5000);
        }),
      ]);
      if (this.#sockets.size || this.#handlers.size) throw new RehydrationError();
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
