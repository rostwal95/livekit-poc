/** Owned off-loop PNG validation. No caller-selected code or inherited worker env. */
import { Worker } from 'node:worker_threads';
import { ContractError, digest, fields, hash, integer } from './contracts.js';
import type { EvidenceRef } from './contracts.js';
import type { EvidenceRecord } from './security.js';
import { SpecialistHttpError } from './http-protocol.js';
export type VerifiedDocumentImage = Readonly<{
  reference: EvidenceRef;
  png: Uint8Array;
  width: number;
  height: number;
  channels: 3 | 4;
  pixel_sha256: string;
}>;
export type DocumentWorkerObservation = Readonly<{
  thread_id: number;
  exit_code: number;
  normal_result: boolean;
}>;
type Owned = { worker: Worker; settled: Promise<void>; terminate: Promise<number> | undefined };
const fixedModule = (): URL =>
  new URL(
    import.meta.url.endsWith('/src/document-png.ts')
      ? '../dist/document-png-worker.js'
      : './document-png-worker.js',
    import.meta.url,
  );
export class DocumentPngDecoder {
  readonly #active = new Set<Owned>();
  readonly #observer: (value: DocumentWorkerObservation) => void;
  #closing = false;
  #started = 0;
  #settled = 0;
  #observerFailures = 0;
  #observerDropped = 0;
  readonly #notices = new Set<Promise<void>>();
  constructor(observer: (value: DocumentWorkerObservation) => void = () => undefined) {
    if (typeof observer !== 'function') throw new ContractError();
    this.#observer = observer;
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({
      workersStarted: this.#started,
      workersSettled: this.#settled,
      workersActive: this.#active.size,
      observerFailures: this.#observerFailures,
      workerObserverPending: this.#notices.size,
      workerObserverDropped: this.#observerDropped,
    });
  }
  #terminate(owned: Owned): void {
    if (owned.terminate !== undefined) return;
    let pending: Promise<number>;
    try {
      pending = owned.worker.terminate();
    } catch {
      pending = Promise.reject(new SpecialistHttpError('cleanup_incomplete'));
    }
    owned.terminate = pending;
    void pending.catch(() => {
      // An explicit later close can retry a definite failed termination, retaining ownership.
      if (this.#active.has(owned) && owned.terminate === pending) owned.terminate = undefined;
    });
  }
  #notify(value: DocumentWorkerObservation): void {
    if (this.#notices.size >= 8) {
      this.#observerDropped++;
      return;
    }
    try {
      const result: unknown = this.#observer(value);
      const notice = Promise.resolve(result).then(
        () => undefined,
        () => {
          this.#observerFailures++;
        },
      );
      this.#notices.add(notice);
      void notice.finally(() => this.#notices.delete(notice));
    } catch {
      this.#observerFailures++;
    }
  }
  decode(
    record: EvidenceRecord,
    signal: AbortSignal,
    deadline: number,
  ): Promise<VerifiedDocumentImage> {
    if (this.#closing) return Promise.reject(new SpecialistHttpError('closing'));
    if (this.#active.size >= 4) return Promise.reject(new ContractError('capacity'));
    if (!(signal instanceof AbortSignal) || signal.aborted)
      return Promise.reject(new SpecialistHttpError('request_aborted'));
    if (!Number.isFinite(deadline) || performance.now() >= deadline)
      return Promise.reject(new SpecialistHttpError('deadline_exceeded'));
    if (
      !(record.body instanceof Uint8Array) ||
      record.body.byteLength < 45 ||
      record.body.byteLength > 2097152
    )
      return Promise.reject(new ContractError('evidence_mismatch'));
    const ref = Object.freeze({ ...record.reference });
    const png = Uint8Array.from(record.body);
    if (
      ref.media_type !== 'image/png' ||
      png.byteLength < 45 ||
      png.byteLength > 2097152 ||
      ref.byte_length !== png.byteLength ||
      hash(png) !== ref.sha256
    )
      return Promise.reject(new ContractError('evidence_mismatch'));
    const header = Buffer.from(png.buffer, png.byteOffset, png.byteLength);
    if (
      !header.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) ||
      header.readUInt32BE(8) !== 13 ||
      header.subarray(12, 16).toString('latin1') !== 'IHDR'
    )
      return Promise.reject(new ContractError('evidence_mismatch'));
    const width = header.readUInt32BE(16),
      height = header.readUInt32BE(20);
    if (width < 1 || height < 1 || width > 2048 || height > 2048 || width * height > 4194304)
      return Promise.reject(new ContractError());
    if (width !== ref.width || height !== ref.height)
      return Promise.reject(new ContractError('evidence_mismatch'));
    const worker = new Worker(fixedModule(), {
      workerData: { bytes: png, width, height, sha256: ref.sha256 },
      env: {},
      execArgv: [],
      resourceLimits: { maxOldGenerationSizeMb: 64, maxYoungGenerationSizeMb: 16, stackSizeMb: 1 },
      stdout: true,
      stderr: true,
    });
    const thread = worker.threadId;
    this.#started++;
    let release!: () => void;
    const owned: Owned = {
      worker,
      settled: new Promise<void>((r) => {
        release = r;
      }),
      terminate: undefined,
    };
    this.#active.add(owned);
    const terminate = (): void => this.#terminate(owned);
    const result = new Promise<VerifiedDocumentImage>((resolve, reject) => {
      let message: unknown, failure: Error | undefined;
      const abort = (): void => {
        failure ??= new SpecialistHttpError('request_aborted');
        terminate();
      };
      const timer = setTimeout(
        () => {
          failure ??= new SpecialistHttpError('deadline_exceeded');
          terminate();
        },
        Math.max(1, Math.min(1000, deadline - performance.now())),
      );
      signal.addEventListener('abort', abort, { once: true });
      worker.once('error', () => {
        failure ??= new ContractError('unsupported_facts');
        terminate();
      });
      worker.on('message', (value) => {
        if (message !== undefined) {
          failure ??= new ContractError('evidence_mismatch');
          terminate();
        } else message = value;
      });
      const unexpectedOutput = (): void => {
        failure ??= new ContractError('unsupported_facts');
        terminate();
      };
      worker.stdout?.on('data', unexpectedOutput);
      worker.stderr?.on('data', unexpectedOutput);
      worker.once('exit', (code) => {
        clearTimeout(timer);
        signal.removeEventListener('abort', abort);
        let output: VerifiedDocumentImage | undefined;
        try {
          if (failure !== undefined) throw failure;
          if (code !== 0) throw new ContractError('unsupported_facts');
          if (performance.now() >= deadline || signal.aborted)
            throw new SpecialistHttpError('deadline_exceeded');
          if (
            message !== null &&
            typeof message === 'object' &&
            'status' in message &&
            message.status === 'failed'
          ) {
            const bad = fields(message, ['status', 'code']);
            if (
              bad.code !== 'invalid_contract' &&
              bad.code !== 'evidence_mismatch' &&
              bad.code !== 'unsupported_facts'
            )
              throw new ContractError();
            throw new ContractError(bad.code);
          }
          const value = fields(message, [
            'status',
            'width',
            'height',
            'channels',
            'pixel_sha256',
            'png_sha256',
          ]);
          if (
            value.status !== 'known' ||
            integer(value.width, 1, 2048) !== width ||
            integer(value.height, 1, 2048) !== height ||
            (value.channels !== 3 && value.channels !== 4) ||
            digest(value.png_sha256) !== ref.sha256
          )
            throw new ContractError('evidence_mismatch');
          output = Object.freeze({
            reference: ref,
            png: Uint8Array.from(png),
            width,
            height,
            channels: value.channels,
            pixel_sha256: digest(value.pixel_sha256),
          });
        } catch (error) {
          failure =
            error instanceof ContractError || error instanceof SpecialistHttpError
              ? error
              : new ContractError('evidence_mismatch');
        }
        this.#active.delete(owned);
        this.#settled++;
        release();
        this.#notify(
          Object.freeze({
            thread_id: thread,
            exit_code: code,
            normal_result: output !== undefined,
          }),
        );
        if (failure !== undefined) reject(failure);
        else resolve(output!);
      });
      if (signal.aborted) abort();
    });
    // Server/client owners may abandon their waiters; the actual promise remains observed.
    void result.catch(() => undefined);
    return result;
  }
  async close(): Promise<void> {
    this.#closing = true;
    for (const owned of this.#active) this.#terminate(owned);
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all([...this.#active].map((x) => x.settled)).then(() =>
          Promise.all([...this.#notices]),
        ),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(() => reject(new SpecialistHttpError('cleanup_incomplete')), 2000);
        }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
    if (this.#active.size !== 0 || this.#notices.size !== 0)
      throw new SpecialistHttpError('cleanup_incomplete');
  }
}
