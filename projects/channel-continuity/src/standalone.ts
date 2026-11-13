/** Standalone input example: committed intake and separately bounded read-only preview. */
import {
  produceTextEvent,
  type AccountScope,
  type ProviderScope,
  type TextEventInput,
} from './index.js';
import { ChannelError } from './public-types.js';
import { WebhookError, type WebhookHeaders } from './security.js';
import type { DurableReceipt, StoredMessage } from './postgres.js';

export type StandaloneErrorCode =
  | 'MissingAdapter'
  | 'InvalidAdapterResult'
  | 'PreviewUnavailable'
  | 'Overloaded'
  | 'CleanupIncomplete'
  | 'Closed'
  | 'AccessDenied';
export class StandaloneError extends Error {
  constructor(readonly code: StandaloneErrorCode) {
    super(code);
    this.name = 'StandaloneError';
  }
}
export type StandaloneBinding = Readonly<{
  providerScope: ProviderScope;
  accountScope: AccountScope;
  conversationId: string;
  caseId: string;
}>;
export type CaseReference = Readonly<{ scope: AccountScope; caseId: string }>;
export type StandaloneCase = CaseReference &
  Readonly<{ revision: string; source: 'synthetic_read_only' }>;
export type ScriptedDecision = Readonly<{
  kind: 'investigation';
  source: 'scripted';
  caseRevision: string;
}>;
export type PendingOperation = Readonly<{
  operationKey: string;
  state: 'not_executed';
  durable: false;
}>;
export type StandalonePorts = Readonly<{
  inbox: {
    acceptSms(
      raw: Uint8Array,
      headers: WebhookHeaders,
    ): Promise<Readonly<{ receipt: DurableReceipt; replayed: boolean }>>;
    inspect(accountToken: string, receiptId: string): Promise<StoredMessage>;
  };
  cases: { inspect(reference: CaseReference, signal: AbortSignal): Promise<StandaloneCase> };
  agent: {
    preview(
      input: Readonly<{ message: StoredMessage; currentCase: StandaloneCase }>,
      signal: AbortSignal,
    ): Promise<ScriptedDecision>;
  };
  operations: {
    inspectPending(
      input: CaseReference & Readonly<{ operationKey: string; expectedRevision: string }>,
      signal: AbortSignal,
    ): Promise<PendingOperation>;
  };
}>;
export type StandaloneLimits = Readonly<{
  maxPreviews: number;
  previewTimeoutMs: number;
  cleanupTimeoutMs: number;
}>;
export type StandalonePreview = Readonly<{
  receipt: DurableReceipt;
  operationKey: string;
  processingState: 'pending';
  currentCase: StandaloneCase;
  decision: ScriptedDecision;
  operation: PendingOperation;
  execution: 'not_executed';
}>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}(?![\s\S])/;
function fail(): never {
  throw new StandaloneError('InvalidAdapterResult');
}
function object(value: unknown): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    fail();
  return value as Record<string, unknown>;
}
function data(
  value: unknown,
  required: readonly string[],
  optional: readonly string[] = [],
): Record<string, unknown> {
  const source = object(value);
  const keys = Reflect.ownKeys(source);
  if (
    keys.length > required.length + optional.length ||
    keys.some((key) => typeof key !== 'string' || ![...required, ...optional].includes(key))
  )
    fail();
  const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const key of keys as string[]) {
    const descriptor = Object.getOwnPropertyDescriptor(source, key);
    if (!descriptor || !('value' in descriptor) || !descriptor.enumerable) fail();
    result[key] = descriptor.value;
  }
  if (required.some((key) => !Object.hasOwn(result, key))) fail();
  return result;
}
function identifier(value: unknown): string {
  if (typeof value !== 'string' || value.length > 128 || !ID.test(value)) fail();
  return value;
}
function uuid(value: unknown): string {
  if (typeof value !== 'string' || value.length !== 36 || !UUID.test(value)) fail();
  return value;
}
function sequence(value: unknown): string {
  if (
    typeof value !== 'string' ||
    value.length > 19 ||
    !/^[1-9][0-9]{0,18}(?![\s\S])/.test(value) ||
    BigInt(value) > 9223372036854775807n
  )
    fail();
  return value;
}
function account(value: unknown): AccountScope {
  const fields = data(value, ['tenantId', 'accountId']);
  return Object.freeze({
    tenantId: identifier(fields.tenantId),
    accountId: identifier(fields.accountId),
  });
}
function sameScope(a: AccountScope, b: AccountScope): boolean {
  return a.tenantId === b.tenantId && a.accountId === b.accountId;
}
function receipt(value: unknown): DurableReceipt {
  const fields = data(value, [
    'receiptId',
    'eventId',
    'messageId',
    'acceptanceSequence',
    'acceptedAt',
  ]);
  if (
    typeof fields.acceptedAt !== 'string' ||
    fields.acceptedAt.length !== 24 ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z(?![\s\S])/.test(fields.acceptedAt)
  )
    fail();
  try {
    if (new Date(fields.acceptedAt).toISOString() !== fields.acceptedAt) fail();
  } catch {
    fail();
  }
  return Object.freeze({
    receiptId: uuid(fields.receiptId),
    eventId: identifier(fields.eventId),
    messageId: identifier(fields.messageId),
    acceptanceSequence: sequence(fields.acceptanceSequence),
    acceptedAt: fields.acceptedAt,
  });
}
function binding(value: StandaloneBinding): StandaloneBinding {
  const fields = data(value, ['providerScope', 'accountScope', 'conversationId', 'caseId']);
  const p = data(fields.providerScope, ['tenantId', 'provider', 'providerAccountId']);
  const providerScope = Object.freeze({
    tenantId: identifier(p.tenantId),
    provider: identifier(p.provider),
    providerAccountId: identifier(p.providerAccountId),
  });
  const accountScope = account(fields.accountScope);
  if (accountScope.tenantId !== providerScope.tenantId) fail();
  return Object.freeze({
    providerScope,
    accountScope,
    conversationId: identifier(fields.conversationId),
    caseId: identifier(fields.caseId),
  });
}
function caseReply(value: unknown, expected: StandaloneBinding): StandaloneCase {
  const fields = data(value, ['scope', 'caseId', 'revision', 'source']);
  const scope = account(fields.scope);
  if (
    !sameScope(scope, expected.accountScope) ||
    fields.caseId !== expected.caseId ||
    fields.source !== 'synthetic_read_only'
  )
    fail();
  return Object.freeze({
    scope,
    caseId: expected.caseId,
    revision: sequence(fields.revision),
    source: 'synthetic_read_only',
  });
}
function messageReply(
  value: unknown,
  expected: StandaloneBinding,
  receiptId: string,
): StoredMessage {
  const fields = data(value, [
    'receipt',
    'event',
    'operationKey',
    'processingState',
    'associationVersion',
  ]);
  const committed = receipt(fields.receipt);
  if (committed.receiptId !== receiptId || fields.processingState !== 'pending') fail();
  const event = data(
    fields.event,
    [
      'schemaVersion',
      'type',
      'eventId',
      'providerScope',
      'accountScope',
      'conversationId',
      'caseId',
      'receivedAt',
      'channel',
      'messageId',
      'senderId',
      'body',
    ],
    [
      'occurredAt',
      'causationId',
      'retryCount',
      'signature',
      'expectedCaseRevision',
      'replyToResponseId',
    ],
  );
  if (event.schemaVersion !== 1 || event.type !== 'text.received') fail();
  const provider = data(event.providerScope, ['tenantId', 'provider', 'providerAccountId']);
  const scope = data(event.accountScope, ['tenantId', 'accountId']);
  const input: Record<string, unknown> = { ...event, providerScope: provider, accountScope: scope };
  delete input.schemaVersion;
  delete input.type;
  const decoded = produceTextEvent(input as TextEventInput, {
    providerScope: expected.providerScope,
    accountScope: expected.accountScope,
  });
  if (
    decoded.event.type !== 'text.received' ||
    decoded.event.eventId !== committed.eventId ||
    decoded.event.messageId !== committed.messageId ||
    decoded.event.conversationId !== expected.conversationId ||
    decoded.event.caseId !== expected.caseId
  )
    fail();
  return Object.freeze({
    receipt: committed,
    event: decoded.event,
    operationKey: uuid(fields.operationKey),
    processingState: 'pending',
    associationVersion: sequence(fields.associationVersion),
  });
}
function decisionReply(value: unknown, currentCase: StandaloneCase): ScriptedDecision {
  const fields = data(value, ['kind', 'source', 'caseRevision']);
  if (
    fields.kind !== 'investigation' ||
    fields.source !== 'scripted' ||
    fields.caseRevision !== currentCase.revision
  )
    fail();
  return Object.freeze({
    kind: 'investigation',
    source: 'scripted',
    caseRevision: currentCase.revision,
  });
}
function operationReply(value: unknown, key: string): PendingOperation {
  const fields = data(value, ['operationKey', 'state', 'durable']);
  if (fields.operationKey !== key || fields.state !== 'not_executed' || fields.durable !== false)
    fail();
  return Object.freeze({ operationKey: key, state: 'not_executed', durable: false });
}
type Slot = { controller: AbortController; settled: Promise<void> };
class StandaloneExample {
  readonly #ports: StandalonePorts;
  readonly #binding: StandaloneBinding;
  readonly #limits: StandaloneLimits;
  readonly #slots = new Set<Slot>();
  #closing = false;
  #closePromise: Promise<void> | undefined;
  constructor(
    ports: StandalonePorts,
    trustedBinding: StandaloneBinding,
    proposed: StandaloneLimits,
  ) {
    try {
      data(ports, ['inbox', 'cases', 'agent', 'operations']);
      if (
        !ports.inbox ||
        typeof ports.inbox.acceptSms !== 'function' ||
        typeof ports.inbox.inspect !== 'function' ||
        !ports.cases ||
        typeof ports.cases.inspect !== 'function' ||
        !ports.agent ||
        typeof ports.agent.preview !== 'function' ||
        !ports.operations ||
        typeof ports.operations.inspectPending !== 'function'
      )
        throw new StandaloneError('MissingAdapter');
      this.#ports = Object.freeze({ ...ports });
    } catch {
      throw new StandaloneError('MissingAdapter');
    }
    try {
      this.#binding = binding(trustedBinding);
    } catch {
      throw new StandaloneError('AccessDenied');
    }
    const fields = data(proposed, ['maxPreviews', 'previewTimeoutMs', 'cleanupTimeoutMs']);
    if (
      !Number.isSafeInteger(fields.maxPreviews) ||
      (fields.maxPreviews as number) < 1 ||
      (fields.maxPreviews as number) > 4 ||
      !Number.isSafeInteger(fields.previewTimeoutMs) ||
      (fields.previewTimeoutMs as number) < 20 ||
      (fields.previewTimeoutMs as number) > 5000 ||
      !Number.isSafeInteger(fields.cleanupTimeoutMs) ||
      (fields.cleanupTimeoutMs as number) < 20 ||
      (fields.cleanupTimeoutMs as number) > 5000
    )
      fail();
    this.#limits = Object.freeze({ ...proposed });
  }
  get activePreviews(): number {
    return this.#slots.size;
  }
  async accept(
    raw: Uint8Array,
    headers: WebhookHeaders,
  ): Promise<Readonly<{ receipt: DurableReceipt; replayed: boolean }>> {
    if (this.#closing) throw new StandaloneError('Closed');
    try {
      const result = data(await this.#ports.inbox.acceptSms(raw, headers), ['receipt', 'replayed']);
      if (typeof result.replayed !== 'boolean') throw new ChannelError('AcknowledgementUnknown');
      return Object.freeze({ receipt: receipt(result.receipt), replayed: result.replayed });
    } catch (error) {
      if (error instanceof ChannelError || error instanceof WebhookError) throw error;
      // A malformed/lost adapter acknowledgement cannot establish non-acceptance.
      throw new ChannelError('AcknowledgementUnknown');
    }
  }
  async preview(accountToken: string, receiptId: string): Promise<StandalonePreview> {
    if (this.#closing) throw new StandaloneError('Closed');
    uuid(receiptId);
    if (this.#slots.size >= this.#limits.maxPreviews) throw new StandaloneError('Overloaded');
    const deadline = performance.now() + this.#limits.previewTimeoutMs;
    const controller = new AbortController();
    const slot: Slot = { controller, settled: Promise.resolve() };
    this.#slots.add(slot);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const work = this.#readPreview(accountToken, receiptId, controller.signal, deadline).finally(
      () => {
        this.#slots.delete(slot);
      },
    );
    slot.settled = work.then(
      () => undefined,
      () => undefined,
    );
    const timeout = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(
        () => {
          controller.abort();
          reject(new StandaloneError('PreviewUnavailable'));
        },
        Math.max(0, deadline - performance.now()),
      );
    });
    try {
      const result = await Promise.race([work, timeout]);
      if (performance.now() >= deadline) {
        controller.abort();
        throw new StandaloneError('PreviewUnavailable');
      }
      return result;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  async #readPreview(
    accountToken: string,
    receiptId: string,
    signal: AbortSignal,
    deadline: number,
  ): Promise<StandalonePreview> {
    const current = (): void => {
      if (signal.aborted || this.#closing || performance.now() >= deadline)
        throw new StandaloneError('PreviewUnavailable');
    };
    try {
      current();
      const message = messageReply(
        await this.#ports.inbox.inspect(accountToken, receiptId),
        this.#binding,
        receiptId,
      );
      current();
      const reference = Object.freeze({
        scope: this.#binding.accountScope,
        caseId: this.#binding.caseId,
      });
      const currentCase = caseReply(
        await this.#ports.cases.inspect(reference, signal),
        this.#binding,
      );
      current();
      const decision = decisionReply(
        await this.#ports.agent.preview(Object.freeze({ message, currentCase }), signal),
        currentCase,
      );
      current();
      const operation = operationReply(
        await this.#ports.operations.inspectPending(
          Object.freeze({
            ...reference,
            operationKey: message.operationKey,
            expectedRevision: currentCase.revision,
          }),
          signal,
        ),
        message.operationKey,
      );
      current();
      return Object.freeze({
        receipt: message.receipt,
        operationKey: message.operationKey,
        processingState: 'pending',
        currentCase,
        decision,
        operation,
        execution: 'not_executed',
      });
    } catch (error) {
      if (error instanceof ChannelError || error instanceof StandaloneError) throw error;
      throw new StandaloneError('PreviewUnavailable');
    }
  }
  close(): Promise<void> {
    if (this.#closePromise) return this.#closePromise;
    this.#closing = true;
    const deadline = performance.now() + this.#limits.cleanupTimeoutMs;
    const slots = [...this.#slots];
    // Publish one owned close promise before adapter abort listeners can re-enter.
    this.#closePromise = Promise.resolve().then(async () => {
      slots.forEach((slot) => slot.controller.abort());
      await this.#waitClosed(slots, deadline);
    });
    return this.#closePromise;
  }
  async #waitClosed(slots: readonly Slot[], deadline: number): Promise<void> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all(slots.map((slot) => slot.settled)),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(
            () => reject(new StandaloneError('CleanupIncomplete')),
            Math.max(0, deadline - performance.now()),
          );
        }),
      ]);
      if (performance.now() >= deadline) throw new StandaloneError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
export function createStandaloneExample(
  ports: StandalonePorts,
  trustedBinding: StandaloneBinding,
  limits: StandaloneLimits = { maxPreviews: 2, previewTimeoutMs: 2000, cleanupTimeoutMs: 1000 },
): StandaloneExample {
  return new StandaloneExample(ports, trustedBinding, limits);
}
