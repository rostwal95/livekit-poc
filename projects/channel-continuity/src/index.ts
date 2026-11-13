/** Versioned data contracts. Parsing does not authenticate or acknowledge acceptance. */
export type ProviderScope = Readonly<{
  tenantId: string;
  provider: string;
  providerAccountId: string;
}>;
export type AccountScope = Readonly<{ tenantId: string; accountId: string }>;
/** Supplied only by a trusted authenticated adapter, never by event JSON. */
export type TrustedPrincipal = Readonly<{
  providerScope: ProviderScope;
  accountScope?: AccountScope;
}>;
type BaseEvent = Readonly<{
  schemaVersion: 1;
  eventId: string;
  providerScope: ProviderScope;
  accountScope?: AccountScope;
  conversationId: string;
  caseId?: string;
  occurredAt?: string;
  receivedAt: string;
  causationId?: string;
  retryCount?: number;
  signature?: string;
}>;
export type TextEvent = BaseEvent &
  Readonly<{
    type: 'text.received';
    channel: 'web_chat' | 'sms' | 'voice_transcript';
    messageId: string;
    senderId: string;
    body: string;
    expectedCaseRevision?: number;
    replyToResponseId?: string;
  }>;
export type ChannelEvent =
  | TextEvent
  | (BaseEvent & Readonly<{ type: 'response.generated'; responseId: string; body: string }>)
  | (BaseEvent &
      Readonly<{
        type: 'playback.reported';
        responseId: string;
        source: 'agent_sdk' | 'browser_client';
        state: 'started' | 'partial' | 'completed' | 'interrupted';
        playedText?: string;
      }>)
  | (BaseEvent &
      Readonly<{
        type: 'delivery.reported';
        messageId: string;
        state: 'accepted_by_provider' | 'delivered' | 'failed' | 'unknown' | 'read_reported';
      }>)
  | (BaseEvent & Readonly<{ type: 'user.acknowledged'; responseId: string; messageId: string }>);
export type TextEventInput = Omit<TextEvent, 'schemaVersion' | 'type'>;
export type ErrorCode =
  | 'InvalidEvent'
  | 'UnsupportedEventVersion'
  | 'AccessDenied'
  | 'AssociationRequired'
  | 'IdentityConflict'
  | 'RevisionConflict'
  | 'ClarificationRequired'
  | 'Overloaded'
  | 'OutcomeUnknown';
export class ContractError extends Error {
  constructor(readonly code: ErrorCode = 'InvalidEvent') {
    super(code);
    this.name = 'ContractError';
  }
}
export type DecodedEvent = Readonly<{
  event: ChannelEvent;
  canonical: string;
  identity: string;
  wireJson: string;
}>;
/** Future persisted runtime contracts; this codec implements no acceptance service. */
export type Receipt = Readonly<{
  receiptId: string;
  messageId: string;
  acceptanceSequence: string;
  status: 'accepted' | 'duplicate';
}>;
export type ReplyIntent = Readonly<{
  replyId: string;
  recipient: AccountScope;
  conversationId: string;
  body: string;
}>;
export type MessageRecord = Readonly<{ receipt: Receipt; event: ChannelEvent }>;
export type HistoryPage = Readonly<{ messages: readonly MessageRecord[]; nextCursor?: string }>;
export interface ChannelContinuity {
  accept(event: ChannelEvent, principal: TrustedPrincipal): Promise<Receipt>;
  inspect(messageId: string, principal: TrustedPrincipal): Promise<MessageRecord>;
  history(conversationId: string, principal: TrustedPrincipal): Promise<HistoryPage>;
  enqueueReply(reply: ReplyIntent, principal: TrustedPrincipal): Promise<Receipt>;
}
export const MAX_WIRE_BYTES = 32768;
export const MAX_TEXT_BYTES = 4096;
const MAX_SAFE_INTEGER = 9007199254740991;
const common = [
  'schemaVersion',
  'eventId',
  'providerScope',
  'conversationId',
  'receivedAt',
  'type',
];
const optionalCommon = [
  'accountScope',
  'caseId',
  'occurredAt',
  'causationId',
  'retryCount',
  'signature',
];
type Rule = 'id' | 'text' | 'revision' | readonly string[];
const specs: Record<string, readonly [Record<string, Rule>, Record<string, Rule>]> = {
  'text.received': [
    {
      channel: ['web_chat', 'sms', 'voice_transcript'],
      messageId: 'id',
      senderId: 'id',
      body: 'text',
    },
    { expectedCaseRevision: 'revision', replyToResponseId: 'id' },
  ],
  'response.generated': [{ responseId: 'id', body: 'text' }, {}],
  'playback.reported': [
    {
      responseId: 'id',
      source: ['agent_sdk', 'browser_client'],
      state: ['started', 'partial', 'completed', 'interrupted'],
    },
    { playedText: 'text' },
  ],
  'delivery.reported': [
    {
      messageId: 'id',
      state: ['accepted_by_provider', 'delivered', 'failed', 'unknown', 'read_reported'],
    },
    {},
  ],
  'user.acknowledged': [{ responseId: 'id', messageId: 'id' }, {}],
};
function text(value: unknown, maximum: number, empty = false): string {
  if (typeof value !== 'string' || value.length > maximum || (!empty && value.length === 0))
    throw new ContractError();
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(++i);
      if (!(next >= 0xdc00 && next <= 0xdfff)) throw new ContractError();
    } else if (code >= 0xdc00 && code <= 0xdfff) throw new ContractError();
  }
  if (new TextEncoder().encode(value).length > maximum) throw new ContractError();
  return value;
}
function identifier(value: unknown): string {
  const result = text(value, 128);
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}(?![\s\S])/.test(result)) throw new ContractError();
  return result;
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new ContractError();
  return value as Record<string, unknown>;
}
function exact(value: Record<string, unknown>, keys: readonly string[]): void {
  if (Object.keys(value).length !== keys.length || keys.some((key) => !Object.hasOwn(value, key)))
    throw new ContractError();
}
function timestamp(value: unknown): void {
  const result = text(value, 24);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(result) || result.startsWith('0000-'))
    throw new ContractError();
  try {
    if (new Date(result).toISOString() !== result) throw new ContractError();
  } catch {
    throw new ContractError();
  }
}
/** Bounded recursive JSON parser retaining duplicate-key evidence before projection. */
function strictJson(raw: string): unknown {
  let offset = 0;
  function whitespace(): void {
    while (offset < raw.length && /[\x20\t\n\r]/.test(raw[offset]!)) offset++;
  }
  function string(): string {
    const start = offset++;
    let escaped = false;
    while (offset < raw.length) {
      const character = raw[offset++]!;
      if (character === '"' && !escaped) {
        let parsed: unknown;
        try {
          parsed = JSON.parse(raw.slice(start, offset));
        } catch {
          throw new ContractError();
        }
        return text(parsed, MAX_WIRE_BYTES, true);
      }
      if (character === '\\' && !escaped) escaped = true;
      else escaped = false;
    }
    throw new ContractError();
  }
  function value(depth: number): unknown {
    whitespace();
    if (depth > 8) throw new ContractError();
    const character = raw[offset];
    if (character === '"') return string();
    if (character === '{') {
      offset++;
      whitespace();
      const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
      if (raw[offset] === '}') {
        offset++;
        return result;
      }
      let count = 0;
      while (true) {
        whitespace();
        if (raw[offset] !== '"' || ++count > 64) throw new ContractError();
        const key = string();
        text(key, 128);
        if (Object.hasOwn(result, key)) throw new ContractError();
        whitespace();
        if (raw[offset++] !== ':') throw new ContractError();
        result[key] = value(depth + 1);
        whitespace();
        const separator = raw[offset++];
        if (separator === '}') return result;
        if (separator !== ',') throw new ContractError();
      }
    }
    if (character === '[') {
      offset++;
      whitespace();
      const result: unknown[] = [];
      if (raw[offset] === ']') {
        offset++;
        return result;
      }
      while (true) {
        if (result.length >= 64) throw new ContractError();
        result.push(value(depth + 1));
        whitespace();
        const separator = raw[offset++];
        if (separator === ']') return result;
        if (separator !== ',') throw new ContractError();
      }
    }
    for (const [literal, parsed] of [
      ['true', true],
      ['false', false],
      ['null', null],
    ] as const) {
      if (raw.startsWith(literal, offset)) {
        offset += literal.length;
        return parsed;
      }
    }
    const numeric = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(raw.slice(offset))?.[0];
    if (!numeric || !/^(?:0|[1-9]\d*)$/.test(numeric)) throw new ContractError();
    const parsed = Number(numeric);
    if (!Number.isSafeInteger(parsed) || parsed > MAX_SAFE_INTEGER) throw new ContractError();
    offset += numeric.length;
    return parsed;
  }
  const parsed = value(0);
  whitespace();
  if (offset !== raw.length) throw new ContractError();
  return parsed;
}
function asciiString(value: string): string {
  let result = '"';
  const short: Record<number, string> = {
    8: '\\b',
    9: '\\t',
    10: '\\n',
    12: '\\f',
    13: '\\r',
    34: '\\"',
    92: '\\\\',
  };
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    result +=
      short[code] ??
      (code < 32 || code >= 127 ? `\\u${code.toString(16).padStart(4, '0')}` : value[i]);
  }
  return result + '"';
}
function canonical(value: unknown): string {
  if (typeof value === 'string') return asciiString(value);
  if (value === null || typeof value === 'boolean' || typeof value === 'number')
    return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  const object = record(value);
  return (
    '{' +
    Object.keys(object)
      .sort()
      .map((key) => asciiString(key) + ':' + canonical(object[key]))
      .join(',') +
    '}'
  );
}
function freeze(value: unknown): void {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
}
export function parseEventJson(raw: string, principal: TrustedPrincipal): DecodedEvent {
  text(raw, MAX_WIRE_BYTES);
  const event = record(strictJson(raw));
  if (typeof event.schemaVersion !== 'number') throw new ContractError();
  if (event.schemaVersion !== 1) throw new ContractError('UnsupportedEventVersion');
  const specification =
    typeof event.type === 'string' && Object.hasOwn(specs, event.type)
      ? specs[event.type]
      : undefined;
  if (!specification) throw new ContractError();
  const [required, optional] = specification;
  const allowed = new Set([
    ...common,
    ...optionalCommon,
    ...Object.keys(required),
    ...Object.keys(optional),
  ]);
  if (
    [...common, ...Object.keys(required)].some((key) => !Object.hasOwn(event, key)) ||
    Object.keys(event).some((key) => !allowed.has(key))
  )
    throw new ContractError();
  for (const key of ['eventId', 'conversationId', 'caseId', 'causationId'])
    if (Object.hasOwn(event, key)) identifier(event[key]);
  timestamp(event.receivedAt);
  if (Object.hasOwn(event, 'occurredAt')) timestamp(event.occurredAt);
  if (Object.hasOwn(event, 'signature')) text(event.signature, 256);
  if (
    Object.hasOwn(event, 'retryCount') &&
    !(
      typeof event.retryCount === 'number' &&
      Number.isSafeInteger(event.retryCount) &&
      event.retryCount >= 0 &&
      event.retryCount <= 1000000
    )
  )
    throw new ContractError();
  const trusted = record(principal);
  exact(
    trusted,
    principal.accountScope === undefined ? ['providerScope'] : ['providerScope', 'accountScope'],
  );
  const provider = record(event.providerScope);
  exact(provider, ['tenantId', 'provider', 'providerAccountId']);
  const expectedProvider = record(trusted.providerScope);
  exact(expectedProvider, ['tenantId', 'provider', 'providerAccountId']);
  Object.values(provider).forEach(identifier);
  Object.values(expectedProvider).forEach(identifier);
  if (canonical(provider) !== canonical(expectedProvider)) throw new ContractError('AccessDenied');
  if (principal.accountScope !== undefined) {
    const expectedAccount = record(principal.accountScope);
    exact(expectedAccount, ['tenantId', 'accountId']);
    Object.values(expectedAccount).forEach(identifier);
    if (expectedAccount.tenantId !== expectedProvider.tenantId)
      throw new ContractError('AccessDenied');
  }
  if (Object.hasOwn(event, 'accountScope')) {
    const account = record(event.accountScope);
    exact(account, ['tenantId', 'accountId']);
    Object.values(account).forEach(identifier);
    if (!principal.accountScope || canonical(account) !== canonical(principal.accountScope))
      throw new ContractError('AccessDenied');
  } else if (principal.accountScope || Object.hasOwn(event, 'caseId'))
    throw new ContractError('AssociationRequired');
  for (const [key, rule] of Object.entries({ ...required, ...optional })) {
    if (!Object.hasOwn(event, key)) continue;
    const item = event[key];
    if (rule === 'id') identifier(item);
    else if (rule === 'text') text(item, MAX_TEXT_BYTES, true);
    else if (rule === 'revision') {
      if (!(typeof item === 'number' && Number.isSafeInteger(item) && item >= 0))
        throw new ContractError();
    } else if (typeof item !== 'string' || !rule.includes(item)) throw new ContractError();
  }
  const semantic = Object.fromEntries(
    Object.entries(event).filter(
      ([key]) => !['receivedAt', 'retryCount', 'signature'].includes(key),
    ),
  );
  const result = {
    event: event as unknown as ChannelEvent,
    canonical: canonical(semantic),
    identity: canonical([
      provider.tenantId,
      provider.provider,
      provider.providerAccountId,
      event.eventId,
    ]),
    wireJson: canonical(event),
  };
  freeze(result);
  return result;
}
function jsonData(value: unknown, depth = 0, budget = { nodes: 256, utf8: MAX_WIRE_BYTES }): void {
  // Count shared descendants per visit so DAG reuse cannot amplify traversal.
  if (depth > 8 || --budget.nodes < 0) throw new ContractError();
  if (value === null || typeof value === 'boolean') return;
  if (typeof value === 'string') {
    text(value, MAX_WIRE_BYTES, true);
    budget.utf8 -= new TextEncoder().encode(value).length;
    if (budget.utf8 < 0) throw new ContractError();
    return;
  }
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value) || value < 0 || Object.is(value, -0))
      throw new ContractError();
    return;
  }
  if (!value || typeof value !== 'object') throw new ContractError();
  if (Array.isArray(value)) throw new ContractError();
  if (Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null)
    throw new ContractError();
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (Object.keys(descriptors).length > 64 || Object.getOwnPropertySymbols(value).length > 0)
    throw new ContractError();
  for (const [key, descriptor] of Object.entries(descriptors)) {
    text(key, 128);
    budget.utf8 -= new TextEncoder().encode(key).length;
    if (budget.utf8 < 0) throw new ContractError();
    if (!('value' in descriptor) || !descriptor.enumerable) throw new ContractError();
    jsonData(descriptor.value, depth + 1, budget);
  }
}
export function produceTextEvent(
  fields: TextEventInput,
  principal: TrustedPrincipal,
): DecodedEvent {
  try {
    record(fields);
    jsonData(fields);
    if ('type' in fields || 'schemaVersion' in fields) throw new ContractError();
    return parseEventJson(
      JSON.stringify({ ...fields, schemaVersion: 1, type: 'text.received' }),
      principal,
    );
  } catch (error) {
    if (error instanceof ContractError) throw error;
    throw new ContractError();
  }
}
export function canonicalEvent(event: DecodedEvent): string {
  return event.canonical;
}
export function eventIdentity(event: DecodedEvent): string {
  return event.identity;
}
