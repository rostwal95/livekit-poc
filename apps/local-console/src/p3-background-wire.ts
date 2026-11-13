/** Closed P3 native text boundary. No credential or arbitrary body enters a display projection. */
import { BackgroundError } from './p3-background-policy';
import type { BackgroundCard } from './p3-background-panel';
const encoder = new TextEncoder();
const ID = /^[a-z][a-z0-9_-]{0,63}(?![\s\S])/u;
const HASH = /^[0-9a-f]{64}(?![\s\S])/u;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/u;
export const P3_PROFILE = 'p3_native_policy_text_v1';
export interface NativeSource {
  readonly role: 'policy' | 'facts';
  readonly source_id: string;
  readonly version: string;
  readonly sha256: string;
  readonly byte_length: number;
}
export interface NativeBinding {
  readonly scope: Readonly<{ tenant_id: string; account_id: string }>;
  readonly case_id: string;
  readonly delegation_id: string;
  readonly request_revision: number;
  readonly input_fingerprint: string;
  readonly sources: readonly [NativeSource, NativeSource];
}
export interface NativeSession {
  readonly schema_version: 1;
  readonly kind: 'native-policy.session';
  readonly session_id: string;
  readonly binding: NativeBinding;
  readonly server_url: string;
  readonly room_name: string;
  readonly participant_identity: string;
  readonly agent_identity: string;
  readonly rtc_token: string;
  readonly profile: typeof P3_PROFILE;
  readonly inference_mode: 'scripted';
  readonly expires_at_ms: number;
}
export interface NativeWork {
  readonly work_id: string;
  readonly request_sha256: string;
  readonly accepted_at_ms: number;
  readonly status:
    | 'accepted'
    | 'running'
    | 'retryable'
    | 'exhausted'
    | 'result_recorded'
    | 'cancelled'
    | 'expired';
  readonly cancel_requested: boolean;
}
export interface NativeAttempt {
  readonly attempt_id: string;
  readonly number: number;
}
export interface NativeFact {
  readonly source_id: string;
  readonly version: string;
  readonly sha256: string;
  readonly fact_id: string;
  readonly days_before_arrival: number;
}
export interface NativeRule {
  readonly source_id: string;
  readonly version: string;
  readonly sha256: string;
  readonly rule_id: 'notice_minimum_days';
  readonly minimum_notice_days: 7;
}
export interface NativeResult {
  readonly attempt_id: string;
  readonly wire_attempt_id: string;
  readonly sha256: string;
  readonly recorded_at_ms: number;
  readonly disposition:
    'eligible_at_commit' | 'cancelled' | 'expired' | 'superseded' | 'lease_expired';
  readonly eligible: boolean | null;
  readonly uncertainty: 'none' | 'missing' | 'conflicting';
  readonly fact_refs: readonly NativeFact[];
  readonly rule_refs: readonly [NativeRule];
}
export type NativeApplicability =
  | null
  | 'missing'
  | 'candidate'
  | 'clarification'
  | 'outdated'
  | 'case_cancelled'
  | 'expired'
  | 'execution_ineligible'
  | 'unavailable';
export interface NativeObservation {
  readonly schema_version: 1;
  readonly kind: 'native-policy.observation';
  readonly binding: NativeBinding;
  readonly state: 'no_work' | 'work' | 'result' | 'outdated' | 'unknown';
  readonly work: NativeWork | null;
  readonly attempt: NativeAttempt | null;
  readonly result: NativeResult | null;
  readonly applicability: NativeApplicability;
  readonly tool_waiter: 'idle' | 'waiting' | 'returned' | 'stopped_waiting';
  readonly owned_run: boolean;
  readonly error:
    | null
    | 'read_unavailable'
    | 'capacity'
    | 'acknowledgement_unknown'
    | 'closed'
    | 'invalid_observation';
  readonly consistency: 'as_of_non_atomic';
  readonly app_read_completed_at_ms: number;
}
function invalid(): never {
  throw new BackgroundError('invalid');
}
function object(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    return invalid();
  const properties = Object.getOwnPropertyDescriptors(value),
    keys = Reflect.ownKeys(properties);
  if (
    keys.length !== fields.length ||
    keys.some((key) => typeof key !== 'string' || !fields.includes(key)) ||
    fields.some(
      (key) => !Object.hasOwn(properties, key) || !Object.hasOwn(properties[key]!, 'value'),
    )
  )
    return invalid();
  return Object.fromEntries(fields.map((key) => [key, properties[key]!.value as unknown]));
}
function literal<T extends string>(value: unknown, values: readonly T[]): T {
  if (typeof value !== 'string' || !values.includes(value as T)) return invalid();
  return value as T;
}
function text(value: unknown, expression: RegExp): string {
  if (typeof value !== 'string' || !expression.test(value)) return invalid();
  return value;
}
function integer(value: unknown, minimum = 0, maximum = 4102444800000): number {
  if (
    typeof value !== 'number' ||
    !Number.isSafeInteger(value) ||
    value < minimum ||
    value > maximum
  )
    return invalid();
  return value;
}
function boolean(value: unknown): boolean {
  if (typeof value !== 'boolean') return invalid();
  return value;
}
function freeze<T>(value: T): T {
  if (value && typeof value === 'object') {
    for (const item of Object.values(value)) freeze(item);
    Object.freeze(value);
  }
  return value;
}
function header(value: Record<string, unknown>, kind: string): void {
  if (value.schema_version !== 1 || value.kind !== kind) invalid();
}
export function parseNativeBinding(value: unknown): NativeBinding {
  const v = object(value, [
      'scope',
      'case_id',
      'delegation_id',
      'request_revision',
      'input_fingerprint',
      'sources',
    ]),
    scope = object(v.scope, ['tenant_id', 'account_id']);
  if (!Array.isArray(v.sources) || v.sources.length !== 2) return invalid();
  const sources = v.sources.map((raw, index): NativeSource => {
    const s = object(raw, ['role', 'source_id', 'version', 'sha256', 'byte_length']);
    if (s.role !== (index === 0 ? 'policy' : 'facts')) return invalid();
    return {
      role: index === 0 ? 'policy' : 'facts',
      source_id: text(s.source_id, ID),
      version: text(s.version, ID),
      sha256: text(s.sha256, HASH),
      byte_length: integer(s.byte_length, 1, 4096),
    };
  });
  if (sources[0]!.source_id === sources[1]!.source_id) return invalid();
  return freeze({
    scope: { tenant_id: text(scope.tenant_id, ID), account_id: text(scope.account_id, ID) },
    case_id: text(v.case_id, ID),
    delegation_id: text(v.delegation_id, ID),
    request_revision: integer(v.request_revision, 1, 1000000),
    input_fingerprint: text(v.input_fingerprint, HASH),
    sources: sources as unknown as [NativeSource, NativeSource],
  });
}
export function sameNativeBinding(a: NativeBinding, b: NativeBinding): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
export function parseNativeSession(value: unknown): NativeSession {
  const v = object(value, [
    'schema_version',
    'kind',
    'session_id',
    'binding',
    'server_url',
    'room_name',
    'participant_identity',
    'agent_identity',
    'rtc_token',
    'profile',
    'inference_mode',
    'expires_at_ms',
  ]);
  header(v, 'native-policy.session');
  const server = text(
    v.server_url,
    /^ws:\/\/(?:127\.0\.0\.1|localhost):[1-9][0-9]{0,4}\/?(?![\s\S])/u,
  );
  let url: URL;
  try {
    url = new URL(server);
  } catch {
    return invalid();
  }
  if (
    Number(url.port || '80') > 65535 ||
    v.profile !== P3_PROFILE ||
    v.inference_mode !== 'scripted' ||
    typeof v.rtc_token !== 'string' ||
    encoder.encode(v.rtc_token).byteLength > 4096 ||
    !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?![\s\S])/u.test(v.rtc_token)
  )
    return invalid();
  const session: NativeSession = {
    schema_version: 1,
    kind: 'native-policy.session',
    session_id: text(v.session_id, UUID),
    binding: parseNativeBinding(v.binding),
    server_url: server,
    room_name: text(v.room_name, ID),
    participant_identity: text(v.participant_identity, ID),
    agent_identity: text(v.agent_identity, ID),
    rtc_token: v.rtc_token,
    profile: P3_PROFILE,
    inference_mode: 'scripted',
    expires_at_ms: integer(v.expires_at_ms),
  };
  if (session.agent_identity === session.participant_identity) return invalid();
  return freeze(session);
}
function sourceMatches(
  value: { source_id: string; version: string; sha256: string },
  source: NativeSource,
): boolean {
  return (
    value.source_id === source.source_id &&
    value.version === source.version &&
    value.sha256 === source.sha256
  );
}
export function parseNativeObservation(value: unknown, binding: NativeBinding): NativeObservation {
  const v = object(value, [
    'schema_version',
    'kind',
    'binding',
    'state',
    'work',
    'attempt',
    'result',
    'applicability',
    'tool_waiter',
    'owned_run',
    'error',
    'consistency',
    'app_read_completed_at_ms',
  ]);
  header(v, 'native-policy.observation');
  const parsedBinding = parseNativeBinding(v.binding);
  if (!sameNativeBinding(parsedBinding, binding)) return invalid();
  const work: NativeWork | null =
    v.work === null
      ? null
      : (() => {
          const w = object(v.work, [
            'work_id',
            'request_sha256',
            'accepted_at_ms',
            'status',
            'cancel_requested',
          ]);
          return freeze({
            work_id: text(w.work_id, UUID),
            request_sha256: text(w.request_sha256, HASH),
            accepted_at_ms: integer(w.accepted_at_ms),
            status: literal(w.status, [
              'accepted',
              'running',
              'retryable',
              'exhausted',
              'result_recorded',
              'cancelled',
              'expired',
            ]),
            cancel_requested: boolean(w.cancel_requested),
          });
        })();
  const attempt: NativeAttempt | null =
    v.attempt === null
      ? null
      : (() => {
          const a = object(v.attempt, ['attempt_id', 'number']);
          return freeze({ attempt_id: text(a.attempt_id, UUID), number: integer(a.number, 1, 3) });
        })();
  const result: NativeResult | null =
    v.result === null
      ? null
      : (() => {
          const r = object(v.result, [
            'attempt_id',
            'wire_attempt_id',
            'sha256',
            'recorded_at_ms',
            'disposition',
            'eligible',
            'uncertainty',
            'fact_refs',
            'rule_refs',
          ]);
          if (
            !Array.isArray(r.fact_refs) ||
            r.fact_refs.length > 2 ||
            !Array.isArray(r.rule_refs) ||
            r.rule_refs.length !== 1
          )
            return invalid();
          const facts = r.fact_refs.map((raw): NativeFact => {
            const f = object(raw, [
              'source_id',
              'version',
              'sha256',
              'fact_id',
              'days_before_arrival',
            ]);
            return {
              source_id: text(f.source_id, ID),
              version: text(f.version, ID),
              sha256: text(f.sha256, HASH),
              fact_id: text(f.fact_id, ID),
              days_before_arrival: integer(f.days_before_arrival, 0, 3650),
            };
          });
          const rawRule = object(r.rule_refs[0], [
            'source_id',
            'version',
            'sha256',
            'rule_id',
            'minimum_notice_days',
          ]);
          if (rawRule.rule_id !== 'notice_minimum_days' || rawRule.minimum_notice_days !== 7)
            return invalid();
          const rule: NativeRule = {
            source_id: text(rawRule.source_id, ID),
            version: text(rawRule.version, ID),
            sha256: text(rawRule.sha256, HASH),
            rule_id: 'notice_minimum_days',
            minimum_notice_days: 7,
          };
          if (
            !sourceMatches(rule, binding.sources[0]) ||
            facts.some((fact) => !sourceMatches(fact, binding.sources[1])) ||
            new Set(facts.map((fact) => fact.fact_id)).size !== facts.length
          )
            return invalid();
          const uncertainty = literal(r.uncertainty, ['none', 'missing', 'conflicting']);
          if (
            uncertainty === 'none'
              ? typeof r.eligible !== 'boolean' ||
                facts.length === 0 ||
                facts.some((fact) => fact.days_before_arrival !== facts[0]!.days_before_arrival) ||
                r.eligible !== facts[0]!.days_before_arrival >= 7
              : r.eligible !== null ||
                (uncertainty === 'missing'
                  ? facts.length !== 0
                  : facts.length !== 2 ||
                    facts[0]!.days_before_arrival === facts[1]!.days_before_arrival)
          )
            return invalid();
          const attemptId = text(r.attempt_id, UUID),
            wireAttempt = text(r.wire_attempt_id, ID);
          if (wireAttempt !== `attempt_${attemptId.replaceAll('-', '')}`) return invalid();
          return freeze({
            attempt_id: attemptId,
            wire_attempt_id: wireAttempt,
            sha256: text(r.sha256, HASH),
            recorded_at_ms: integer(r.recorded_at_ms),
            disposition: literal(r.disposition, [
              'eligible_at_commit',
              'cancelled',
              'expired',
              'superseded',
              'lease_expired',
            ]),
            eligible: r.eligible as boolean | null,
            uncertainty,
            fact_refs: facts,
            rule_refs: [rule] as [NativeRule],
          });
        })();
  const state = literal(v.state, ['no_work', 'work', 'result', 'outdated', 'unknown']);
  const applicability =
    v.applicability === null
      ? null
      : literal(v.applicability, [
          'missing',
          'candidate',
          'clarification',
          'outdated',
          'case_cancelled',
          'expired',
          'execution_ineligible',
          'unavailable',
        ]);
  const error =
    v.error === null
      ? null
      : literal(v.error, [
          'read_unavailable',
          'capacity',
          'acknowledgement_unknown',
          'closed',
          'invalid_observation',
        ]);
  if (v.consistency !== 'as_of_non_atomic') return invalid();
  if (state === 'no_work' || state === 'unknown') {
    if (
      work !== null ||
      attempt !== null ||
      result !== null ||
      applicability !== null ||
      (state === 'no_work' ? error !== null : error === null)
    )
      return invalid();
  } else if (
    !work ||
    error !== null ||
    (state === 'work'
      ? result !== null || applicability !== 'missing' || work.status === 'result_recorded'
      : !result ||
        !attempt ||
        applicability === null ||
        applicability === 'missing' ||
        (state === 'outdated') !== (applicability === 'outdated'))
  )
    return invalid();
  if (
    result &&
    (result.attempt_id !== attempt?.attempt_id ||
      (work?.status === 'result_recorded' && result.disposition !== 'eligible_at_commit'))
  )
    return invalid();
  return freeze({
    schema_version: 1,
    kind: 'native-policy.observation',
    binding: parsedBinding,
    state,
    work,
    attempt,
    result,
    applicability,
    tool_waiter: literal(v.tool_waiter, ['idle', 'waiting', 'returned', 'stopped_waiting']),
    owned_run: boolean(v.owned_run),
    error,
    consistency: 'as_of_non_atomic',
    app_read_completed_at_ms: integer(v.app_read_completed_at_ms),
  });
}
/** JSON.parse alone discards duplicate keys and permits lone surrogate escapes. */
export function parseNativeJson(input: string, maximum: number): unknown {
  if (encoder.encode(input).byteLength > maximum) return invalid();
  let parsed: unknown;
  try {
    parsed = JSON.parse(input);
  } catch {
    return invalid();
  }
  const stack: (Set<string> | null)[] = [];
  for (let i = 0; i < input.length; i++) {
    const ch = input[i];
    if (ch === '{' || ch === '[') {
      stack.push(ch === '{' ? new Set() : null);
      if (stack.length > 8) return invalid();
    } else if (ch === '}' || ch === ']') stack.pop();
    else if (ch === '"') {
      const start = i++;
      while (i < input.length) {
        if (input[i] === '\\') i += 2;
        else if (input[i] === '"') break;
        else i++;
      }
      let next = i + 1;
      while (next < input.length && /\s/u.test(input[next]!)) next++;
      if (input[next] === ':') {
        const keys = stack.at(-1),
          key: unknown = JSON.parse(input.slice(start, i + 1));
        if (!keys || typeof key !== 'string' || keys.has(key)) return invalid();
        keys.add(key);
      }
    }
  }
  let nodes = 0;
  function visit(value: unknown): void {
    if (++nodes > 256 || (typeof value === 'number' && !Number.isFinite(value))) return invalid();
    if (typeof value === 'string') {
      for (let i = 0; i < value.length; i++) {
        const unit = value.charCodeAt(i);
        if (unit >= 0xd800 && unit <= 0xdbff) {
          const low = value.charCodeAt(++i);
          if (!(low >= 0xdc00 && low <= 0xdfff)) return invalid();
        } else if (unit >= 0xdc00 && unit <= 0xdfff) return invalid();
      }
    } else if (value && typeof value === 'object')
      for (const [key, child] of Object.entries(value)) {
        visit(key);
        visit(child);
      }
  }
  visit(parsed);
  return parsed;
}
export function nativeErrorCode(
  value: unknown,
  status: number,
): 'access_denied' | 'invalid' | 'closed' | 'unavailable' {
  const v = object(value, ['schema_version', 'kind', 'code']);
  header(v, 'native-policy.error');
  const code = literal(v.code, [
    'unauthorized',
    'forbidden',
    'invalid_request',
    'closed',
    'unavailable',
  ]);
  if (
    code === 'invalid_request'
      ? ![400, 404, 405].includes(status)
      : status !==
        ({ unauthorized: 401, forbidden: 403, closed: 503, unavailable: 503 } as const)[code]
  )
    return invalid();
  return code === 'unauthorized' || code === 'forbidden'
    ? 'access_denied'
    : code === 'invalid_request'
      ? 'invalid'
      : code;
}
function instant(value: number): string {
  return new Date(value).toISOString();
}
export function projectNativeObservation(value: NativeObservation): BackgroundCard {
  const facts: { label: string; value: string }[] = [
    { label: 'Original request revision', value: String(value.binding.request_revision) },
    { label: 'Application read completed', value: instant(value.app_read_completed_at_ms) },
  ];
  if (value.work)
    facts.unshift(
      { label: 'Work state', value: value.work.status.replaceAll('_', ' ') },
      { label: 'Work reference', value: value.work.work_id },
    );
  if (value.result)
    facts.push(
      {
        label: 'Original result disposition',
        value: value.result.disposition.replaceAll('_', ' '),
      },
      { label: 'Result recorded', value: instant(value.result.recorded_at_ms) },
    );
  if (value.applicability)
    facts.push({ label: 'As-of applicability', value: value.applicability.replaceAll('_', ' ') });
  const heading = {
    no_work: 'No accepted work observed',
    work: 'Work observed',
    result:
      value.result?.uncertainty === 'none' ? 'Policy result observed' : 'Clarification observed',
    outdated: 'Historical result · outdated',
    unknown: 'Latest work state unknown',
  }[value.state];
  const summary =
    value.state === 'outdated'
      ? 'The original result is retained. It is outdated for the current case.'
      : value.state === 'unknown'
        ? 'The application could not establish a fresh work observation. Check again; no new request was submitted.'
        : value.result?.uncertainty === 'none'
          ? value.result.eligible
            ? 'The verified notice evidence meets the seven-day policy rule.'
            : 'The verified notice evidence does not meet the seven-day policy rule.'
          : value.result
            ? value.result.uncertainty === 'missing'
              ? 'The verified result needs notice evidence before a policy conclusion.'
              : 'The verified notice evidence conflicts. Clarification is required.'
            : value.state === 'no_work'
              ? 'The authenticated application found no accepted request for this configured delegation.'
              : 'This is the actual execution state returned by the application.';
  return Object.freeze({
    heading,
    summary,
    facts: Object.freeze(facts),
    evidence: Object.freeze({
      state: value.state,
      workId: value.work?.work_id ?? null,
      requestRevision: value.binding.request_revision,
      inputFingerprint: value.binding.input_fingerprint,
      ownedRun: value.owned_run,
      hasResult: value.result !== null,
      applicability: value.applicability,
      resultSha256: value.result?.sha256 ?? null,
      disposition: value.result?.disposition ?? null,
      attemptId: value.attempt?.attempt_id ?? null,
      appReadCompletedAtMs: value.app_read_completed_at_ms,
    }),
  });
}
