/** Pure browser policy: media transport and output never imply durable acceptance. */
export const NATIVE_TEXT_BYTES = 2048;
export const NATIVE_ACK_BYTES = 2048;
export const NATIVE_HISTORY_LIMIT = 32;
export const NATIVE_INPUT_ATTRIBUTE = 'p2.input_id';
const utf8 = new TextEncoder();
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/;
const IDENTITY = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}(?![\s\S])/;
const SEQUENCE = /^[1-9][0-9]{0,18}(?![\s\S])/;
const CODES = new Set([
  'invalid_input',
  'forbidden',
  'idempotency_conflict',
  'capacity_exhausted',
  'dependency_unavailable',
  'acknowledgement_unknown',
  'closed',
]);
export type NativeChannel = 'web_chat' | 'voice_transcript';
export type NativeInputStatus = 'pending' | 'accepted' | 'replayed' | 'unknown' | 'rejected';
export class NativeUiError extends Error {
  constructor(
    readonly code: 'invalid' | 'capacity' | 'unknown',
    message: string,
  ) {
    super(message);
  }
}
function invalid(): never {
  throw new NativeUiError('invalid', 'The local native session data could not be verified.');
}
function record(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  )
    return invalid();
  const own = Object.getOwnPropertyDescriptors(value);
  if (
    Reflect.ownKeys(own).length !== keys.length ||
    keys.some((key) => !Object.hasOwn(own, key) || !Object.hasOwn(own[key]!, 'value'))
  )
    return invalid();
  return Object.fromEntries(keys.map((key) => [key, own[key]!.value as unknown]));
}
function wellFormed(value: string): boolean {
  for (let n = 0; n < value.length; n++) {
    const code = value.charCodeAt(n);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(++n);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
    } else if (code >= 0xdc00 && code <= 0xdfff) return false;
  }
  return true;
}
function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID.test(value);
}
function isIdentity(value: unknown): value is string {
  return typeof value === 'string' && IDENTITY.test(value);
}
function flatJson(raw: string, count: number): unknown {
  try {
    const keys = [...raw.matchAll(/"((?:[^"\\]|\\.)*)"\s*:/gu)].map(
      (match) => JSON.parse('"' + match[1]! + '"') as unknown,
    );
    if (
      keys.length !== count ||
      keys.some((key) => typeof key !== 'string') ||
      new Set(keys).size !== keys.length
    )
      return invalid();
    return JSON.parse(raw) as unknown;
  } catch {
    return invalid();
  }
}
export interface NativeSession {
  readonly schemaVersion: 1;
  readonly url: string;
  readonly token: string;
  readonly roomId: string;
  readonly participantId: string;
  readonly agentId: string;
  readonly bindingId: string;
}
export function parseNativeSession(value: unknown): NativeSession {
  const row = record(value, [
    'schemaVersion',
    'url',
    'token',
    'roomId',
    'participantId',
    'agentId',
    'bindingId',
  ]);
  if (
    row.schemaVersion !== 1 ||
    typeof row.url !== 'string' ||
    row.url.length > 256 ||
    typeof row.token !== 'string' ||
    !row.token ||
    utf8.encode(row.token).length > 8192 ||
    /[\s\x00-\x1f\x7f]/u.test(row.token) ||
    !isIdentity(row.roomId) ||
    !isIdentity(row.participantId) ||
    !isIdentity(row.agentId) ||
    row.participantId === row.agentId ||
    !isUuid(row.bindingId)
  )
    return invalid();
  let url: URL;
  try {
    url = new URL(row.url);
  } catch {
    return invalid();
  }
  if (
    !['ws:', 'wss:'].includes(url.protocol) ||
    !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== '/'
  )
    return invalid();
  return Object.freeze(row) as unknown as NativeSession;
}
export function nativeReady(
  connected: boolean,
  expected: NativeSession | null,
  identity: string | null,
  kind: 'agent' | 'other',
  attributes: Readonly<Record<string, string>>,
): boolean {
  return (
    connected &&
    expected !== null &&
    identity === expected.agentId &&
    kind === 'agent' &&
    attributes['p2.session_ready'] === 'true' &&
    attributes['p2.inference_mode'] === 'scripted' &&
    ['idle', 'listening', 'thinking', 'speaking'].includes(attributes['lk.agent.state'] ?? '')
  );
}
export interface FrozenNativeInput {
  readonly inputId: string;
  readonly channel: NativeChannel;
  readonly body: string | null;
}
export function freezeNativeInput(
  inputId: string,
  channel: NativeChannel,
  body: string | null,
): FrozenNativeInput {
  if (!isUuid(inputId) || !['web_chat', 'voice_transcript'].includes(channel)) return invalid();
  if (
    channel === 'web_chat'
      ? typeof body !== 'string' ||
        !wellFormed(body) ||
        body.trim().length === 0 ||
        utf8.encode(body).length > NATIVE_TEXT_BYTES ||
        /[\x00]/u.test(body)
      : body !== null
  )
    return invalid();
  return Object.freeze({ inputId, channel, body });
}
export interface NativeAck {
  readonly schemaVersion: 1;
  readonly bindingId: string;
  readonly inputId: string;
  readonly channel: NativeChannel;
  readonly status: Exclude<NativeInputStatus, 'pending'>;
  readonly receiptId: string | null;
  readonly operationKey: string | null;
  readonly acceptanceSequence: string | null;
  readonly code: string | null;
}
export function parseNativeAck(raw: Uint8Array, bindingId: string): NativeAck {
  if (!isUuid(bindingId) || raw.byteLength === 0 || raw.byteLength > NATIVE_ACK_BYTES)
    return invalid();
  let parsed: unknown;
  try {
    const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
    // The flat fixed wire has no nested objects. Reject repeated fields before
    // JSON.parse could silently select one value, including escaped key aliases.
    parsed = flatJson(text, 9);
  } catch {
    return invalid();
  }
  const row = record(parsed, [
    'schemaVersion',
    'bindingId',
    'inputId',
    'channel',
    'status',
    'receiptId',
    'operationKey',
    'acceptanceSequence',
    'code',
  ]);
  if (
    row.schemaVersion !== 1 ||
    row.bindingId !== bindingId ||
    !isUuid(row.inputId) ||
    !['web_chat', 'voice_transcript'].includes(row.channel as string) ||
    !['accepted', 'replayed', 'unknown', 'rejected'].includes(row.status as string)
  )
    return invalid();
  if (row.status === 'accepted' || row.status === 'replayed') {
    if (
      !isUuid(row.receiptId) ||
      !isUuid(row.operationKey) ||
      typeof row.acceptanceSequence !== 'string' ||
      !SEQUENCE.test(row.acceptanceSequence) ||
      BigInt(row.acceptanceSequence) > 9223372036854775807n ||
      row.code !== null
    )
      return invalid();
  } else if (
    row.receiptId !== null ||
    row.operationKey !== null ||
    row.acceptanceSequence !== null ||
    typeof row.code !== 'string' ||
    !CODES.has(row.code) ||
    (row.status === 'unknown'
      ? row.code !== 'acknowledgement_unknown'
      : row.code === 'acknowledgement_unknown')
  )
    return invalid();
  return Object.freeze(row) as unknown as NativeAck;
}
export type TurnMethod = 'p2.start_turn' | 'p2.commit_turn' | 'p2.interrupt';
export function turnPayload(method: TurnMethod, inputId: string | null): string {
  if (method === 'p2.interrupt') {
    if (inputId !== null) return invalid();
    return '{"schemaVersion":1}';
  }
  if (!['p2.start_turn', 'p2.commit_turn'].includes(method) || !isUuid(inputId)) return invalid();
  return JSON.stringify({ schemaVersion: 1, inputId });
}
export function parseNativeTurnReply(
  raw: string,
  method: TurnMethod,
  inputId: string | null,
): string {
  turnPayload(method, inputId);
  if (typeof raw !== 'string' || utf8.encode(raw).length > 256) return invalid();
  let value: unknown;
  try {
    value = flatJson(raw, 3);
  } catch {
    return invalid();
  }
  const row = record(value, ['schemaVersion', 'status', 'inputId']);
  const states =
    method === 'p2.start_turn'
      ? ['turn_started']
      : method === 'p2.commit_turn'
        ? ['turn_committed', 'no_audio']
        : ['speech_interrupted'];
  if (row.schemaVersion !== 1 || row.inputId !== inputId || !states.includes(row.status as string))
    return invalid();
  return row.status as string;
}
export interface NativeInputView extends FrozenNativeInput {
  readonly status: NativeInputStatus;
  readonly receiptId: string | null;
  readonly operationKey: string | null;
  readonly acceptanceSequence: string | null;
}
export class NativeInputs {
  readonly #rows = new Map<string, NativeInputView>();
  #last: string | null = null;
  add(input: FrozenNativeInput): NativeInputView {
    const frozen = freezeNativeInput(input.inputId, input.channel, input.body);
    const previous = this.#rows.get(frozen.inputId);
    if (previous) {
      if (previous.channel !== frozen.channel || previous.body !== frozen.body)
        throw new NativeUiError(
          'invalid',
          'Reuse the original input unchanged, or create a new input.',
        );
      return previous;
    }
    if (this.#rows.size >= NATIVE_HISTORY_LIMIT)
      throw new NativeUiError(
        'capacity',
        'This demo session has reached its retained input limit.',
      );
    const row = Object.freeze({
      ...frozen,
      status: 'pending' as const,
      receiptId: null,
      operationKey: null,
      acceptanceSequence: null,
    });
    this.#rows.set(row.inputId, row);
    this.#last = row.inputId;
    return row;
  }
  apply(ack: NativeAck): boolean {
    const previous = this.#rows.get(ack.inputId);
    if (!previous || previous.channel !== ack.channel) return false;
    // A later rejected retry cannot establish that an earlier uncertain send
    // never committed. Only a known original receipt resolves that uncertainty.
    if (previous.status === 'unknown' && ack.status === 'rejected') return false;
    // Known accepted identity is immutable; late absence/error cannot erase it.
    if (previous.receiptId !== null) {
      if (ack.status === 'unknown' || ack.status === 'rejected') return false;
      if (
        previous.receiptId !== ack.receiptId ||
        previous.operationKey !== ack.operationKey ||
        previous.acceptanceSequence !== ack.acceptanceSequence
      )
        throw new NativeUiError(
          'unknown',
          'Conflicting acknowledgement; inspect the original input.',
        );
    }
    this.#rows.set(
      ack.inputId,
      Object.freeze({
        ...previous,
        status: ack.status,
        receiptId: ack.receiptId,
        operationKey: ack.operationKey,
        acceptanceSequence: ack.acceptanceSequence,
      }),
    );
    return true;
  }
  uncertain(inputId: string): void {
    const row = this.#rows.get(inputId);
    if (row && row.receiptId === null)
      this.#rows.set(inputId, Object.freeze({ ...row, status: 'unknown' }));
  }
  last(): NativeInputView | null {
    return this.#last === null ? null : (this.#rows.get(this.#last) ?? null);
  }
  values(): readonly NativeInputView[] {
    return Object.freeze([...this.#rows.values()]);
  }
}

/** SDK generation facts are independent of durable intake and browser playback. */
export interface NativeGeneration {
  readonly schemaVersion: 1;
  readonly bindingId: string;
  readonly inputId: string;
  readonly operationKey: string;
  readonly generationId: string;
  readonly status: 'started' | 'completed' | 'interrupted' | 'unknown';
}
export function parseNativeGeneration(raw: Uint8Array, bindingId: string): NativeGeneration {
  if (!isUuid(bindingId) || raw.byteLength === 0 || raw.byteLength > 1024) return invalid();
  let value: unknown;
  try {
    value = flatJson(new TextDecoder('utf-8', { fatal: true }).decode(raw), 6);
  } catch {
    return invalid();
  }
  const row = record(value, [
    'schemaVersion',
    'bindingId',
    'inputId',
    'operationKey',
    'generationId',
    'status',
  ]);
  if (
    row.schemaVersion !== 1 ||
    row.bindingId !== bindingId ||
    !isUuid(row.inputId) ||
    !isUuid(row.operationKey) ||
    !isUuid(row.generationId) ||
    row.generationId[14] !== '4' ||
    !['started', 'completed', 'interrupted', 'unknown'].includes(row.status as string)
  )
    return invalid();
  return Object.freeze(row) as unknown as NativeGeneration;
}
export class NativeGenerations {
  readonly #rows = new Map<string, NativeGeneration>();
  apply(value: NativeGeneration, inputs: NativeInputs): boolean {
    const input = inputs.values().find((row) => row.inputId === value.inputId);
    if (!input?.receiptId || input.operationKey !== value.operationKey) return false;
    const previous = this.#rows.get(value.generationId);
    if (previous) {
      if (
        previous.inputId !== value.inputId ||
        previous.operationKey !== value.operationKey ||
        previous.bindingId !== value.bindingId
      )
        throw new NativeUiError(
          'unknown',
          'The native generation reference conflicted with its original input.',
        );
      if (previous.status === 'completed' || previous.status === 'interrupted') {
        if (value.status === 'started' || value.status === 'unknown') return false;
        if (value.status !== previous.status)
          throw new NativeUiError('unknown', 'Conflicting native generation observations.');
      }
      if (previous.status === value.status) return false;
    } else if (this.#rows.size >= 64)
      throw new NativeUiError('capacity', 'The local native observation limit was reached.');
    this.#rows.set(value.generationId, Object.freeze({ ...value }));
    return true;
  }
  values(): readonly NativeGeneration[] {
    return Object.freeze([...this.#rows.values()]);
  }
  completedInputs(): number {
    return new Set(
      [...this.#rows.values()]
        .filter((row) => row.status === 'completed')
        .map((row) => row.inputId),
    ).size;
  }
}
