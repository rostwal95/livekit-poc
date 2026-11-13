/** Explicit opaque receiver/read facades over the existing outbox owner; imports start no I/O. */
import { checkedSignal, isAborted, listenAbort, unlistenAbort } from './routing-types.js';
import { rehydrationInbox } from './rehydration-access.js';
import { resultOutbox } from './result-receiver-access.js';
import type { ChannelInbox } from './postgres.js';
import type { ChannelGateway } from './gateway.js';
import type { ChannelOutbox } from './outbox.js';
import type { OutboxStore } from './outbox-store.js';
import type { CurrentCasePort } from './rehydration-types.js';
import {
  ResultReceiverError,
  type P1ResultIntent,
  type P1ResultReceipt,
  type ResultRouteBinding,
  type ResultReceiverBinding,
  type ResultReceiverConfiguration,
  type ResultReaderConfiguration,
  type ResultNativeView,
  type ResultReceiverOptions,
  type ResultReceiverEvent,
} from './result-receiver-types.js';
import {
  resultFields,
  resultUuid,
  resultIntent,
  resultRoute,
  receiverToken,
  safeResultError,
} from './result-receiver-codec.js';
export * from './result-receiver-types.js';
export {
  parseResultIntent,
  encodeResultIntent,
  resultReceipt,
  matchResultReceipt,
} from './result-receiver-codec.js';
type Owned = { controller: AbortController; settled: Promise<void> };
class ResultOwner {
  readonly #tasks = new Set<Owned>();
  readonly #notices = new Set<Promise<void>>();
  readonly #maximum: number;
  readonly #timeout: number;
  readonly #cleanup: number;
  readonly #observer: ResultReceiverOptions['observer'];
  #closing = false;
  #counts = {
    started: 0,
    completed: 0,
    rejected: 0,
    waiterRejected: 0,
    observerFailures: 0,
    observerDropped: 0,
  };
  constructor(options: ResultReceiverOptions, reader = false) {
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new ResultReceiverError('InvalidCommand');
    const keys = Reflect.ownKeys(options);
    if (
      keys.some(
        (k) =>
          typeof k !== 'string' || !['maxActive', 'timeoutMs', 'cleanupMs', 'observer'].includes(k),
      )
    )
      throw new ResultReceiverError('InvalidCommand');
    const v = resultFields(options, keys as string[]);
    this.#maximum = (v.maxActive ?? (reader ? 1 : 2)) as number;
    this.#timeout = (v.timeoutMs ?? (reader ? 3000 : 2000)) as number;
    this.#cleanup = (v.cleanupMs ?? 2000) as number;
    this.#observer = v.observer as ResultReceiverOptions['observer'];
    if (
      !Number.isSafeInteger(this.#maximum) ||
      this.#maximum < 1 ||
      this.#maximum > (reader ? 1 : 2) ||
      !Number.isSafeInteger(this.#timeout) ||
      this.#timeout < 20 ||
      this.#timeout > 5000 ||
      !Number.isSafeInteger(this.#cleanup) ||
      this.#cleanup < 20 ||
      this.#cleanup > 2000 ||
      (this.#observer !== undefined && typeof this.#observer !== 'function')
    )
      throw new ResultReceiverError('InvalidCommand');
  }
  metrics() {
    return Object.freeze({
      ...this.#counts,
      active: this.#tasks.size,
      observerPending: this.#notices.size,
      closing: this.#closing,
    });
  }
  #emit(event: ResultReceiverEvent): void {
    if (!this.#observer) return;
    if (this.#notices.size >= 8) {
      this.#counts.observerDropped++;
      return;
    }
    // Reserve before invoking an arbitrary observer (including reentrant close/then access).
    let finish!: () => void;
    const retained = new Promise<void>((resolve) => {
      finish = resolve;
    });
    this.#notices.add(retained);
    try {
      const value = this.#observer(Object.freeze({ ...event }));
      Promise.resolve(value)
        .then(
          () => undefined,
          () => {
            this.#counts.observerFailures++;
          },
        )
        .finally(() => {
          this.#notices.delete(retained);
          finish();
        });
    } catch {
      this.#counts.observerFailures++;
      this.#notices.delete(retained);
      finish();
    }
  }
  protected run<T>(
    write: boolean,
    code: 'accepted' | 'found' | 'read',
    work: (signal: AbortSignal) => Promise<T>,
    external?: AbortSignal,
  ): Promise<T> {
    if (external !== undefined) {
      try {
        checkedSignal(external);
      } catch {
        return Promise.reject(new ResultReceiverError('InvalidCommand'));
      }
    }
    if (this.#closing) return Promise.reject(new ResultReceiverError('Closed'));
    if (this.#tasks.size >= this.#maximum)
      return Promise.reject(new ResultReceiverError('Overloaded'));
    if (external !== undefined && isAborted(external))
      return Promise.reject(new ResultReceiverError('Unavailable'));
    const controller = new AbortController(),
      owned: Owned = { controller, settled: Promise.resolve() };
    this.#tasks.add(owned);
    this.#counts.started++;
    let timer: ReturnType<typeof setTimeout> | undefined, abort: (() => void) | undefined;
    const unknown = () => new ResultReceiverError(write ? 'AcknowledgementUnknown' : 'Unavailable');
    const early = new Promise<never>((_resolve, reject) => {
      const fail = () => {
        this.#counts.waiterRejected++;
        controller.abort();
        this.#emit({ event: 'waiter_rejected', code: 'unavailable' });
        reject(unknown());
      };
      timer = setTimeout(fail, this.#timeout);
      if (external !== undefined) {
        abort = fail;
        listenAbort(external, abort);
      }
    });
    const actual = Promise.resolve()
      .then(() => work(controller.signal))
      .then(
        (value) => {
          this.#counts.completed++;
          this.#emit({ event: 'completed', code: value === null ? 'absent' : code });
          return value;
        },
        (error) => {
          this.#counts.rejected++;
          this.#emit({ event: 'rejected', code: 'rejected' });
          throw safeResultError(error);
        },
      );
    owned.settled = actual
      .then(
        () => undefined,
        () => undefined,
      )
      .finally(() => {
        this.#tasks.delete(owned);
        if (timer) clearTimeout(timer);
        if (external !== undefined && abort) unlistenAbort(external, abort);
      });
    return Promise.race([actual, early]).then((value) => {
      if (controller.signal.aborted) throw unknown();
      return value;
    });
  }
  async close(): Promise<void> {
    this.#closing = true;
    for (const owned of this.#tasks) owned.controller.abort();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all([...this.#tasks].map((t) => t.settled).concat([...this.#notices])),
        new Promise<never>((_r, reject) => {
          timer = setTimeout(
            () => reject(new ResultReceiverError('CleanupIncomplete')),
            this.#cleanup,
          );
        }),
      ]);
      if (this.#tasks.size || this.#notices.size)
        throw new ResultReceiverError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
function routes(values: unknown): readonly ResultRouteBinding[] {
  if (
    !Array.isArray(values) ||
    Object.getPrototypeOf(values) !== Array.prototype ||
    values.length < 1 ||
    values.length > 64 ||
    Reflect.ownKeys(values).length !== values.length + 1
  )
    throw new ResultReceiverError('InvalidCommand');
  const copy: ResultRouteBinding[] = [];
  for (let n = 0; n < values.length; n++) {
    const d = Object.getOwnPropertyDescriptor(values, String(n));
    if (!d || !('value' in d) || !d.enumerable) throw new ResultReceiverError('InvalidCommand');
    copy.push(resultRoute(d.value));
  }
  if (
    new Set(copy.map((r) => JSON.stringify([r.scope, r.caseId, r.conversationId]))).size !==
      copy.length ||
    new Set(copy.map((r) => JSON.stringify([r.scope, r.recipientId]))).size !== copy.length
  )
    throw new ResultReceiverError('InvalidCommand');
  return Object.freeze(copy);
}
export class ChannelResultReceiver extends ResultOwner {
  readonly #receiverId: string;
  get receiverId(): string {
    return this.#receiverId;
  }
  readonly #store: OutboxStore;
  readonly #bindings: readonly ResultReceiverBinding[];
  constructor(
    outbox: ChannelOutbox,
    configuration: ResultReceiverConfiguration,
    options: ResultReceiverOptions = {},
  ) {
    super(options);
    const c = resultFields(configuration, ['receiverId', 'bindings']);
    this.#receiverId = resultUuid(c.receiverId);
    const store = resultOutbox(outbox);
    if (!store) throw new ResultReceiverError('InvalidCommand');
    this.#store = store;
    if (
      !Array.isArray(c.bindings) ||
      Object.getPrototypeOf(c.bindings) !== Array.prototype ||
      c.bindings.length < 1 ||
      c.bindings.length > 64 ||
      Reflect.ownKeys(c.bindings).length !== c.bindings.length + 1
    )
      throw new ResultReceiverError('InvalidCommand');
    const bound: ResultReceiverBinding[] = [];
    for (let n = 0; n < c.bindings.length; n++) {
      const d = Object.getOwnPropertyDescriptor(c.bindings, String(n));
      if (!d || !('value' in d) || !d.enumerable) throw new ResultReceiverError('InvalidCommand');
      const b = resultFields(d.value, [
        'scope',
        'caseId',
        'conversationId',
        'recipientId',
        'publisherToken',
      ]);
      bound.push(
        Object.freeze({
          ...resultRoute({
            scope: b.scope,
            caseId: b.caseId,
            conversationId: b.conversationId,
            recipientId: b.recipientId,
          }),
          publisherToken: receiverToken(b.publisherToken),
        }),
      );
    }
    routes(
      bound.map((b) => ({
        scope: b.scope,
        caseId: b.caseId,
        conversationId: b.conversationId,
        recipientId: b.recipientId,
      })),
    );
    if (new Set(bound.map((b) => b.publisherToken)).size !== bound.length)
      throw new ResultReceiverError('InvalidCommand');
    this.#bindings = Object.freeze(bound);
  }
  #binding(token: string): ResultReceiverBinding {
    receiverToken(token);
    const b = this.#bindings.find((b) => b.publisherToken === token);
    if (!b) throw new ResultReceiverError('AccessDenied');
    return b;
  }
  accept(
    publisherToken: string,
    value: P1ResultIntent,
    signal?: AbortSignal,
  ): Promise<P1ResultReceipt> {
    const intent = resultIntent(value),
      b = this.#binding(publisherToken);
    return this.run(
      true,
      'accepted',
      (s) => this.#store.acceptResult(publisherToken, this.receiverId, b, intent, s),
      signal,
    );
  }
  find(
    publisherToken: string,
    value: P1ResultIntent,
    signal?: AbortSignal,
  ): Promise<P1ResultReceipt | null> {
    const intent = resultIntent(value),
      b = this.#binding(publisherToken);
    return this.run(
      false,
      'found',
      (s) => this.#store.findResult(publisherToken, this.receiverId, b, intent, s),
      signal,
    );
  }
}
function currentCasePort(cases: CurrentCasePort): CurrentCasePort {
  let object: object | null = cases;
  for (let depth = 0; object && depth < 4; depth++, object = Object.getPrototypeOf(object)) {
    const d = Object.getOwnPropertyDescriptor(object, 'inspect');
    if (d) {
      if (!('value' in d) || typeof d.value !== 'function')
        throw new ResultReceiverError('InvalidCommand');
      return Object.freeze({
        inspect: Function.prototype.bind.call(d.value, cases) as CurrentCasePort['inspect'],
      });
    }
  }
  throw new ResultReceiverError('InvalidCommand');
}
export class ChannelResultReader extends ResultOwner {
  readonly #store: OutboxStore;
  readonly #access: NonNullable<ReturnType<typeof rehydrationInbox>>;
  readonly #cases: CurrentCasePort;
  readonly #routes: readonly ResultRouteBinding[];
  readonly #receiverId: string;
  constructor(
    outbox: ChannelOutbox,
    inbox: ChannelInbox | ChannelGateway,
    cases: CurrentCasePort,
    configuration: ResultReaderConfiguration,
    options: ResultReceiverOptions = {},
  ) {
    super(options, true);
    const c = resultFields(configuration, ['receiverId', 'bindings']);
    this.#receiverId = resultUuid(c.receiverId);
    this.#routes = routes(c.bindings);
    const store = resultOutbox(outbox),
      access = rehydrationInbox(inbox);
    if (!store || !access || access.databaseIdentity !== store.databaseIdentity)
      throw new ResultReceiverError('InvalidCommand');
    this.#store = store;
    this.#access = access;
    this.#cases = currentCasePort(cases);
  }
  native(
    bindingBearer: string,
    deliveryId: string,
    signal?: AbortSignal,
  ): Promise<ResultNativeView | null> {
    const bearer = receiverToken(bindingBearer),
      id = resultUuid(deliveryId);
    return this.run(
      false,
      'read',
      (s) =>
        this.#store.readNativeResult(
          this.#receiverId,
          this.#routes,
          this.#access,
          this.#cases,
          bearer,
          id,
          s,
        ),
      signal,
    );
  }
}
