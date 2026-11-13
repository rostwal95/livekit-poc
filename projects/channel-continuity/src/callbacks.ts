/** Explicit bounded raw callback intake. Application owns its listener; SDK owns SQL/tasks. */
import type { DatabaseSettings } from './public-types.js';
import { SeededAccounts } from './postgres.js';
import type { WebhookHeaders } from './security.js';
import type { FakeSmsCallbackIntegration } from './callback-security.js';
import { record } from './outbox-types.js';
import { CallbackStore } from './callback-store.js';
import { checkedSignal, isAborted, listenAbort, unlistenAbort } from './routing-types.js';
import {
  CallbackError,
  safeCallback,
  type CallbackReceipt,
  type CallbackAttempt,
  type CallbackOptions,
  type CallbackEvent,
} from './callback-types.js';
export {
  CallbackError,
  reduceCallbackEvidence,
  DEFAULT_CALLBACK_LIMITS,
} from './callback-types.js';
export type {
  CallbackState,
  CallbackObservation,
  CallbackReceipt,
  CallbackAttempt,
  CallbackEvidence,
  RetainedCallback,
  CallbackLimits,
  CallbackOptions,
  CallbackEvent,
  CallbackCode,
} from './callback-types.js';
export { createFakeSmsCallbackIntegration, signFakeSmsCallback } from './callback-security.js';
export type { FakeSmsCallbackIntegration } from './callback-security.js';
type Task = { controller: AbortController; settled: Promise<void> };
export class CallbackInbox {
  readonly #store: CallbackStore;
  readonly #timeout: number;
  readonly #cleanup: number;
  readonly #observer: NonNullable<CallbackOptions['observer']>;
  readonly #tasks = new Set<Task>();
  #closing = false;
  #ending: Promise<void> | undefined;
  #notifications = 0;
  #counts = {
    accepted: 0,
    replayed: 0,
    rejected: 0,
    conflicts: 0,
    webhookRejected: 0,
    waiterRejected: 0,
    telemetryFailures: 0,
    observerDropped: 0,
  };
  constructor(
    database: DatabaseSettings,
    integration: FakeSmsCallbackIntegration,
    accounts: SeededAccounts,
    options: CallbackOptions = {},
  ) {
    try {
      const fields = Object.keys(options);
      if (fields.some((k) => !['timeoutMs', 'cleanupMs', 'observer'].includes(k))) throw Error();
      options = record(options, fields) as CallbackOptions;
    } catch {
      throw new CallbackError('InvalidCommand');
    }
    this.#timeout = options.timeoutMs ?? 2000;
    this.#cleanup = options.cleanupMs ?? 2000;
    for (const [v, max] of [
      [this.#timeout, 5000],
      [this.#cleanup, 2000],
    ])
      if (!Number.isSafeInteger(v) || v! < 20 || v! > max!)
        throw new CallbackError('InvalidCommand');
    this.#observer =
      options.observer ??
      ((e) => console.info(JSON.stringify({ component: 'channel_callbacks', ...e })));
    if (typeof this.#observer !== 'function') throw new CallbackError('InvalidCommand');
    this.#store = new CallbackStore(database, integration, accounts);
  }
  #emit(event: CallbackEvent): void {
    if (this.#notifications >= 8) {
      this.#counts.observerDropped++;
      return;
    }
    try {
      const value = this.#observer(Object.freeze(event));
      if (value !== undefined) {
        this.#notifications++;
        void Promise.resolve(value)
          .catch(() => {
            this.#counts.telemetryFailures++;
          })
          .finally(() => {
            this.#notifications--;
          });
      }
    } catch {
      this.#counts.telemetryFailures++;
    }
  }
  #failure(error: unknown): CallbackError {
    const e = safeCallback(error);
    this.#counts.rejected++;
    if (e.code === 'WebhookRejected') this.#counts.webhookRejected++;
    if (e.code === 'IdentityConflict') this.#counts.conflicts++;
    this.#emit({
      event: 'rejected',
      code:
        e.code === 'IdentityConflict'
          ? 'identity_conflict'
          : e.code === 'WebhookRejected'
            ? 'webhook_rejected'
            : e.code === 'AcknowledgementUnknown'
              ? 'unknown'
              : e.code === 'Overloaded'
                ? 'overloaded'
                : 'rejected',
    });
    return e;
  }
  #run<T>(
    write: boolean,
    external: AbortSignal | undefined,
    action: (signal: AbortSignal) => Promise<T>,
  ): Promise<T> {
    if (external !== undefined)
      try {
        checkedSignal(external);
      } catch {
        throw this.#failure(new CallbackError('InvalidCommand'));
      }
    if (this.#closing) throw this.#failure(new CallbackError('Closed'));
    if (this.#tasks.size >= 4) throw this.#failure(new CallbackError('Overloaded'));
    const signal = external ?? new AbortController().signal;
    if (isAborted(signal)) throw this.#failure(new CallbackError('Unavailable'));
    const task: Task = { controller: new AbortController(), settled: Promise.resolve() },
      deadline = performance.now() + this.#timeout;
    this.#tasks.add(task);
    let timer: ReturnType<typeof setTimeout> | undefined,
      abort: (() => void) | undefined,
      abandoned = false;
    const fallback = write ? 'AcknowledgementUnknown' : 'Unavailable';
    const waiter = new Promise<never>((_, reject) => {
      abort = () => {
        if (abandoned) return;
        abandoned = true;
        task.controller.abort();
        this.#counts.waiterRejected++;
        this.#emit({ event: 'waiter_rejected', code: write ? 'unknown' : 'unavailable' });
        reject(new CallbackError(fallback));
      };
      timer = setTimeout(abort, this.#timeout);
      listenAbort(signal, abort);
    });
    const work = Promise.resolve().then(() => {
      if (task.controller.signal.aborted || performance.now() >= deadline)
        throw new CallbackError('Unavailable');
      return action(task.controller.signal);
    });
    task.settled = work.then(
      () => {
        this.#tasks.delete(task);
      },
      () => {
        this.#tasks.delete(task);
      },
    );
    return Promise.race([work, waiter])
      .then((value) => {
        if (isAborted(signal) || performance.now() >= deadline) throw new CallbackError(fallback);
        return value;
      })
      .catch((error) => {
        throw this.#failure(error);
      })
      .finally(() => {
        if (timer) clearTimeout(timer);
        if (abort) unlistenAbort(signal, abort);
      });
  }
  accept(raw: Uint8Array, headers: WebhookHeaders, signal?: AbortSignal): Promise<CallbackReceipt> {
    // Copy transport before the next await, including accessor-free headers.
    let bytes: Uint8Array, copy: WebhookHeaders;
    try {
      if (!(raw instanceof Uint8Array) || !raw.byteLength || raw.byteLength > 4096) throw Error();
      const d = record(headers, ['timestamp', 'signature']);
      bytes = Buffer.from(raw);
      copy = Object.freeze({ timestamp: d.timestamp as string, signature: d.signature as string });
    } catch {
      return Promise.reject(this.#failure(new CallbackError('WebhookRejected')));
    }
    return this.#run(true, signal, (own) =>
      this.#store.accept(bytes, copy, own).then((result) => {
        this.#counts[result.created ? 'accepted' : 'replayed']++;
        this.#emit({ event: result.created ? 'accepted' : 'replayed', code: 'ok' });
        return result.receipt;
      }),
    );
  }
  inspectAttempt(
    token: string,
    input: Readonly<{ outboundId: string; attemptId: string }>,
    signal?: AbortSignal,
  ): Promise<CallbackAttempt> {
    // Validate/copy the identifier object synchronously through strict descriptors.
    let copy: Readonly<{ outboundId: string; attemptId: string }>;
    try {
      const d = record(input, ['outboundId', 'attemptId']);
      copy = Object.freeze({
        outboundId: d.outboundId as string,
        attemptId: d.attemptId as string,
      });
    } catch {
      throw this.#failure(new CallbackError('InvalidCommand'));
    }
    return this.#run(false, signal, (own) => this.#store.inspectAttempt(token, copy, own));
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({
      ...this.#counts,
      active: this.#tasks.size,
      observerPending: this.#notifications,
      storageActive: this.#store.metrics().active!,
    });
  }
  async close(): Promise<void> {
    this.#closing = true;
    for (const t of this.#tasks) t.controller.abort();
    this.#ending ??= Promise.allSettled([...this.#tasks].map((t) => t.settled)).then(() =>
      this.#store.close(),
    );
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        this.#ending,
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new CallbackError('CleanupIncomplete')), this.#cleanup);
        }),
      ]);
      if (this.#tasks.size) throw new CallbackError('CleanupIncomplete');
      this.#emit({ event: 'closed', code: 'ok' });
    } catch (e) {
      void this.#ending.catch(() => {
        this.#ending = undefined;
      });
      throw safeCallback(e);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
