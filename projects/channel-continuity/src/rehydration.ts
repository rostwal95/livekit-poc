/** Opt-in read-only context assembly; a current grant admits disclosure, never execution. */
import { randomUUID } from 'node:crypto';
import type { ChannelInbox } from './postgres.js';
import type { ChannelGateway } from './gateway.js';
import { ChannelError } from './public-types.js';
import { rehydrationInbox } from './rehydration-access.js';
import { RehydrationStore, type Source } from './rehydration-store.js';
import { authenticateFakeSms, type FakeSmsIntegration, type WebhookHeaders } from './security.js';
import { nativeToken } from './native-types.js';
import { checkedSignal, isAborted, listenAbort, unlistenAbort } from './routing-types.js';
import {
  RehydrationError,
  rehydrationFields,
  rehydrationQuery,
  rehydrationContext,
  currentCase,
  type CurrentCasePort,
  type RehydrationContext,
  type RehydrationQuery,
} from './rehydration-types.js';
export * from './rehydration-types.js';
export { CurrentCaseHttpClient, referenceCurrentCase } from './rehydration-case-http.js';
export { RehydrationHttpServer } from './rehydration-http.js';
export type RehydrationEvent = Readonly<{
  event: 'completed' | 'rejected' | 'waiter_rejected' | 'closed';
  code:
    'known' | 'access_denied' | 'invalid_query' | 'context_unavailable' | 'overloaded' | 'closed';
}>;
export type RehydrationOptions = Readonly<{
  timeoutMs?: number;
  cleanupMs?: number;
  maxActive?: number;
  observer?: (event: RehydrationEvent) => void | Promise<void>;
}>;
type Task = { controller: AbortController; settled: Promise<void> };
function portMethod(cases: CurrentCasePort): CurrentCasePort['inspect'] {
  try {
    let object: object | null = cases;
    for (let depth = 0; object && depth < 4; depth++, object = Object.getPrototypeOf(object)) {
      const d = Object.getOwnPropertyDescriptor(object, 'inspect');
      if (d) {
        if (!('value' in d) || typeof d.value !== 'function') throw Error();
        return d.value.bind(cases) as CurrentCasePort['inspect'];
      }
    }
  } catch {
    /*fixed below*/
  }
  throw new RehydrationError('invalid_query');
}
export class ChannelRehydrator {
  readonly #store: RehydrationStore;
  readonly #inspect: CurrentCasePort['inspect'];
  readonly #tasks = new Set<Task>();
  readonly #timeout: number;
  readonly #cleanup: number;
  readonly #maximum: number;
  readonly #observer: RehydrationOptions['observer'];
  #closing = false;
  #notifications = 0;
  readonly #counts = {
    started: 0,
    known: 0,
    denied: 0,
    invalid: 0,
    unavailable: 0,
    overloaded: 0,
    waiterRejected: 0,
    telemetryFailures: 0,
    observerDropped: 0,
  };
  constructor(
    inbox: ChannelInbox | ChannelGateway,
    cases: CurrentCasePort,
    sms: FakeSmsIntegration,
    options: RehydrationOptions = {},
  ) {
    try {
      const access = rehydrationInbox(inbox);
      if (!access) throw Error();
      this.#store = new RehydrationStore(access, sms);
      this.#inspect = portMethod(cases);
      const names = Reflect.ownKeys(options);
      if (
        names.some(
          (k) =>
            typeof k !== 'string' ||
            !['timeoutMs', 'cleanupMs', 'maxActive', 'observer'].includes(k),
        )
      )
        throw Error();
      const o = rehydrationFields(options, names as string[]);
      this.#timeout = (o.timeoutMs ?? 3000) as number;
      this.#cleanup = (o.cleanupMs ?? 5000) as number;
      this.#maximum = (o.maxActive ?? 2) as number;
      this.#observer = o.observer as RehydrationOptions['observer'];
      if (
        !Number.isInteger(this.#timeout) ||
        this.#timeout < 20 ||
        this.#timeout > 5000 ||
        !Number.isInteger(this.#cleanup) ||
        this.#cleanup < 20 ||
        this.#cleanup > 5000 ||
        !Number.isInteger(this.#maximum) ||
        this.#maximum < 1 ||
        this.#maximum > 2 ||
        (this.#observer !== undefined && typeof this.#observer !== 'function')
      )
        throw Error();
    } catch {
      throw new RehydrationError('invalid_query');
    }
  }
  metrics() {
    return Object.freeze({
      ...this.#counts,
      active: this.#tasks.size,
      observerPending: this.#notifications,
    });
  }
  #emit(event: RehydrationEvent) {
    if (!this.#observer) return;
    if (this.#notifications >= 8) {
      this.#counts.observerDropped++;
      return;
    }
    try {
      const value = this.#observer(Object.freeze({ ...event }));
      if (value && typeof value.then === 'function') {
        this.#notifications++;
        void Promise.resolve(value)
          .then(
            () => undefined,
            () => {
              this.#counts.telemetryFailures++;
            },
          )
          .finally(() => {
            this.#notifications--;
          });
      }
    } catch {
      this.#counts.telemetryFailures++;
    }
  }
  native(
    bindingBearer: string,
    query?: RehydrationQuery,
    signal?: AbortSignal,
  ): Promise<RehydrationContext> {
    let bearer: string;
    try {
      bearer = nativeToken(bindingBearer);
    } catch {
      return Promise.reject(new RehydrationError('access_denied'));
    }
    return this.#run(Object.freeze({ kind: 'native', bearer }), rehydrationQuery(query), signal);
  }
  sms(
    raw: Uint8Array,
    headers: WebhookHeaders,
    query?: RehydrationQuery,
    signal?: AbortSignal,
  ): Promise<RehydrationContext> {
    let source: Source;
    try {
      if (!(raw instanceof Uint8Array) || raw.byteLength < 1 || raw.byteLength > 32768)
        throw Error();
      const h = rehydrationFields(headers, ['timestamp', 'signature']);
      source = Object.freeze({
        kind: 'sms',
        raw: Buffer.from(raw),
        headers: Object.freeze({
          timestamp: h.timestamp as string,
          signature: h.signature as string,
        }),
      });
      authenticateFakeSms(
        source.raw,
        source.headers,
        this.#store.sms,
        Math.floor(Date.now() / 1000),
      );
    } catch {
      return Promise.reject(new RehydrationError('access_denied'));
    }
    return this.#run(source, rehydrationQuery(query), signal);
  }
  async #run(
    source: Source,
    query: RehydrationQuery,
    external?: AbortSignal,
  ): Promise<RehydrationContext> {
    try {
      if (external !== undefined) checkedSignal(external);
    } catch {
      throw new RehydrationError('invalid_query');
    }
    if (this.#closing) throw new RehydrationError('closed');
    if (this.#tasks.size >= this.#maximum) {
      this.#counts.overloaded++;
      throw new RehydrationError('overloaded');
    }
    if (external !== undefined && isAborted(external)) throw new RehydrationError();
    const controller = new AbortController(),
      deadline = performance.now() + this.#timeout,
      task: Task = { controller, settled: Promise.resolve() };
    this.#tasks.add(task);
    this.#counts.started++;
    const check = () => {
      if (this.#closing || controller.signal.aborted || performance.now() >= deadline)
        throw new RehydrationError(this.#closing ? 'closed' : 'context_unavailable');
    };
    let timer: ReturnType<typeof setTimeout> | undefined, onAbort: (() => void) | undefined;
    const rejected = new Promise<never>((_, reject) => {
      const fail = () => {
        this.#counts.waiterRejected++;
        controller.abort();
        this.#emit({
          event: 'waiter_rejected',
          code: this.#closing ? 'closed' : 'context_unavailable',
        });
        reject(new RehydrationError(this.#closing ? 'closed' : 'context_unavailable'));
      };
      timer = setTimeout(fail, this.#timeout);
      if (external !== undefined) {
        onAbort = fail;
        listenAbort(external, onAbort);
      }
    });
    const work = Promise.resolve().then(async () => {
      try {
        check();
        const snapshot = await this.#store.snapshot(source, query);
        check();
        const authority = currentCase(
            await this.#inspect(snapshot.ref, controller.signal),
            snapshot.ref,
          ),
          caseObservedAt = new Date().toISOString();
        check();
        const disclosureAdmittedAt = await this.#store.disclose(source, snapshot);
        check();
        const result = rehydrationContext(
          {
            schemaVersion: 1,
            contextId: randomUUID(),
            access: snapshot.access,
            case: authority,
            history: snapshot.history,
            work: snapshot.work,
            responses: snapshot.responses,
            replies: snapshot.replies,
            observed: {
              p2ObservedAt: snapshot.p2ObservedAt,
              caseObservedAt,
              disclosureAdmittedAt,
              atomic: false,
            },
          },
          snapshot.ref,
        );
        check();
        this.#emit({ event: 'completed', code: 'known' });
        check();
        this.#counts.known++;
        return result;
      } catch (error) {
        const safe =
          error instanceof RehydrationError
            ? error
            : new RehydrationError(
                error instanceof ChannelError &&
                  [
                    'AccessDenied',
                    'AssociationRequired',
                    'AssociationRejected',
                    'NotFound',
                  ].includes(error.code)
                  ? 'access_denied'
                  : error instanceof ChannelError && error.code === 'Overloaded'
                    ? 'overloaded'
                    : 'context_unavailable',
              );
        this.#counts[
          safe.code === 'access_denied'
            ? 'denied'
            : safe.code === 'invalid_query'
              ? 'invalid'
              : safe.code === 'overloaded'
                ? 'overloaded'
                : 'unavailable'
        ]++;
        this.#emit({ event: 'rejected', code: safe.code });
        throw safe;
      }
    });
    task.settled = work
      .then(
        () => undefined,
        () => undefined,
      )
      .finally(() => {
        this.#tasks.delete(task);
        if (timer) clearTimeout(timer);
        if (external !== undefined && onAbort) unlistenAbort(external, onAbort);
      });
    const result = await Promise.race([work, rejected]);
    check();
    if (external !== undefined && isAborted(external)) throw new RehydrationError();
    return result;
  }
  async close(): Promise<void> {
    this.#closing = true;
    for (const task of this.#tasks) task.controller.abort();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all([...this.#tasks].map((t) => t.settled)),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new RehydrationError()), this.#cleanup);
        }),
      ]);
      if (this.#tasks.size) throw new RehydrationError();
      this.#emit({ event: 'closed', code: 'closed' });
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
