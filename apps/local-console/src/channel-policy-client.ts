/** Three retained HTTP owners; the third is reserved for one End, including cleanup. */
import { JoinedUiError } from './channel-policy-contract';
import {
  UI_LIMITS,
  PURPOSES,
  json,
  errorCode,
  safeCode,
  encodeRequest,
} from './channel-policy-wire';
import type { Purpose } from './channel-policy-wire';
export interface RequestOwner<T> {
  readonly result: Promise<T>;
  readonly actualResult: Promise<T>;
  readonly settled: Promise<void>;
  abort(): void;
  retryCleanup(): Promise<void>;
}
interface Call {
  readonly purpose: Purpose;
  cleanupActual: Promise<void> | null;
  readonly release: () => void;
  readonly abort: AbortController;
  actual: Promise<unknown> | null;
  reader: ReadableStreamDefaultReader<Uint8Array> | null;
  settled: boolean;
}
export class JoinedClient {
  #calls = new Set<Call>();
  #closing = false;
  #closePass: Promise<void> | null = null;
  #closeActual: Promise<void> | null = null;
  constructor(readonly fetcher: typeof fetch = fetch) {}
  get pendingCount(): number {
    return this.#calls.size;
  }
  request<T>(
    purpose: Purpose,
    body: unknown,
    credential: string,
    decode: (value: unknown) => T,
    signal?: AbortSignal,
  ): Promise<T> {
    try {
      return this.begin(purpose, body, credential, decode, signal).result;
    } catch (error) {
      return Promise.reject(safeCode(error));
    }
  }
  begin<T>(
    purpose: Purpose,
    body: unknown,
    credential: string,
    decode: (value: unknown) => T,
    signal?: AbortSignal,
  ): RequestOwner<T> {
    if (this.#closing) throw new JoinedUiError('unavailable');
    if (!PURPOSES.includes(purpose) || !/^[A-Za-z0-9_-]{43}$/u.test(credential))
      throw new JoinedUiError('invalid');
    const raw = encodeRequest(purpose, body);
    const ends = [...this.#calls].filter((call) => call.purpose === 'end').length;
    if (this.#calls.size >= 3 || (purpose === 'end' ? ends >= 1 : this.#calls.size - ends >= 2))
      throw new JoinedUiError('capacity');
    let release!: () => void;
    const settled = new Promise<void>((resolve) => {
      release = resolve;
    });
    const call: Call = {
      purpose,
      cleanupActual: null,
      release,
      abort: new AbortController(),
      actual: null,
      reader: null,
      settled: false,
    };
    this.#calls.add(call);
    const abort = (): void => call.abort.abort();
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) abort();
    const actual = this.#perform(call, purpose, raw, credential, decode);
    call.actual = actual;
    void actual
      .then(
        () => {
          call.settled = true;
          this.#release(call);
        },
        () => {
          call.settled = true;
          this.#release(call);
        },
      )
      .finally(() => signal?.removeEventListener('abort', abort));
    const result = observed(actual, UI_LIMITS.httpMs, () => {
      call.abort.abort();
      return new JoinedUiError(
        ['start', 'end', 'sms'].includes(purpose) ? 'unknown' : 'unavailable',
      );
    });
    const retryCleanup = (): Promise<void> =>
      observed(
        this.#cleanup(call),
        UI_LIMITS.closeMs,
        () => new JoinedUiError('cleanup_incomplete'),
      );
    return Object.freeze({ result, actualResult: actual, settled, abort, retryCleanup });
  }
  async #perform<T>(
    call: Call,
    purpose: Purpose,
    raw: string,
    credential: string,
    decode: (value: unknown) => T,
  ): Promise<T> {
    let done = false;
    try {
      const fetcher = this.fetcher;
      const response = await fetcher('/v1/channel-policy-demo/' + purpose, {
        method: 'POST',
        headers: {
          Authorization: 'Bearer ' + credential,
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: raw,
        credentials: 'omit',
        cache: 'no-store',
        redirect: 'error',
        signal: call.abort.signal,
      });
      if (!response.body) throw new JoinedUiError('invalid');
      call.reader = response.body.getReader();
      const declared = response.headers.get('Content-Length');
      if (
        response.redirected ||
        !/^application\/json(?:\s*;\s*charset=utf-8)?$/iu.test(
          response.headers.get('Content-Type') ?? '',
        ) ||
        response.headers.get('Cache-Control') !== 'no-store' ||
        (declared !== null &&
          (!/^(0|[1-9][0-9]*)$/u.test(declared) ||
            !Number.isSafeInteger(Number(declared)) ||
            Number(declared) > UI_LIMITS.responseBytes))
      )
        throw new JoinedUiError('invalid');
      let size = 0,
        text = '';
      const decoder = new TextDecoder('utf-8', { fatal: true });
      while (true) {
        const part = await call.reader.read();
        if (part.done) {
          done = true;
          break;
        }
        size += part.value.byteLength;
        if (size > UI_LIMITS.responseBytes) throw new JoinedUiError('invalid');
        try {
          text += decoder.decode(part.value, { stream: true });
        } catch {
          throw new JoinedUiError('invalid');
        }
      }
      try {
        text += decoder.decode();
      } catch {
        throw new JoinedUiError('invalid');
      }
      if (declared !== null && Number(declared) !== size) throw new JoinedUiError('invalid');
      const value = json(text);
      if (response.status !== 200)
        throw Object.assign(new Error(), {
          code: errorCode(value, response.status),
        });
      return decode(value);
    } catch (error) {
      throw safeCode(error, ['start', 'end', 'sms'].includes(purpose) ? 'unknown' : 'unavailable');
    } finally {
      if (call.reader) {
        try {
          if (!done) await call.reader.cancel();
          call.reader.releaseLock();
          call.reader = null;
        } catch {
          /* Keep the actual reader and capacity for an explicit close retry. */
        }
      }
    }
  }
  #release(call: Call): void {
    if (call.settled && call.reader === null && call.cleanupActual === null) {
      this.#calls.delete(call);
      call.release();
    }
  }
  #cleanup(call: Call): Promise<void> {
    if (!call.settled) return Promise.reject(new JoinedUiError('cleanup_incomplete'));
    if (call.cleanupActual) return call.cleanupActual;
    if (!call.reader) {
      this.#release(call);
      return Promise.resolve();
    }
    const actual = (async () => {
      try {
        await call.reader!.cancel();
        call.reader!.releaseLock();
        call.reader = null;
      } catch {
        throw new JoinedUiError('cleanup_incomplete');
      }
    })();
    call.cleanupActual = actual;
    void actual.then(
      () => {
        if (call.cleanupActual === actual) call.cleanupActual = null;
        this.#release(call);
      },
      () => {
        if (call.cleanupActual === actual) call.cleanupActual = null;
      },
    );
    return actual;
  }
  abortRequests(): void {
    for (const call of this.#calls) call.abort.abort();
  }
  close(): Promise<void> {
    this.#closing = true;
    this.abortRequests();
    if (this.#closePass) return this.#closePass;
    if (!this.#closeActual) {
      const actual = (async () => {
        await Promise.allSettled([...this.#calls].map((c) => c.actual));
        await Promise.all([...this.#calls].map((call) => this.#cleanup(call)));
        if (this.#calls.size) throw new JoinedUiError('cleanup_incomplete');
      })();
      this.#closeActual = actual;
      void actual.then(
        () => {
          if (this.#closeActual === actual) this.#closeActual = null;
        },
        () => {
          if (this.#closeActual === actual) this.#closeActual = null;
        },
      );
    }
    const pass = observed(
      this.#closeActual,
      UI_LIMITS.closeMs,
      () => new JoinedUiError('cleanup_incomplete'),
    );
    this.#closePass = pass;
    void pass
      .finally(() => {
        if (this.#closePass === pass) this.#closePass = null;
      })
      .catch(() => undefined);
    return pass;
  }
}
export function observed<T>(
  actual: Promise<T>,
  milliseconds: number,
  error: () => Error,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(error()), milliseconds);
  });
  return Promise.race([actual, timeout]).finally(() => {
    if (timer !== undefined) clearTimeout(timer);
  });
}
