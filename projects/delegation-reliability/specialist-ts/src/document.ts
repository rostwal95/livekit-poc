import { SpecialistClient } from './client.js';
import type { ClientOptions, CallOptions } from './client.js';
import type { Endpoint, AttemptObservation } from './http-protocol.js';
/** Explicit scripted document provider and image handler; no business ports/OCR. */
import { ContractError, canonical, digest, fields, hash } from './contracts.js';
import type { Producer } from './contracts.js';
import type { EvidenceRecord } from './security.js';
import {
  DOCUMENT_CAPABILITY,
  parseDocumentRequest,
  encodeDocumentRequest,
  parseDocumentResult,
  matchDocumentResult,
} from './document-contracts.js';
import type {
  DocumentRequest,
  DocumentResult,
  DocumentOutcome,
  DocumentField,
  DocumentFieldName,
} from './document-contracts.js';
import { DocumentPngDecoder } from './document-png.js';
import type { DocumentWorkerObservation, VerifiedDocumentImage } from './document-png.js';
import { SpecialistHttpError } from './http-protocol.js';
export type DocumentExtraction = Readonly<{
  outcome: DocumentOutcome;
  fields: Readonly<Record<DocumentFieldName, DocumentField>>;
}>;
export type DocumentExtractionProvider = Readonly<{
  producer: Producer;
  extract: (
    request: DocumentRequest,
    image: VerifiedDocumentImage,
    signal: AbortSignal,
  ) => DocumentExtraction | Promise<DocumentExtraction>;
}>;
export type DocumentHandlerOptions = Readonly<{
  workerObserver?: (value: DocumentWorkerObservation) => void;
}>;
export type DocumentAfterDecode = (
  context: Readonly<{
    request: DocumentRequest;
    image: VerifiedDocumentImage;
    signal: AbortSignal;
  }>,
) => void | Promise<void>;
export class DocumentHandler {
  readonly #provider: DocumentExtractionProvider;
  readonly #decoder: DocumentPngDecoder;
  readonly #work = new Set<
    Readonly<{ promise: Promise<DocumentResult>; controller: AbortController }>
  >();
  #closing = false;
  readonly #counts = { providerStarted: 0, providerSettled: 0, providerFailed: 0 };
  constructor(provider: DocumentExtractionProvider, options: DocumentHandlerOptions = {}) {
    const configured = fields(provider, ['producer', 'extract']);
    if (
      typeof configured.extract !== 'function' ||
      Object.keys(options).some((k) => k !== 'workerObserver')
    )
      throw new ContractError();
    const p = fields(configured.producer, [
      'producer_id',
      'model_id',
      'model_version',
      'config_fingerprint',
    ]);
    // Reuse strict document result producer validation before retaining trusted config.
    if (
      typeof p.producer_id !== 'string' ||
      !/^[a-z][a-z0-9_-]{0,63}(?![\s\S])/.test(p.producer_id) ||
      (p.model_id !== null &&
        (typeof p.model_id !== 'string' ||
          p.model_id.length === 0 ||
          Buffer.byteLength(p.model_id) > 64)) ||
      (p.model_version !== null &&
        (typeof p.model_version !== 'string' ||
          p.model_version.length === 0 ||
          Buffer.byteLength(p.model_version) > 64)) ||
      (p.model_id === null) !== (p.model_version === null)
    )
      throw new ContractError();
    const producer: Producer = Object.freeze({
      producer_id: p.producer_id,
      model_id: p.model_id as string | null,
      model_version: p.model_version as string | null,
      config_fingerprint: digest(p.config_fingerprint),
    });
    this.#provider = Object.freeze({
      producer,
      extract: configured.extract as DocumentExtractionProvider['extract'],
    });
    this.#decoder = new DocumentPngDecoder(options.workerObserver);
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({
      ...this.#counts,
      ...this.#decoder.metrics(),
      providerActive: this.#counts.providerStarted - this.#counts.providerSettled,
      active: this.#work.size,
    });
  }
  evaluate(
    input: DocumentRequest,
    record: EvidenceRecord,
    signal: AbortSignal,
    deadline: number,
    afterDecode?: DocumentAfterDecode,
  ): Promise<DocumentResult> {
    if (this.#closing) return Promise.reject(new SpecialistHttpError('closing'));
    if (this.#work.size >= 4) return Promise.reject(new ContractError('capacity'));
    const request = parseDocumentRequest(encodeDocumentRequest(input));
    const source = fields(record, ['scope', 'reference', 'body']);
    if (
      Buffer.compare(
        Buffer.from(canonical(source.scope)),
        Buffer.from(canonical(request.scope)),
      ) !== 0 ||
      Buffer.compare(
        Buffer.from(canonical(source.reference)),
        Buffer.from(canonical(request.evidence[0])),
      ) !== 0
    )
      return Promise.reject(new ContractError('evidence_mismatch'));

    if (!(signal instanceof AbortSignal))
      return Promise.reject(new SpecialistHttpError('invalid_http'));
    const controller = new AbortController();
    const abort = () => controller.abort(new SpecialistHttpError('request_aborted'));
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
    const check = () => {
      if (controller.signal.aborted || this.#closing)
        throw new SpecialistHttpError('request_aborted');
      if (performance.now() >= deadline || Date.now() >= request.deadline_at_ms)
        throw new SpecialistHttpError('deadline_exceeded');
    };
    const promise = (async () => {
      try {
        check();
        const image = await this.#decoder.decode(record, controller.signal, deadline);
        await afterDecode?.(Object.freeze({ request, image, signal: controller.signal }));
        // Decode/harness completion never extends original authority time.
        check();
        this.#counts.providerStarted++;
        let answer: DocumentExtraction;
        try {
          answer = await this.#provider.extract(request, image, controller.signal);
        } catch (error) {
          this.#counts.providerFailed++;
          throw error;
        } finally {
          this.#counts.providerSettled++;
        }
        check();
        const value = fields(answer, ['outcome', 'fields']);
        const result = parseDocumentResult(
          canonical({
            schema_version: 1,
            kind: 'delegation.result',
            capability: DOCUMENT_CAPABILITY,
            result_schema_version: 1,
            scope: request.scope,
            delegation_id: request.delegation_id,
            case_id: request.case_id,
            request_revision: request.request_revision,
            attempt_id: request.attempt.attempt_id,
            input_fingerprint: request.input_fingerprint,
            outcome: value.outcome,
            fields: value.fields,
            producer: this.#provider.producer,
            completed_at_ms: Date.now(),
          }),
        );
        if (matchDocumentResult(request, result, Date.now()) !== 'candidate')
          throw new SpecialistHttpError('deadline_exceeded');
        return result;
      } catch (error) {
        throw error instanceof ContractError || error instanceof SpecialistHttpError
          ? error
          : new ContractError('unsupported_facts');
      } finally {
        signal.removeEventListener('abort', abort);
      }
    })();
    const owned = Object.freeze({ promise, controller });
    this.#work.add(owned);
    void promise.then(
      () => this.#work.delete(owned),
      () => this.#work.delete(owned),
    );
    return promise;
  }
  async close(): Promise<void> {
    this.#closing = true;
    for (const owned of this.#work) owned.controller.abort(new SpecialistHttpError('closing'));
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all([
          this.#decoder.close(),
          ...[...this.#work].map((x) => x.promise.catch(() => undefined)),
        ]),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(() => reject(new SpecialistHttpError('cleanup_incomplete')), 2000);
        }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
    if (this.#work.size !== 0 || this.#decoder.metrics().workersActive !== 0)
      throw new SpecialistHttpError('cleanup_incomplete');
  }
}
export type ScriptedDocumentFixture = Readonly<{
  sha256: string;
  pixel_sha256: string;
  outcome: DocumentOutcome;
  fields: Readonly<Record<DocumentFieldName, DocumentField>>;
}>;
export function createScriptedDocumentProvider(
  configured: readonly ScriptedDocumentFixture[],
): DocumentExtractionProvider {
  if (!Array.isArray(configured) || configured.length < 1 || configured.length > 8)
    throw new ContractError();
  const copies = configured.map(
    (item) => JSON.parse(Buffer.from(canonical(item)).toString('utf8')) as unknown,
  );
  const map = new Map<
    string,
    Readonly<{
      pixel_sha256: string;
      outcome: DocumentOutcome;
      fields: Readonly<Record<DocumentFieldName, DocumentField>>;
    }>
  >();
  for (const item of copies) {
    const f = fields(item, ['sha256', 'pixel_sha256', 'outcome', 'fields']);
    const key = digest(f.sha256);
    if (map.has(key)) throw new ContractError();
    if (f.outcome !== 'extracted' && f.outcome !== 'clarification_required')
      throw new ContractError();
    const checked = parseDocumentResult(
      canonical({
        schema_version: 1,
        kind: 'delegation.result',
        capability: DOCUMENT_CAPABILITY,
        result_schema_version: 1,
        scope: { tenant_id: 'configuration', account_id: 'configuration' },
        delegation_id: 'configuration',
        case_id: 'configuration',
        request_revision: 1,
        attempt_id: 'configuration',
        input_fingerprint: '0'.repeat(64),
        outcome: f.outcome,
        fields: f.fields,
        producer: {
          producer_id: 'scripted_document_fixture_v1',
          model_id: null,
          model_version: null,
          config_fingerprint: '0'.repeat(64),
        },
        completed_at_ms: 0,
      }),
    );

    map.set(
      key,
      Object.freeze({
        pixel_sha256: digest(f.pixel_sha256),
        outcome: f.outcome,
        fields: checked.fields,
      }),
    );
  }
  const producer = Object.freeze({
    producer_id: 'scripted_document_fixture_v1',
    model_id: null,
    model_version: null,
    config_fingerprint: hash(canonical(copies.map((item) => hash(canonical(item))))),
  });
  return Object.freeze({
    producer,
    extract: (
      _request: DocumentRequest,
      image: VerifiedDocumentImage,
      signal: AbortSignal,
    ): DocumentExtraction => {
      if (signal.aborted) throw new SpecialistHttpError('request_aborted');
      const fixture = map.get(image.reference.sha256);
      if (!fixture || fixture.pixel_sha256 !== image.pixel_sha256)
        throw new ContractError('unsupported_facts');
      // Explicit finite fixture mapping, not pixel recognition or a factual oracle.
      return JSON.parse(
        Buffer.from(canonical({ outcome: fixture.outcome, fields: fixture.fields })).toString(
          'utf8',
        ),
      ) as DocumentExtraction;
    },
  });
}
export {
  DOCUMENT_CAPABILITY,
  DOCUMENT_FIELDS,
  parseDocumentRequest,
  produceDocumentRequest,
  encodeDocumentRequest,
  parseDocumentResult,
  encodeDocumentResult,
  matchDocumentResult,
} from './document-contracts.js';
export type {
  DocumentRequest,
  DocumentResult,
  DocumentField,
  DocumentRegion,
  DocumentEvidence,
  DocumentOutcome,
  DocumentState,
} from './document-contracts.js';
export type { VerifiedDocumentImage, DocumentWorkerObservation } from './document-png.js';

/** Typed image facade over the same finite socket/task owner as policy clients. */
export class DocumentSpecialistClient {
  readonly #transport: SpecialistClient;
  constructor(endpoint: Endpoint, authorization: string, options: ClientOptions = {}) {
    this.#transport = new SpecialistClient(endpoint, authorization, options);
  }
  get active(): number {
    return this.#transport.active;
  }
  invoke(request: DocumentRequest, options: CallOptions = {}): Promise<DocumentResult> {
    return this.#transport.invokeDocument(request, options);
  }
  status(request: DocumentRequest, options: CallOptions = {}): Promise<AttemptObservation> {
    return this.#transport.statusDocument(request, options);
  }
  cancel(request: DocumentRequest, options: CallOptions = {}): Promise<AttemptObservation> {
    return this.#transport.cancelDocument(request, options);
  }
  close(): Promise<void> {
    return this.#transport.close();
  }
}
