/** Fixed-loopback client: bounded bodies, explicit abort, no redirects or retries. */
import { request as httpRequest, type ClientRequest, type IncomingMessage } from 'node:http';
import {
  ContractError,
  decode,
  fields,
  encodeRequest,
  matchResult,
  MAX_RESULT_BYTES,
  parseError,
  parseRequest,
  parseResult,
} from './contracts.js';
import type { DelegationRequest, DelegationResult } from './contracts.js';
import { encodeCapabilityRequest, parseCapabilityRequest } from './capability-codec.js';
import {
  parseFixedPolicyRequest,
  encodeFixedPolicyRequest,
  parseFixedPolicyResult,
  matchFixedPolicyResult,
} from './fixed-policy-contracts.js';
import type { FixedPolicyRequest, FixedPolicyResult } from './fixed-policy-contracts.js';
import { snapshotFixedPolicyRecords, verifyFixedPolicyFacts } from './fixed-policy.js';
import type { FixedPolicyResultObservation } from './fixed-policy.js';
import type { EvidenceRecord } from './security.js';
import type { CapabilityRequest } from './capability-codec.js';
import {
  encodeDocumentRequest,
  parseDocumentRequest,
  parseDocumentResult,
  matchDocumentResult,
} from './document-contracts.js';
import type { DocumentRequest, DocumentResult } from './document-contracts.js';
import {
  endpoint,
  parseHttpError,
  parseObservation,
  SpecialistHttpError,
} from './http-protocol.js';
import type { AttemptObservation, Endpoint } from './http-protocol.js';
export type ClientOptions = Readonly<{ timeoutMs?: number; maxActive?: number }>;
export type CallOptions = Readonly<{ signal?: AbortSignal }>;
/** Counts actual owned HTTP registrations and closes, not facade entries or remote work. */
export type SpecialistClientMetrics = Readonly<{
  active: number;
  started: number;
  settled: number;
  invokeStarted: number;
  statusStarted: number;
  cancelStarted: number;
  validated: number;
  validationFailed: number;
  capacityRejected: number;
}>;
type Owned = Readonly<{ request: ClientRequest; closed: Promise<void> }>;
function remoteFailure(bytes: Uint8Array): ContractError | SpecialistHttpError {
  try {
    const value = decode(bytes, 512);
    if (value && typeof value === 'object' && 'kind' in value && value.kind === 'delegation.error')
      return new ContractError(parseError(bytes).code);
    return parseHttpError(bytes);
  } catch {
    return new SpecialistHttpError('invalid_response');
  }
}
function responseLength(response: IncomingMessage, maximum: number): number {
  const seen = new Set<string>();
  for (let index = 0; index < response.rawHeaders.length; index += 2) {
    const name = response.rawHeaders[index]!.toLowerCase();
    if (seen.has(name)) throw new SpecialistHttpError('invalid_response');
    seen.add(name);
  }
  const length = response.headers['content-length'];
  if (
    response.headers['content-type'] !== 'application/json' ||
    response.headers['transfer-encoding'] !== undefined ||
    response.headers['content-encoding'] !== undefined ||
    typeof length !== 'string' ||
    !/^[1-9][0-9]{0,5}(?![\s\S])/.test(length) ||
    Number(length) > maximum
  )
    throw new SpecialistHttpError('invalid_response');
  return Number(length);
}
export class SpecialistClient {
  readonly #endpoint: Endpoint;
  readonly #authorization: string;
  readonly #timeout: number;
  readonly #maxActive: number;
  readonly #active = new Set<Owned>();
  #closing = false;
  readonly #counts = {
    started: 0,
    settled: 0,
    invokeStarted: 0,
    statusStarted: 0,
    cancelStarted: 0,
    validated: 0,
    validationFailed: 0,
    capacityRejected: 0,
  };
  constructor(selected: Endpoint, authorization: string, options: ClientOptions = {}) {
    this.#endpoint = endpoint(selected);
    if (
      typeof authorization !== 'string' ||
      !/^Bearer [A-Za-z0-9_-]{43}(?![\s\S])/.test(authorization)
    )
      throw new SpecialistHttpError('invalid_http');
    this.#authorization = authorization;
    this.#timeout = options.timeoutMs ?? 5000;
    this.#maxActive = options.maxActive ?? 4;
    if (
      !Number.isSafeInteger(this.#timeout) ||
      this.#timeout < 20 ||
      this.#timeout > 5000 ||
      !Number.isSafeInteger(this.#maxActive) ||
      this.#maxActive < 1 ||
      this.#maxActive > 16 ||
      Object.keys(options).some((key) => !['timeoutMs', 'maxActive'].includes(key))
    )
      throw new SpecialistHttpError('invalid_http');
  }
  get active(): number {
    return this.#active.size;
  }
  metrics(): SpecialistClientMetrics {
    return Object.freeze({ ...this.#counts, active: this.#active.size });
  }
  async invoke(input: DelegationRequest, options: CallOptions = {}): Promise<DelegationResult> {
    const snapshot = parseRequest(encodeRequest(input));
    const bytes = await this.#call('invoke', snapshot, options);
    let result: DelegationResult;
    try {
      result = parseResult(bytes);
      if (matchResult(snapshot, result, Date.now()) !== 'candidate')
        throw new SpecialistHttpError('deadline_exceeded');
    } catch (error) {
      this.#counts.validationFailed++;
      if (error instanceof SpecialistHttpError) throw error;
      throw new SpecialistHttpError('invalid_response');
    }
    this.#counts.validated++;
    return result;
  }
  async invokeDocument(input: DocumentRequest, options: CallOptions = {}): Promise<DocumentResult> {
    const snapshot = parseDocumentRequest(encodeDocumentRequest(input));
    const bytes = await this.#call('invoke', snapshot, options);
    try {
      const result = parseDocumentResult(bytes);
      if (matchDocumentResult(snapshot, result, Date.now()) !== 'candidate')
        throw new SpecialistHttpError('deadline_exceeded');
      this.#counts.validated++;
      return result;
    } catch (error) {
      this.#counts.validationFailed++;
      if (error instanceof SpecialistHttpError) throw error;
      throw new SpecialistHttpError('invalid_response');
    }
  }
  async invokeFixedPolicy(
    input: FixedPolicyRequest,
    options: CallOptions = {},
  ): Promise<FixedPolicyResult> {
    return (await this.#fixedPolicyResult(input, options, false)).result;
  }
  async invokeFixedPolicyObserved(
    input: FixedPolicyRequest,
    records: readonly EvidenceRecord[],
    options: CallOptions = {},
  ): Promise<FixedPolicyResultObservation> {
    // The verified API admits exactly its two immutable JSON sources.
    if (!Array.isArray(records) || records.length !== 2)
      throw new ContractError('invalid_contract');
    for (let index = 0; index < 2; index++) {
      const item = Object.getOwnPropertyDescriptor(records, String(index));
      if (!item || !('value' in item)) throw new ContractError('invalid_contract');
      const raw = fields(item.value, ['scope', 'reference', 'body']),
        reference = fields(raw.reference, [
          'source_id',
          'version',
          'sha256',
          'media_type',
          'byte_length',
          'width',
          'height',
        ]);
      if (
        !(raw.body instanceof Uint8Array) ||
        raw.body.byteLength < 1 ||
        raw.body.byteLength > 4096 ||
        reference.media_type !== 'application/json' ||
        reference.width !== null ||
        reference.height !== null
      )
        throw new ContractError('invalid_contract');
      const value = decode(raw.body, 4096);
      if (!value || typeof value !== 'object' || Array.isArray(value))
        throw new ContractError('invalid_contract');
    }
    // Copy every source and the request before the first await.
    const snapshot = parseFixedPolicyRequest(encodeFixedPolicyRequest(input)),
      evidence = snapshotFixedPolicyRecords(records);
    for (const reference of snapshot.evidence) {
      const matching = evidence.filter(
        (record) =>
          record.scope.tenant_id === snapshot.scope.tenant_id &&
          record.scope.account_id === snapshot.scope.account_id &&
          record.reference.source_id === reference.source_id,
      );
      if (
        matching.length !== 1 ||
        (
          [
            'source_id',
            'version',
            'sha256',
            'media_type',
            'byte_length',
            'width',
            'height',
          ] as const
        ).some((key) => matching[0]!.reference[key] !== reference[key])
      )
        throw new ContractError('evidence_mismatch');
      if (reference.media_type !== 'application/json' || matching[0]!.body.byteLength > 4096)
        throw new ContractError('invalid_contract');
    }
    return this.#fixedPolicyResult(snapshot, options, true, evidence);
  }
  async #fixedPolicyResult(
    input: FixedPolicyRequest,
    options: CallOptions,
    includeExpired: boolean,
    records?: readonly EvidenceRecord[],
  ): Promise<FixedPolicyResultObservation> {
    const snapshot = parseFixedPolicyRequest(encodeFixedPolicyRequest(input)),
      bytes = await this.#call('invoke', snapshot, options);
    try {
      const result = parseFixedPolicyResult(bytes),
        observedAtMs = Date.now();
      const applicability =
        records === undefined
          ? matchFixedPolicyResult(snapshot, result, observedAtMs)
          : verifyFixedPolicyFacts(snapshot, result, records, observedAtMs);
      if (applicability === 'expired' && !includeExpired)
        throw new SpecialistHttpError('deadline_exceeded');
      this.#counts.validated++;
      return Object.freeze({ result, applicability, observedAtMs });
    } catch (error) {
      this.#counts.validationFailed++;
      if (error instanceof SpecialistHttpError) throw error;
      throw new SpecialistHttpError('invalid_response');
    }
  }
  async statusFixedPolicy(
    input: FixedPolicyRequest,
    options: CallOptions = {},
  ): Promise<AttemptObservation> {
    return this.#observe('status', input, options);
  }
  async cancelFixedPolicy(
    input: FixedPolicyRequest,
    options: CallOptions = {},
  ): Promise<AttemptObservation> {
    return this.#observe('cancel', input, options);
  }
  async statusDocument(
    input: DocumentRequest,
    options: CallOptions = {},
  ): Promise<AttemptObservation> {
    return this.#observe('status', input, options);
  }
  async cancelDocument(
    input: DocumentRequest,
    options: CallOptions = {},
  ): Promise<AttemptObservation> {
    return this.#observe('cancel', input, options);
  }
  async status(input: DelegationRequest, options: CallOptions = {}): Promise<AttemptObservation> {
    return await this.#observe('status', input, options);
  }
  async cancel(input: DelegationRequest, options: CallOptions = {}): Promise<AttemptObservation> {
    return await this.#observe('cancel', input, options);
  }
  async #observe(
    operation: 'status' | 'cancel',
    input: CapabilityRequest,
    options: CallOptions,
  ): Promise<AttemptObservation> {
    const snapshot = parseCapabilityRequest(encodeCapabilityRequest(input));
    const bytes = await this.#call(operation, snapshot, options);
    try {
      const result = parseObservation(bytes);
      if (
        result.scope.tenant_id !== snapshot.scope.tenant_id ||
        result.scope.account_id !== snapshot.scope.account_id ||
        result.delegation_id !== snapshot.delegation_id ||
        result.attempt_id !== snapshot.attempt.attempt_id ||
        result.input_fingerprint !== snapshot.input_fingerprint ||
        (operation === 'cancel' && !result.cancel_requested)
      )
        throw new SpecialistHttpError('invalid_response');
      this.#counts.validated++;
      return result;
    } catch {
      this.#counts.validationFailed++;
      throw new SpecialistHttpError('invalid_response');
    }
  }
  #call(
    operation: 'invoke' | 'status' | 'cancel',
    input: CapabilityRequest,
    options: CallOptions,
  ): Promise<Uint8Array> {
    if (this.#closing) return Promise.reject(new SpecialistHttpError('client_closed'));
    if (this.#active.size >= this.#maxActive) {
      this.#counts.capacityRejected++;
      return Promise.reject(new SpecialistHttpError('client_capacity'));
    }
    if (options.signal !== undefined && !(options.signal instanceof AbortSignal))
      return Promise.reject(new SpecialistHttpError('invalid_http'));
    if (options.signal?.aborted) return Promise.reject(new SpecialistHttpError('request_aborted'));
    const body = encodeCapabilityRequest(input);
    const deadline = performance.now() + this.#timeout;
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error?: Error, bytes?: Uint8Array): void => {
        if (settled) return;
        settled = true;
        if (!error && performance.now() >= deadline)
          error = new SpecialistHttpError('deadline_exceeded');
        clearTimeout(timer);
        options.signal?.removeEventListener('abort', abort);
        if (error) {
          request.destroy();
          reject(error);
        } else resolve(bytes!);
      };
      const request = httpRequest(
        {
          host: this.#endpoint.host,
          port: this.#endpoint.port,
          path: '/v1/' + operation,
          method: 'POST',
          agent: false,
          maxHeaderSize: 8192,
          headers: {
            authorization: this.#authorization,
            'content-type': 'application/json',
            'content-length': body.byteLength,
            connection: 'close',
          },
        },
        (response) => {
          try {
            const code = response.statusCode ?? 0;
            if (code !== (operation === 'cancel' ? 202 : 200) && (code < 400 || code > 599))
              throw new SpecialistHttpError('invalid_response');
            const length = responseLength(
              response,
              code >= 400 ? 512 : operation === 'invoke' ? MAX_RESULT_BYTES : 1024,
            );
            const bytes = Buffer.alloc(length);
            let received = 0;
            response.on('data', (chunk: Buffer) => {
              if (received + chunk.length > length) {
                finish(new SpecialistHttpError('invalid_response'));
                return;
              }
              chunk.copy(bytes, received);
              received += chunk.length;
            });
            response.once('end', () => {
              if (received !== length) finish(new SpecialistHttpError('invalid_response'));
              else if (code >= 400) finish(remoteFailure(bytes));
              else finish(undefined, bytes);
            });
            response.once('aborted', () => finish(new SpecialistHttpError('invalid_response')));
            response.once('error', () => finish(new SpecialistHttpError('connection_failed')));
          } catch {
            response.destroy();
            finish(new SpecialistHttpError('invalid_response'));
          }
        },
      );
      let closed!: () => void;
      const done = new Promise<void>((resolveClosed) => {
        closed = resolveClosed;
      });
      const owned = Object.freeze({ request, closed: done });
      this.#active.add(owned);
      this.#counts.started++;
      if (operation === 'invoke') this.#counts.invokeStarted++;
      else if (operation === 'status') this.#counts.statusStarted++;
      else this.#counts.cancelStarted++;
      request.once('close', () => {
        this.#counts.settled++;
        this.#active.delete(owned);
        closed();
        if (!settled) finish(new SpecialistHttpError('connection_failed'));
      });
      request.once('error', () => finish(new SpecialistHttpError('connection_failed')));
      const abort = (): void => finish(new SpecialistHttpError('request_aborted'));
      const timer = setTimeout(
        () => finish(new SpecialistHttpError('deadline_exceeded')),
        this.#timeout,
      );
      options.signal?.addEventListener('abort', abort, { once: true });
      request.end(body);
    });
  }
  async close(): Promise<void> {
    this.#closing = true;
    const deadline = performance.now() + 1000;
    const owned = [...this.#active];
    for (const item of owned) item.request.destroy();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all(owned.map((item) => item.closed)),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(() => reject(new SpecialistHttpError('cleanup_incomplete')), 1000);
        }),
      ]);
    } finally {
      if (timer) clearTimeout(timer);
    }
    if (this.#active.size !== 0 || performance.now() > deadline)
      throw new SpecialistHttpError('cleanup_incomplete');
  }
}
