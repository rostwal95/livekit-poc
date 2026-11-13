/** One fresh bounded loopback connection per authority call; no retry or remote-stop claim. */
import { request, type ClientRequest } from 'node:http';
import type { Socket } from 'node:net';
import {
  RoutingError,
  fields,
  checkedSignal,
  isAborted,
  listenAbort,
  unlistenAbort,
} from './routing-types.js';
export type CaseAuthorityEndpoint = Readonly<{ host: '127.0.0.1'; port: number }>;
export type CaseAuthorityHttpOptions = Readonly<{
  timeoutMs?: number;
  cleanupMs?: number;
  maxActive?: number;
}>;
type Call = { request?: ClientRequest; socket?: Socket; settled: Promise<void> };
export type LocalCaseDecoded<T> =
  Readonly<{ status: 'known'; value: T }> | Readonly<{ status: 'rejected'; error: Error }>;
export class LocalCaseHttpTransport {
  readonly #endpoint: CaseAuthorityEndpoint;
  readonly #authorization: string;
  readonly #timeout: number;
  readonly #cleanup: number;
  readonly #maximum: number;
  readonly #calls = new Set<Call>();
  #closing = false;
  #counts = { started: 0, known: 0, rejected: 0, unknown: 0, failed: 0 };
  constructor(
    endpoint: CaseAuthorityEndpoint,
    authorization: string,
    options: CaseAuthorityHttpOptions = {},
    private readonly maximumRequestBytes: 8192 | 32768 = 8192,
  ) {
    const e = fields(endpoint, ['host', 'port']);
    if (
      ![8192, 32768].includes(this.maximumRequestBytes) ||
      e.host !== '127.0.0.1' ||
      !Number.isInteger(e.port) ||
      Number(e.port) < 1 ||
      Number(e.port) > 65535 ||
      typeof authorization !== 'string' ||
      !/^Bearer [A-Za-z0-9_-]{43}(?![\s\S])/.test(authorization)
    )
      throw new RoutingError('InvalidCommand');
    this.#endpoint = Object.freeze({ host: '127.0.0.1', port: Number(e.port) });
    this.#authorization = authorization;
    if (Object.keys(options).some((key) => !['timeoutMs', 'cleanupMs', 'maxActive'].includes(key)))
      throw new RoutingError('InvalidCommand');
    this.#timeout = options.timeoutMs ?? 2000;
    this.#cleanup = options.cleanupMs ?? 1000;
    this.#maximum = options.maxActive ?? 2;
    if (
      !Number.isInteger(this.#timeout) ||
      this.#timeout < 20 ||
      this.#timeout > 5000 ||
      !Number.isInteger(this.#cleanup) ||
      this.#cleanup < 20 ||
      this.#cleanup > 2000 ||
      !Number.isInteger(this.#maximum) ||
      this.#maximum < 1 ||
      this.#maximum > 4
    )
      throw new RoutingError('InvalidCommand');
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({ ...this.#counts, active: this.#calls.size });
  }
  exchange<T>(
    path: string,
    body: unknown,
    signal: AbortSignal,
    possibleWrite: boolean,
    decode: (value: unknown) => LocalCaseDecoded<T>,
  ): Promise<T> {
    checkedSignal(signal);
    if (this.#closing) return Promise.reject(new RoutingError('Closed'));
    if (this.#calls.size >= this.#maximum) return Promise.reject(new RoutingError('Overloaded'));
    if (isAborted(signal)) return Promise.reject(new RoutingError('Unavailable'));
    const payload = Buffer.from(JSON.stringify(body)),
      deadline = performance.now() + this.#timeout;
    if (payload.byteLength > this.maximumRequestBytes)
      return Promise.reject(new RoutingError('InvalidCommand'));
    let finished!: () => void;
    const call: Call = {
      settled: new Promise<void>((resolve) => {
        finished = resolve;
      }),
    };
    this.#calls.add(call);
    this.#counts.started++;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delivered = false,
      requestClosed = false,
      socketClosed = true,
      released = false;
    const failure = () => new RoutingError(possibleWrite ? 'OutcomeUnknown' : 'Unavailable');
    const result = new Promise<T>((resolve, reject) => {
      const fail = (error = failure()) => {
        if (!delivered) {
          delivered = true;
          this.#counts[error.code === 'OutcomeUnknown' ? 'unknown' : 'failed']++;
          reject(error);
        }
        call.request?.destroy();
        call.socket?.destroy();
      };
      const abort = () => fail();
      listenAbort(signal, abort);
      const release = () => {
        if (released || !requestClosed || !socketClosed) return;
        released = true;
        if (timer) clearTimeout(timer);
        unlistenAbort(signal, abort);
        this.#calls.delete(call);
        finished();
      };
      try {
        const outgoing = request({
          host: this.#endpoint.host,
          port: this.#endpoint.port,
          method: 'POST',
          path,
          agent: false,
          maxHeaderSize: 4096,
          headers: {
            Authorization: this.#authorization,
            'Content-Type': 'application/json',
            'Content-Length': String(payload.byteLength),
            Connection: 'close',
          },
        });
        call.request = outgoing;
        outgoing.on('socket', (socket) => {
          call.socket = socket;
          socketClosed = false;
          socket.once('close', () => {
            socketClosed = true;
            if (!delivered) fail();
            release();
          });
          if (requestClosed) socket.destroy();
        });
        outgoing.once('close', () => {
          requestClosed = true;
          if (!delivered) fail();
          release();
        });
        outgoing.once('error', () => {
          fail();
        });
        outgoing.once('response', (response) => {
          let size = 0;
          const chunks: Buffer[] = [];
          const seen = new Set<string>();
          for (let i = 0; i < response.rawHeaders.length; i += 2) {
            const name = response.rawHeaders[i]!.toLowerCase();
            if (
              seen.has(name) ||
              !['content-length', 'content-type', 'connection', 'date', 'server'].includes(name)
            ) {
              fail();
              return;
            }
            seen.add(name);
          }
          const length = response.headers['content-length'];
          if (
            response.statusCode !== 200 ||
            response.headers.connection !== 'close' ||
            response.headers['transfer-encoding'] !== undefined ||
            response.headers['content-type'] !== 'application/json' ||
            typeof length !== 'string' ||
            !/^[1-9][0-9]{0,3}(?![\s\S])/.test(length) ||
            Number(length) > 8192
          ) {
            fail();
            return;
          }
          response.on('data', (chunk: Buffer) => {
            size += chunk.byteLength;
            if (size > 8192) fail();
            else chunks.push(chunk);
          });
          response.once('error', () => fail());
          response.once('aborted', () => fail());
          response.once('end', () => {
            if (delivered) return;
            try {
              if (size !== Number(length) || isAborted(signal) || performance.now() >= deadline)
                throw failure();
              const raw = new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks));
              const value: unknown = JSON.parse(raw);
              if (JSON.stringify(value) !== raw) throw failure();
              const decoded = decode(value);
              delivered = true;
              if (decoded.status === 'known') {
                this.#counts.known++;
                resolve(decoded.value);
              } else {
                this.#counts.rejected++;
                reject(decoded.error);
              }
            } catch {
              fail();
            }
          });
        });
        timer = setTimeout(abort, this.#timeout);
        outgoing.end(payload);
      } catch {
        fail();
        if (!call.request) {
          requestClosed = true;
          release();
        }
      }
    });
    return result.then((value) => {
      if (isAborted(signal) || performance.now() >= deadline) throw failure();
      return value;
    });
  }
  async close(): Promise<void> {
    this.#closing = true;
    for (const call of this.#calls) {
      call.request?.destroy();
      call.socket?.destroy();
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all([...this.#calls].map((call) => call.settled)),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new RoutingError('CleanupIncomplete')), this.#cleanup);
        }),
      ]);
      if (this.#calls.size) throw new RoutingError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
