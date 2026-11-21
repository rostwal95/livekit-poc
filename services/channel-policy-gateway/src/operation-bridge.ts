/** Source-attested, two-ticket operation adapter; no queue, cache, fake work or authority. */
import { createHash } from 'node:crypto';
import { request, type ClientRequest } from 'node:http';
import type { Socket } from 'node:net';
import type { AccountScope } from '@livekit-ecosystem/channel-continuity';
import { ChannelError } from '@livekit-ecosystem/channel-continuity/postgres';
import type {
  DispatchPorts,
  PreparedDispatch,
  OperationLookup,
  OperationReceipt,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import { ExternalOperationClient } from './external-operation-client.js';
import {
  runtimeFields,
  runtimeString,
  runtimeEndpoint,
  GatewayRuntimeError,
  type LoopbackEndpoint,
} from './runtime-config.js';
type Source = 'native' | 'sms';
type LookupResult = Awaited<ReturnType<DispatchPorts['operations']['lookup']>>;
type Reply = LookupResult | OperationReceipt;
export type OperationBridgeConfiguration = Readonly<{
  profileId: string;
  scope: AccountScope;
  caseId: string;
  conversationId: string;
  worker: Readonly<{ endpoint: LoopbackEndpoint; bearer: string }>;
  origins: Readonly<{
    native: Readonly<{ endpoint: LoopbackEndpoint; bearer: string }>;
    sms: Readonly<{ endpoint: LoopbackEndpoint; bearer: string }>;
  }>;
  timeoutMs?: number;
  cleanupMs?: number;
}>;
type SourceCall = {
  request: ClientRequest | undefined;
  socket: Socket | undefined;
  requestClosed: boolean;
  socketClosed: boolean;
  done: Promise<void>;
};
type Call = {
  source: Source;
  write: boolean;
  input: PreparedDispatch | OperationLookup;
  deadline: number;
  controller: AbortController;
  abandoned: boolean;
  acceptStarted: boolean;
  unknownObserved: boolean;
  replySettled: boolean;
  client: ExternalOperationClient | undefined;
  requests: Set<SourceCall>;
  task: Promise<void> | undefined;
  taskDone: boolean;
  closed: boolean;
  resolve: (reply: Reply) => void;
  reject: (error: ChannelError) => void;
  cleanup: Promise<void> | undefined;
};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ID = /^[a-z][a-z0-9_-]{0,63}$/;
const P2ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const SHA = /^[0-9a-f]{64}$/;
const aborted = Object.getOwnPropertyDescriptor(AbortSignal.prototype, 'aborted')!.get!;
function isAborted(signal: AbortSignal): boolean {
  try {
    return Reflect.apply(aborted, signal, []) as boolean;
  } catch {
    throw new ChannelError('OperationConflict');
  }
}
function budget(input: unknown, fallback: number): number {
  const v = input === undefined ? fallback : input;
  if (typeof v !== 'number' || !Number.isSafeInteger(v) || v < 20 || v > 5000)
    throw new GatewayRuntimeError('invalid_configuration');
  return v;
}
function digest(raw: string): string {
  return createHash('sha256').update(raw, 'utf8').digest('hex');
}
function scope(value: unknown, expected: AccountScope): AccountScope {
  const s = runtimeFields(value, ['tenantId', 'accountId']);
  if (s.tenantId !== expected.tenantId || s.accountId !== expected.accountId)
    throw new ChannelError('AccessDenied');
  return expected;
}
function lookup(value: unknown, expected: AccountScope): OperationLookup {
  const p = runtimeFields(value, ['operationKey', 'scope', 'payloadDigest']);
  return Object.freeze({
    operationKey: runtimeString(p.operationKey, UUID),
    scope: scope(p.scope, expected),
    payloadDigest: runtimeString(p.payloadDigest, SHA),
  });
}
function prepared(
  value: unknown,
  c: OperationBridgeConfiguration,
  source: Source,
): PreparedDispatch {
  const p = runtimeFields(value, ['submission', 'canonicalPayload', 'payloadDigest']),
    s = runtimeFields(p.submission, [
      'schemaVersion',
      'kind',
      'operationKey',
      'scope',
      'caseId',
      'caseRevision',
      'conversationId',
      'message',
    ]),
    m = runtimeFields(s.message, ['receiptId', 'eventId', 'messageId', 'senderId', 'body']);
  if (
    s.schemaVersion !== 1 ||
    s.kind !== 'investigation' ||
    s.caseId !== c.caseId ||
    s.conversationId !== c.conversationId
  )
    throw new ChannelError('AccessDenied');
  const revision = runtimeString(s.caseRevision, /^[1-9][0-9]{0,6}$/);
  if (BigInt(revision) > 1000000n) throw new ChannelError('OperationConflict');
  if (
    typeof m.body !== 'string' ||
    Buffer.byteLength(m.body, 'utf8') > 4096 ||
    /[\ud800-\udfff]/u.test(m.body)
  )
    throw new ChannelError('OperationConflict');
  const submission = Object.freeze({
    schemaVersion: 1 as const,
    kind: 'investigation' as const,
    operationKey: runtimeString(s.operationKey, UUID),
    scope: scope(s.scope, c.scope),
    caseId: c.caseId,
    caseRevision: revision,
    conversationId: c.conversationId,
    message: Object.freeze({
      receiptId: runtimeString(m.receiptId, UUID),
      eventId: runtimeString(m.eventId, P2ID),
      messageId: runtimeString(m.messageId, P2ID),
      senderId: runtimeString(m.senderId, source === 'native' ? UUID : P2ID),
      body: m.body,
    }),
  });
  const canonicalPayload = JSON.stringify(submission),
    payloadDigest = runtimeString(p.payloadDigest, SHA);
  if (p.canonicalPayload !== canonicalPayload || payloadDigest !== digest(canonicalPayload))
    throw new ChannelError('OperationConflict');
  return Object.freeze({ submission, canonicalPayload, payloadDigest });
}
function frame(raw: Buffer, c: OperationBridgeConfiguration, source: Source): PreparedDispatch {
  const text = new TextDecoder('utf8', { fatal: true, ignoreBOM: true }).decode(raw),
    p = runtimeFields(JSON.parse(text) as unknown, [
      'schemaVersion',
      'canonicalPayload',
      'payloadDigest',
    ]);
  if (text !== JSON.stringify(p) || p.schemaVersion !== 1 || typeof p.canonicalPayload !== 'string')
    throw new ChannelError('OperationConflict');
  return prepared(
    {
      submission: JSON.parse(p.canonicalPayload) as unknown,
      canonicalPayload: p.canonicalPayload,
      payloadDigest: p.payloadDigest,
    },
    c,
    source,
  );
}
/** Both facets share two actual attestation/client/call/close tickets, including abandoned waiters.
 * P2 source HTTP may own deeper SQL after its client socket closes; the application
 * drains its SourceReader separately. This adapter never claims that SQL ownership.
 */
export class ChannelPolicyOperationBridge {
  readonly #c: OperationBridgeConfiguration;
  readonly #timeout: number;
  readonly #cleanupMs: number;
  readonly #calls = new Set<Call>();
  readonly native: DispatchPorts['operations'];
  readonly sms: DispatchPorts['operations'];
  #closing = false;
  #closeTask: Promise<void> | undefined;
  #started = 0;
  #completed = 0;
  #unknown = 0;
  #rejected = 0;
  constructor(configuration: OperationBridgeConfiguration) {
    try {
      const p = runtimeFields(configuration, [
          'profileId',
          'scope',
          'caseId',
          'conversationId',
          'worker',
          'origins',
          ...(Object.hasOwn(configuration, 'timeoutMs') ? ['timeoutMs'] : []),
          ...(Object.hasOwn(configuration, 'cleanupMs') ? ['cleanupMs'] : []),
        ]),
        s = runtimeFields(p.scope, ['tenantId', 'accountId']),
        w = runtimeFields(p.worker, ['endpoint', 'bearer']),
        o = runtimeFields(p.origins, ['native', 'sms']);
      const origin = (v: unknown) => {
        const a = runtimeFields(v, ['endpoint', 'bearer']);
        return Object.freeze({
          endpoint: runtimeEndpoint(a.endpoint),
          bearer: runtimeString(a.bearer, /^[A-Za-z0-9_-]{43}$/),
        });
      };
      const worker = Object.freeze({
          endpoint: runtimeEndpoint(w.endpoint),
          bearer: runtimeString(w.bearer, /^[A-Za-z0-9_-]{43}$/),
        }),
        origins = Object.freeze({ native: origin(o.native), sms: origin(o.sms) });
      if (new Set([worker.bearer, origins.native.bearer, origins.sms.bearer]).size !== 3)
        throw new GatewayRuntimeError('invalid_configuration');
      this.#c = Object.freeze({
        profileId: runtimeString(p.profileId, UUID),
        scope: Object.freeze({
          tenantId: runtimeString(s.tenantId, ID),
          accountId: runtimeString(s.accountId, ID),
        }),
        caseId: runtimeString(p.caseId, ID),
        conversationId: runtimeString(p.conversationId, ID),
        worker,
        origins,
      });
      this.#timeout = budget(p.timeoutMs, 1500);
      this.#cleanupMs = budget(p.cleanupMs, 1000);
    } catch {
      throw new GatewayRuntimeError('invalid_configuration');
    }
    const facet = (source: Source): DispatchPorts['operations'] =>
      Object.freeze({
        capabilities: 'stable_idempotency_and_lookup',
        lookup: (input, signal) =>
          this.#observe(source, false, input, signal) as Promise<LookupResult>,
        accept: (input, signal) =>
          this.#observe(source, true, input, signal) as Promise<OperationReceipt>,
      });
    this.native = facet('native');
    this.sms = facet('sms');
    Object.defineProperties(this, {
      native: { value: this.native, writable: false, configurable: false },
      sms: { value: this.sms, writable: false, configurable: false },
    });
  }
  metrics(): Readonly<{
    active: number;
    sourceRequests: number;
    sourceSockets: number;
    operationCalls: number;
    started: number;
    completed: number;
    unknown: number;
    rejected: number;
    closing: boolean;
  }> {
    return Object.freeze({
      active: this.#calls.size,
      sourceRequests: [...this.#calls].reduce((n, c) => n + c.requests.size, 0),
      sourceSockets: [...this.#calls].reduce(
        (n, c) =>
          n + [...c.requests].filter((r) => r.socket !== undefined && !r.socketClosed).length,
        0,
      ),
      operationCalls: [...this.#calls].reduce((n, c) => n + (c.client?.metrics().active ?? 0), 0),
      started: this.#started,
      completed: this.#completed,
      unknown: this.#unknown,
      rejected: this.#rejected,
      closing: this.#closing,
    });
  }
  #check(call: Call): void {
    if (
      this.#closing ||
      call.abandoned ||
      isAborted(call.controller.signal) ||
      performance.now() >= call.deadline
    )
      throw new ChannelError('DispatchUnavailable');
  }
  #failure(call: Call): ChannelError {
    if (call.acceptStarted) {
      if (!call.unknownObserved) {
        this.#unknown++;
        call.unknownObserved = true;
      }
      return new ChannelError('AcknowledgementUnknown');
    }
    return new ChannelError('DispatchUnavailable');
  }
  #prune(): void {
    for (const call of this.#calls) if (call.closed && call.taskDone) this.#calls.delete(call);
  }
  #retry(): void {
    this.#prune();
    for (const call of this.#calls)
      if (call.taskDone && !call.closed && !call.cleanup) {
        const actual = this.#closeOwner(call);
        call.cleanup = actual;
        void actual.then(
          () => {
            call.cleanup = undefined;
            this.#prune();
          },
          () => {
            call.cleanup = undefined;
          },
        );
      }
  }
  async #source(
    call: Call,
    path: string,
    payload: Buffer,
    maximum: number,
    allowMissing = false,
  ): Promise<Buffer | null> {
    this.#check(call);
    let done!: () => void;
    const owner: SourceCall = {
      request: undefined,
      socket: undefined,
      requestClosed: false,
      socketClosed: true,
      done: new Promise<void>((r) => {
        done = r;
      }),
    };
    call.requests.add(owner);
    const release = () => {
      if (owner.requestClosed && owner.socketClosed && call.requests.delete(owner)) done();
    };
    let timer: ReturnType<typeof setTimeout> | undefined, abort: (() => void) | undefined;
    try {
      const raw = await new Promise<Buffer | null>((resolve, reject) => {
        let delivered = false;
        const fail = () => {
          if (!delivered) {
            delivered = true;
            reject(new ChannelError('DispatchUnavailable'));
          }
          owner.request?.destroy();
          owner.socket?.destroy();
        };
        timer = setTimeout(fail, Math.max(0, call.deadline - performance.now()));
        try {
          const req = request(
            {
              hostname: '127.0.0.1',
              port: this.#c.worker.endpoint.port,
              path,
              method: 'POST',
              agent: false,
              maxHeaderSize: 8192,
              joinDuplicateHeaders: false,
              headers: {
                authorization: 'Bearer ' + this.#c.worker.bearer,
                'content-type': 'application/json',
                'content-length': payload.length,
                connection: 'close',
              },
            },
            (res) => {
              const headers: Record<string, string> = Object.create(null) as Record<string, string>;
              let invalid = res.rawHeaders.length > 16;
              for (let i = 0; i < res.rawHeaders.length; i += 2) {
                const k = res.rawHeaders[i]!.toLowerCase(),
                  v = res.rawHeaders[i + 1]!;
                if (
                  Object.hasOwn(headers, k) ||
                  ![
                    'content-type',
                    'content-length',
                    'cache-control',
                    'connection',
                    'date',
                  ].includes(k)
                )
                  invalid = true;
                headers[k] = v;
              }
              const length = headers['content-length'];
              if (
                invalid ||
                headers['content-type'] !== 'application/json' ||
                headers['cache-control'] !== 'no-store' ||
                headers.connection !== 'close' ||
                length === undefined ||
                !/^(0|[1-9][0-9]{0,4})$/.test(length) ||
                Number(length) > maximum ||
                !(
                  res.statusCode === 200 ||
                  (allowMissing && res.statusCode === 204 && length === '0')
                )
              ) {
                res.resume();
                fail();
                return;
              }
              const parts: Buffer[] = [];
              let size = 0;
              res.on('data', (chunk: Buffer) => {
                size += chunk.length;
                if (size > Number(length)) {
                  res.destroy();
                  fail();
                } else parts.push(Buffer.from(chunk));
              });
              res.once('error', fail);
              res.once('aborted', fail);
              res.once('end', () => {
                if (delivered) return;
                if (size !== Number(length) || isAborted(call.controller.signal)) {
                  fail();
                  return;
                }
                delivered = true;
                resolve(res.statusCode === 204 ? null : Buffer.concat(parts));
              });
            },
          );
          owner.request = req;
          req.once('close', () => {
            owner.requestClosed = true;
            release();
          });
          req.once('error', fail);
          req.once('socket', (s) => {
            owner.socket = s;
            owner.socketClosed = false;
            s.once('close', () => {
              owner.socketClosed = true;
              release();
            });
          });
          abort = fail;
          EventTarget.prototype.addEventListener.call(call.controller.signal, 'abort', abort, {
            once: true,
          });
          if (isAborted(call.controller.signal)) fail();
          else req.end(payload);
        } catch {
          fail();
          if (!owner.request) {
            owner.requestClosed = true;
            release();
          }
        }
      });
      // Complete physical source socket ownership before admitting the next stage.
      await owner.done;
      this.#check(call);
      return raw;
    } finally {
      if (timer) clearTimeout(timer);
      if (abort)
        EventTarget.prototype.removeEventListener.call(call.controller.signal, 'abort', abort);
    }
  }
  async #attest(call: Call): Promise<PreparedDispatch> {
    let id: string;
    if (call.write) id = (call.input as PreparedDispatch).submission.message.receiptId;
    else {
      const raw = await this.#source(
        call,
        '/v1/policy/discovery',
        Buffer.from('{"schemaVersion":1}'),
        8192,
      );
      this.#check(call);
      if (raw === null) throw new ChannelError('OperationConflict');
      const text = new TextDecoder('utf8', { fatal: true, ignoreBOM: true }).decode(raw);
      const value: unknown = JSON.parse(text);
      if (text !== JSON.stringify(value)) throw new ChannelError('OperationConflict');
      const p = runtimeFields(value, [
        'schemaVersion',
        'kind',
        'profileId',
        'scope',
        'caseId',
        'conversationId',
        'readCompletedAt',
        'items',
        'overflow',
        'nextCursor',
      ]);
      if (
        p.schemaVersion !== 1 ||
        p.kind !== 'channel.policy_discovery' ||
        p.profileId !== this.#c.profileId ||
        p.caseId !== this.#c.caseId ||
        p.conversationId !== this.#c.conversationId ||
        p.overflow !== false ||
        p.nextCursor !== null ||
        !Array.isArray(p.items) ||
        p.items.length > 16
      )
        throw new ChannelError('OperationConflict');
      scope(p.scope, this.#c.scope);
      const observed = runtimeString(
        p.readCompletedAt,
        /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$/,
      );
      if (new Date(observed).toISOString() !== observed)
        throw new ChannelError('OperationConflict');

      let match: string | undefined;
      const seen = new Set<string>(),
        receipts = new Set<string>(),
        work = new Set<string>();
      let sequence = 0n;
      for (const item of p.items) {
        const row = runtimeFields(item, [
          'receiptId',
          'operationKey',
          'acceptanceSequence',
          'sourceBindingId',
          'state',
          'possibleExternal',
          'externalReceiptId',
        ]);
        const op = runtimeString(row.operationKey, UUID),
          receipt = runtimeString(row.receiptId, UUID),
          seq = runtimeString(row.acceptanceSequence, /^[1-9][0-9]{0,18}$/);
        if (
          BigInt(seq) <= sequence ||
          BigInt(seq) > 9223372036854775807n ||
          seen.has(op) ||
          receipts.has(receipt)
        )
          throw new ChannelError('OperationConflict');
        seen.add(op);
        receipts.add(receipt);
        sequence = BigInt(seq);
        if (
          !['pending', 'running', 'dispatched', 'blocked', 'exhausted', 'uncertain'].includes(
            String(row.state),
          ) ||
          typeof row.possibleExternal !== 'boolean'
        )
          throw new ChannelError('OperationConflict');
        if (row.externalReceiptId !== null) {
          const external = runtimeString(row.externalReceiptId, UUID);
          if (work.has(external)) throw new ChannelError('OperationConflict');
          work.add(external);
        }
        if (
          row.state === 'dispatched'
            ? !row.possibleExternal || row.externalReceiptId === null
            : row.externalReceiptId !== null
        )
          throw new ChannelError('OperationConflict');
        if (row.sourceBindingId !== 'native' && row.sourceBindingId !== 'sms')
          throw new ChannelError('OperationConflict');
        if (op === (call.input as OperationLookup).operationKey) {
          if (row.sourceBindingId !== call.source) throw new ChannelError('AccessDenied');
          match = receipt;
        }
      }
      if (match === undefined) throw new ChannelError('DispatchUnavailable');
      id = match;
    }
    const raw = await this.#source(
      call,
      '/v1/policy/prepared',
      Buffer.from(
        JSON.stringify({ schemaVersion: 1, receiptId: id, sourceBindingId: call.source }),
      ),
      32768,
      true,
    );
    this.#check(call);
    if (raw === null) throw new ChannelError('DispatchUnavailable');
    const actual = frame(raw, this.#c, call.source),
      expected = call.input;
    if (actual.submission.message.receiptId !== id) throw new ChannelError('OperationConflict');
    if (call.write) {
      const input = expected as PreparedDispatch;
      if (
        input.canonicalPayload !== actual.canonicalPayload ||
        input.payloadDigest !== actual.payloadDigest
      )
        throw new ChannelError('OperationConflict');
    } else {
      const input = expected as OperationLookup;
      if (
        input.operationKey !== actual.submission.operationKey ||
        input.payloadDigest !== actual.payloadDigest
      )
        throw new ChannelError('OperationConflict');
    }
    return actual;
  }
  async #business(call: Call): Promise<Reply> {
    const actual = await this.#attest(call);
    this.#check(call);
    const origin = this.#c.origins[call.source];
    const client = (call.client = new ExternalOperationClient(
      origin.endpoint,
      origin.bearer,
      this.#timeout,
    ));
    this.#check(call);
    if (call.write) {
      call.acceptStarted = true;
      return await client.accept(actual, call.controller.signal);
    }
    return await client.lookup(call.input as OperationLookup, call.controller.signal);
  }
  async #closeOwner(call: Call): Promise<void> {
    await Promise.all([...call.requests].map((r) => r.done));
    if (call.client) {
      await call.client.close();
      if (call.client.metrics().active !== 0) throw new ChannelError('CleanupIncomplete');
    }
    if (call.requests.size) throw new ChannelError('CleanupIncomplete');
    call.closed = true;
  }
  async #lifetime(call: Call): Promise<void> {
    try {
      const result = await this.#business(call);
      this.#completed++;
      call.resolve(result);
    } catch (error) {
      this.#rejected++;
      const d =
        error instanceof ChannelError ? Object.getOwnPropertyDescriptor(error, 'code') : undefined;
      const code = d && 'value' in d ? d.value : undefined;
      const safe =
        !call.acceptStarted &&
        typeof code === 'string' &&
        ['AccessDenied', 'OperationConflict', 'Overloaded', 'StorageUnavailable'].includes(code)
          ? new ChannelError(code as ChannelError['code'])
          : this.#failure(call);
      call.reject(safe);
    } finally {
      try {
        await this.#closeOwner(call);
      } catch {
        /* retained slot, useful receipt/error already published */
      }
      call.taskDone = true;
      this.#prune();
    }
  }
  #observe(
    source: Source,
    write: boolean,
    input: PreparedDispatch | OperationLookup,
    signal: AbortSignal,
  ): Promise<Reply> {
    let copied: PreparedDispatch | OperationLookup;
    try {
      if (this.#closing) throw new ChannelError('StorageUnavailable');
      if (isAborted(signal)) throw new ChannelError('DispatchUnavailable');
      copied = write ? prepared(input, this.#c, source) : lookup(input, this.#c.scope);
    } catch (error) {
      return Promise.reject(
        error instanceof ChannelError ? error : new ChannelError('OperationConflict'),
      );
    }
    this.#retry();
    if (this.#calls.size >= 2) return Promise.reject(new ChannelError('Overloaded'));
    let resolve!: (r: Reply) => void, reject!: (e: ChannelError) => void;
    const reply = new Promise<Reply>((a, b) => {
      resolve = a;
      reject = b;
    });
    void reply.catch(() => {});
    const call: Call = {
      source,
      write,
      input: copied,
      deadline: performance.now() + this.#timeout,
      controller: new AbortController(),
      abandoned: false,
      acceptStarted: false,
      unknownObserved: false,
      replySettled: false,
      client: undefined,
      requests: new Set(),
      task: undefined,
      taskDone: false,
      closed: false,
      resolve,
      reject,
      cleanup: undefined,
    };
    call.resolve = (value) => {
      if (!call.replySettled) {
        call.replySettled = true;
        resolve(value);
      }
    };
    call.reject = (error) => {
      if (!call.replySettled) {
        call.replySettled = true;
        reject(error);
      }
    };
    this.#calls.add(call);
    this.#started++;
    const abandon = () => {
      if (!call.abandoned && !call.replySettled) {
        call.abandoned = true;
        call.controller.abort();
        call.reject(this.#failure(call));
      }
    };
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      EventTarget.prototype.addEventListener.call(signal, 'abort', abandon, { once: true });
      if (isAborted(signal)) abandon();
      timer = setTimeout(abandon, Math.max(0, call.deadline - performance.now()));
      call.task = this.#lifetime(call);
      void call.task.catch(() => {});
    } catch {
      call.taskDone = true;
      call.closed = true;
      this.#prune();
      reject(new ChannelError('DispatchUnavailable'));
    }
    return reply.finally(() => {
      if (timer) clearTimeout(timer);
      EventTarget.prototype.removeEventListener.call(signal, 'abort', abandon);
    });
  }
  close(): Promise<void> {
    this.#closing = true;
    if (!this.#closeTask) {
      const actual = (async () => {
        this.#retry();
        await Promise.all([...this.#calls].map((c) => c.task));
        this.#retry();
        await Promise.all([...this.#calls].map((c) => c.cleanup));
        this.#prune();
        if (this.#calls.size) throw new ChannelError('CleanupIncomplete');
      })();
      this.#closeTask = actual;
      void actual.then(
        () => {
          this.#closeTask = undefined;
        },
        () => {
          this.#closeTask = undefined;
        },
      );
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    return Promise.race([
      this.#closeTask,
      new Promise<never>((_r, reject) => {
        timer = setTimeout(() => reject(new ChannelError('CleanupIncomplete')), this.#cleanupMs);
      }),
    ])
      .catch(() => {
        throw new ChannelError('CleanupIncomplete');
      })
      .finally(() => {
        if (timer) clearTimeout(timer);
      });
  }
}
