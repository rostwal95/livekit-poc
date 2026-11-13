/** Bounded explicit reply sends. Queued acceptance is not provider or human acknowledgement. */
import type { DatabaseSettings } from './public-types.js';
import type { FakeSmsIntegration } from './security.js';
import { SeededAccounts } from './postgres.js';
import { checkedSignal, isAborted, listenAbort, unlistenAbort } from './routing-types.js';
import { OutboxStore } from './outbox-store.js';
import { registerResultOutbox } from './result-receiver-access.js';
import {
  OutboxError,
  uuid,
  carrierResult,
  safe,
  type OutboxPublisher,
  type ReplyDraft,
  type OutboxReceipt,
  type OutboundRoute,
  type OutboxObservation,
  type SendOutcome,
  type CarrierSendPort,
  type OutboxOptions,
  type OutboxEvent,
} from './outbox-types.js';
import { record, uuid as checkedUuid, type IdempotentCarrierSendPort } from './outbox-types.js';
import {
  lookup,
  operationDigest,
  type ProviderLookup,
  type RecoveryCommandView,
  type RecoveryKind,
  type RecoverySummary,
} from './send-policy-types.js';
export {
  operation as providerOperation,
  operationFrom as providerOperationFromRequest,
  operationDigest,
} from './send-policy-types.js';
export type {
  ProviderOperation,
  ProviderLookup,
  RecoveryController,
  SendPolicyLimits,
  RecoveryKind,
  RecoveryReceipt,
  RecoveryObservation,
  RecoveryCommandView,
  RecoverySummary,
} from './send-policy-types.js';
export type { OrdinaryCarrierSendPort, IdempotentCarrierSendPort } from './outbox-types.js';
export { OutboxError } from './outbox-types.js';
export type {
  OutboxCode,
  OutboxPublisher,
  ReplyDraft,
  ReplyEnvelope,
  OutboxReceipt,
  OutboundRoute,
  SendRequest,
  CarrierResult,
  CarrierSendPort,
  SendAttempt,
  OutboxObservation,
  SendOutcome,
  OutboxOptions,
  OutboxEvent,
  OutboxLimits,
} from './outbox-types.js';
function configuredPort(value: CarrierSendPort): CarrierSendPort {
  const data = (key: string): unknown => {
    let current: object | null = value;
    for (let depth = 0; depth < 5 && current !== null; depth++) {
      const d = Object.getOwnPropertyDescriptor(current, key);
      if (d) {
        if (!('value' in d)) throw new OutboxError('InvalidCommand');
        return d.value;
      }
      current = Object.getPrototypeOf(current) as object | null;
    }
    throw new OutboxError('InvalidCommand');
  };
  try {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error();
    const mode = data('capabilities'),
      send = data('send');
    if (
      typeof send !== 'function' ||
      !['ordinary_fake_sms_v1', 'idempotent_fake_sms_v1'].includes(mode as string)
    )
      throw Error();
    const bound = Function.prototype.bind.call(send, value) as CarrierSendPort['send'];
    if (mode === 'ordinary_fake_sms_v1')
      return Object.freeze({ capabilities: 'ordinary_fake_sms_v1', send: bound });
    const lookup = data('lookup');
    if (typeof lookup !== 'function') throw Error();
    return Object.freeze({
      capabilities: 'idempotent_fake_sms_v1',
      send: bound,
      lookup: Function.prototype.bind.call(lookup, value) as IdempotentCarrierSendPort['lookup'],
    });
  } catch {
    throw new OutboxError('InvalidCommand');
  }
}
type Task = {
  controller: AbortController;
  settled: Promise<void>;
  possible: boolean;
  attemptId: string | null;
};
export class ChannelOutbox {
  readonly #store: OutboxStore;
  readonly #carrier: CarrierSendPort;
  readonly #tasks = new Set<Task>();
  readonly #maximum: number;
  readonly #timeout: number;
  readonly #cleanup: number;
  readonly #observer: NonNullable<OutboxOptions['observer']>;
  #closing = false;
  #notifications = 0;
  #ending: Promise<void> | undefined;
  #counts = {
    enqueued: 0,
    enqueueReplayed: 0,
    enqueueConflicts: 0,
    routeSelections: 0,
    suppressionObserved: 0,
    controlRejected: 0,
    started: 0,
    accepted: 0,
    definitiveFailure: 0,
    unknown: 0,
    held: 0,
    rejected: 0,
    waiterRejected: 0,
    telemetryFailures: 0,
    observerDropped: 0,
    recoveryStarted: 0,
    recoveryReplayed: 0,
    recoveryKnown: 0,
    recoveryUnknown: 0,
    recoveryHeld: 0,
    recoveryRejected: 0,
    retryReservations: 0,
    retryInvocations: 0,
    lookupInvocations: 0,
    lookupAccepted: 0,
    lookupDefinitiveFailure: 0,
    lookupAbsent: 0,
    lookupUnknown: 0,
    lookupConflicts: 0,
    retryAccepted: 0,
    retryDefinitiveFailure: 0,
    retryUnknown: 0,
    retryConflicts: 0,
    ordinaryHolds: 0,
    callbackVetoes: 0,
    permissionVetoes: 0,
    attemptLimitHolds: 0,
    recoveryConflicts: 0,
    priorOperationVetoes: 0,
    recoveryAcknowledgementUnknown: 0,
    recoveryAuthorizationRejected: 0,
    recoveryCapacityRejected: 0,
    recoveryIdentityConflicts: 0,
    recoveryRevisionConflicts: 0,
  };
  constructor(
    database: DatabaseSettings,
    integration: FakeSmsIntegration,
    accounts: SeededAccounts,
    publishers: readonly OutboxPublisher[],
    carrier: CarrierSendPort,
    options: OutboxOptions = {},
  ) {
    try {
      const keys = Object.keys(options);
      if (
        keys.some(
          (k) =>
            !['maxActive', 'timeoutMs', 'cleanupMs', 'observer', 'recoveryControllers'].includes(k),
        )
      )
        throw Error();
      options = record(options, keys) as OutboxOptions;
    } catch {
      throw new OutboxError('InvalidCommand');
    }
    const port = configuredPort(carrier);
    this.#maximum = options.maxActive ?? 2;
    this.#timeout = options.timeoutMs ?? 2000;
    this.#cleanup = options.cleanupMs ?? 2000;
    this.#observer =
      options.observer ??
      ((event) => console.info(JSON.stringify({ component: 'channel_outbox', ...event })));
    for (const [value, min, max] of [
      [this.#maximum, 1, 4],
      [this.#timeout, 20, 5000],
      [this.#cleanup, 20, 2000],
    ])
      if (!Number.isSafeInteger(value) || value! < min! || value! > max!)
        throw new OutboxError('InvalidCommand');
    if (typeof this.#observer !== 'function') throw new OutboxError('InvalidCommand');
    this.#carrier = port;
    this.#store = new OutboxStore(
      database,
      integration,
      accounts,
      publishers,
      options.recoveryControllers ?? [],
    );
    registerResultOutbox(this, this.#store);
  }
  #signal(signal?: AbortSignal): AbortSignal {
    if (signal !== undefined)
      try {
        checkedSignal(signal);
      } catch {
        throw new OutboxError('InvalidCommand');
      }
    return signal ?? new AbortController().signal;
  }
  #open(): void {
    if (this.#closing) throw new OutboxError('Closed');
  }
  enqueue(token: string, draft: ReplyDraft, signal?: AbortSignal): Promise<OutboxReceipt> {
    this.#open();
    const own = this.#signal(signal);
    return this.#store.enqueue(token, draft, own).then(
      (result) => {
        this.#counts[result.created ? 'enqueued' : 'enqueueReplayed']++;
        this.#emit({ event: 'completed', code: result.created ? 'queued' : 'replayed' });
        if (isAborted(own)) throw new OutboxError('AcknowledgementUnknown');
        return result.receipt;
      },
      (error) => {
        const failure = safe(error);
        this.#counts.controlRejected++;
        if (failure.code === 'IdentityConflict') this.#counts.enqueueConflicts++;
        this.#emit({
          event: 'rejected',
          code:
            failure.code === 'IdentityConflict'
              ? 'identity_conflict'
              : failure.code === 'AcknowledgementUnknown'
                ? 'unknown'
                : 'rejected',
        });
        throw failure;
      },
    );
  }
  inspect(token: string, outboundId: string, signal?: AbortSignal): Promise<OutboxObservation> {
    this.#open();
    return this.#store.inspect(token, outboundId, this.#signal(signal));
  }
  pending(token: string, limit = 32, signal?: AbortSignal): Promise<readonly string[]> {
    this.#open();
    return this.#store.pending(token, limit, this.#signal(signal));
  }
  inspectRoute(token: string, signal?: AbortSignal): Promise<OutboundRoute> {
    this.#open();
    return this.#store.inspectRoute(token, this.#signal(signal));
  }
  selectRoute(
    token: string,
    input: Readonly<{ senderId: string; associationVersion: string; expectedRouteVersion: string }>,
    signal?: AbortSignal,
  ): Promise<OutboundRoute> {
    this.#open();
    const own = this.#signal(signal);
    return this.#store.selectRoute(token, input, own).then(
      (value) => {
        this.#counts.routeSelections++;
        this.#emit({ event: 'completed', code: 'route_selected' });
        if (isAborted(own)) throw new OutboxError('AcknowledgementUnknown');
        return value;
      },
      (error) => {
        this.#counts.controlRejected++;
        this.#emit({ event: 'rejected', code: 'rejected' });
        throw safe(error);
      },
    );
  }
  setSuppressed(
    token: string,
    input: Readonly<{ suppressed: boolean; expectedRouteVersion: string }>,
    signal?: AbortSignal,
  ): Promise<OutboundRoute> {
    this.#open();
    const own = this.#signal(signal);
    return this.#store.setSuppressed(token, input, own).then(
      (value) => {
        this.#counts.suppressionObserved++;
        this.#emit({ event: 'completed', code: value.suppressed ? 'suppressed' : 'unsuppressed' });
        if (isAborted(own)) throw new OutboxError('AcknowledgementUnknown');
        return value;
      },
      (error) => {
        this.#counts.controlRejected++;
        this.#emit({ event: 'rejected', code: 'rejected' });
        throw safe(error);
      },
    );
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({
      ...this.#counts,
      active: this.#tasks.size,
      observerPending: this.#notifications,
      storageActive: this.#store.metrics().active!,
    });
  }
  #emit(event: OutboxEvent): void {
    if (this.#notifications >= 8) {
      this.#counts.observerDropped++;
      return;
    }
    try {
      const result = this.#observer(Object.freeze(event));
      if (result !== undefined) {
        this.#notifications++;
        void Promise.resolve(result)
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
  send(token: string, outboundId: string, external?: AbortSignal): Promise<SendOutcome> {
    const signal = this.#signal(external),
      key = uuid(outboundId);
    this.#open();
    if (this.#tasks.size >= this.#maximum) return Promise.reject(new OutboxError('Overloaded'));
    if (isAborted(signal)) return Promise.reject(new OutboxError('Unavailable'));
    const task: Task = {
        controller: new AbortController(),
        settled: Promise.resolve(),
        possible: false,
        attemptId: null,
      },
      deadline = performance.now() + this.#timeout;
    this.#tasks.add(task);
    this.#counts.started++;
    let timer: ReturnType<typeof setTimeout> | undefined,
      abort: (() => void) | undefined,
      abandoned = false;
    const uncertain = (): SendOutcome =>
      Object.freeze({ status: 'unknown', outboundId: key, attemptId: task.attemptId });
    const waiter = new Promise<SendOutcome>((resolve, reject) => {
      abort = () => {
        if (abandoned) return;
        abandoned = true;
        task.controller.abort();
        this.#counts.waiterRejected++;
        this.#emit({ event: 'waiter_rejected', code: task.possible ? 'unknown' : 'unavailable' });
        if (task.possible) resolve(uncertain());
        else reject(new OutboxError('Unavailable'));
      };
      timer = setTimeout(abort, this.#timeout);
      listenAbort(signal, abort);
    });
    const work = Promise.resolve().then(async () => {
      const check = () => {
        if (task.controller.signal.aborted || performance.now() >= deadline)
          throw new OutboxError(task.possible ? 'OutcomeUnknown' : 'Unavailable');
      };
      let outcome: SendOutcome;
      try {
        check();
        const reserved = await this.#store.reserve(
          token,
          key,
          task.controller.signal,
          this.#carrier.capabilities,
        );
        if ('result' in reserved) {
          outcome = reserved.result;
        } else {
          task.possible = true;
          task.attemptId = reserved.request.attemptId;
          check();
          const result = carrierResult(
            await this.#carrier.send(reserved.request, task.controller.signal),
            reserved.request,
          );
          await this.#store.recordResult(reserved.request, result);
          outcome = Object.freeze({
            status: result.status,
            outboundId: key,
            attemptId: reserved.request.attemptId,
          });
        }
        if (outcome.status === 'accepted_by_provider') this.#counts.accepted++;
        else if (outcome.status === 'definitive_not_accepted') this.#counts.definitiveFailure++;
        else if (outcome.status === 'unknown') this.#counts.unknown++;
        else if (outcome.status === 'held') this.#counts.held++;
        this.#emit({ event: 'completed', code: outcome.status });
        return outcome;
      } catch (error) {
        const failure = safe(error, task.possible ? 'OutcomeUnknown' : 'Unavailable');
        if (
          task.possible ||
          failure.code === 'AcknowledgementUnknown' ||
          failure.code === 'OutcomeUnknown'
        ) {
          this.#counts.unknown++;
          this.#emit({ event: 'completed', code: 'unknown' });
          return uncertain();
        }
        this.#counts.rejected++;
        this.#emit({ event: 'rejected', code: 'rejected' });
        throw failure;
      }
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
        if (isAborted(signal) || performance.now() >= deadline) {
          if (task.possible) return uncertain();
          throw new OutboxError('Unavailable');
        }
        return value;
      })
      .finally(() => {
        if (timer) clearTimeout(timer);
        if (abort) unlistenAbort(signal, abort);
      });
  }

  recoveryCommand(
    accountToken: string,
    commandId: string,
    signal?: AbortSignal,
  ): Promise<RecoveryCommandView | null> {
    this.#open();
    return this.#store.recoveryCommand(accountToken, checkedUuid(commandId), this.#signal(signal));
  }
  inspectRecovery(
    accountToken: string,
    outboundId: string,
    signal?: AbortSignal,
  ): Promise<RecoverySummary> {
    this.#open();
    return this.#store.inspectRecovery(accountToken, checkedUuid(outboundId), this.#signal(signal));
  }
  reconcile(
    controllerToken: string,
    input: Readonly<{ commandId: string; outboundId: string; attemptId: string }>,
    signal?: AbortSignal,
  ): Promise<RecoveryCommandView> {
    const p = record(input, ['commandId', 'outboundId', 'attemptId']);
    return this.#recover(
      'reconcile',
      controllerToken,
      checkedUuid(p.commandId),
      checkedUuid(p.outboundId),
      checkedUuid(p.attemptId),
      signal,
    );
  }
  retry(
    controllerToken: string,
    input: Readonly<{ commandId: string; outboundId: string; expectedAttemptId: string }>,
    signal?: AbortSignal,
  ): Promise<RecoveryCommandView> {
    const p = record(input, ['commandId', 'outboundId', 'expectedAttemptId']);
    return this.#recover(
      'retry',
      controllerToken,
      checkedUuid(p.commandId),
      checkedUuid(p.outboundId),
      checkedUuid(p.expectedAttemptId),
      signal,
    );
  }
  #recover(
    kind: RecoveryKind,
    token: string,
    commandId: string,
    outboundId: string,
    sourceAttemptId: string,
    external?: AbortSignal,
  ): Promise<RecoveryCommandView> {
    const signal = this.#signal(external);
    this.#open();
    if (this.#tasks.size >= this.#maximum) return Promise.reject(new OutboxError('Overloaded'));
    if (isAborted(signal)) return Promise.reject(new OutboxError('Unavailable'));
    const task: Task = {
        controller: new AbortController(),
        settled: Promise.resolve(),
        possible: false,
        attemptId: null,
      },
      deadline = performance.now() + this.#timeout;
    this.#tasks.add(task);
    this.#counts.recoveryStarted++;
    let timer: ReturnType<typeof setTimeout> | undefined,
      abort: (() => void) | undefined,
      abandoned = false;
    const waiter = new Promise<never>((_, reject) => {
      abort = () => {
        if (abandoned) return;
        abandoned = true;
        task.controller.abort();
        this.#counts.waiterRejected++;
        this.#emit({ event: 'waiter_rejected', code: 'recovery_unknown' });
        reject(new OutboxError('AcknowledgementUnknown'));
      };
      timer = setTimeout(abort, this.#timeout);
      listenAbort(signal, abort);
    });
    const work = Promise.resolve().then(async () => {
      const check = () => {
        if (task.controller.signal.aborted || performance.now() >= deadline)
          throw new OutboxError(task.possible ? 'AcknowledgementUnknown' : 'Unavailable');
      };
      check();
      const reserved = await this.#store.reserveRecovery(
        token,
        kind,
        commandId,
        outboundId,
        sourceAttemptId,
        this.#carrier.capabilities,
        task.controller.signal,
      );
      task.possible = reserved.created;
      task.attemptId = reserved.view.receipt.newAttemptId;
      let view = reserved.view;
      if (reserved.created && reserved.action === 'send') this.#counts.retryReservations++;
      if (!reserved.created) {
        this.#counts.recoveryReplayed++;
        this.#emit({ event: 'completed', code: 'recovery_replayed' });
        return view;
      }
      if (reserved.action !== 'none') {
        check();
        if (this.#carrier.capabilities !== 'idempotent_fake_sms_v1')
          throw new OutboxError('IdentityConflict');
        const carrier: IdempotentCarrierSendPort = this.#carrier,
          op = reserved.operation;
        let observed: ProviderLookup = lookup(
            {
              schemaVersion: 1,
              providerScope: op.providerScope,
              providerOperationKey: op.providerOperationKey,
              operationDigest: operationDigest(op),
              state: 'unknown',
              providerMessageId: null,
            },
            op,
          ),
          sent: Parameters<OutboxStore['recordRecovery']>[4];
        try {
          if (reserved.action === 'lookup') {
            check();
            this.#counts.lookupInvocations++;
            const pending = carrier.lookup(op, task.controller.signal);
            this.#emit({ event: 'completed', code: 'lookup_started' });
            observed = lookup(await pending, op);
          } else {
            if (!reserved.request) throw new OutboxError('Unavailable');
            check();
            this.#counts.retryInvocations++;
            const pending = carrier.send(reserved.request, task.controller.signal);
            this.#emit({ event: 'completed', code: 'retry_started' });
            const result = carrierResult(await pending, reserved.request);
            sent = Object.freeze({ request: reserved.request, result });
            observed = lookup(
              {
                schemaVersion: 1,
                providerScope: op.providerScope,
                providerOperationKey: op.providerOperationKey,
                operationDigest: operationDigest(op),
                state: result.status,
                providerMessageId:
                  result.status === 'accepted_by_provider' ? result.providerMessageId : null,
              },
              op,
            );
          }
        } catch {
          /* A transport or unvalidated observation never becomes failure-for-retry. */
        }
        view = await this.#store.recordRecovery(
          reserved.view.receipt,
          op,
          observed,
          reserved.action === 'send' ? 'send' : 'lookup',
          sent,
        );
      }
      if (view.receipt.code === 'prior_operation_evidence') this.#counts.priorOperationVetoes++;
      if (view.receipt.code === 'ordinary_no_resend') this.#counts.ordinaryHolds++;
      if (view.receipt.code === 'callback_veto') this.#counts.callbackVetoes++;
      if (
        ['route_missing', 'association_required', 'suppressed', 'route_changed'].includes(
          view.receipt.code,
        )
      )
        this.#counts.permissionVetoes++;
      if (view.receipt.code === 'attempt_exhausted') this.#counts.attemptLimitHolds++;
      const observation = view.observation;
      if (observation && ['lookup', 'send'].includes(observation.source)) {
        const prefix = observation.source === 'lookup' ? 'lookup' : 'retry';
        const suffix =
          observation.assessment === 'conflicted'
            ? 'Conflicts'
            : observation.state === 'accepted_by_provider'
              ? 'Accepted'
              : observation.state === 'definitive_not_accepted'
                ? 'DefinitiveFailure'
                : observation.state === 'absent'
                  ? 'Absent'
                  : 'Unknown';
        if (prefix === 'lookup') {
          if (suffix === 'Accepted') this.#counts.lookupAccepted++;
          else if (suffix === 'DefinitiveFailure') this.#counts.lookupDefinitiveFailure++;
          else if (suffix === 'Absent') this.#counts.lookupAbsent++;
          else if (suffix === 'Conflicts') this.#counts.lookupConflicts++;
          else this.#counts.lookupUnknown++;
        } else {
          if (suffix === 'Accepted') this.#counts.retryAccepted++;
          else if (suffix === 'DefinitiveFailure') this.#counts.retryDefinitiveFailure++;
          else if (suffix === 'Conflicts') this.#counts.retryConflicts++;
          else this.#counts.retryUnknown++;
        }
      }
      if (observation?.assessment === 'conflicted') {
        this.#counts.recoveryConflicts++;
        this.#emit({ event: 'completed', code: 'recovery_conflicted' });
      } else if (
        observation?.state === 'accepted_by_provider' ||
        observation?.state === 'definitive_not_accepted'
      ) {
        this.#counts.recoveryKnown++;
        this.#emit({ event: 'completed', code: 'recovery_known' });
      } else if (view.receipt.decision === 'held') {
        this.#counts.recoveryHeld++;
        this.#emit({ event: 'completed', code: 'recovery_held' });
      } else {
        this.#counts.recoveryUnknown++;
        this.#emit({ event: 'completed', code: 'recovery_unknown' });
      }
      return view;
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
      .then((view) => {
        if (isAborted(signal) || performance.now() >= deadline)
          throw new OutboxError('AcknowledgementUnknown');
        return view;
      })
      .catch((error) => {
        const failure = safe(error, task.possible ? 'AcknowledgementUnknown' : 'Unavailable');
        if (failure.code === 'AcknowledgementUnknown' || failure.code === 'OutcomeUnknown') {
          this.#counts.recoveryAcknowledgementUnknown++;
          this.#emit({ event: 'completed', code: 'recovery_unknown' });
        } else {
          this.#counts.recoveryRejected++;
          if (failure.code === 'AccessDenied') this.#counts.recoveryAuthorizationRejected++;
          if (failure.code === 'Overloaded') this.#counts.recoveryCapacityRejected++;
          if (failure.code === 'IdentityConflict') this.#counts.recoveryIdentityConflicts++;
          if (failure.code === 'RevisionConflict') this.#counts.recoveryRevisionConflicts++;
          this.#emit({ event: 'rejected', code: 'rejected' });
        }
        throw failure;
      })
      .finally(() => {
        if (timer) clearTimeout(timer);
        if (abort) unlistenAbort(signal, abort);
      });
  }
  async close(): Promise<void> {
    this.#closing = true;
    for (const task of this.#tasks) task.controller.abort();
    this.#ending ??= Promise.all([...this.#tasks].map((t) => t.settled)).then(() =>
      this.#store.close(),
    );
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        this.#ending,
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new OutboxError('CleanupIncomplete')), this.#cleanup);
        }),
      ]);
      if (this.#tasks.size) throw new OutboxError('CleanupIncomplete');
      this.#emit({ event: 'closed', code: 'ok' });
    } catch (error) {
      void this.#ending.catch(() => {
        this.#ending = undefined;
      });
      throw safe(error);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
