/** Explicit bounded routing of an authenticated accepted investigation-revision command. */
import {
  RoutingError,
  acceptedMessage,
  allowedReferences,
  decodeRevisionCommand,
  reference,
  revisedSnapshot,
  snapshot,
  safeRoutingCode,
  checkedSignal,
  isAborted,
  listenAbort,
  unlistenAbort,
  type AcceptedInputPort,
  type CaseAuthorityPort,
  type CaseReference,
  type CaseSnapshot,
  type RouterOptions,
  type RoutingEvent,
  type RoutingIdentity,
  type RoutingResult,
} from './routing-types.js';
export { RoutingError, encodeRevisionCommand, decodeRevisionCommand } from './routing-types.js';
export type {
  AcceptedInputPort,
  CaseAuthorityPort,
  CaseReference,
  CaseRevision,
  CaseSnapshot,
  InvestigationRequest,
  RevisionCommand,
  RouterOptions,
  RoutingCode,
  RoutingEvent,
  RoutingIdentity,
  RoutingResult,
} from './routing-types.js';
export { CaseAuthorityHttpClient } from './case-http.js';
export type { CaseAuthorityEndpoint, CaseAuthorityHttpOptions } from './case-http.js';

type Task = {
  controller: AbortController;
  settled: Promise<void>;
  writing: boolean;
  identity?: RoutingIdentity;
};
export class RevisionRouter {
  readonly #input: AcceptedInputPort;
  readonly #cases: CaseAuthorityPort;
  readonly #allowed: readonly CaseReference[];
  readonly #tasks = new Set<Task>();
  readonly #timeout: number;
  readonly #cleanup: number;
  readonly #maximum: number;
  readonly #observer: NonNullable<RouterOptions['observer']>;
  #closing = false;
  #notifications = 0;
  #counts = {
    started: 0,
    revised: 0,
    unchanged: 0,
    conflicts: 0,
    clarification: 0,
    unknown: 0,
    unavailable: 0,
    waiterRejected: 0,
    telemetryFailures: 0,
    observerDropped: 0,
  };
  constructor(
    input: AcceptedInputPort,
    cases: CaseAuthorityPort,
    allowedCases: readonly CaseReference[],
    options: RouterOptions = {},
  ) {
    if (
      !input ||
      typeof input.inspect !== 'function' ||
      !cases ||
      typeof cases.inspect !== 'function' ||
      typeof cases.revise !== 'function'
    )
      throw new RoutingError('InvalidCommand');
    this.#input = input;
    this.#cases = cases;
    this.#allowed = allowedReferences(allowedCases);
    const keys = Object.keys(options);
    if (keys.some((key) => !['maxActive', 'timeoutMs', 'cleanupMs', 'observer'].includes(key)))
      throw new RoutingError('InvalidCommand');
    const maximum = options.maxActive ?? 2,
      timeout = options.timeoutMs ?? 2000,
      cleanup = options.cleanupMs ?? 1000;
    if (
      !Number.isInteger(maximum) ||
      maximum < 1 ||
      maximum > 4 ||
      !Number.isInteger(timeout) ||
      timeout < 20 ||
      timeout > 5000 ||
      !Number.isInteger(cleanup) ||
      cleanup < 20 ||
      cleanup > 2000 ||
      (options.observer !== undefined && typeof options.observer !== 'function')
    )
      throw new RoutingError('InvalidCommand');
    this.#maximum = maximum;
    this.#timeout = timeout;
    this.#cleanup = cleanup;
    this.#observer =
      options.observer ??
      ((event) => {
        console.info(JSON.stringify({ component: 'case_routing', ...event }));
      });
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({
      ...this.#counts,
      active: this.#tasks.size,
      observerPending: this.#notifications,
    });
  }
  #emit(event: RoutingEvent): void {
    if (this.#notifications >= 8) {
      this.#counts.observerDropped++;
      return;
    }
    try {
      const emitted = this.#observer(Object.freeze(event));
      if (emitted !== undefined) {
        this.#notifications++;
        void Promise.resolve(emitted)
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
  route(accountToken: string, receiptId: string, signal?: AbortSignal): Promise<RoutingResult> {
    return this.#start(accountToken, receiptId, false, signal) as Promise<RoutingResult>;
  }
  inspect(accountToken: string, receiptId: string, signal?: AbortSignal): Promise<CaseSnapshot> {
    return this.#start(accountToken, receiptId, true, signal) as Promise<CaseSnapshot>;
  }
  #start(
    accountToken: string,
    receiptId: string,
    inspect: boolean,
    external?: AbortSignal,
  ): Promise<RoutingResult | CaseSnapshot> {
    if (external !== undefined) checkedSignal(external);
    if (this.#closing) return Promise.reject(new RoutingError('Closed'));
    if (this.#tasks.size >= this.#maximum) return Promise.reject(new RoutingError('Overloaded'));
    if (external !== undefined && isAborted(external))
      return Promise.reject(new RoutingError('Unavailable'));
    const controller = new AbortController(),
      deadline = performance.now() + this.#timeout;
    const task: Task = { controller, settled: Promise.resolve(), writing: false };
    this.#tasks.add(task);
    this.#counts.started++;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let abandoned = false;
    let onAbort: (() => void) | undefined;
    const rejection = new Promise<RoutingResult | CaseSnapshot>((resolve, reject) => {
      onAbort = () => {
        if (abandoned) return;
        abandoned = true;
        controller.abort();
        this.#counts.waiterRejected++;
        this.#emit({
          event: 'waiter_rejected',
          code: task.writing ? 'outcome_unknown' : 'unavailable',
        });
        if (task.writing && task.identity)
          resolve(Object.freeze({ ...task.identity, status: 'outcome_unknown' }));
        else reject(new RoutingError('Unavailable'));
      };
      timer = setTimeout(onAbort, this.#timeout);
      if (external) listenAbort(external, onAbort);
    });
    const work = Promise.resolve().then(async () => {
      const check = () => {
        if (controller.signal.aborted || performance.now() >= deadline)
          throw new RoutingError(task.writing ? 'OutcomeUnknown' : 'Unavailable');
      };
      let outcome: RoutingResult | CaseSnapshot;
      try {
        check();
        let value: unknown;
        try {
          value = await this.#input.inspect(accountToken, receiptId);
        } catch {
          throw new RoutingError('AccessDenied');
        }
        check();
        const message = acceptedMessage(value, receiptId, this.#allowed),
          event = message.event;
        if (event.type !== 'text.received' || !event.accountScope || !event.caseId)
          throw new RoutingError('InvalidAdapterResponse');
        const ref = reference({ scope: event.accountScope, caseId: event.caseId });
        task.identity = Object.freeze({
          receiptId,
          operationKey: message.operationKey,
          eventId: event.eventId,
          messageId: event.messageId,
          channel: event.channel,
        });
        if (inspect) {
          outcome = snapshot(await this.#cases.inspect(ref, controller.signal), ref);
          check();
          return outcome;
        }
        let command;
        try {
          command = decodeRevisionCommand(event.body);
        } catch {
          this.#counts.clarification++;
          this.#emit({ event: 'completed', code: 'clarification_required' });
          check();
          return Object.freeze({ ...task.identity, status: 'clarification_required' as const });
        }
        if (
          event.expectedCaseRevision !== undefined &&
          String(event.expectedCaseRevision) !== command.expectedRevision
        ) {
          this.#counts.clarification++;
          this.#emit({ event: 'completed', code: 'clarification_required' });
          check();
          return Object.freeze({ ...task.identity, status: 'clarification_required' as const });
        }
        check();
        const proposed = Object.freeze({
          ...ref,
          expectedRevision: command.expectedRevision,
          request: command.request,
        });
        task.writing = true;
        const updated = revisedSnapshot(
          await this.#cases.revise(proposed, controller.signal),
          proposed,
        );
        const status = updated.revision === command.expectedRevision ? 'unchanged' : 'revised';
        this.#counts[status]++;
        outcome = Object.freeze({ ...task.identity, status, case: updated });
      } catch (error) {
        const code = safeRoutingCode(error) ?? (task.writing ? 'OutcomeUnknown' : 'Unavailable');
        if (task.writing && task.identity && code === 'RevisionConflict') {
          this.#counts.conflicts++;
          outcome = Object.freeze({ ...task.identity, status: 'revision_conflict' });
        } else if (
          task.writing &&
          task.identity &&
          code !== 'AccessDenied' &&
          code !== 'Overloaded' &&
          code !== 'InvalidCommand'
        ) {
          this.#counts.unknown++;
          outcome = Object.freeze({ ...task.identity, status: 'outcome_unknown' });
        } else {
          this.#counts.unavailable++;
          throw new RoutingError(
            code === 'AccessDenied'
              ? 'AccessDenied'
              : code === 'Overloaded'
                ? 'Overloaded'
                : 'Unavailable',
          );
        }
      }
      this.#emit({ event: 'completed', code: (outcome as RoutingResult).status });
      if (controller.signal.aborted || performance.now() >= deadline) {
        if (task.writing && task.identity)
          return Object.freeze({ ...task.identity, status: 'outcome_unknown' as const });
        throw new RoutingError('Unavailable');
      }
      return outcome;
    });
    task.settled = work
      .then(
        () => undefined,
        () => undefined,
      )
      .finally(() => {
        this.#tasks.delete(task);
        if (timer) clearTimeout(timer);
        if (onAbort && external) unlistenAbort(external, onAbort);
      });
    return Promise.race([work, rejection]).then((value) => {
      if ((external !== undefined && isAborted(external)) || performance.now() >= deadline) {
        if (task.writing && task.identity)
          return Object.freeze({ ...task.identity, status: 'outcome_unknown' as const });
        throw new RoutingError('Unavailable');
      }
      return value;
    });
  }
  async close(): Promise<void> {
    this.#closing = true;
    for (const task of this.#tasks) task.controller.abort();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all([...this.#tasks].map((task) => task.settled)),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new RoutingError('CleanupIncomplete')), this.#cleanup);
        }),
      ]);
      if (this.#tasks.size) throw new RoutingError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
