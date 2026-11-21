/** Bounded client for original operation lookup and acceptance on an owned loopback socket. */
import { request as httpRequest, type ClientRequest } from 'node:http';
import type { Socket } from 'node:net';
import type {
  OperationLookup,
  OperationReceipt,
  PreparedDispatch,
} from '@livekit-ecosystem/channel-continuity/dispatch';

import { runtimeFields as fields, runtimeString, type LoopbackEndpoint } from './runtime-config.js';

const REQUEST_BYTES = 32768;
const RESPONSE_BYTES = 4096;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

type ErrorCode =
  | 'InvalidConfiguration'
  | 'InvalidCommand'
  | 'IdentityConflict'
  | 'Unavailable'
  | 'OutcomeUnknown'
  | 'CleanupIncomplete'
  | 'Closed'
  | 'Overloaded';

class OperationClientError extends Error {
  constructor(readonly code: ErrorCode) {
    super(code);
    this.name = 'OperationClientError';
  }
}

type LookupResult =
  Readonly<{ status: 'absent' }> | Readonly<{ status: 'accepted'; receipt: OperationReceipt }>;

/** Reject duplicate fields and malformed or oversized JSON before checking the response shape. */
function parseJson(raw: Uint8Array, maximum: number): unknown {
  if (!raw.length || raw.length > maximum) throw new OperationClientError('InvalidConfiguration');
  let source: string;
  try {
    source = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw);
  } catch {
    throw new OperationClientError('InvalidConfiguration');
  }
  let at = 0,
    entries = 0;
  const ws = () => {
    while (/[\x20\t\r\n]/.test(source[at] ?? 'x')) at++;
  };
  const string = (): string => {
    const begin = at++;
    while (at < source.length) {
      const ch = source[at++];
      if (ch === '\\') {
        at++;
        continue;
      }
      if (ch === '"') {
        try {
          const v = JSON.parse(source.slice(begin, at)) as unknown;
          if (typeof v !== 'string' || /[\ud800-\udfff]/u.test(v)) throw Error();
          return v;
        } catch {
          throw new OperationClientError('InvalidConfiguration');
        }
      }
    }
    throw new OperationClientError('InvalidConfiguration');
  };
  const value = (depth: number): unknown => {
    ws();
    if (depth > 12 || ++entries > 2048) throw new OperationClientError('InvalidConfiguration');
    const ch = source[at];
    if (ch === '"') return string();
    if (ch === '{') {
      at++;
      ws();
      const out: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
      if (source[at] === '}') {
        at++;
        return out;
      }
      for (;;) {
        ws();
        if (source[at] !== '"') throw new OperationClientError('InvalidConfiguration');
        const key = string();
        ws();
        if (Object.hasOwn(out, key) || source[at++] !== ':')
          throw new OperationClientError('InvalidConfiguration');
        out[key] = value(depth + 1);
        ws();
        const next = source[at++];
        if (next === '}') return out;
        if (next !== ',') throw new OperationClientError('InvalidConfiguration');
      }
    }
    if (ch === '[') {
      at++;
      ws();
      const out: unknown[] = [];
      if (source[at] === ']') {
        at++;
        return out;
      }
      for (;;) {
        out.push(value(depth + 1));
        ws();
        const next = source[at++];
        if (next === ']') return out;
        if (next !== ',') throw new OperationClientError('InvalidConfiguration');
      }
    }
    for (const [literal, result] of [
      ['true', true],
      ['false', false],
      ['null', null],
    ] as const)
      if (source.slice(at, at + literal.length) === literal) {
        at += literal.length;
        return result;
      }
    const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(source.slice(at));
    if (!match) throw new OperationClientError('InvalidConfiguration');
    at += match[0].length;
    const n = Number(match[0]);
    if (!Number.isFinite(n) || (Number.isInteger(n) && !Number.isSafeInteger(n)))
      throw new OperationClientError('InvalidConfiguration');
    return n;
  };
  const result = value(0);
  ws();
  if (at !== source.length) throw new OperationClientError('InvalidConfiguration');
  return result;
}
/** One actual close pass and one bounded observation, shared across repeated callers. */
class CloseObservation {
  #view: Promise<void> | undefined;
  #complete = false;
  observe(action: () => Promise<void>, timeoutMs = 2000): Promise<void> {
    if (this.#complete) return Promise.resolve();
    if (this.#view) return this.#view;
    let resolve!: () => void, reject!: (e: OperationClientError) => void;
    const view = new Promise<void>((ok, bad) => {
      resolve = ok;
      reject = bad;
    });
    this.#view = view;
    const timer = setTimeout(
      () => reject(new OperationClientError('CleanupIncomplete')),
      timeoutMs,
    );
    // Reservation precedes action and thenable assimilation, including reentrant close.
    const actual = Promise.resolve().then(action);
    void actual.then(
      () => {
        clearTimeout(timer);
        this.#complete = true;
        resolve();
      },
      () => {
        clearTimeout(timer);
        if (this.#view === view) this.#view = undefined;
        reject(new OperationClientError('CleanupIncomplete'));
      },
    );
    void view.catch(() => undefined);
    return view;
  }
}

type ClientCall = {
  done: Promise<void>;
  finish(): void;
  request?: ClientRequest;
  socket?: Socket;
  requestClosed: boolean;
  socketClosed: boolean;
};
export class ExternalOperationClient {
  readonly #endpoint: LoopbackEndpoint;
  readonly #bearer: string;
  readonly #timeoutMs: number;
  readonly #calls = new Set<ClientCall>();
  #closing = false;
  readonly #closeObservation = new CloseObservation();
  constructor(endpoint: LoopbackEndpoint, bearer: string, timeoutMs: number) {
    this.#endpoint = endpoint;
    this.#bearer = bearer;
    this.#timeoutMs = timeoutMs;
  }
  metrics(): Readonly<{ active: number; closing: boolean }> {
    return Object.freeze({ active: this.#calls.size, closing: this.#closing });
  }
  lookup(input: OperationLookup, signal: AbortSignal): Promise<LookupResult> {
    return this.#exchange('/v1/investigations/lookup', input, signal, false, (value) => {
      const p = fields(value, ['schemaVersion', 'status', 'observation']);
      if (p.schemaVersion !== 1 || p.status !== 'known')
        throw new OperationClientError('Unavailable');
      const o = fields(p.observation, [
        'status',
        ...(Object.hasOwn(p.observation as object, 'receipt') ? ['receipt'] : []),
      ]);
      if (o.status === 'absent') return Object.freeze({ status: 'absent' as const });
      if (o.status !== 'accepted') throw new OperationClientError('Unavailable');
      return Object.freeze({
        status: 'accepted' as const,
        receipt: this.#receipt(o.receipt, input),
      });
    });
  }
  accept(input: PreparedDispatch, signal: AbortSignal): Promise<OperationReceipt> {
    return this.#exchange(
      '/v1/investigations/accept',
      {
        schemaVersion: 1,
        canonicalPayload: input.canonicalPayload,
        payloadDigest: input.payloadDigest,
      },
      signal,
      true,
      (value) => {
        const p = fields(value, ['schemaVersion', 'status', 'receipt']);
        if (p.schemaVersion !== 1 || p.status !== 'known')
          throw new OperationClientError('OutcomeUnknown');
        return this.#receipt(p.receipt, {
          operationKey: input.submission.operationKey,
          scope: input.submission.scope,
          payloadDigest: input.payloadDigest,
        });
      },
    );
  }
  #receipt(value: unknown, input: OperationLookup): OperationReceipt {
    const p = fields(value, ['operationKey', 'scope', 'payloadDigest', 'receiptId']);
    const s = fields(p.scope, ['tenantId', 'accountId']);
    if (
      p.operationKey !== input.operationKey ||
      p.payloadDigest !== input.payloadDigest ||
      s.tenantId !== input.scope.tenantId ||
      s.accountId !== input.scope.accountId
    )
      throw new OperationClientError('IdentityConflict');
    return Object.freeze({ ...input, receiptId: runtimeString(p.receiptId, UUID) });
  }
  #exchange<T>(
    path: string,
    value: unknown,
    signal: AbortSignal,
    write: boolean,
    decode: (v: unknown) => T,
  ): Promise<T> {
    if (this.#closing) return Promise.reject(new OperationClientError('Closed'));
    if (this.#calls.size >= 2) return Promise.reject(new OperationClientError('Overloaded'));
    if (signal.aborted) return Promise.reject(new OperationClientError('Unavailable'));
    const payload = Buffer.from(JSON.stringify(value));
    if (payload.length > REQUEST_BYTES)
      return Promise.reject(new OperationClientError('InvalidCommand'));
    let done!: () => void;
    const call: ClientCall = {
      done: new Promise<void>((r) => {
        done = r;
      }),
      finish: () => done(),
      requestClosed: false,
      socketClosed: true,
    };
    this.#calls.add(call);
    const failure = () => new OperationClientError(write ? 'OutcomeUnknown' : 'Unavailable');
    let timer: ReturnType<typeof setTimeout> | undefined, abort: (() => void) | undefined;
    const release = () => {
      if (call.requestClosed && call.socketClosed && this.#calls.delete(call)) call.finish();
    };
    return new Promise<T>((resolve, reject) => {
      let delivered = false;
      const fail = () => {
        if (!delivered) {
          delivered = true;
          reject(failure());
        }
        call.request?.destroy();
        call.socket?.destroy();
      };
      timer = setTimeout(fail, this.#timeoutMs);
      try {
        const req = httpRequest(
          {
            hostname: '127.0.0.1',
            port: this.#endpoint.port,
            path,
            method: 'POST',
            agent: false,
            headers: {
              host: '127.0.0.1:' + this.#endpoint.port,
              authorization: 'Bearer ' + this.#bearer,
              'content-type': 'application/json',
              'content-length': payload.length,
              connection: 'close',
            },
          },
          (res) => {
            const length = res.headers['content-length'];
            if (
              res.statusCode !== 200 ||
              res.headers['content-type'] !== 'application/json' ||
              res.headers.connection !== 'close' ||
              res.headers['cache-control'] !== 'no-store' ||
              res.headers['transfer-encoding'] !== undefined ||
              typeof length !== 'string' ||
              !/^[1-9][0-9]{0,4}$/.test(length) ||
              Number(length) > RESPONSE_BYTES
            ) {
              res.resume();
              fail();
              return;
            }
            const chunks: Buffer[] = [];
            let total = 0;
            res.on('data', (b: Buffer) => {
              total += b.length;
              if (total > Number(length)) {
                res.destroy();
                fail();
              } else chunks.push(b);
            });
            res.once('aborted', fail);
            res.once('error', fail);
            res.once('end', () => {
              if (delivered) return;
              try {
                if (total !== Number(length) || signal.aborted) throw failure();
                const result = decode(parseJson(Buffer.concat(chunks), RESPONSE_BYTES));
                delivered = true;
                resolve(result);
              } catch {
                fail();
              }
            });
          },
        );
        call.request = req;
        req.once('close', () => {
          call.requestClosed = true;
          release();
        });
        req.once('error', fail);
        req.once('socket', (s) => {
          call.socket = s;
          call.socketClosed = false;
          s.once('close', () => {
            call.socketClosed = true;
            release();
          });
        });
        if (this.#calls.has(call)) {
          abort = fail;
          signal.addEventListener('abort', abort, { once: true });
        }
        if (signal.aborted) fail();
        else req.end(payload);
      } catch {
        fail();
        if (!call.request) {
          call.requestClosed = true;
          release();
        }
      }
    }).finally(() => {
      if (timer) clearTimeout(timer);
      if (abort) signal.removeEventListener('abort', abort);
    });
  }
  close(): Promise<void> {
    this.#closing = true;
    return this.#closeObservation.observe(async () => {
      await Promise.all([...this.#calls].map((c) => c.done));
    });
  }
}
