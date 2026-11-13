/** Explicit routing of original linked user consent to an exact atomic case authority. */
import { ChannelError } from './public-types.js';
import {
  acceptedMessage,
  allowedReferences,
  checkedSignal,
  isAborted,
  listenAbort,
  unlistenAbort,
  reference,
  type CaseReference,
  type RoutingIdentity,
} from './routing-types.js';
import {
  ConfirmationError,
  safeConfirmationCode,
  linkedAnswer,
  storedPrompt,
  confirmationReceipt,
  type ConfirmationAuthorityPort,
  type ConfirmationInputPort,
  type ConfirmationPromptPort,
  type ConfirmationOptions,
  type ConfirmationEvent,
  type ConfirmationResult,
} from './confirmation-types.js';
export { ConfirmationError, encodeConfirmation, quoteDigest } from './confirmation-types.js';
export type {
  ConfirmationCode,
  ConfirmationPrompt,
  StoredPrompt,
  PromptReference,
  ConfirmationInputPort,
  ConfirmationPromptPort,
  ExactConfirmation,
  ConfirmationReceipt,
  ConfirmationAuthorityPort,
  ConfirmationResult,
  StructuredConfirmation,
  ConfirmationOptions,
  ConfirmationEvent,
} from './confirmation-types.js';
export { ConfirmationHttpClient } from './confirmation-http.js';
type Task = {
  controller: AbortController;
  settled: Promise<void>;
  writing: boolean;
  identity?: RoutingIdentity;
};
export class ConfirmationRouter {
  readonly #input: ConfirmationInputPort;
  readonly #prompts: ConfirmationPromptPort;
  readonly #authority: ConfirmationAuthorityPort;
  readonly #allowed: readonly CaseReference[];
  readonly #tasks = new Set<Task>();
  readonly #timeout: number;
  readonly #cleanup: number;
  readonly #maximum: number;
  readonly #observer: NonNullable<ConfirmationOptions['observer']>;
  #closing = false;
  #notifications = 0;
  #counts = {
    started: 0,
    accepted: 0,
    clarification: 0,
    unknown: 0,
    rejected: 0,
    waiterRejected: 0,
    telemetryFailures: 0,
    observerDropped: 0,
  };
  constructor(
    input: ConfirmationInputPort,
    prompts: ConfirmationPromptPort,
    authority: ConfirmationAuthorityPort,
    allowedCases: readonly CaseReference[],
    options: ConfirmationOptions = {},
  ) {
    if (
      !input ||
      typeof input.inspect !== 'function' ||
      typeof input.inspectForConfirmation !== 'function' ||
      !prompts ||
      typeof prompts.find !== 'function' ||
      !authority ||
      typeof authority.confirm !== 'function'
    )
      throw new ConfirmationError('InvalidCommand');
    this.#input = input;
    this.#prompts = prompts;
    this.#authority = authority;
    this.#allowed = allowedReferences(allowedCases);
    if (
      Object.keys(options).some(
        (key) => !['maxActive', 'timeoutMs', 'cleanupMs', 'observer'].includes(key),
      )
    )
      throw new ConfirmationError('InvalidCommand');
    this.#maximum = options.maxActive ?? 2;
    this.#timeout = options.timeoutMs ?? 2000;
    this.#cleanup = options.cleanupMs ?? 1000;
    this.#observer =
      options.observer ??
      ((event) => console.info(JSON.stringify({ component: 'confirmation_routing', ...event })));
    if (
      !Number.isInteger(this.#maximum) ||
      this.#maximum < 1 ||
      this.#maximum > 4 ||
      !Number.isInteger(this.#timeout) ||
      this.#timeout < 20 ||
      this.#timeout > 5000 ||
      !Number.isInteger(this.#cleanup) ||
      this.#cleanup < 20 ||
      this.#cleanup > 2000 ||
      typeof this.#observer !== 'function'
    )
      throw new ConfirmationError('InvalidCommand');
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({
      ...this.#counts,
      active: this.#tasks.size,
      observerPending: this.#notifications,
    });
  }
  #emit(event: ConfirmationEvent): void {
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
  confirm(
    accountToken: string,
    receiptId: string,
    external?: AbortSignal,
  ): Promise<ConfirmationResult> {
    try {
      if (external !== undefined) checkedSignal(external);
    } catch {
      throw new ConfirmationError('InvalidCommand');
    }
    if (this.#closing) return Promise.reject(new ConfirmationError('Closed'));
    if (this.#tasks.size >= this.#maximum)
      return Promise.reject(new ConfirmationError('Overloaded'));
    if (external && isAborted(external))
      return Promise.reject(new ConfirmationError('Unavailable'));
    const controller = new AbortController(),
      deadline = performance.now() + this.#timeout;
    const task: Task = { controller, settled: Promise.resolve(), writing: false };
    this.#tasks.add(task);
    this.#counts.started++;
    let timer: ReturnType<typeof setTimeout> | undefined,
      onAbort: (() => void) | undefined,
      abandoned = false;
    const timeout = new Promise<ConfirmationResult>((resolve, reject) => {
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
        else reject(new ConfirmationError('Unavailable'));
      };
      timer = setTimeout(onAbort, this.#timeout);
      if (external) listenAbort(external, onAbort);
    });
    const work = Promise.resolve().then(async () => {
      const check = () => {
        if (controller.signal.aborted || performance.now() >= deadline)
          throw new ConfirmationError(task.writing ? 'OutcomeUnknown' : 'Unavailable');
      };
      let outcome: ConfirmationResult;
      try {
        check();
        const read = async (current: boolean): Promise<unknown> => {
          try {
            return await (current
              ? this.#input.inspectForConfirmation(accountToken, receiptId)
              : this.#input.inspect(accountToken, receiptId));
          } catch (error) {
            const own = safeConfirmationCode(error);
            const d =
              error instanceof ChannelError
                ? Object.getOwnPropertyDescriptor(error, 'code')
                : undefined;
            const code =
              own ??
              (d && 'value' in d && d.value === 'Overloaded'
                ? 'Overloaded'
                : d &&
                    'value' in d &&
                    [
                      'AccessDenied',
                      'NotFound',
                      'AssociationRequired',
                      'AssociationRejected',
                    ].includes(d.value)
                  ? 'AccessDenied'
                  : 'Unavailable');
            throw new ConfirmationError(code);
          }
        };
        const raw = await read(false);
        check();
        const message = acceptedMessage(raw, receiptId, this.#allowed),
          event = message.event;
        const fingerprint = (value: typeof message) =>
          JSON.stringify({
            receipt: { ...value.receipt },
            event: value.event,
            operationKey: value.operationKey,
            associationVersion: value.associationVersion,
          });
        const originalFingerprint = fingerprint(message);
        if (event.type !== 'text.received' || !event.accountScope || !event.caseId)
          throw new ConfirmationError('InvalidAdapterResponse');
        task.identity = Object.freeze({
          receiptId,
          operationKey: message.operationKey,
          eventId: event.eventId,
          messageId: event.messageId,
          channel: event.channel,
        });
        const answer = linkedAnswer(message),
          ref = Object.freeze({
            ...reference({ scope: event.accountScope, caseId: event.caseId }),
            conversationId: event.conversationId,
            responseId: answer.responseId,
          });
        const observed = await this.#prompts.find(ref, controller.signal);
        check();
        if (observed === null) throw new ConfirmationError('ClarificationRequired');
        const bound = storedPrompt(observed, ref);
        if (
          (answer.expectedRevision !== undefined && answer.expectedRevision !== bound.revision) ||
          (answer.quoteDigest !== undefined && answer.quoteDigest !== bound.quoteDigest)
        )
          throw new ConfirmationError('ClarificationRequired');
        const command = Object.freeze({
          scope: ref.scope,
          caseId: ref.caseId,
          commandId: message.operationKey,
          expectedRevision: bound.revision,
          quoteId: bound.quoteId,
          quoteDigest: bound.quoteDigest,
          quoteJson: bound.quoteJson,
          explicit: true as const,
        });
        check();
        const eligible = acceptedMessage(await read(true), receiptId, this.#allowed);
        check();
        if (fingerprint(eligible) !== originalFingerprint)
          throw new ConfirmationError('AccessDenied');
        task.writing = true;
        const receipt = confirmationReceipt(
          await this.#authority.confirm(command, controller.signal),
          command,
        );
        this.#counts.accepted++;
        outcome = Object.freeze({
          ...task.identity,
          status: 'accepted',
          responseId: ref.responseId,
          receipt,
        });
      } catch (error) {
        const code =
          safeConfirmationCode(error) ?? (task.writing ? 'OutcomeUnknown' : 'Unavailable');
        if (
          task.identity &&
          [
            'ClarificationRequired',
            'RevisionConflict',
            'IdentityConflict',
            'InvalidCommand',
          ].includes(code)
        ) {
          this.#counts.clarification++;
          outcome = Object.freeze({ ...task.identity, status: 'clarification_required' });
        } else if (
          task.writing &&
          task.identity &&
          code !== 'AccessDenied' &&
          code !== 'Overloaded'
        ) {
          this.#counts.unknown++;
          outcome = Object.freeze({ ...task.identity, status: 'outcome_unknown' });
        } else {
          this.#counts.rejected++;
          throw new ConfirmationError(
            code === 'AccessDenied'
              ? 'AccessDenied'
              : code === 'Overloaded'
                ? 'Overloaded'
                : 'Unavailable',
          );
        }
      }
      this.#emit({ event: 'completed', code: outcome.status });
      if (controller.signal.aborted || performance.now() >= deadline) {
        if (task.writing && task.identity)
          return Object.freeze({ ...task.identity, status: 'outcome_unknown' as const });
        throw new ConfirmationError('Unavailable');
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
        if (external && onAbort) unlistenAbort(external, onAbort);
      });
    return Promise.race([work, timeout]).then((value) => {
      if ((external && isAborted(external)) || performance.now() >= deadline) {
        if (task.writing && task.identity)
          return Object.freeze({ ...task.identity, status: 'outcome_unknown' as const });
        throw new ConfirmationError('Unavailable');
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
          timer = setTimeout(
            () => reject(new ConfirmationError('CleanupIncomplete')),
            this.#cleanup,
          );
        }),
      ]);
      if (this.#tasks.size) throw new ConfirmationError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
