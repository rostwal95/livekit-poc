import { timingSafeEqual } from 'node:crypto';
import {
  MAX_DEADLINE_WINDOW_MS,
  MAX_TIMESTAMP_MS,
  ContractError,
  canonical,
  decode,
  digest,
  fields,
  hash,
  identifier,
  integer,
  matchResult,
} from './contracts.js';
import type { DelegationRequest, DelegationResult, EvidenceRef, Scope } from './contracts.js';
import {
  encodeCapabilityRequest,
  parseCapabilityRequest,
  SUPPORTED_CAPABILITIES,
} from './capability-codec.js';
import type { CapabilityRequest } from './capability-codec.js';
import type { DocumentRequest } from './document-contracts.js';
export type Operation = 'invoke' | 'result' | 'cancel' | 'evidence';
export type ScopeGrant = Readonly<{
  scope: Scope;
  invoke_capabilities: readonly string[];
  result_capabilities: readonly string[];
  cancel_capabilities: readonly string[];
  evidence_sources: readonly string[];
}>;
export type PrincipalGrant = Readonly<{
  principal_id: string;
  token_sha256: string;
  scopes: readonly ScopeGrant[];
}>;
export function tokenDigest(token: string): string {
  if (typeof token !== 'string' || !/^[A-Za-z0-9_-]{43}(?![\s\S])/.test(token))
    throw new ContractError('unauthorized');
  return hash(Buffer.from(token, 'ascii'));
}
const sameScope = (a: Scope, b: Scope) =>
  a.tenant_id === b.tenant_id && a.account_id === b.account_id;
export class LocalTrust {
  readonly #grants: readonly PrincipalGrant[];
  constructor(input: readonly PrincipalGrant[]) {
    const copy = decode(canonical(input), 16384);
    if (!Array.isArray(copy) || copy.length < 1 || copy.length > 32) throw new ContractError();
    const ids = new Set<string>(),
      keys = new Set<string>();
    this.#grants = Object.freeze(
      copy.map((value) => {
        const grant = fields(value, ['principal_id', 'token_sha256', 'scopes']);
        const principal = identifier(grant.principal_id),
          key = digest(grant.token_sha256);
        if (ids.has(principal) || keys.has(key)) throw new ContractError();
        ids.add(principal);
        keys.add(key);
        if (!Array.isArray(grant.scopes) || grant.scopes.length < 1 || grant.scopes.length > 16)
          throw new ContractError();
        const seen = new Set<string>();
        const scopes = Object.freeze(
          grant.scopes.map((value) => {
            const scope = fields(value, [
              'scope',
              'invoke_capabilities',
              'result_capabilities',
              'cancel_capabilities',
              'evidence_sources',
            ]);
            const namespace = fields(scope.scope, ['tenant_id', 'account_id']);
            const ns = Object.freeze({
              tenant_id: identifier(namespace.tenant_id),
              account_id: identifier(namespace.account_id),
            });
            const identity = ns.tenant_id + '/' + ns.account_id;
            if (seen.has(identity)) throw new ContractError();
            seen.add(identity);
            const caps = (value: unknown): readonly string[] => {
              if (
                !Array.isArray(value) ||
                value.length > 2 ||
                value.some(
                  (item) =>
                    !SUPPORTED_CAPABILITIES.includes(
                      item as (typeof SUPPORTED_CAPABILITIES)[number],
                    ),
                ) ||
                new Set(value).size !== value.length
              )
                throw new ContractError();
              return Object.freeze([...value] as string[]);
            };
            if (!Array.isArray(scope.evidence_sources) || scope.evidence_sources.length > 64)
              throw new ContractError();
            const sources = scope.evidence_sources.map(identifier);
            if (new Set(sources).size !== sources.length) throw new ContractError();
            return Object.freeze({
              scope: ns,
              invoke_capabilities: caps(scope.invoke_capabilities),
              result_capabilities: caps(scope.result_capabilities),
              cancel_capabilities: caps(scope.cancel_capabilities),
              evidence_sources: Object.freeze(sources),
            });
          }),
        );
        return Object.freeze({
          principal_id: principal,
          token_sha256: key,
          scopes,
        });
      }),
    );
  }
  authenticate(authorization: string): PrincipalGrant {
    if (
      typeof authorization !== 'string' ||
      authorization.length !== 50 ||
      !authorization.startsWith('Bearer ')
    )
      throw new ContractError('unauthorized');
    const supplied = Buffer.from(tokenDigest(authorization.slice(7)), 'hex');
    let matched: PrincipalGrant | undefined;
    for (const grant of this.#grants) {
      if (timingSafeEqual(supplied, Buffer.from(grant.token_sha256, 'hex'))) matched = grant;
    }
    if (!matched) throw new ContractError('unauthorized');
    return matched;
  }
  authorize(
    authorization: string,
    operation: Operation,
    request: CapabilityRequest,
    sourceId?: string,
  ): string {
    const grant = this.authenticate(authorization);
    for (const scope of grant.scopes) {
      if (!sameScope(scope.scope, request.scope)) continue;
      if (operation === 'evidence') {
        if (sourceId !== undefined && scope.evidence_sources.includes(sourceId))
          return grant.principal_id;
      } else if (operation === 'invoke' || operation === 'result' || operation === 'cancel') {
        const caps = {
          invoke: scope.invoke_capabilities,
          result: scope.result_capabilities,
          cancel: scope.cancel_capabilities,
        }[operation];
        if (caps.includes(request.capability)) return grant.principal_id;
      }
    }
    throw new ContractError('unauthorized');
  }
}
export type EvidenceRecord = Readonly<{
  scope: Scope;
  reference: EvidenceRef;
  body: Uint8Array;
}>;
const evidenceKey = (scope: Scope, id: string) =>
  scope.tenant_id + '/' + scope.account_id + '/' + id;
export class EvidenceRegistry {
  readonly #records = new Map<string, EvidenceRecord>();
  constructor(records: readonly EvidenceRecord[]) {
    if (!Array.isArray(records) || records.length > 32) throw new ContractError();
    let total = 0;
    for (const record of records) {
      if (
        !(record.body instanceof Uint8Array) ||
        record.body.byteLength < 1 ||
        record.body.byteLength > 2097152
      )
        throw new ContractError();
      total += record.body.byteLength;
      if (total > 8388608) throw new ContractError();
      const metadata = decode(
        canonical({
          scope: record.scope,
          reference: record.reference,
        }),
        16384,
      ) as {
        scope: Scope;
        reference: EvidenceRef;
      };
      const ref = metadata.reference;
      identifier(metadata.scope.tenant_id);
      identifier(metadata.scope.account_id);
      identifier(ref.source_id);
      identifier(ref.version);
      digest(ref.sha256);
      integer(ref.byte_length, 1, 2097152);
      if (ref.media_type === 'application/json') {
        if (ref.byte_length > 4096 || ref.width !== null || ref.height !== null)
          throw new ContractError();
      } else if (ref.media_type === 'image/png') {
        integer(ref.width, 1, 2048);
        integer(ref.height, 1, 2048);
      } else throw new ContractError();
      const key = evidenceKey(metadata.scope, ref.source_id);
      if (
        this.#records.has(key) ||
        record.body.byteLength !== ref.byte_length ||
        hash(record.body) !== ref.sha256
      )
        throw new ContractError('evidence_mismatch');
      this.#records.set(
        key,
        Object.freeze({
          scope: Object.freeze(metadata.scope),
          reference: Object.freeze(ref),
          body: Buffer.from(record.body),
        }),
      );
    }
  }
  resolve(
    authorization: string,
    request: CapabilityRequest,
    trust: LocalTrust,
  ): readonly EvidenceRecord[] {
    return Object.freeze(
      request.evidence.map((ref) => {
        trust.authorize(authorization, 'evidence', request, ref.source_id);
        const record = this.#records.get(evidenceKey(request.scope, ref.source_id));
        if (
          !record ||
          Buffer.compare(Buffer.from(canonical(record.reference)), Buffer.from(canonical(ref))) !==
            0
        )
          throw new ContractError('evidence_mismatch'); // Typed arrays cannot be frozen; never expose the registry's owned byte buffer.
        return Object.freeze({
          ...record,
          body: Buffer.from(record.body),
        });
      }),
    );
  }
}
export type AttemptPermit = Readonly<{
  principal_id: string;
  attempt_id: string;
  scope: Scope;
  input_fingerprint: string;
}>;
export class AttemptBoundary {
  readonly #trust: LocalTrust;
  readonly #evidence: EvidenceRegistry;
  readonly #maxActive: number;
  readonly #maxPerPrincipal: number;
  readonly #active = new Map<
    string,
    {
      permit: AttemptPermit;
      request: CapabilityRequest;
    }
  >();
  constructor(trust: LocalTrust, evidence: EvidenceRegistry, maxActive = 4, maxPerPrincipal = 2) {
    this.#trust = trust;
    this.#evidence = evidence;
    this.#maxActive = integer(maxActive, 1, 16);
    this.#maxPerPrincipal = integer(maxPerPrincipal, 1, maxActive);
  }
  get active(): number {
    return this.#active.size;
  }
  acquire(authorization: string, input: CapabilityRequest, observedAtMs: number): AttemptPermit {
    const request = parseCapabilityRequest(encodeCapabilityRequest(input));
    const principal = this.#trust.authorize(authorization, 'invoke', request);
    integer(observedAtMs, 0, MAX_TIMESTAMP_MS);
    const remaining = request.deadline_at_ms - observedAtMs;
    if (remaining <= 0 || remaining > MAX_DEADLINE_WINDOW_MS) throw new ContractError('expired');
    this.#evidence.resolve(authorization, request, this.#trust);
    const key = evidenceKey(request.scope, request.attempt.attempt_id);
    if (this.#active.has(key)) throw new ContractError('identity_conflict');
    for (const active of this.#active.values()) {
      if (
        sameScope(active.request.scope, request.scope) &&
        active.request.delegation_id === request.delegation_id &&
        active.request.input_fingerprint !== request.input_fingerprint
      )
        throw new ContractError('identity_conflict');
    }
    if (
      this.#active.size >= this.#maxActive ||
      [...this.#active.values()].filter((item) => item.permit.principal_id === principal).length >=
        this.#maxPerPrincipal
    )
      throw new ContractError('capacity');
    const permit = Object.freeze({
      principal_id: principal,
      attempt_id: request.attempt.attempt_id,
      scope: request.scope,
      input_fingerprint: request.input_fingerprint,
    });
    this.#active.set(key, {
      permit,
      request,
    });
    return permit;
  }
  inspect(
    authorization: string,
    input: DelegationRequest,
    operation: 'result' | 'cancel',
  ): DelegationRequest;
  inspect(
    authorization: string,
    input: DocumentRequest,
    operation: 'result' | 'cancel',
  ): DocumentRequest;
  inspect(
    authorization: string,
    input: CapabilityRequest,
    operation: 'result' | 'cancel',
  ): CapabilityRequest;
  inspect(
    authorization: string,
    input: CapabilityRequest,
    operation: 'result' | 'cancel',
  ): CapabilityRequest {
    if (operation !== 'result' && operation !== 'cancel') throw new ContractError('unauthorized');
    const request = parseCapabilityRequest(encodeCapabilityRequest(input));
    this.#trust.authorize(authorization, operation, request);
    const observed = this.#active.get(evidenceKey(request.scope, request.attempt.attempt_id));
    if (!observed) throw new ContractError('unknown_attempt');
    if (
      observed.request.input_fingerprint !== request.input_fingerprint ||
      observed.request.delegation_id !== request.delegation_id ||
      observed.request.attempt.number !== request.attempt.number
    )
      throw new ContractError('identity_conflict');
    return observed.request;
  }
  release(permit: AttemptPermit): void {
    const key = evidenceKey(permit.scope, permit.attempt_id);
    if (this.#active.get(key)?.permit !== permit) throw new ContractError('unknown_attempt');
    this.#active.delete(key);
  }
}
export function verifyPolicyFacts(
  request: DelegationRequest,
  result: DelegationResult,
  records: readonly EvidenceRecord[],
  observedAtMs: number,
): 'candidate' | 'expired' | 'clarification' {
  const applicability = matchResult(request, result, observedAtMs);
  const policy = records.find(
    (item) =>
      sameScope(item.scope, request.scope) &&
      item.reference.source_id === request.context_snapshot.policy_source_id,
  );
  if (
    !policy ||
    !request.evidence.some(
      (ref) =>
        Buffer.compare(Buffer.from(canonical(ref)), Buffer.from(canonical(policy.reference))) === 0,
    ) ||
    hash(policy.body) !== policy.reference.sha256
  )
    throw new ContractError('evidence_mismatch');
  const value = fields(decode(policy.body, 4096), ['policy_version', 'minimum_notice_days']);
  if (value.policy_version !== request.context_snapshot.policy_version)
    throw new ContractError('unsupported_facts');
  const days = integer(value.minimum_notice_days, 0, 3650);
  const refs = result.evidence_refs.filter((ref) => ref.source_id === policy.reference.source_id);
  if (refs.length !== 1 || refs[0]!.rule_id !== 'notice_minimum_days')
    throw new ContractError('unsupported_facts');
  if (applicability === 'expired') return 'expired';
  if (result.uncertainty !== 'none') return 'clarification';
  if (result.eligible !== request.context_snapshot.days_before_arrival >= days)
    throw new ContractError('unsupported_facts');
  return 'candidate';
}
