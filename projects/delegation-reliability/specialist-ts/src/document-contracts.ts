/** Additive read-only document contract; policy codecs retain their exact shape. */
import {
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

export const DOCUMENT_CAPABILITY = 'booking.extract_document' as const;
export const DOCUMENT_FIELDS = Object.freeze([
  'booking_reference',
  'property_name',
  'check_in',
  'check_out',
] as const);
export type DocumentFieldName = (typeof DOCUMENT_FIELDS)[number];
export type DocumentState = 'known' | 'missing' | 'ambiguous';
export type DocumentOutcome = 'extracted' | 'clarification_required';
export type DocumentRequest = Readonly<{
  schema_version: 1;
  kind: 'delegation.request';
  capability: typeof DOCUMENT_CAPABILITY;
  input_schema_version: 1;
  scope: Scope;
  delegation_id: string;
  case_id: string;
  request_revision: number;
  context_snapshot: Readonly<{
    document_kind: 'booking_confirmation_v1';
    document_source_id: string;
    requested_fields: typeof DOCUMENT_FIELDS;
    note: string;
  }>;
  evidence: readonly EvidenceRef[];
  deadline_at_ms: number;
  result_route: Readonly<{ conversation_id: string }>;
  attempt: Readonly<{ attempt_id: string; number: number }>;
  input_fingerprint: string;
}>;
export type DocumentRegion = Readonly<{ x: number; y: number; width: number; height: number }>;
export type DocumentEvidence = Readonly<{
  source_id: string;
  version: string;
  sha256: string;
  region: DocumentRegion;
}>;
export type DocumentField = Readonly<{
  state: DocumentState;
  value: string | null;
  evidence_refs: readonly DocumentEvidence[];
}>;
export type DocumentResult = Readonly<{
  schema_version: 1;
  kind: 'delegation.result';
  capability: typeof DOCUMENT_CAPABILITY;
  result_schema_version: 1;
  scope: Scope;
  delegation_id: string;
  case_id: string;
  request_revision: number;
  attempt_id: string;
  input_fingerprint: string;
  outcome: DocumentOutcome;
  fields: Readonly<Record<DocumentFieldName, DocumentField>>;
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
  'outcome',
  'fields',
  'producer',
  'completed_at_ms',
] as const;
function freeze<T>(value: T): T {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}
function scope(value: unknown): Scope {
  const obj = fields(value, ['tenant_id', 'account_id']);
  return { tenant_id: identifier(obj.tenant_id), account_id: identifier(obj.account_id) };
}
function header(obj: Record<string, unknown>, kind: string, version: string): void {
  if (obj.schema_version !== 1 || obj[version] !== 1)
    throw new ContractError('unsupported_version');
  if (obj.kind !== kind) throw new ContractError();
  if (obj.capability !== DOCUMENT_CAPABILITY) throw new ContractError('unknown_capability');
}
export function logicalDocumentFingerprint(wire: Record<string, unknown>): string {
  return logicalFingerprint(wire);
}
export function parseDocumentRequest(payload: Uint8Array): DocumentRequest {
  const obj = fields(decode(payload, MAX_REQUEST_BYTES), REQUEST_FIELDS);
  header(obj, 'delegation.request', 'input_schema_version');
  const context = fields(obj.context_snapshot, [
    'document_kind',
    'document_source_id',
    'requested_fields',
    'note',
  ]);
  if (
    context.document_kind !== 'booking_confirmation_v1' ||
    !Array.isArray(context.requested_fields) ||
    context.requested_fields.length !== DOCUMENT_FIELDS.length ||
    context.requested_fields.some((v, i) => v !== DOCUMENT_FIELDS[i])
  )
    throw new ContractError();
  if (!Array.isArray(obj.evidence) || obj.evidence.length !== 1) throw new ContractError();
  const ref = fields(obj.evidence[0], [
    'source_id',
    'version',
    'sha256',
    'media_type',
    'byte_length',
    'width',
    'height',
  ]);
  if (ref.media_type !== 'image/png') throw new ContractError();
  const source = identifier(context.document_source_id);
  const evidence: EvidenceRef = {
    source_id: identifier(ref.source_id),
    version: identifier(ref.version),
    sha256: digest(ref.sha256),
    media_type: 'image/png',
    byte_length: integer(ref.byte_length, 1, 2097152),
    width: integer(ref.width, 1, 2048),
    height: integer(ref.height, 1, 2048),
  };
  if (evidence.source_id !== source) throw new ContractError('evidence_mismatch');
  const fingerprint = digest(obj.input_fingerprint);
  if (fingerprint !== logicalDocumentFingerprint(obj)) throw new ContractError('identity_conflict');
  const route = fields(obj.result_route, ['conversation_id']),
    attempt = fields(obj.attempt, ['attempt_id', 'number']);
  return freeze({
    schema_version: 1,
    kind: 'delegation.request',
    capability: DOCUMENT_CAPABILITY,
    input_schema_version: 1,
    scope: scope(obj.scope),
    delegation_id: identifier(obj.delegation_id),
    case_id: identifier(obj.case_id),
    request_revision: integer(obj.request_revision, 1, 1000000),
    context_snapshot: {
      document_kind: 'booking_confirmation_v1',
      document_source_id: source,
      requested_fields: DOCUMENT_FIELDS,
      note: text(context.note),
    },
    evidence: [evidence],
    deadline_at_ms: integer(obj.deadline_at_ms, 0, MAX_TIMESTAMP_MS),
    result_route: { conversation_id: identifier(route.conversation_id) },
    attempt: {
      attempt_id: identifier(attempt.attempt_id),
      number: integer(attempt.number, 1, 1000),
    },
    input_fingerprint: fingerprint,
  });
}
export function produceDocumentRequest(input: unknown): DocumentRequest {
  const obj = fields(
    decode(canonical(input), MAX_REQUEST_BYTES),
    REQUEST_FIELDS.filter((x) => x !== 'input_fingerprint'),
  );
  return parseDocumentRequest(
    canonical({ ...obj, input_fingerprint: logicalDocumentFingerprint(obj) }),
  );
}
export function encodeDocumentRequest(value: DocumentRequest): Uint8Array {
  const bytes = canonical(value);
  parseDocumentRequest(bytes);
  return bytes;
}
function evidence(value: unknown): DocumentEvidence {
  const obj = fields(value, ['source_id', 'version', 'sha256', 'region']);
  const r = fields(obj.region, ['x', 'y', 'width', 'height']);
  const region = {
    x: integer(r.x, 0, 2047),
    y: integer(r.y, 0, 2047),
    width: integer(r.width, 1, 2048),
    height: integer(r.height, 1, 2048),
  };
  if (region.x + region.width > 2048 || region.y + region.height > 2048) throw new ContractError();
  return {
    source_id: identifier(obj.source_id),
    version: identifier(obj.version),
    sha256: digest(obj.sha256),
    region,
  };
}
function calendar(value: string): string {
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}(?![\s\S])/.test(value)) throw new ContractError();
  const year = Number(value.slice(0, 4)),
    month = Number(value.slice(5, 7)),
    day = Number(value.slice(8));
  if (year < 1970 || year > 2100) throw new ContractError();
  const d = new Date(Date.UTC(year, month - 1, day));
  if (d.getUTCFullYear() !== year || d.getUTCMonth() !== month - 1 || d.getUTCDate() !== day)
    throw new ContractError();
  return value;
}
function field(value: unknown, name: DocumentFieldName): DocumentField {
  const obj = fields(value, ['state', 'value', 'evidence_refs']);
  if (
    typeof obj.state !== 'string' ||
    !['known', 'missing', 'ambiguous'].includes(obj.state) ||
    !Array.isArray(obj.evidence_refs)
  )
    throw new ContractError();
  let val: string | null = null;
  if (obj.state === 'known') {
    val = text(obj.value, 128);
    if (val.trim().length === 0 || obj.evidence_refs.length < 1 || obj.evidence_refs.length > 2)
      throw new ContractError();
    if (name === 'check_in' || name === 'check_out') val = calendar(val);
  } else if (obj.value !== null || obj.evidence_refs.length !== (obj.state === 'missing' ? 0 : 2))
    throw new ContractError();
  const refs = obj.evidence_refs.map(evidence);
  if (new Set(refs.map((r) => Buffer.from(canonical(r)).toString('hex'))).size !== refs.length)
    throw new ContractError();
  return { state: obj.state as DocumentState, value: val, evidence_refs: refs };
}
export function parseDocumentResult(payload: Uint8Array): DocumentResult {
  const obj = fields(decode(payload, MAX_RESULT_BYTES), RESULT_FIELDS);
  header(obj, 'delegation.result', 'result_schema_version');
  const f = fields(obj.fields, DOCUMENT_FIELDS);
  const parsed = {
    booking_reference: field(f.booking_reference, 'booking_reference'),
    property_name: field(f.property_name, 'property_name'),
    check_in: field(f.check_in, 'check_in'),
    check_out: field(f.check_out, 'check_out'),
  };
  const outcome = Object.values(parsed).every((x) => x.state === 'known')
    ? 'extracted'
    : 'clarification_required';
  if (obj.outcome !== outcome) throw new ContractError();
  if (
    parsed.check_in.value !== null &&
    parsed.check_out.value !== null &&
    parsed.check_out.value <= parsed.check_in.value
  )
    throw new ContractError();
  const p = fields(obj.producer, [
    'producer_id',
    'model_id',
    'model_version',
    'config_fingerprint',
  ]);
  const model_id = p.model_id === null ? null : text(p.model_id, 64),
    model_version = p.model_version === null ? null : text(p.model_version, 64);
  if ((model_id === null) !== (model_version === null) || model_id === '' || model_version === '')
    throw new ContractError();
  return freeze({
    schema_version: 1,
    kind: 'delegation.result',
    capability: DOCUMENT_CAPABILITY,
    result_schema_version: 1,
    scope: scope(obj.scope),
    delegation_id: identifier(obj.delegation_id),
    case_id: identifier(obj.case_id),
    request_revision: integer(obj.request_revision, 1, 1000000),
    attempt_id: identifier(obj.attempt_id),
    input_fingerprint: digest(obj.input_fingerprint),
    outcome,
    fields: parsed,
    producer: {
      producer_id: identifier(p.producer_id),
      model_id,
      model_version,
      config_fingerprint: digest(p.config_fingerprint),
    },
    completed_at_ms: integer(obj.completed_at_ms, 0, MAX_TIMESTAMP_MS),
  });
}
export function encodeDocumentResult(value: DocumentResult): Uint8Array {
  const bytes = canonical(value);
  parseDocumentResult(bytes);
  return bytes;
}
export function matchDocumentResult(
  request: DocumentRequest,
  result: DocumentResult,
  observedAtMs: number,
): 'candidate' | 'expired' {
  request = parseDocumentRequest(encodeDocumentRequest(request));
  result = parseDocumentResult(encodeDocumentResult(result));
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
  const source = request.evidence[0]!;
  for (const item of Object.values(result.fields))
    for (const ref of item.evidence_refs) {
      if (
        ref.source_id !== source.source_id ||
        ref.version !== source.version ||
        ref.sha256 !== source.sha256
      )
        throw new ContractError('evidence_mismatch');
      if (
        ref.region.x + ref.region.width > source.width! ||
        ref.region.y + ref.region.height > source.height!
      )
        throw new ContractError('evidence_mismatch');
    }
  return observedAtMs >= request.deadline_at_ms ? 'expired' : 'candidate';
}
