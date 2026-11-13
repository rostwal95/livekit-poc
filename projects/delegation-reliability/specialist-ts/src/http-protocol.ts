/** Version-one transport observations; none is durable acceptance or cancellation proof. */
import { ContractError, canonical, decode, digest, fields, identifier } from './contracts.js';
import type { Scope } from './contracts.js';
export const HTTP_CODES = [
  'invalid_http',
  'body_limit',
  'body_timeout',
  'request_aborted',
  'deadline_exceeded',
  'closing',
  'internal_error',
  'cleanup_incomplete',
  'invalid_response',
  'connection_failed',
  'client_closed',
  'client_capacity',
] as const;
export type HttpCode = (typeof HTTP_CODES)[number];
export class SpecialistHttpError extends Error {
  constructor(readonly code: HttpCode) {
    super(code);
    this.name = 'SpecialistHttpError';
  }
}
export type Endpoint = Readonly<{ host: '127.0.0.1'; port: number }>;
export function endpoint(input: Endpoint): Endpoint {
  const value = fields(input, ['host', 'port']);
  if (
    value.host !== '127.0.0.1' ||
    typeof value.port !== 'number' ||
    !Number.isSafeInteger(value.port) ||
    value.port < 1 ||
    value.port > 65535
  )
    throw new SpecialistHttpError('invalid_http');
  return Object.freeze({ host: '127.0.0.1', port: value.port });
}
export type AttemptObservation = Readonly<{
  schema_version: 1;
  kind: 'specialist.attempt_observation';
  scope: Scope;
  delegation_id: string;
  attempt_id: string;
  input_fingerprint: string;
  state: 'running';
  cancel_requested: boolean;
  deadline_exceeded: boolean;
  transport_disconnected: boolean;
  closing: boolean;
  durable: false;
}>;
export function parseObservation(bytes: Uint8Array): AttemptObservation {
  const value = fields(decode(bytes, 1024), [
    'schema_version',
    'kind',
    'scope',
    'delegation_id',
    'attempt_id',
    'input_fingerprint',
    'state',
    'cancel_requested',
    'deadline_exceeded',
    'transport_disconnected',
    'closing',
    'durable',
  ]);
  const scope = fields(value.scope, ['tenant_id', 'account_id']);
  if (
    value.schema_version !== 1 ||
    value.kind !== 'specialist.attempt_observation' ||
    value.state !== 'running' ||
    value.durable !== false ||
    ['cancel_requested', 'deadline_exceeded', 'transport_disconnected', 'closing'].some(
      (key) => typeof value[key] !== 'boolean',
    )
  )
    throw new SpecialistHttpError('invalid_response');
  return Object.freeze({
    schema_version: 1,
    kind: 'specialist.attempt_observation',
    scope: Object.freeze({
      tenant_id: identifier(scope.tenant_id),
      account_id: identifier(scope.account_id),
    }),
    delegation_id: identifier(value.delegation_id),
    attempt_id: identifier(value.attempt_id),
    input_fingerprint: digest(value.input_fingerprint),
    state: 'running',
    cancel_requested: value.cancel_requested as boolean,
    deadline_exceeded: value.deadline_exceeded as boolean,
    transport_disconnected: value.transport_disconnected as boolean,
    closing: value.closing as boolean,
    durable: false,
  });
}
export function httpErrorBytes(code: HttpCode, requestId: string): Uint8Array {
  if (!HTTP_CODES.includes(code)) throw new ContractError();
  return canonical({
    schema_version: 1,
    kind: 'specialist.http_error',
    code,
    request_id: identifier(requestId),
    retryable: false,
  });
}
export function parseHttpError(bytes: Uint8Array): SpecialistHttpError {
  const value = fields(decode(bytes, 512), [
    'schema_version',
    'kind',
    'code',
    'request_id',
    'retryable',
  ]);
  if (
    value.schema_version !== 1 ||
    value.kind !== 'specialist.http_error' ||
    value.retryable !== false ||
    typeof value.code !== 'string' ||
    !(HTTP_CODES as readonly string[]).includes(value.code)
  )
    throw new SpecialistHttpError('invalid_response');
  identifier(value.request_id);
  return new SpecialistHttpError(value.code as HttpCode);
}
