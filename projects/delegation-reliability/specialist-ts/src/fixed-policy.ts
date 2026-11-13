/** Finite deterministic notice-v1 evaluator; no tools, models, stores or side effects. */
import {
  CAPABILITY,
  ContractError,
  canonical,
  decode,
  fields,
  hash,
  identifier,
  integer,
  text,
} from './contracts.js';
import type { EvidenceRef, Producer, Scope } from './contracts.js';
import {
  FIXED_POLICY_VERSION,
  FIXED_POLICY_RULE,
  FIXED_POLICY_MINIMUM_DAYS,
  encodeFixedPolicyRequest,
  encodeFixedPolicyResult,
  matchFixedPolicyResult,
  parseFixedPolicyRequest,
  parseFixedPolicyResult,
} from './fixed-policy-contracts.js';
import type {
  FixedPolicyRequest,
  FixedPolicyResult,
  FixedPolicyFactEvidence,
  FixedPolicyApplicability,
} from './fixed-policy-contracts.js';
import { EvidenceRegistry } from './security.js';
import type { EvidenceRecord } from './security.js';
import { SpecialistClient } from './client.js';
import type { CallOptions, ClientOptions, SpecialistClientMetrics } from './client.js';
import type { Endpoint, AttemptObservation } from './http-protocol.js';

export function snapshotFixedPolicyRecords(
  records: readonly EvidenceRecord[],
): readonly EvidenceRecord[] {
  if (!Array.isArray(records) || records.length > 32) throw new ContractError();
  let total = 0;
  const copied = records.map((input) => {
    const r = fields(input, ['scope', 'reference', 'body']);
    if (!(r.body instanceof Uint8Array) || r.body.byteLength < 1 || r.body.byteLength > 2097152)
      throw new ContractError();
    total += r.body.byteLength;
    if (total > 8388608) throw new ContractError();
    const meta = decode(canonical({ scope: r.scope, reference: r.reference }), 16384) as {
      scope: Scope;
      reference: EvidenceRef;
    };
    return Object.freeze({
      scope: Object.freeze(meta.scope),
      reference: Object.freeze(meta.reference),
      body: Buffer.from(r.body),
    });
  });
  new EvidenceRegistry(copied);
  return Object.freeze(copied);
}
function sourceFacts(
  request: FixedPolicyRequest,
  records: readonly EvidenceRecord[],
): readonly FixedPolicyFactEvidence[] {
  const selected = request.evidence.map((ref) => {
    const matches = records.filter(
      (r) =>
        r.scope.tenant_id === request.scope.tenant_id &&
        r.scope.account_id === request.scope.account_id &&
        r.reference.source_id === ref.source_id,
    );
    if (
      matches.length !== 1 ||
      Buffer.compare(Buffer.from(canonical(matches[0]!.reference)), Buffer.from(canonical(ref))) !==
        0
    )
      throw new ContractError('evidence_mismatch');
    return matches[0]!;
  });
  const policy = fields(decode(selected[0]!.body, 4096), [
    'schema_version',
    'kind',
    'policy_version',
    'rule_id',
    'minimum_notice_days',
    'note',
  ]);
  text(policy.note);
  if (
    policy.schema_version !== 1 ||
    policy.kind !== 'booking.notice_policy' ||
    policy.policy_version !== request.context_snapshot.policy_version ||
    policy.policy_version !== FIXED_POLICY_VERSION ||
    policy.rule_id !== FIXED_POLICY_RULE ||
    policy.minimum_notice_days !== FIXED_POLICY_MINIMUM_DAYS
  )
    throw new ContractError('unsupported_facts');
  const facts = fields(decode(selected[1]!.body, 4096), [
    'schema_version',
    'kind',
    'observations',
    'note',
  ]);
  text(facts.note);
  if (
    facts.schema_version !== 1 ||
    facts.kind !== 'booking.notice_facts' ||
    !Array.isArray(facts.observations) ||
    facts.observations.length > 2
  )
    throw new ContractError('unsupported_facts');
  const source = request.evidence[1]!;
  const observations = Object.freeze(
    facts.observations.map((item: unknown) => {
      const f = fields(item, ['fact_id', 'days_before_arrival']);
      return Object.freeze({
        source_id: source.source_id,
        version: source.version,
        sha256: source.sha256,
        fact_id: identifier(f.fact_id),
        days_before_arrival: integer(f.days_before_arrival, 0, 3650),
      });
    }),
  );
  if (new Set(observations.map((f) => f.fact_id)).size !== observations.length)
    throw new ContractError('unsupported_facts');
  return observations;
}
export function verifyFixedPolicyFacts(
  request: FixedPolicyRequest,
  result: FixedPolicyResult,
  records: readonly EvidenceRecord[],
  observedAtMs: number,
): FixedPolicyApplicability {
  request = parseFixedPolicyRequest(encodeFixedPolicyRequest(request));
  result = parseFixedPolicyResult(encodeFixedPolicyResult(result));
  const snapshot = snapshotFixedPolicyRecords(records),
    timeliness = matchFixedPolicyResult(request, result, observedAtMs);
  const expected = sourceFacts(request, snapshot),
    rule = result.rule_refs[0]!;
  if (rule.rule_id !== FIXED_POLICY_RULE || rule.minimum_notice_days !== FIXED_POLICY_MINIMUM_DAYS)
    throw new ContractError('unsupported_facts');
  const sorted = (refs: readonly FixedPolicyFactEvidence[]) =>
    [...refs].sort((a, b) => (a.fact_id < b.fact_id ? -1 : a.fact_id > b.fact_id ? 1 : 0));
  if (
    Buffer.compare(
      Buffer.from(canonical(sorted(expected))),
      Buffer.from(canonical(sorted(result.fact_refs))),
    ) !== 0
  )
    throw new ContractError('unsupported_facts');
  const values = new Set(expected.map((f) => f.days_before_arrival)),
    uncertainty = values.size === 0 ? 'missing' : values.size === 1 ? 'none' : 'conflicting';
  const eligible =
    uncertainty === 'none' ? expected[0]!.days_before_arrival >= FIXED_POLICY_MINIMUM_DAYS : null;
  if (result.uncertainty !== uncertainty || result.eligible !== eligible)
    throw new ContractError('unsupported_facts');
  return timeliness;
}
export class FixedPolicyHandler {
  readonly #producer: Producer = Object.freeze({
    producer_id: 'deterministic_notice_v1',
    model_id: null,
    model_version: null,
    config_fingerprint: hash(
      canonical({
        policy_version: FIXED_POLICY_VERSION,
        rule_id: FIXED_POLICY_RULE,
        minimum_notice_days: FIXED_POLICY_MINIMUM_DAYS,
      }),
    ),
  });
  #evaluated = 0;
  #clarified = 0;
  metrics(): Readonly<{ evaluated: number; clarified: number }> {
    return Object.freeze({ evaluated: this.#evaluated, clarified: this.#clarified });
  }
  evaluate(
    input: FixedPolicyRequest,
    records: readonly EvidenceRecord[],
    observedAtMs: number,
  ): FixedPolicyResult {
    const request = parseFixedPolicyRequest(encodeFixedPolicyRequest(input)),
      snapshot = snapshotFixedPolicyRecords(records),
      facts = sourceFacts(request, snapshot);
    integer(observedAtMs, 0, 4102444800000);
    if (observedAtMs >= request.deadline_at_ms) throw new ContractError('expired');
    const values = new Set(facts.map((f) => f.days_before_arrival)),
      uncertainty = values.size === 0 ? 'missing' : values.size === 1 ? 'none' : 'conflicting',
      source = request.evidence[0]!;
    const result = parseFixedPolicyResult(
      canonical({
        schema_version: 1,
        kind: 'delegation.result',
        capability: CAPABILITY,
        result_schema_version: 2,
        scope: request.scope,
        delegation_id: request.delegation_id,
        case_id: request.case_id,
        request_revision: request.request_revision,
        attempt_id: request.attempt.attempt_id,
        input_fingerprint: request.input_fingerprint,
        eligible:
          uncertainty === 'none'
            ? facts[0]!.days_before_arrival >= FIXED_POLICY_MINIMUM_DAYS
            : null,
        uncertainty,
        rule_refs: [
          {
            source_id: source.source_id,
            version: source.version,
            sha256: source.sha256,
            rule_id: FIXED_POLICY_RULE,
            minimum_notice_days: FIXED_POLICY_MINIMUM_DAYS,
          },
        ],
        fact_refs: facts,
        producer: this.#producer,
        completed_at_ms: observedAtMs,
      }),
    );
    verifyFixedPolicyFacts(request, result, snapshot, observedAtMs);
    this.#evaluated++;
    if (uncertainty !== 'none') this.#clarified++;
    return result;
  }
}
/** Fully immutable-source-verified observation, not durable eligibility. */
export type FixedPolicyResultObservation = Readonly<{
  result: FixedPolicyResult;
  applicability: FixedPolicyApplicability;
  observedAtMs: number;
}>;

export class FixedPolicySpecialistClient {
  readonly #transport: SpecialistClient;
  constructor(endpoint: Endpoint, authorization: string, options: ClientOptions = {}) {
    this.#transport = new SpecialistClient(endpoint, authorization, options);
  }
  get active(): number {
    return this.#transport.active;
  }
  metrics(): SpecialistClientMetrics {
    return this.#transport.metrics();
  }
  invoke(request: FixedPolicyRequest, options: CallOptions = {}): Promise<FixedPolicyResult> {
    return this.#transport.invokeFixedPolicy(request, options);
  }
  invokeObserved(
    request: FixedPolicyRequest,
    records: readonly EvidenceRecord[],
    options: CallOptions = {},
  ): Promise<FixedPolicyResultObservation> {
    return this.#transport.invokeFixedPolicyObserved(request, records, options);
  }
  status(request: FixedPolicyRequest, options: CallOptions = {}): Promise<AttemptObservation> {
    return this.#transport.statusFixedPolicy(request, options);
  }
  cancel(request: FixedPolicyRequest, options: CallOptions = {}): Promise<AttemptObservation> {
    return this.#transport.cancelFixedPolicy(request, options);
  }
  close(): Promise<void> {
    return this.#transport.close();
  }
}
export * from './fixed-policy-contracts.js';

export type { SpecialistClientMetrics } from './client.js';
