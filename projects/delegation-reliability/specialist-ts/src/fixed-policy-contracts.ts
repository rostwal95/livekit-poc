/** Explicit policy-v2 wire boundary. Legacy policy APIs remain version1 only. */
import {
  CAPABILITY,
  ContractError,
  MAX_REQUEST_BYTES,
  MAX_RESULT_BYTES,
  MAX_TIMESTAMP_MS,
  canonical,
  decode,
  digest,
  fields,
  identifier,
  integer,
  logicalFingerprint,
  text,
} from './contracts.js';
import type { EvidenceRef, Producer, Scope } from './contracts.js';

export const FIXED_POLICY_VERSION = 'notice_v1' as const;
export const FIXED_POLICY_RULE = 'notice_minimum_days' as const;
export const FIXED_POLICY_MINIMUM_DAYS = 7;
export type FixedPolicyApplicability = 'candidate' | 'clarification' | 'expired';
export type FixedPolicyRequest = Readonly<{
  schema_version: 1;
  kind: 'delegation.request';
  capability: typeof CAPABILITY;
  input_schema_version: 2;
  scope: Scope;
  delegation_id: string;
  case_id: string;
  request_revision: number;
  context_snapshot: Readonly<{
    policy_version: string;
    policy_source_id: string;
    facts_source_id: string;
  }>;
  evidence: readonly EvidenceRef[];
  deadline_at_ms: number;
  result_route: Readonly<{ conversation_id: string }>;
  attempt: Readonly<{ attempt_id: string; number: number }>;
  input_fingerprint: string;
}>;
export type FixedPolicyRuleEvidence = Readonly<{
  source_id: string;
  version: string;
  sha256: string;
  rule_id: string;
  minimum_notice_days: number;
}>;
export type FixedPolicyFactEvidence = Readonly<{
  source_id: string;
  version: string;
  sha256: string;
  fact_id: string;
  days_before_arrival: number;
}>;
export type FixedPolicyResult = Readonly<{
  schema_version: 1;
  kind: 'delegation.result';
  capability: typeof CAPABILITY;
  result_schema_version: 2;
  scope: Scope;
  delegation_id: string;
  case_id: string;
  request_revision: number;
  attempt_id: string;
  input_fingerprint: string;
  eligible: boolean | null;
  uncertainty: 'none' | 'missing' | 'conflicting';
  rule_refs: readonly FixedPolicyRuleEvidence[];
  fact_refs: readonly FixedPolicyFactEvidence[];
  producer: Producer;
  completed_at_ms: number;
}>;
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
];
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
  'rule_refs',
  'fact_refs',
  'producer',
  'completed_at_ms',
];
function header(v: Record<string, unknown>, kind: string, version: string): void {
  if (v.schema_version !== 1 || v[version] !== 2) throw new ContractError('unsupported_version');
  if (v.kind !== kind) throw new ContractError();
  if (v.capability !== CAPABILITY) throw new ContractError('unknown_capability');
}
function scope(value: unknown): Scope {
  const v = fields(value, ['tenant_id', 'account_id']);
  return Object.freeze({
    tenant_id: identifier(v.tenant_id),
    account_id: identifier(v.account_id),
  });
}
function reference(value: unknown): EvidenceRef {
  const v = fields(value, [
    'source_id',
    'version',
    'sha256',
    'media_type',
    'byte_length',
    'width',
    'height',
  ]);
  if (v.media_type !== 'application/json' || v.width !== null || v.height !== null)
    throw new ContractError();
  return Object.freeze({
    source_id: identifier(v.source_id),
    version: identifier(v.version),
    sha256: digest(v.sha256),
    media_type: 'application/json',
    byte_length: integer(v.byte_length, 1, 4096),
    width: null,
    height: null,
  });
}
export function parseFixedPolicyRequest(payload: Uint8Array): FixedPolicyRequest {
  const v = fields(decode(payload, MAX_REQUEST_BYTES), REQUEST_FIELDS);
  header(v, 'delegation.request', 'input_schema_version');
  const c = fields(v.context_snapshot, ['policy_version', 'policy_source_id', 'facts_source_id']);
  const context = Object.freeze({
    policy_version: identifier(c.policy_version),
    policy_source_id: identifier(c.policy_source_id),
    facts_source_id: identifier(c.facts_source_id),
  });
  if (!Array.isArray(v.evidence) || v.evidence.length !== 2) throw new ContractError();
  const evidence = Object.freeze(v.evidence.map(reference));
  if (
    context.policy_source_id === context.facts_source_id ||
    evidence[0]!.source_id !== context.policy_source_id ||
    evidence[1]!.source_id !== context.facts_source_id
  )
    throw new ContractError('evidence_mismatch');
  const fp = digest(v.input_fingerprint);
  if (fp !== logicalFingerprint(v)) throw new ContractError('identity_conflict');
  const route = fields(v.result_route, ['conversation_id']),
    attempt = fields(v.attempt, ['attempt_id', 'number']);
  return Object.freeze({
    schema_version: 1,
    kind: 'delegation.request',
    capability: CAPABILITY,
    input_schema_version: 2,
    scope: scope(v.scope),
    delegation_id: identifier(v.delegation_id),
    case_id: identifier(v.case_id),
    request_revision: integer(v.request_revision, 1, 1000000),
    context_snapshot: context,
    evidence,
    deadline_at_ms: integer(v.deadline_at_ms, 0, MAX_TIMESTAMP_MS),
    result_route: Object.freeze({ conversation_id: identifier(route.conversation_id) }),
    attempt: Object.freeze({
      attempt_id: identifier(attempt.attempt_id),
      number: integer(attempt.number, 1, 16),
    }),
    input_fingerprint: fp,
  });
}
export function produceFixedPolicyRequest(value: unknown): FixedPolicyRequest {
  const v = fields(
    decode(canonical(value), MAX_REQUEST_BYTES),
    REQUEST_FIELDS.filter((x) => x !== 'input_fingerprint'),
  );
  return parseFixedPolicyRequest(canonical({ ...v, input_fingerprint: logicalFingerprint(v) }));
}
export function encodeFixedPolicyRequest(value: FixedPolicyRequest): Uint8Array {
  const bytes = canonical(value);
  parseFixedPolicyRequest(bytes);
  return bytes;
}
function producer(value: unknown): Producer {
  const v = fields(value, ['producer_id', 'model_id', 'model_version', 'config_fingerprint']);
  const model = v.model_id === null ? null : text(v.model_id, 64),
    version = v.model_version === null ? null : text(v.model_version, 64);
  if ((model === null) !== (version === null) || model === '' || version === '')
    throw new ContractError();
  return Object.freeze({
    producer_id: identifier(v.producer_id),
    model_id: model,
    model_version: version,
    config_fingerprint: digest(v.config_fingerprint),
  });
}
export function parseFixedPolicyResult(payload: Uint8Array): FixedPolicyResult {
  const v = fields(decode(payload, MAX_RESULT_BYTES), RESULT_FIELDS);
  header(v, 'delegation.result', 'result_schema_version');
  if (
    !Array.isArray(v.rule_refs) ||
    v.rule_refs.length !== 1 ||
    !Array.isArray(v.fact_refs) ||
    v.fact_refs.length > 2
  )
    throw new ContractError();
  const rule = fields(v.rule_refs[0], [
    'source_id',
    'version',
    'sha256',
    'rule_id',
    'minimum_notice_days',
  ]);
  const rules = Object.freeze([
    Object.freeze({
      source_id: identifier(rule.source_id),
      version: identifier(rule.version),
      sha256: digest(rule.sha256),
      rule_id: identifier(rule.rule_id),
      minimum_notice_days: integer(rule.minimum_notice_days, 0, 3650),
    }),
  ]);
  const facts = Object.freeze(
    v.fact_refs.map((value: unknown) => {
      const f = fields(value, ['source_id', 'version', 'sha256', 'fact_id', 'days_before_arrival']);
      return Object.freeze({
        source_id: identifier(f.source_id),
        version: identifier(f.version),
        sha256: digest(f.sha256),
        fact_id: identifier(f.fact_id),
        days_before_arrival: integer(f.days_before_arrival, 0, 3650),
      });
    }),
  );
  if (new Set(facts.map((f) => f.fact_id)).size !== facts.length) throw new ContractError();
  const eligible = v.eligible,
    uncertainty = v.uncertainty,
    values = new Set(facts.map((f) => f.days_before_arrival));
  if (uncertainty === 'none') {
    if (typeof eligible !== 'boolean' || facts.length === 0 || values.size !== 1)
      throw new ContractError();
  } else if (uncertainty === 'missing') {
    if (eligible !== null || facts.length !== 0) throw new ContractError();
  } else if (uncertainty === 'conflicting') {
    if (eligible !== null || facts.length !== 2 || values.size !== 2) throw new ContractError();
  } else throw new ContractError();
  return Object.freeze({
    schema_version: 1,
    kind: 'delegation.result',
    capability: CAPABILITY,
    result_schema_version: 2,
    scope: scope(v.scope),
    delegation_id: identifier(v.delegation_id),
    case_id: identifier(v.case_id),
    request_revision: integer(v.request_revision, 1, 1000000),
    attempt_id: identifier(v.attempt_id),
    input_fingerprint: digest(v.input_fingerprint),
    eligible: eligible as boolean | null,
    uncertainty,
    rule_refs: rules,
    fact_refs: facts,
    producer: producer(v.producer),
    completed_at_ms: integer(v.completed_at_ms, 0, MAX_TIMESTAMP_MS),
  });
}
export function encodeFixedPolicyResult(value: FixedPolicyResult): Uint8Array {
  const bytes = canonical(value);
  parseFixedPolicyResult(bytes);
  return bytes;
}
export function matchFixedPolicyResult(
  request: FixedPolicyRequest,
  result: FixedPolicyResult,
  observedAtMs: number,
): FixedPolicyApplicability {
  request = parseFixedPolicyRequest(encodeFixedPolicyRequest(request));
  result = parseFixedPolicyResult(encodeFixedPolicyResult(result));
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
  const check = (ref: FixedPolicyRuleEvidence | FixedPolicyFactEvidence, source: EvidenceRef) => {
    if (
      ref.source_id !== source.source_id ||
      ref.version !== source.version ||
      ref.sha256 !== source.sha256
    )
      throw new ContractError('evidence_mismatch');
  };
  for (const ref of result.rule_refs) check(ref, request.evidence[0]!);
  for (const ref of result.fact_refs) check(ref, request.evidence[1]!);
  return observedAtMs >= request.deadline_at_ms
    ? 'expired'
    : result.uncertainty === 'none'
      ? 'candidate'
      : 'clarification';
}
