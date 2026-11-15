/** One explicitly requested persisted investigation dispatch step. No scheduler or mutation authority. */
import type { DatabaseSettings } from './public-types.js';
import { ChannelError } from './public-types.js';
import { SeededAccounts } from './postgres.js';
import type { FakeSmsIntegration } from './security.js';
import { DispatchStore, type DispatchClaim } from './dispatch-store.js';
import {
  dispatchFields,
  operationLookup,
  prepareDispatch,
  validateDispatchCase,
  validateOperationReceipt,
  type DispatchOptions,
  type DispatchPorts,
  type DispatchStepResult,
  type PreparedDispatch,
} from './dispatch-types.js';
export type {
  DispatchCase,
  DispatchDecision,
  DispatchObservation,
  DispatchOptions,
  DispatchPorts,
  DispatchStepResult,
  InvestigationSubmission,
  OperationLookup,
  OperationReceipt,
  PreparedDispatch,
} from './dispatch-types.js';
export { ChannelError } from './public-types.js';
const SAFE_CODES = new Set([
  'InvalidConfiguration',
  'AccessDenied',
  'AssociationRequired',
  'AssociationRejected',
  'IdentityConflict',
  'Overloaded',
  'NotFound',
  'StorageUnavailable',
  'AcknowledgementUnknown',
  'SchemaMismatch',
  'CleanupIncomplete',
  'UpgradeRequired',
  'DispatchClaimLost',
  'DispatchUnavailable',
  'OperationConflict',
]);
function safeError(value: unknown): ChannelError {
  if (value instanceof ChannelError) {
    const code = Object.getOwnPropertyDescriptor(value, 'code');
    if (code && 'value' in code && typeof code.value === 'string' && SAFE_CODES.has(code.value))
      return new ChannelError(code.value as ChannelError['code']);
  }
  return new ChannelError('DispatchUnavailable');
}
type Task = { controller: AbortController; settled: Promise<void> };
function limits(value: DispatchOptions): Readonly<{
  timeoutMs: number;
  cleanupTimeoutMs: number;
  observer: DispatchOptions['observer'];
}> {
  const keys = Reflect.ownKeys(value);
  if (
    keys.length > 3 ||
    keys.some(
      (key) =>
        typeof key !== 'string' || !['timeoutMs', 'cleanupTimeoutMs', 'observer'].includes(key),
    )
  )
    throw new ChannelError('InvalidConfiguration');
  const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const key of keys as string[]) {
    const d = Object.getOwnPropertyDescriptor(value, key);
    if (!d || !('value' in d) || !d.enumerable) throw new ChannelError('InvalidConfiguration');
    result[key] = d.value;
  }
  const timeoutMs = result.timeoutMs ?? 2000,
    cleanupTimeoutMs = result.cleanupTimeoutMs ?? 1000;
  if (
    !Number.isInteger(timeoutMs) ||
    Number(timeoutMs) < 20 ||
    Number(timeoutMs) > 5000 ||
    !Number.isInteger(cleanupTimeoutMs) ||
    Number(cleanupTimeoutMs) < 20 ||
    Number(cleanupTimeoutMs) > 2000 ||
    (result.observer !== undefined && typeof result.observer !== 'function')
  )
    throw new ChannelError('InvalidConfiguration');
  return {
    timeoutMs: Number(timeoutMs),
    cleanupTimeoutMs: Number(cleanupTimeoutMs),
    observer: result.observer as DispatchOptions['observer'],
  };
}
function ports(value: DispatchPorts): DispatchPorts {
  try {
    const p = dispatchFields(value, ['cases', 'agent', 'operations']),
      cases = dispatchFields(p.cases, ['inspect']),
      agent = dispatchFields(p.agent, ['prepare']),
      operations = dispatchFields(p.operations, ['capabilities', 'lookup', 'accept']);
    if (
      typeof cases.inspect !== 'function' ||
      typeof agent.prepare !== 'function' ||
      operations.capabilities !== 'stable_idempotency_and_lookup' ||
      typeof operations.lookup !== 'function' ||
      typeof operations.accept !== 'function'
    )
      throw new Error();
    return Object.freeze({
      cases: Object.freeze({
        inspect: (cases.inspect as DispatchPorts['cases']['inspect']).bind(p.cases),
      }),
      agent: Object.freeze({
        prepare: (agent.prepare as DispatchPorts['agent']['prepare']).bind(p.agent),
      }),
      operations: Object.freeze({
        capabilities: 'stable_idempotency_and_lookup' as const,
        lookup: (operations.lookup as DispatchPorts['operations']['lookup']).bind(p.operations),
        accept: (operations.accept as DispatchPorts['operations']['accept']).bind(p.operations),
      }),
    });
  } catch {
    throw new ChannelError('InvalidConfiguration');
  }
}
/** Explicit adapters must cooperate on immutable operation key/scope/digest and durable lookup. */
export class ChannelDispatcher {
  readonly #store: DispatchStore;
  readonly #ports: DispatchPorts;
  readonly #options: ReturnType<typeof limits>;
  readonly #tasks = new Set<Task>();
  #closing = false;
  #closed: Promise<void> | undefined;
  #notifications = 0;
  readonly #counts: Record<string, number> = Object.create(null) as Record<string, number>;
  constructor(
    database: DatabaseSettings,
    integration: FakeSmsIntegration,
    accounts: SeededAccounts,
    adapters: DispatchPorts,
    options: DispatchOptions = {},
  ) {
    this.#ports = ports(adapters);
    try {
      if (
        !options ||
        typeof options !== 'object' ||
        ![Object.prototype, null].includes(Object.getPrototypeOf(options))
      )
        throw new Error();
      this.#options = limits(options);
    } catch {
      throw new ChannelError('InvalidConfiguration');
    }
    this.#store = new DispatchStore(database, integration, accounts);
  }
  #emit(event: string, code: string): void {
    const name = `${event}:${code}`;
    this.#counts[name] = Math.min(Number.MAX_SAFE_INTEGER, (this.#counts[name] ?? 0) + 1);
    if (!this.#options.observer || this.#notifications >= 8) return;
    try {
      const result = this.#options.observer(Object.freeze({ event, code }));
      if (result && typeof result.then === 'function') {
        this.#notifications++;
        void Promise.resolve(result)
          .catch(() => undefined)
          .finally(() => {
            this.#notifications--;
          });
      }
    } catch {
      /* Diagnostics cannot change persisted outcomes. */
    }
  }
  counters(): Readonly<Record<string, number>> {
    return Object.freeze({ ...this.#counts });
  }
  /** A bounded observation of persisted due work, never execution permission. */
  eligible(accountToken: string, limit = 4): Promise<readonly string[]> {
    if (this.#closing) return Promise.reject(new ChannelError('StorageUnavailable'));
    return this.#store.eligible(accountToken, limit);
  }
  /** Existing prepared history only; never computes, claims or submits work. */
  readPrepared(accountToken: string, receiptId: string): Promise<PreparedDispatch | null> {
    if (this.#closing) return Promise.reject(new ChannelError('StorageUnavailable'));
    return this.#store.readPrepared(accountToken, receiptId);
  }
  inspect(accountToken: string, receiptId: string) {
    if (this.#closing) return Promise.reject(new ChannelError('StorageUnavailable'));
    return this.#store.inspect(accountToken, receiptId);
  }
  step(accountToken: string, receiptId: string): Promise<DispatchStepResult> {
    return this.#start(accountToken, receiptId, 'dispatch');
  }
  /** Lookup only: no case/agent/accept, including after the ordinary attempt budget or sender revocation. */
  reconcile(accountToken: string, receiptId: string): Promise<DispatchStepResult> {
    return this.#start(accountToken, receiptId, 'reconcile');
  }
  #start(token: string, id: string, kind: 'dispatch' | 'reconcile'): Promise<DispatchStepResult> {
    if (this.#closing) return Promise.reject(new ChannelError('StorageUnavailable'));
    if (this.#tasks.size >= 2) return Promise.reject(new ChannelError('Overloaded'));
    const controller = new AbortController(),
      deadline = performance.now() + this.#options.timeoutMs;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const task: Task = { controller, settled: Promise.resolve() };
    const work = this.#run(token, id, kind, controller.signal, deadline).then((result) => {
      this.#check(controller.signal, deadline);
      return result;
    });
    task.settled = work
      .then(
        () => undefined,
        () => undefined,
      )
      .finally(() => {
        this.#tasks.delete(task);
        if (timer) clearTimeout(timer);
      });
    this.#tasks.add(task);
    const timeout = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => {
        controller.abort();
        this.#emit('dispatch', 'timeout');
        reject(new ChannelError('DispatchUnavailable'));
      }, this.#options.timeoutMs);
    });
    return Promise.race([work, timeout]);
  }
  #check(signal: AbortSignal, deadline: number): void {
    if (signal.aborted || performance.now() >= deadline)
      throw new ChannelError('DispatchUnavailable');
  }
  async #run(
    token: string,
    id: string,
    kind: 'dispatch' | 'reconcile',
    signal: AbortSignal,
    deadline: number,
  ): Promise<DispatchStepResult> {
    let claim: DispatchClaim | undefined;
    try {
      this.#check(signal, deadline);
      const outcome = await this.#store.claim(token, id, kind);
      if ('claim' in outcome) claim = outcome.claim;
      this.#check(signal, deadline);
      if ('result' in outcome) {
        this.#emit('dispatch', outcome.result.status);
        return outcome.result;
      }
      claim = outcome.claim;
      let prepared: PreparedDispatch | undefined = claim.prepared ?? undefined;
      if (!prepared) {
        if (kind === 'reconcile') throw new ChannelError('SchemaMismatch');
        const event = claim.message.event;
        if (!event.accountScope || !event.caseId) throw new ChannelError('OperationConflict');
        this.#check(signal, deadline);
        const current = validateDispatchCase(
          await this.#ports.cases.inspect(
            Object.freeze({ scope: event.accountScope, caseId: event.caseId }),
            signal,
          ),
          claim.message,
        );
        this.#check(signal, deadline);
        const decision = await this.#ports.agent.prepare(
          Object.freeze({ message: claim.message, currentCase: current }),
          signal,
        );
        this.#check(signal, deadline);
        const proposed = prepareDispatch(claim.message, current, decision);
        prepared = (await this.#store.prepare(token, claim, proposed)) ?? undefined;
        this.#check(signal, deadline);
        if (!prepared) {
          this.#emit('dispatch', 'blocked');
          return Object.freeze({
            status: claim.possibleExternal ? 'uncertain' : 'blocked',
            receiptId: claim.receiptId,
            operationKey: claim.operationKey,
          });
        }
      }
      this.#check(signal, deadline);
      const observed = await this.#ports.operations.lookup(operationLookup(prepared), signal);
      // A known durable receipt is useful truth even if its response arrived after our caller deadline.
      const shape =
        observed &&
        typeof observed === 'object' &&
        Object.getOwnPropertyDescriptor(observed, 'status');
      const status = shape && 'value' in shape ? shape.value : undefined;
      if (status === 'accepted') {
        const fields = dispatchFields(observed, ['status', 'receipt']),
          receipt = validateOperationReceipt(fields.receipt, prepared);
        await this.#store.finish(token, claim, receipt);
        claim = undefined;
        this.#check(signal, deadline);
        this.#emit('dispatch', 'dispatched');
        return Object.freeze({
          status: 'dispatched',
          receiptId: id,
          operationKey: receipt.operationKey,
          externalReceiptId: receipt.receiptId,
          reconciled: true,
        });
      }
      const absent = dispatchFields(observed, ['status']);
      if (absent.status !== 'absent') throw new ChannelError('OperationConflict');
      this.#check(signal, deadline);
      if (kind === 'reconcile') {
        await this.#store.fail(token, claim, 'lookup_absent');
        claim = undefined;
        this.#check(signal, deadline);
        this.#emit('dispatch', 'uncertain');
        return Object.freeze({
          status: 'uncertain',
          receiptId: id,
          operationKey: prepared.submission.operationKey,
        });
      }
      const reserved = await this.#store.reserve(token, claim);
      this.#check(signal, deadline);
      if (!reserved) {
        this.#emit('dispatch', 'blocked');
        return Object.freeze({
          status: claim.possibleExternal ? 'uncertain' : 'blocked',
          receiptId: id,
          operationKey: claim.operationKey,
        });
      }
      const receipt = validateOperationReceipt(
        await this.#ports.operations.accept(prepared, signal),
        prepared,
      );
      await this.#store.finish(token, claim, receipt);
      claim = undefined;
      this.#check(signal, deadline);
      this.#emit('dispatch', 'dispatched');
      return Object.freeze({
        status: 'dispatched',
        receiptId: id,
        operationKey: receipt.operationKey,
        externalReceiptId: receipt.receiptId,
        reconciled: false,
      });
    } catch (error) {
      const checked = safeError(error);
      const code = checked.code;
      if (claim) {
        const classification =
          code === 'OperationConflict'
            ? 'operation_conflict'
            : signal.aborted || performance.now() >= deadline
              ? 'timeout'
              : 'adapter_unavailable';
        try {
          await this.#store.fail(token, claim, classification);
        } catch (failure) {
          if (failure instanceof ChannelError && failure.code === 'DispatchClaimLost') {
            this.#emit('dispatch', 'DispatchClaimLost');
            throw failure;
          }
          this.#emit('dispatch', 'StorageUnavailable');
          throw failure instanceof ChannelError ? failure : new ChannelError('StorageUnavailable');
        }
      }
      this.#emit('dispatch', code);
      throw checked;
    }
  }
  close(): Promise<void> {
    if (this.#closed) return this.#closed;
    this.#closing = true;
    let resolve!: () => void, reject!: (reason: unknown) => void;
    this.#closed = new Promise<void>((done, fail) => {
      resolve = done;
      reject = fail;
    });
    const deadline = performance.now() + this.#options.cleanupTimeoutMs;
    const tasks = [...this.#tasks];
    for (const task of tasks) task.controller.abort();
    void this.#close(tasks, deadline).then(resolve, (error: unknown) => {
      this.#closed = undefined;
      reject(error);
    });
    return this.#closed;
  }
  async #close(tasks: readonly Task[], deadline: number): Promise<void> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all(tasks.map((task) => task.settled)).then(() => this.#store.close()),
        new Promise<never>((_done, reject) => {
          timer = setTimeout(
            () => reject(new ChannelError('CleanupIncomplete')),
            Math.max(0, deadline - performance.now()),
          );
        }),
      ]);
      if (performance.now() >= deadline) throw new ChannelError('CleanupIncomplete');
    } catch {
      throw new ChannelError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
