/** Closed additive dispatcher. Public legacy policy codecs remain policy-only. */
import {
  CAPABILITY,
  ContractError,
  MAX_REQUEST_BYTES,
  MAX_RESULT_BYTES,
  decode,
  encodeRequest,
  encodeResult,
  parseRequest,
  parseResult,
} from './contracts.js';
import type { DelegationRequest, DelegationResult } from './contracts.js';
import {
  DOCUMENT_CAPABILITY,
  encodeDocumentRequest,
  encodeDocumentResult,
  parseDocumentRequest,
  parseDocumentResult,
} from './document-contracts.js';
import type { DocumentRequest, DocumentResult } from './document-contracts.js';
import {
  parseFixedPolicyRequest,
  encodeFixedPolicyRequest,
  parseFixedPolicyResult,
  encodeFixedPolicyResult,
} from './fixed-policy-contracts.js';
import type { FixedPolicyRequest, FixedPolicyResult } from './fixed-policy-contracts.js';
export type CapabilityRequest = DelegationRequest | DocumentRequest | FixedPolicyRequest;
export type CapabilityResult = DelegationResult | DocumentResult | FixedPolicyResult;
function header(bytes: Uint8Array, maximum: number): Record<string, unknown> {
  const value = decode(bytes, maximum);
  if (value === null || typeof value !== 'object' || Array.isArray(value))
    throw new ContractError();
  return value as Record<string, unknown>;
}
export function parseCapabilityRequest(bytes: Uint8Array): CapabilityRequest {
  const value = header(bytes, MAX_REQUEST_BYTES);
  if (value.capability === DOCUMENT_CAPABILITY) return parseDocumentRequest(bytes);
  return value.capability === CAPABILITY && value.input_schema_version === 2
    ? parseFixedPolicyRequest(bytes)
    : parseRequest(bytes);
}
export function encodeCapabilityRequest(value: CapabilityRequest): Uint8Array {
  if (value.capability === DOCUMENT_CAPABILITY) return encodeDocumentRequest(value);
  return value.input_schema_version === 2 ? encodeFixedPolicyRequest(value) : encodeRequest(value);
}
export function parseCapabilityResult(bytes: Uint8Array): CapabilityResult {
  const value = header(bytes, MAX_RESULT_BYTES);
  if (value.capability === DOCUMENT_CAPABILITY) return parseDocumentResult(bytes);
  return value.capability === CAPABILITY && value.result_schema_version === 2
    ? parseFixedPolicyResult(bytes)
    : parseResult(bytes);
}
export function encodeCapabilityResult(value: CapabilityResult): Uint8Array {
  if (value.capability === DOCUMENT_CAPABILITY) return encodeDocumentResult(value);
  return value.result_schema_version === 2 ? encodeFixedPolicyResult(value) : encodeResult(value);
}
export const SUPPORTED_CAPABILITIES = Object.freeze([CAPABILITY, DOCUMENT_CAPABILITY] as const);
