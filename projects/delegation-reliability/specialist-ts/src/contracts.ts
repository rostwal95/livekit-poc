import { createHash } from 'node:crypto';
export const MAX_REQUEST_BYTES = 16384;
export const MAX_RESULT_BYTES = 8192;
export const MAX_TIMESTAMP_MS = 4102444800000;
export const MAX_DEADLINE_WINDOW_MS = 60000;
export const CAPABILITY = 'booking.evaluate_policy' as const;
export const ERROR_CODES = [
  'invalid_json',
  'invalid_contract',
  'unsupported_version',
  'unknown_capability',
  'identity_conflict',
  'result_mismatch',
  'evidence_mismatch',
  'unsupported_facts',
  'unauthorized',
  'expired',
  'capacity',
  'unknown_attempt',
] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];
export class ContractError extends Error {
  readonly code: ErrorCode;
  constructor(code: ErrorCode = 'invalid_contract') {
    super(code);
    this.name = 'ContractError';
    this.code = code;
  }
}
export type Scope = Readonly<{
  tenant_id: string;
  account_id: string;
}>;
export type EvidenceRef = Readonly<{
  source_id: string;
  version: string;
  sha256: string;
  media_type: 'application/json' | 'image/png';
  byte_length: number;
  width: number | null;
  height: number | null;
}>;
export type ContextSnapshot = Readonly<{
  policy_version: string;
  policy_source_id: string;
  days_before_arrival: number;
  note: string;
}>;
export type DelegationRequest = Readonly<{
  schema_version: 1;
  kind: 'delegation.request';
  capability: typeof CAPABILITY;
  input_schema_version: 1;
  scope: Scope;
  delegation_id: string;
  case_id: string;
  request_revision: number;
  context_snapshot: ContextSnapshot;
  evidence: readonly EvidenceRef[];
  deadline_at_ms: number;
  result_route: Readonly<{
    conversation_id: string;
  }>;
  attempt: Readonly<{
    attempt_id: string;
    number: number;
  }>;
  input_fingerprint: string;
}>;
export type ResultEvidence = Readonly<{
  source_id: string;
  version: string;
  sha256: string;
  rule_id: string;
}>;
export type Producer = Readonly<{
  producer_id: string;
  model_id: string | null;
  model_version: string | null;
  config_fingerprint: string;
}>;
export type DelegationResult = Readonly<{
  schema_version: 1;
  kind: 'delegation.result';
  capability: typeof CAPABILITY;
  result_schema_version: 1;
  scope: Scope;
  delegation_id: string;
  case_id: string;
  request_revision: number;
  attempt_id: string;
  input_fingerprint: string;
  eligible: boolean | null;
  uncertainty: 'none' | 'missing' | 'conflicting';
  evidence_refs: readonly ResultEvidence[];
  producer: Producer;
  completed_at_ms: number;
}>;
export type ErrorEnvelope = Readonly<{
  schema_version: 1;
  kind: 'delegation.error';
  code: ErrorCode;
  request_id: string;
  retryable: false;
}>;
export function fields(value: unknown, expected: readonly string[]): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value))
    throw new ContractError();
  const keys = Reflect.ownKeys(value);
  if (
    keys.length !== expected.length ||
    keys.some((key) => typeof key !== 'string' || !expected.includes(key))
  )
    throw new ContractError();
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (
    keys.length !== expected.length ||
    keys.some((key) => typeof key !== 'string' || !expected.includes(key)) ||
    Object.values(descriptors).some((item) => !('value' in item) || !item.enumerable)
  )
    throw new ContractError();
  const result: Record<string, unknown> = Object.create(null);
  for (const key of expected) result[key] = descriptors[key]!.value;
  return result;
}
export function integer(value: unknown, min: number, max: number): number {
  if (
    typeof value !== 'number' ||
    !Number.isSafeInteger(value) ||
    Object.is(value, -0) ||
    value < min ||
    value > max
  )
    throw new ContractError();
  return value;
}
export function identifier(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-z][a-z0-9_-]{0,63}(?![\s\S])/.test(value))
    throw new ContractError();
  return value;
}
export function digest(value: unknown): string {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}(?![\s\S])/.test(value))
    throw new ContractError();
  return value;
}
export function text(value: unknown, maximum = 1024): string {
  if (
    typeof value !== 'string' ||
    value.length > maximum ||
    Buffer.byteLength(value, 'utf8') > maximum
  )
    throw new ContractError();
  for (let i = 0; i < value.length; i++) {
    const c = value.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const d = value.charCodeAt(++i);
      if (!(d >= 0xdc00 && d <= 0xdfff)) throw new ContractError();
    } else if (c >= 0xdc00 && c <= 0xdfff) throw new ContractError();
  }
  return value;
}
function boundedCopy(
  value: unknown,
  state = {
    nodes: 256,
    bytes: MAX_REQUEST_BYTES,
  },
  depth = 0,
  seen = new Set<object>(),
): unknown {
  if (--state.nodes < 0 || depth > 12) throw new ContractError('invalid_json');
  if (value === null || typeof value === 'boolean') return value;
  if (typeof value === 'number')
    return integer(value, -Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER);
  if (typeof value === 'string') {
    text(value, MAX_REQUEST_BYTES);
    state.bytes -= Buffer.byteLength(value, 'utf8');
    if (state.bytes < 0) throw new ContractError('invalid_json');
    return value;
  }
  if (typeof value !== 'object' || seen.has(value) || depth >= 12)
    throw new ContractError('invalid_json');
  const proto = Object.getPrototypeOf(value);
  if (proto !== Object.prototype && proto !== null && !Array.isArray(value))
    throw new ContractError('invalid_json');
  seen.add(value);
  try {
    if (Array.isArray(value)) {
      if (value.length > 256 || Reflect.ownKeys(value).length !== value.length + 1)
        throw new ContractError('invalid_json');
      const descriptors = Object.getOwnPropertyDescriptors(value);
      const output: unknown[] = [];
      for (let i = 0; i < value.length; i++) {
        const item = descriptors[String(i)];
        if (!item || !('value' in item)) throw new ContractError('invalid_json');
        output.push(boundedCopy(item.value, state, depth + 1, seen));
      }
      return output;
    }
    const keys = Reflect.ownKeys(value);
    if (keys.length > 64 || keys.some((key) => typeof key !== 'string'))
      throw new ContractError('invalid_json');
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const output: Record<string, unknown> = Object.create(null);
    for (const key of (keys as string[]).sort()) {
      const item = descriptors[key]!;
      if (!('value' in item) || !item.enumerable) throw new ContractError('invalid_json');
      text(key, 64);
      state.bytes -= Buffer.byteLength(key);
      if (state.bytes < 0) throw new ContractError('invalid_json');
      output[key] = boundedCopy(item.value, state, depth + 1, seen);
    }
    return output;
  } finally {
    seen.delete(value);
  }
}
export function canonical(value: unknown): Uint8Array {
  try {
    return Buffer.from(JSON.stringify(boundedCopy(value)), 'utf8');
  } catch (error) {
    if (error instanceof ContractError) throw error;
    throw new ContractError('invalid_json');
  }
}
export function hash(value: Uint8Array): string {
  return createHash('sha256').update(value).digest('hex');
}
/** Purpose-built bounded JSON reader; rejects duplicate keys before object construction. */
export function decode(payload: Uint8Array, maximum: number): unknown {
  if (!(payload instanceof Uint8Array) || payload.byteLength === 0 || payload.byteLength > maximum)
    throw new ContractError('invalid_json');
  let raw: string;
  try {
    raw = new TextDecoder('utf-8', {
      fatal: true,
      ignoreBOM: true,
    }).decode(payload);
  } catch {
    throw new ContractError('invalid_json');
  }
  let at = 0,
    nodes = 0;
  const fail = (): never => {
    throw new ContractError('invalid_json');
  };
  const space = () => {
    while (at < raw.length && /[ \t\r\n]/.test(raw[at]!)) at++;
  };
  const string = (): string => {
    const begin = at++;
    let escaped = false;
    while (at < raw.length) {
      const c = raw[at++]!;
      if (escaped) {
        escaped = false;
        continue;
      }
      if (c === '\\') {
        escaped = true;
        continue;
      }
      if (c === '"') {
        try {
          return text(JSON.parse(raw.slice(begin, at)) as unknown, MAX_REQUEST_BYTES);
        } catch {
          return fail();
        }
      }
    }
    return fail();
  };
  const value = (depth: number): unknown => {
    space();
    if (++nodes > 256 || depth > 12) return fail();
    const c = raw[at];
    if (c === '"') return string();
    if (c === '{') {
      if (depth >= 12) return fail();
      at++;
      space();
      const output: Record<string, unknown> = Object.create(null);
      if (raw[at] === '}') {
        at++;
        return output;
      }
      while (true) {
        space();
        if (raw[at] !== '"') return fail();
        const key = string();
        if (Buffer.byteLength(key) > 64 || Object.hasOwn(output, key)) return fail();
        space();
        if (raw[at++] !== ':') return fail();
        output[key] = value(depth + 1);
        space();
        const end = raw[at++];
        if (end === '}') return output;
        if (end !== ',') return fail();
      }
    }
    if (c === '[') {
      if (depth >= 12) return fail();
      at++;
      space();
      const output: unknown[] = [];
      if (raw[at] === ']') {
        at++;
        return output;
      }
      while (true) {
        output.push(value(depth + 1));
        space();
        const end = raw[at++];
        if (end === ']') return output;
        if (end !== ',') return fail();
      }
    }
    for (const [word, result] of [
      ['true', true],
      ['false', false],
      ['null', null],
    ] as const) {
      if (raw.startsWith(word, at)) {
        at += word.length;
        return result;
      }
    }
    const match = raw.slice(at).match(/^-?(?:0|[1-9][0-9]*)/);
    if (!match || match[0] === '-0' || match[0].length > 16) return fail();
    at += match[0].length;
    const result = Number(match[0]);
    if (!Number.isSafeInteger(result)) return fail();
    return result;
  };
  const output = value(0);
  space();
  if (at !== raw.length) return fail();
  return output;
}
function freeze<T>(value: T): Readonly<T> {
  if (value !== null && typeof value === 'object') {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}
const REQUEST_FIELDS = [
  'schema_version',
  'kind',
  'capability',
  'input_schema_version',
  'scope',
  'delegation_id',
  'case_id',
  'request_revision',
  'context_snapshot',
  'evidence',
  'deadline_at_ms',
  'result_route',
  'attempt',
  'input_fingerprint',
] as const;
const RESULT_FIELDS = [
  'schema_version',
  'kind',
  'capability',
  'result_schema_version',
  'scope',
  'delegation_id',
  'case_id',
  'request_revision',
  'attempt_id',
  'input_fingerprint',
  'eligible',
  'uncertainty',
  'evidence_refs',
  'producer',
  'completed_at_ms',
] as const;
function scope(value: unknown): Scope {
  const obj = fields(value, ['tenant_id', 'account_id']);
  return {
    tenant_id: identifier(obj.tenant_id),
    account_id: identifier(obj.account_id),
  };
}
function evidence(value: unknown): EvidenceRef {
  const obj = fields(value, [
    'source_id',
    'version',
    'sha256',
    'media_type',
    'byte_length',
    'width',
    'height',
  ]);
  const length = integer(obj.byte_length, 1, 2097152);
  let width: number | null = null,
    height: number | null = null;
  if (obj.media_type === 'application/json') {
    if (length > 4096 || obj.width !== null || obj.height !== null) throw new ContractError();
  } else if (obj.media_type === 'image/png') {
    width = integer(obj.width, 1, 2048);
    height = integer(obj.height, 1, 2048);
  } else throw new ContractError();
  return {
    source_id: identifier(obj.source_id),
    version: identifier(obj.version),
    sha256: digest(obj.sha256),
    media_type: obj.media_type,
    byte_length: length,
    width,
    height,
  };
}
function header(obj: Record<string, unknown>, kind: string, versionField: string) {
  if (obj.schema_version !== 1 || obj[versionField] !== 1)
    throw new ContractError('unsupported_version');
  if (obj.kind !== kind) throw new ContractError();
  if (obj.capability !== CAPABILITY) throw new ContractError('unknown_capability');
}
export function logicalFingerprint(wire: Record<string, unknown>): string {
  return hash(
    canonical(
      Object.fromEntries(
        Object.entries(wire).filter(([key]) => key !== 'attempt' && key !== 'input_fingerprint'),
      ),
    ),
  );
}
export function parseRequest(payload: Uint8Array): DelegationRequest {
  const obj = fields(decode(payload, MAX_REQUEST_BYTES), REQUEST_FIELDS);
  header(obj, 'delegation.request', 'input_schema_version');
  const context = fields(obj.context_snapshot, [
    'policy_version',
    'policy_source_id',
    'days_before_arrival',
    'note',
  ]);
  const route = fields(obj.result_route, ['conversation_id']);
  const attempt = fields(obj.attempt, ['attempt_id', 'number']);
  if (!Array.isArray(obj.evidence) || obj.evidence.length < 1 || obj.evidence.length > 4)
    throw new ContractError();
  const refs = obj.evidence.map(evidence);
  if (new Set(refs.map((x) => x.source_id)).size !== refs.length) throw new ContractError();
  const policy = identifier(context.policy_source_id);
  if (!refs.some((x) => x.source_id === policy && x.media_type === 'application/json'))
    throw new ContractError('evidence_mismatch');
  const fingerprint = digest(obj.input_fingerprint);
  if (fingerprint !== logicalFingerprint(obj)) throw new ContractError('identity_conflict');
  return freeze({
    schema_version: 1,
    kind: 'delegation.request',
    capability: CAPABILITY,
    input_schema_version: 1,
    scope: scope(obj.scope),
    delegation_id: identifier(obj.delegation_id),
    case_id: identifier(obj.case_id),
    request_revision: integer(obj.request_revision, 1, 1000000),
    context_snapshot: {
      policy_version: identifier(context.policy_version),
      policy_source_id: policy,
      days_before_arrival: integer(context.days_before_arrival, 0, 3650),
      note: text(context.note),
    },
    evidence: refs,
    deadline_at_ms: integer(obj.deadline_at_ms, 0, MAX_TIMESTAMP_MS),
    result_route: {
      conversation_id: identifier(route.conversation_id),
    },
    attempt: {
      attempt_id: identifier(attempt.attempt_id),
      number: integer(attempt.number, 1, 16),
    },
    input_fingerprint: fingerprint,
  });
}
export function produceRequest(input: unknown): DelegationRequest {
  try {
    const obj = fields(
      input,
      REQUEST_FIELDS.filter((x) => x !== 'input_fingerprint'),
    );
    const copy = boundedCopy(obj) as Record<string, unknown>;
    return parseRequest(
      canonical({
        ...copy,
        input_fingerprint: logicalFingerprint(copy),
      }),
    );
  } catch (error) {
    if (error instanceof ContractError) throw error;
    throw new ContractError();
  }
}
export function encodeRequest(value: DelegationRequest): Uint8Array {
  const bytes = canonical(value);
  parseRequest(bytes);
  return bytes;
}
export function checkReplay(
  original: DelegationRequest,
  candidate: DelegationRequest,
): 'duplicate' | 'distinct' {
  if (
    original.scope.tenant_id !== candidate.scope.tenant_id ||
    original.scope.account_id !== candidate.scope.account_id ||
    original.delegation_id !== candidate.delegation_id
  )
    return 'distinct';
  if (original.input_fingerprint !== candidate.input_fingerprint)
    throw new ContractError('identity_conflict');
  return 'duplicate';
}
export function parseResult(payload: Uint8Array): DelegationResult {
  const obj = fields(decode(payload, MAX_RESULT_BYTES), RESULT_FIELDS);
  header(obj, 'delegation.result', 'result_schema_version');
  if (
    obj.uncertainty !== 'none' &&
    obj.uncertainty !== 'missing' &&
    obj.uncertainty !== 'conflicting'
  )
    throw new ContractError();
  if (
    (obj.uncertainty === 'none' && typeof obj.eligible !== 'boolean') ||
    (obj.uncertainty !== 'none' && obj.eligible !== null)
  )
    throw new ContractError();
  if (
    !Array.isArray(obj.evidence_refs) ||
    obj.evidence_refs.length < 1 ||
    obj.evidence_refs.length > 4
  )
    throw new ContractError();
  const refs = obj.evidence_refs.map((value) => {
    const ref = fields(value, ['source_id', 'version', 'sha256', 'rule_id']);
    return {
      source_id: identifier(ref.source_id),
      version: identifier(ref.version),
      sha256: digest(ref.sha256),
      rule_id: identifier(ref.rule_id),
    };
  });
  if (new Set(refs.map((x) => x.source_id)).size !== refs.length) throw new ContractError();
  const p = fields(obj.producer, [
    'producer_id',
    'model_id',
    'model_version',
    'config_fingerprint',
  ]);
  return freeze({
    schema_version: 1,
    kind: 'delegation.result',
    capability: CAPABILITY,
    result_schema_version: 1,
    scope: scope(obj.scope),
    delegation_id: identifier(obj.delegation_id),
    case_id: identifier(obj.case_id),
    request_revision: integer(obj.request_revision, 1, 1000000),
    attempt_id: identifier(obj.attempt_id),
    input_fingerprint: digest(obj.input_fingerprint),
    eligible: obj.eligible as boolean | null,
    uncertainty: obj.uncertainty,
    evidence_refs: refs,
    producer: {
      producer_id: identifier(p.producer_id),
      model_id: p.model_id === null ? null : identifier(p.model_id),
      model_version: p.model_version === null ? null : identifier(p.model_version),
      config_fingerprint: digest(p.config_fingerprint),
    },
    completed_at_ms: integer(obj.completed_at_ms, 0, MAX_TIMESTAMP_MS),
  });
}
export function encodeResult(value: DelegationResult): Uint8Array {
  const bytes = canonical(value);
  parseResult(bytes);
  return bytes;
}
export function matchResult(
  request: DelegationRequest,
  result: DelegationResult,
  observedAtMs: number,
): 'candidate' | 'expired' {
  integer(observedAtMs, 0, MAX_TIMESTAMP_MS);
  if (
    request.scope.tenant_id !== result.scope.tenant_id ||
    request.scope.account_id !== result.scope.account_id ||
    request.delegation_id !== result.delegation_id ||
    request.case_id !== result.case_id ||
    request.request_revision !== result.request_revision ||
    request.attempt.attempt_id !== result.attempt_id ||
    request.input_fingerprint !== result.input_fingerprint
  )
    throw new ContractError('result_mismatch');
  for (const ref of result.evidence_refs) {
    const original = request.evidence.find((x) => x.source_id === ref.source_id);
    if (!original || original.version !== ref.version || original.sha256 !== ref.sha256)
      throw new ContractError('evidence_mismatch');
  }
  return observedAtMs >= request.deadline_at_ms ? 'expired' : 'candidate';
}
export function encodeError(code: ErrorCode, requestId: string): Uint8Array {
  if (!ERROR_CODES.includes(code)) throw new ContractError();
  return canonical({
    schema_version: 1,
    kind: 'delegation.error',
    code,
    request_id: identifier(requestId),
    retryable: false,
  });
}
export function parseError(payload: Uint8Array): ErrorEnvelope {
  const obj = fields(decode(payload, 512), [
    'schema_version',
    'kind',
    'code',
    'request_id',
    'retryable',
  ]);
  if (obj.schema_version !== 1) throw new ContractError('unsupported_version');
  if (
    obj.kind !== 'delegation.error' ||
    !ERROR_CODES.includes(obj.code as ErrorCode) ||
    obj.retryable !== false
  )
    throw new ContractError();
  return freeze({
    schema_version: 1,
    kind: 'delegation.error',
    code: obj.code as ErrorCode,
    request_id: identifier(obj.request_id),
    retryable: false,
  });
}
