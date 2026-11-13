/** Persisted P2 observations for one trusted route; never an execution queue. */
import { createHash } from 'node:crypto';
import { snapshotMethod } from './read-ports.js';
import {
  parseEventJson,
  ContractError,
  type AccountScope,
  type ProviderScope,
  type TextEvent,
} from '@livekit-ecosystem/channel-continuity';
import {
  ChannelError,
  type ChannelInbox,
  type StoredMessage,
} from '@livekit-ecosystem/channel-continuity/postgres';
import type {
  ChannelDispatcher,
  DispatchObservation,
  PreparedDispatch,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import type { ChannelGateway } from '@livekit-ecosystem/channel-continuity/gateway';

export const DISCOVERY_ITEMS = 16;
export const DISCOVERY_BYTES = 8192;
export const PREPARED_BYTES = 32768;
export type SourceId = 'native' | 'sms';
type ReadCode =
  | 'invalid_input'
  | 'unauthorized'
  | 'not_found'
  | 'invalid_state'
  | 'capacity'
  | 'unavailable'
  | 'closed'
  | 'cleanup_incomplete';
const CODES = new Set<string>([
  'invalid_input',
  'unauthorized',
  'not_found',
  'invalid_state',
  'capacity',
  'unavailable',
  'closed',
  'cleanup_incomplete',
]);
export class SourceReadError extends Error {
  readonly code: ReadCode;
  constructor(code: ReadCode) {
    const safe = typeof code === 'string' && CODES.has(code) ? code : 'unavailable';
    super(safe);
    this.name = 'SourceReadError';
    this.code = safe;
  }
}
export type SourceOwner = Readonly<{
  providerScope: ProviderScope;
  dispatch: Pick<ChannelDispatcher, 'inspect'>;
  prepared: Pick<ChannelGateway, 'readPrepared'>;
}>;
export type SourceReaderConfiguration = Readonly<{
  profileId: string;
  scope: AccountScope;
  caseId: string;
  conversationId: string;
  accountToken: string;
  inbox: Pick<ChannelInbox, 'history' | 'inspect'>;
  sources: Readonly<{ native: SourceOwner; sms: SourceOwner }>;
}>;
export type DiscoveryItem = Readonly<{
  receiptId: string;
  operationKey: string;
  acceptanceSequence: string;
  sourceBindingId: SourceId;
  state: DispatchObservation['state'];
  possibleExternal: boolean;
  externalReceiptId: string | null;
}>;
export type DiscoveryPage = Readonly<{
  schemaVersion: 1;
  kind: 'channel.policy_discovery';
  profileId: string;
  scope: AccountScope;
  caseId: string;
  conversationId: string;
  readCompletedAt: string;
  items: readonly DiscoveryItem[];
  overflow: boolean;
  nextCursor: string | null;
}>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ID = /^[a-z][a-z0-9_-]{0,63}$/;
const P2ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const STATES = new Set(['pending', 'running', 'dispatched', 'blocked', 'exhausted', 'uncertain']);
function requireValue(condition: boolean): asserts condition {
  if (!condition) throw new SourceReadError('invalid_state');
}
function fields(value: unknown, names: readonly string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw new SourceReadError('invalid_input');
  const keys = Reflect.ownKeys(value);
  if (keys.length !== names.length || keys.some((k) => typeof k !== 'string' || !names.includes(k)))
    throw new SourceReadError('invalid_input');
  const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const name of names) {
    const d = Object.getOwnPropertyDescriptor(value, name);
    if (!d || !('value' in d) || !d.enumerable) throw new SourceReadError('invalid_input');
    result[name] = d.value;
  }
  return result;
}
function string(value: unknown, pattern: RegExp): string {
  if (typeof value !== 'string' || pattern.exec(value)?.[0] !== value)
    throw new SourceReadError('invalid_input');
  return value;
}
function sequence(value: unknown): string {
  const result = string(value, /^[1-9][0-9]{0,18}$/);
  if (BigInt(result) > 9223372036854775807n) throw new SourceReadError('invalid_state');
  return result;
}
function sameScope(actual: AccountScope, expected: AccountScope): boolean {
  return actual.tenantId === expected.tenantId && actual.accountId === expected.accountId;
}
function sameProvider(a: ProviderScope, b: ProviderScope): boolean {
  return (
    a.tenantId === b.tenantId &&
    a.provider === b.provider &&
    a.providerAccountId === b.providerAccountId
  );
}
function owner(
  value: SourceOwner,
  provider: 'livekit' | 'fake_sms',
  tenantId: string,
): SourceOwner {
  const v = fields(value, ['providerScope', 'dispatch', 'prepared']);
  const p = fields(v.providerScope, ['tenantId', 'provider', 'providerAccountId']);
  if (p.tenantId !== tenantId || p.provider !== provider)
    throw new SourceReadError('invalid_input');
  const inspect = snapshotMethod<SourceOwner['dispatch']['inspect']>(v.dispatch, 'inspect');
  const readPrepared = snapshotMethod<SourceOwner['prepared']['readPrepared']>(
    v.prepared,
    'readPrepared',
  );
  return Object.freeze({
    providerScope: Object.freeze({
      tenantId,
      provider,
      providerAccountId: string(p.providerAccountId, P2ID),
    }),
    dispatch: Object.freeze({
      inspect,
    }),
    prepared: Object.freeze({
      readPrepared,
    }),
  });
}
export function sourceReadFailure(error: unknown): SourceReadError {
  try {
    const known =
      error instanceof SourceReadError ||
      error instanceof ChannelError ||
      error instanceof ContractError;
    const descriptor = known ? Object.getOwnPropertyDescriptor(error, 'code') : undefined;
    const code =
      descriptor && 'value' in descriptor && typeof descriptor.value === 'string'
        ? (descriptor.value as string)
        : undefined;
    if (error instanceof SourceReadError)
      return new SourceReadError(
        code !== undefined && CODES.has(code) ? (code as ReadCode) : 'unavailable',
      );
    if (error instanceof ContractError)
      return new SourceReadError(code === 'AccessDenied' ? 'unauthorized' : 'invalid_state');
    if (error instanceof ChannelError) {
      if (code === 'NotFound') return new SourceReadError('not_found');
      if (code === 'AccessDenied') return new SourceReadError('unauthorized');
      if (code === 'Overloaded') return new SourceReadError('capacity');
      if (
        code !== undefined &&
        ['SchemaMismatch', 'IdentityConflict', 'OperationConflict'].includes(code)
      )
        return new SourceReadError('invalid_state');
    }
  } catch {
    // Invalid dependency observations cannot supply a diagnostic or execute a getter.
  }
  return new SourceReadError('unavailable');
}

function duration(value: number): number {
  if (!Number.isSafeInteger(value) || value < 20 || value > 5000)
    throw new SourceReadError('invalid_input');
  return value;
}
/** Own at most two complete reads; timed-out waiters retain their actual slots.
 * Borrow all P2 owners. close() drains reads; the application then closes P2.
 */
export class ChannelPolicySourceReader {
  readonly #config: SourceReaderConfiguration;
  readonly #timeoutMs: number;
  readonly #cleanupMs: number;
  readonly #actual = new Set<Promise<unknown>>();
  #closing = false;
  #completed = 0;
  #failed = 0;
  constructor(configuration: SourceReaderConfiguration, timeoutMs = 2000, cleanupMs = 1000) {
    try {
      const c = fields(configuration, [
        'profileId',
        'scope',
        'caseId',
        'conversationId',
        'accountToken',
        'inbox',
        'sources',
      ]);
      const s = fields(c.scope, ['tenantId', 'accountId']);
      const sources = fields(c.sources, ['native', 'sms']);
      const scope = Object.freeze({
        tenantId: string(s.tenantId, ID),
        accountId: string(s.accountId, ID),
      });
      const history = snapshotMethod<SourceReaderConfiguration['inbox']['history']>(
        c.inbox,
        'history',
      );
      const inspect = snapshotMethod<SourceReaderConfiguration['inbox']['inspect']>(
        c.inbox,
        'inspect',
      );
      this.#timeoutMs = duration(timeoutMs);
      this.#cleanupMs = duration(cleanupMs);
      this.#config = Object.freeze({
        profileId: string(c.profileId, UUID),
        scope,
        caseId: string(c.caseId, ID),
        conversationId: string(c.conversationId, ID),
        accountToken: string(c.accountToken, /^[A-Za-z0-9_-]{43}$/),
        inbox: Object.freeze({
          history,
          inspect,
        }),
        sources: Object.freeze({
          native: owner(sources.native as SourceOwner, 'livekit', scope.tenantId),
          sms: owner(sources.sms as SourceOwner, 'fake_sms', scope.tenantId),
        }),
      });
    } catch {
      throw new SourceReadError('invalid_input');
    }
  }
  metrics(): Readonly<{ active: number; completed: number; failed: number; closing: boolean }> {
    return Object.freeze({
      active: this.#actual.size,
      completed: this.#completed,
      failed: this.#failed,
      closing: this.#closing,
    });
  }
  #run<T>(action: () => Promise<T>): Promise<T> {
    if (this.#closing) return Promise.reject(new SourceReadError('closed'));
    if (this.#actual.size >= 2) return Promise.reject(new SourceReadError('capacity'));
    // Defer user code until the actual lifetime is registered, including sync throws.
    const actual = Promise.resolve()
      .then(action)
      .then(
        (result) => {
          this.#completed++;
          return result;
        },
        (error) => {
          this.#failed++;
          throw sourceReadFailure(error);
        },
      );
    this.#actual.add(actual);
    void actual.then(
      () => this.#actual.delete(actual),
      () => this.#actual.delete(actual),
    );
    let timer: ReturnType<typeof setTimeout>;
    const timeout = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new SourceReadError('unavailable')), this.#timeoutMs);
    });
    return Promise.race([actual, timeout]).finally(() => clearTimeout(timer));
  }
  #source(
    message: StoredMessage,
  ): Readonly<{ id: SourceId; owner: SourceOwner; event: TextEvent }> {
    const c = this.#config,
      e = message.event;
    const selected: SourceId | undefined = sameProvider(
      e.providerScope,
      c.sources.native.providerScope,
    )
      ? 'native'
      : sameProvider(e.providerScope, c.sources.sms.providerScope)
        ? 'sms'
        : undefined;
    if (selected === undefined) throw new SourceReadError('unauthorized');
    const source = c.sources[selected];
    const validated = parseEventJson(JSON.stringify(e), {
      providerScope: source.providerScope,
      accountScope: c.scope,
    }).event;
    if (
      validated.type !== 'text.received' ||
      validated.caseId !== c.caseId ||
      validated.conversationId !== c.conversationId ||
      (selected === 'sms'
        ? validated.channel !== 'sms'
        : !['web_chat', 'voice_transcript'].includes(validated.channel))
    )
      throw new SourceReadError('unauthorized');
    string(message.receipt.receiptId, UUID);
    string(message.operationKey, UUID);
    sequence(message.receipt.acceptanceSequence);
    requireValue(
      message.receipt.eventId === validated.eventId &&
        message.receipt.messageId === validated.messageId,
    );
    return Object.freeze({ id: selected, owner: source, event: validated });
  }
  discover(): Promise<DiscoveryPage> {
    return this.#run(async () => {
      const c = this.#config;
      const history = await c.inbox.history(c.accountToken, { after: '0', limit: DISCOVERY_ITEMS });
      requireValue(Array.isArray(history.messages) && history.messages.length <= DISCOVERY_ITEMS);
      const items: DiscoveryItem[] = [];
      const receipts = new Set<string>(),
        operations = new Set<string>(),
        work = new Set<string>();
      for (const message of history.messages) {
        const source = this.#source(message);
        const observed = await source.owner.dispatch.inspect(
          c.accountToken,
          message.receipt.receiptId,
        );
        requireValue(
          observed.receiptId === message.receipt.receiptId &&
            observed.operationKey === message.operationKey,
        );
        requireValue(STATES.has(observed.state) && typeof observed.possibleExternal === 'boolean');
        if (observed.externalReceiptId !== null) string(observed.externalReceiptId, UUID);
        requireValue(
          observed.state === 'dispatched'
            ? observed.possibleExternal && observed.externalReceiptId !== null
            : observed.externalReceiptId === null,
        );
        requireValue(!receipts.has(observed.receiptId) && !operations.has(observed.operationKey));
        receipts.add(observed.receiptId);
        operations.add(observed.operationKey);
        if (observed.externalReceiptId !== null) {
          requireValue(!work.has(observed.externalReceiptId));
          work.add(observed.externalReceiptId);
        }
        const last = items.at(-1);
        requireValue(
          last === undefined ||
            BigInt(last.acceptanceSequence) < BigInt(message.receipt.acceptanceSequence),
        );
        items.push(
          Object.freeze({
            receiptId: observed.receiptId,
            operationKey: observed.operationKey,
            acceptanceSequence: message.receipt.acceptanceSequence,
            sourceBindingId: source.id,
            state: observed.state,
            possibleExternal: observed.possibleExternal,
            externalReceiptId: observed.externalReceiptId,
          }),
        );
      }
      const overflow = history.nextCursor !== undefined;
      requireValue(
        !overflow ||
          (items.length === DISCOVERY_ITEMS &&
            history.nextCursor === items.at(-1)!.acceptanceSequence),
      );
      const page: DiscoveryPage = Object.freeze({
        schemaVersion: 1,
        kind: 'channel.policy_discovery',
        profileId: c.profileId,
        scope: c.scope,
        caseId: c.caseId,
        conversationId: c.conversationId,
        readCompletedAt: new Date().toISOString(),
        items: Object.freeze(items),
        overflow,
        nextCursor: overflow ? history.nextCursor! : null,
      });
      requireValue(Buffer.byteLength(JSON.stringify(page), 'utf8') <= DISCOVERY_BYTES);
      return page;
    });
  }
  /** Source labels are consistency checks; persisted provider identity selects the owner. */
  prepared(receiptId: string, expectedSource: SourceId): Promise<Buffer | null> {
    try {
      string(receiptId, UUID);
      if (expectedSource !== 'native' && expectedSource !== 'sms')
        throw new SourceReadError('invalid_input');
    } catch (error) {
      return Promise.reject(sourceReadFailure(error));
    }
    return this.#run(async () => {
      const c = this.#config;
      const message = await c.inbox.inspect(c.accountToken, receiptId);
      requireValue(message.receipt.receiptId === receiptId);
      const selected = this.#source(message);
      if (selected.id !== expectedSource) throw new SourceReadError('unauthorized');
      const p: PreparedDispatch | null = await selected.owner.prepared.readPrepared(
        c.accountToken,
        receiptId,
      );
      if (p === null) return null;
      const s = p.submission,
        m = s.message,
        e = selected.event;
      const normalized = {
        schemaVersion: 1,
        kind: 'investigation',
        operationKey: message.operationKey,
        scope: c.scope,
        caseId: c.caseId,
        caseRevision: s.caseRevision,
        conversationId: c.conversationId,
        message: {
          receiptId,
          eventId: e.eventId,
          messageId: e.messageId,
          senderId: e.senderId,
          body: e.body,
        },
      };
      requireValue(
        s.schemaVersion === 1 &&
          s.kind === 'investigation' &&
          s.operationKey === message.operationKey &&
          sameScope(s.scope, c.scope) &&
          s.caseId === c.caseId &&
          s.conversationId === c.conversationId &&
          m.receiptId === receiptId &&
          m.eventId === e.eventId &&
          m.messageId === e.messageId &&
          m.senderId === e.senderId &&
          m.body === e.body &&
          typeof s.caseRevision === 'string' &&
          /^[1-9][0-9]{0,6}$/.exec(s.caseRevision)?.[0] === s.caseRevision &&
          BigInt(s.caseRevision) <= 1000000n &&
          p.canonicalPayload === JSON.stringify(normalized) &&
          Buffer.byteLength(p.canonicalPayload, 'utf8') <= PREPARED_BYTES &&
          p.payloadDigest === createHash('sha256').update(p.canonicalPayload, 'utf8').digest('hex'),
      );
      const frame = Buffer.from(
        JSON.stringify({
          schemaVersion: 1,
          canonicalPayload: p.canonicalPayload,
          payloadDigest: p.payloadDigest,
        }),
        'utf8',
      );
      requireValue(frame.byteLength <= PREPARED_BYTES);
      return frame;
    });
  }
  async close(): Promise<void> {
    this.#closing = true;
    if (this.#actual.size === 0) return;
    let timer: ReturnType<typeof setTimeout>;
    try {
      await Promise.race([
        Promise.allSettled([...this.#actual]),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(
            () => reject(new SourceReadError('cleanup_incomplete')),
            this.#cleanupMs,
          );
        }),
      ]);
    } finally {
      clearTimeout(timer!);
    }
    if (this.#actual.size !== 0) throw new SourceReadError('cleanup_incomplete');
  }
}
