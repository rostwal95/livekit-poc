/** Bounded loopback fake external ports. No durable work scheduling or real carrier I/O. */
import {
  createServer,
  request as httpRequest,
  type Server,
  type IncomingMessage,
  type ServerResponse,
  type ClientRequest,
} from 'node:http';
import type { Socket } from 'node:net';
import type {
  OperationLookup,
  OperationReceipt,
  PreparedDispatch,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import type { CarrierResult, SendRequest } from '@livekit-ecosystem/channel-continuity/outbox';
import type {
  ProviderOperation,
  ProviderLookup,
} from '@livekit-ecosystem/channel-continuity/idempotent-fake-sms';
import {
  StarterError,
  safeStarterCode,
  STARTER_LIMITS,
  fields,
  id,
  uuid,
  digest,
  token,
  CloseObservation,
  parseConfig,
  parseCredentials,
  parseJson,
  type StarterConfig,
  type StarterBinding,
  type ExternalCredentials,
  type RuntimeCredentials,
} from './config.js';
import { ExternalReceiptStore } from './receipt-store.js';

export type ExternalLedgerPort = Readonly<{
  preflight(): Promise<void>;
  accept(input: PreparedDispatch): Promise<OperationReceipt>;
  lookup(
    input: OperationLookup,
  ): Promise<
    Readonly<{ status: 'absent' }> | Readonly<{ status: 'accepted'; receipt: OperationReceipt }>
  >;
  ordinarySend(input: SendRequest): Promise<CarrierResult>;
  idempotentSend(
    input: ProviderOperation,
    operationDigest: string,
    attemptId: string,
    requestDigest: string,
  ): Promise<CarrierResult>;
  idempotentLookup(
    scope: ProviderOperation['providerScope'],
    key: string,
    operationDigest: string,
  ): Promise<ProviderLookup>;
  close(): Promise<void>;
}>;
export type ExternalEndpoint = Readonly<{ host: '127.0.0.1'; port: number }>;
type OperationBinding = Pick<
  StarterBinding,
  'alias' | 'accountScope' | 'caseId' | 'conversationId' | 'senderId'
>;
export type OperationClientBinding = OperationBinding & Readonly<{ operationBearer: string }>;
export type OperationClientConfig = Readonly<{
  schemaVersion: 1;
  profileId: string;
  endpoint: ExternalEndpoint;
  bindings: readonly OperationClientBinding[];
  /** Deadline for one external call (20–5,000ms); defaults to the starter's 2,000ms. */
  callTimeoutMs?: number;
}>;
function operationConfig(value: unknown): OperationClientConfig {
  try {
    const timed =
      value !== null && typeof value === 'object' && Object.hasOwn(value, 'callTimeoutMs');
    const p = fields(value, [
      'schemaVersion',
      'profileId',
      'endpoint',
      'bindings',
      ...(timed ? ['callTimeoutMs'] : []),
    ]);
    const endpoint = fields(p.endpoint, ['host', 'port']);
    if (
      (timed &&
        (!Number.isSafeInteger(p.callTimeoutMs) ||
          (p.callTimeoutMs as number) < 20 ||
          (p.callTimeoutMs as number) > 5000)) ||
      p.schemaVersion !== 1 ||
      endpoint.host !== '127.0.0.1' ||
      !Number.isSafeInteger(endpoint.port) ||
      (endpoint.port as number) < 1 ||
      (endpoint.port as number) > 65535 ||
      !Array.isArray(p.bindings) ||
      Object.getPrototypeOf(p.bindings) !== Array.prototype ||
      p.bindings.length < 1 ||
      p.bindings.length > STARTER_LIMITS.maxBindings ||
      Reflect.ownKeys(p.bindings).length !== p.bindings.length + 1
    )
      throw new StarterError('InvalidConfiguration');
    const aliases = new Set<string>(),
      accounts = new Set<string>();
    const bindings: OperationClientBinding[] = [];
    for (let index = 0; index < p.bindings.length; index++) {
      const descriptor = Object.getOwnPropertyDescriptor(p.bindings, String(index));
      if (!descriptor || !('value' in descriptor) || !descriptor.enumerable)
        throw new StarterError('InvalidConfiguration');
      const b = fields(descriptor.value, [
        'alias',
        'accountScope',
        'caseId',
        'conversationId',
        'senderId',
        'operationBearer',
      ]);
      const rawScope = fields(b.accountScope, ['tenantId', 'accountId']);
      const accountScope = Object.freeze({
        tenantId: id(rawScope.tenantId),
        accountId: id(rawScope.accountId),
      });
      const alias = id(b.alias),
        operationBearer = token(b.operationBearer);
      const account = JSON.stringify(accountScope);
      if (aliases.has(alias) || accounts.has(account) || operationBearer.length !== 43)
        throw new StarterError('InvalidConfiguration');
      aliases.add(alias);
      accounts.add(account);
      bindings.push(
        Object.freeze({
          alias,
          accountScope,
          caseId: id(b.caseId),
          conversationId: id(b.conversationId),
          senderId: id(b.senderId),
          operationBearer,
        }),
      );
    }
    return Object.freeze({
      schemaVersion: 1,
      profileId: uuid(p.profileId),
      endpoint: Object.freeze({ host: '127.0.0.1', port: endpoint.port as number }),
      bindings: Object.freeze(bindings),
      ...(timed ? { callTimeoutMs: p.callTimeoutMs as number } : {}),
    });
  } catch {
    throw new StarterError('InvalidConfiguration');
  }
}
function hash(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value))
    throw new StarterError('InvalidCommand');
  return value;
}
function revision(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !/^[1-9][0-9]{0,18}$/.test(value) ||
    BigInt(value) > 9223372036854775807n
  )
    throw new StarterError('InvalidCommand');
  return value;
}
function body(value: unknown, empty = false): string {
  if (
    typeof value !== 'string' ||
    (!empty && value.length < 1) ||
    Buffer.byteLength(value, 'utf8') > 4096 ||
    /[\ud800-\udfff]/u.test(value)
  )
    throw new StarterError('InvalidCommand');
  return value;
}
function scope(raw: unknown, binding: OperationBinding): ProviderOperation['scope'] {
  const s = fields(raw, ['tenantId', 'accountId']);
  if (
    s.tenantId !== binding.accountScope.tenantId ||
    s.accountId !== binding.accountScope.accountId
  )
    throw new StarterError('AccessDenied');
  return binding.accountScope;
}
function provider(raw: unknown, binding: StarterBinding): ProviderOperation['providerScope'] {
  const p = fields(raw, ['tenantId', 'provider', 'providerAccountId']);
  if (
    p.tenantId !== binding.providerScope.tenantId ||
    p.provider !== 'fake_sms' ||
    p.providerAccountId !== binding.providerScope.providerAccountId
  )
    throw new StarterError('AccessDenied');
  return binding.providerScope;
}
function bound(p: Record<string, unknown>, binding: StarterBinding): void {
  if (
    p.caseId !== binding.caseId ||
    p.conversationId !== binding.conversationId ||
    p.senderId !== binding.senderId
  )
    throw new StarterError('AccessDenied');
}
export function checkedPrepared(value: unknown, binding: OperationBinding): PreparedDispatch {
  const p = fields(value, ['submission', 'canonicalPayload', 'payloadDigest']);
  const s = fields(p.submission, [
    'schemaVersion',
    'kind',
    'operationKey',
    'scope',
    'caseId',
    'caseRevision',
    'conversationId',
    'message',
  ]);
  const m = fields(s.message, ['receiptId', 'eventId', 'messageId', 'senderId', 'body']);
  if (
    s.schemaVersion !== 1 ||
    s.kind !== 'investigation' ||
    s.caseId !== binding.caseId ||
    s.conversationId !== binding.conversationId ||
    m.senderId !== binding.senderId
  )
    throw new StarterError('AccessDenied');
  const submission = Object.freeze({
    schemaVersion: 1 as const,
    kind: 'investigation' as const,
    operationKey: uuid(s.operationKey),
    scope: scope(s.scope, binding),
    caseId: binding.caseId,
    caseRevision: revision(s.caseRevision),
    conversationId: binding.conversationId,
    message: Object.freeze({
      receiptId: uuid(m.receiptId),
      eventId: id(m.eventId),
      messageId: id(m.messageId),
      senderId: binding.senderId,
      body: body(m.body, true),
    }),
  });
  const canonicalPayload = JSON.stringify(submission);
  if (p.canonicalPayload !== canonicalPayload || p.payloadDigest !== digest(canonicalPayload))
    throw new StarterError('IdentityConflict');
  return Object.freeze({ submission, canonicalPayload, payloadDigest: p.payloadDigest });
}
function checkedLookup(value: unknown, binding: OperationBinding): OperationLookup {
  const p = fields(value, ['operationKey', 'scope', 'payloadDigest']);
  return Object.freeze({
    operationKey: uuid(p.operationKey),
    scope: scope(p.scope, binding),
    payloadDigest: hash(p.payloadDigest),
  });
}
function checkedOperation(value: unknown, binding: StarterBinding): ProviderOperation {
  const p = fields(value, [
    'schemaVersion',
    'capability',
    'providerScope',
    'scope',
    'caseId',
    'conversationId',
    'outboundId',
    'responseId',
    'providerOperationKey',
    'senderId',
    'body',
  ]);
  bound(p, binding);
  if (p.schemaVersion !== 1 || p.capability !== 'idempotent_fake_sms_v1')
    throw new StarterError('InvalidCommand');
  return Object.freeze({
    schemaVersion: 1,
    capability: 'idempotent_fake_sms_v1',
    providerScope: provider(p.providerScope, binding),
    scope: scope(p.scope, binding),
    caseId: binding.caseId,
    conversationId: binding.conversationId,
    outboundId: uuid(p.outboundId),
    responseId: id(p.responseId),
    providerOperationKey: uuid(p.providerOperationKey),
    senderId: binding.senderId,
    body: body(p.body),
  });
}
function checkedSend(value: unknown, binding: StarterBinding): SendRequest {
  const p = fields(value, [
    'schemaVersion',
    'outboundId',
    'attemptId',
    'providerOperationKey',
    'providerScope',
    'scope',
    'caseId',
    'conversationId',
    'responseId',
    'senderId',
    'associationVersion',
    'routeVersion',
    'body',
  ]);
  bound(p, binding);
  if (p.schemaVersion !== 1) throw new StarterError('InvalidCommand');
  return Object.freeze({
    schemaVersion: 1,
    outboundId: uuid(p.outboundId),
    responseId: id(p.responseId),
    body: body(p.body),
    scope: scope(p.scope, binding),
    caseId: binding.caseId,
    conversationId: binding.conversationId,
    attemptId: uuid(p.attemptId),
    providerOperationKey: uuid(p.providerOperationKey),
    providerScope: provider(p.providerScope, binding),
    senderId: binding.senderId,
    associationVersion: revision(p.associationVersion),
    routeVersion: revision(p.routeVersion),
  });
}
function receipt(value: unknown, expected: OperationLookup): OperationReceipt {
  const p = fields(value, ['operationKey', 'scope', 'payloadDigest', 'receiptId']);
  const sc = fields(p.scope, ['tenantId', 'accountId']);
  if (
    p.operationKey !== expected.operationKey ||
    p.payloadDigest !== expected.payloadDigest ||
    sc.tenantId !== expected.scope.tenantId ||
    sc.accountId !== expected.scope.accountId
  )
    throw new StarterError('Unavailable');
  return Object.freeze({
    operationKey: expected.operationKey,
    scope: expected.scope,
    payloadDigest: expected.payloadDigest,
    receiptId: uuid(p.receiptId),
  });
}
function carrier(value: unknown, attemptId: string, requestDigest: string): CarrierResult {
  const desc =
    value && typeof value === 'object'
      ? Object.getOwnPropertyDescriptor(value, 'status')
      : undefined;
  const accepted = desc && 'value' in desc && desc.value === 'accepted_by_provider';
  const p = fields(value, [
    'schemaVersion',
    'attemptId',
    'requestDigest',
    'status',
    ...(accepted ? ['providerMessageId'] : []),
  ]);
  if (
    p.schemaVersion !== 1 ||
    p.attemptId !== attemptId ||
    p.requestDigest !== requestDigest ||
    (!accepted && p.status !== 'definitive_not_accepted')
  )
    throw new StarterError('Unavailable');
  return accepted
    ? Object.freeze({
        schemaVersion: 1,
        attemptId,
        requestDigest,
        status: 'accepted_by_provider',
        providerMessageId: id(p.providerMessageId),
      })
    : Object.freeze({
        schemaVersion: 1,
        attemptId,
        requestDigest,
        status: 'definitive_not_accepted',
      });
}
function providerLookup(
  value: unknown,
  sc: ProviderOperation['providerScope'],
  key: string,
  dg: string,
): ProviderLookup {
  const p = fields(value, [
    'schemaVersion',
    'providerScope',
    'providerOperationKey',
    'operationDigest',
    'state',
    'providerMessageId',
  ]);
  const ps = fields(p.providerScope, ['tenantId', 'provider', 'providerAccountId']);
  if (
    p.schemaVersion !== 1 ||
    p.providerOperationKey !== key ||
    p.operationDigest !== dg ||
    ps.tenantId !== sc.tenantId ||
    ps.provider !== sc.provider ||
    ps.providerAccountId !== sc.providerAccountId ||
    !['accepted_by_provider', 'definitive_not_accepted', 'absent', 'unknown'].includes(
      p.state as string,
    )
  )
    throw new StarterError('Unavailable');
  const providerMessageId = p.state === 'accepted_by_provider' ? id(p.providerMessageId) : null;
  if (providerMessageId === null && p.providerMessageId !== null)
    throw new StarterError('Unavailable');
  return Object.freeze({
    schemaVersion: 1,
    providerScope: sc,
    providerOperationKey: key,
    operationDigest: dg,
    state: p.state as ProviderLookup['state'],
    providerMessageId,
  });
}
function status(code: string): number {
  return code === 'AccessDenied'
    ? 403
    : code === 'IdentityConflict'
      ? 409
      : code === 'Overloaded'
        ? 429
        : code === 'InvalidCommand' || code === 'InvalidConfiguration'
          ? 400
          : 503;
}
export class ExternalHttpServer {
  readonly #config: StarterConfig;
  readonly #credentials: ExternalCredentials;
  readonly #ledger: ExternalLedgerPort;
  readonly #server: Server;
  readonly #sockets = new Map<Socket, Promise<void>>();
  readonly #handlers = new Set<Promise<void>>();
  #starting: Promise<ExternalEndpoint> | undefined;
  #ending: Promise<void> | undefined;
  #endpoint: ExternalEndpoint | undefined;
  #closing = false;
  readonly #closeObservation = new CloseObservation();
  #started = 0;
  #known = 0;
  #rejected = 0;
  #profileReads = 0;
  constructor(
    configInput: StarterConfig,
    credentialsInput: ExternalCredentials,
    ledger?: ExternalLedgerPort,
  ) {
    this.#config = parseConfig(configInput);
    const c = parseCredentials(credentialsInput, this.#config);
    if (c.role !== 'external') throw new StarterError('AccessDenied');
    this.#credentials = c;
    this.#ledger = ledger ?? new ExternalReceiptStore(this.#config, c);
    this.#server = createServer(
      { maxHeaderSize: STARTER_LIMITS.externalHeaderBytes, joinDuplicateHeaders: false },
      (req, res) => {
        if (this.#closing || this.#handlers.size >= STARTER_LIMITS.externalHandlers) {
          req.socket.destroy();
          return;
        }
        const work = Promise.resolve().then(() => this.#handle(req, res));
        this.#handlers.add(work);
        void work.then(
          () => this.#handlers.delete(work),
          () => this.#handlers.delete(work),
        );
      },
    );
    this.#server.maxConnections = STARTER_LIMITS.externalSockets;
    this.#server.maxHeadersCount = 0;
    this.#server.headersTimeout = 1000;
    this.#server.requestTimeout = 2000;
    this.#server.keepAliveTimeout = 1;
    this.#server.on('connection', (socket) => {
      if (this.#closing || this.#sockets.size >= STARTER_LIMITS.externalSockets) {
        socket.destroy();
        return;
      }
      let done!: () => void;
      this.#sockets.set(
        socket,
        new Promise<void>((r) => {
          done = r;
        }),
      );
      socket.once('close', () => {
        done();
        this.#sockets.delete(socket);
      });
      socket.setTimeout(STARTER_LIMITS.externalCallMs, () => socket.destroy());
    });
    this.#server.on('clientError', (_error, socket) => socket.destroy());
    this.#server.on('error', () => undefined);
  }
  metrics(): Readonly<{
    started: number;
    known: number;
    rejected: number;
    active: number;
    sockets: number;
    closing: boolean;
    profileReads: number;
  }> {
    return Object.freeze({
      started: this.#started,
      known: this.#known,
      rejected: this.#rejected,
      active: this.#handlers.size,
      sockets: this.#sockets.size,
      closing: this.#closing,
      profileReads: this.#profileReads,
    });
  }
  start(port = this.#config.endpoints.external): Promise<ExternalEndpoint> {
    if (this.#closing) return Promise.reject(new StarterError('Closed'));
    if (!Number.isInteger(port) || port < 0 || port > 65535)
      return Promise.reject(new StarterError('InvalidCommand'));
    this.#starting ??= Promise.resolve().then(async () => {
      await this.#ledger.preflight();
      if (this.#closing) throw new StarterError('Closed');
      await new Promise<void>((resolve, reject) => {
        const error = () => {
          this.#server.off('listening', ready);
          reject(new StarterError('Unavailable'));
        };
        const ready = () => {
          this.#server.off('error', error);
          resolve();
        };
        this.#server.once('error', error);
        this.#server.once('listening', ready);
        this.#server.listen(port, '127.0.0.1');
      });
      const a = this.#server.address();
      if (!a || typeof a === 'string' || this.#closing) throw new StarterError('Closed');
      this.#endpoint = Object.freeze({ host: '127.0.0.1', port: a.port });
      return this.#endpoint;
    });
    void this.#starting.catch(() => undefined);
    return this.#starting;
  }
  #authorize(
    req: IncomingMessage,
  ): Readonly<{ binding: StarterBinding; role: 'operation' | 'ordinary' | 'idempotent' }> {
    const names = new Set<string>();
    if (req.rawHeaders.length / 2 > 16) throw new StarterError('InvalidCommand');
    for (let i = 0; i < req.rawHeaders.length; i += 2) {
      const name = req.rawHeaders[i]!.toLowerCase();
      if (
        names.has(name) ||
        ![
          'host',
          'connection',
          'content-length',
          'content-type',
          'authorization',
          'accept',
          'user-agent',
        ].includes(name)
      )
        throw new StarterError('InvalidCommand');
      names.add(name);
    }
    if (
      req.method !== 'POST' ||
      req.headers.host !== '127.0.0.1:' + this.#endpoint?.port ||
      req.headers['transfer-encoding'] !== undefined ||
      req.headers['content-type'] !== 'application/json' ||
      typeof req.headers['content-length'] !== 'string' ||
      !/^(0|[1-9][0-9]{0,5})$/.test(req.headers['content-length'])
    )
      throw new StarterError('InvalidCommand');
    const auth = req.headers.authorization;
    if (typeof auth !== 'string' || !/^Bearer [A-Za-z0-9_-]{32,128}$/.test(auth))
      throw new StarterError('AccessDenied');
    const token = auth.slice(7);
    for (const b of this.#credentials.bearers)
      for (const role of ['operation', 'ordinary', 'idempotent'] as const)
        if (b[role] === token)
          return Object.freeze({
            binding: this.#config.bindings.find((c) => c.alias === b.alias)!,
            role,
          });
    throw new StarterError('AccessDenied');
  }
  async #body(req: IncomingMessage): Promise<unknown> {
    const size = Number(req.headers['content-length']);
    if (size < 1 || size > STARTER_LIMITS.externalRequestBytes)
      throw new StarterError('InvalidCommand');
    const chunks: Buffer[] = [];
    let total = 0;
    await new Promise<void>((resolve, reject) => {
      const finish = (e?: StarterError) => {
        clearTimeout(timer);
        req.off('data', data);
        req.off('end', end);
        req.off('aborted', aborted);
        req.off('error', aborted);
        e ? reject(e) : resolve();
      };
      const data = (chunk: Buffer) => {
        total += chunk.length;
        if (total > size) finish(new StarterError('InvalidCommand'));
        else chunks.push(chunk);
      };
      const end = () => finish(total === size ? undefined : new StarterError('InvalidCommand'));
      const aborted = () => finish(new StarterError('Unavailable'));
      const timer = setTimeout(() => {
        finish(new StarterError('Unavailable'));
        req.destroy();
      }, 1000);
      req.on('data', data);
      req.once('end', end);
      req.once('aborted', aborted);
      req.once('error', aborted);
    });
    try {
      return parseJson(Buffer.concat(chunks), STARTER_LIMITS.externalRequestBytes);
    } catch {
      throw new StarterError('InvalidCommand');
    }
  }
  async #handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    this.#started++;
    try {
      const a = this.#authorize(req),
        value = await this.#body(req);
      let reply: unknown;
      if (req.url === '/v1/investigations/inspect-profile' && a.role === 'operation') {
        const p = fields(value, ['schemaVersion', 'profileId']);
        if (p.schemaVersion !== 1 || p.profileId !== this.#config.profileId)
          throw new StarterError('AccessDenied');
        await this.#ledger.preflight();
        this.#profileReads++;
        reply = {
          schemaVersion: 1,
          status: 'known',
          profileId: this.#config.profileId,
          ready: true,
        };
      } else if (req.url === '/v1/investigations/accept' && a.role === 'operation') {
        const p = fields(value, ['schemaVersion', 'canonicalPayload', 'payloadDigest']);
        if (
          p.schemaVersion !== 1 ||
          typeof p.canonicalPayload !== 'string' ||
          Buffer.byteLength(p.canonicalPayload, 'utf8') > 32768
        )
          throw new StarterError('InvalidCommand');
        const checked = checkedPrepared(
          {
            submission: parseJson(Buffer.from(p.canonicalPayload), 32768),
            canonicalPayload: p.canonicalPayload,
            payloadDigest: p.payloadDigest,
          },
          a.binding,
        );
        const expected = {
          operationKey: checked.submission.operationKey,
          scope: checked.submission.scope,
          payloadDigest: checked.payloadDigest,
        };
        reply = {
          schemaVersion: 1,
          status: 'known',
          receipt: receipt(await this.#ledger.accept(checked), expected),
        };
      } else if (req.url === '/v1/investigations/lookup' && a.role === 'operation') {
        const checked = checkedLookup(value, a.binding),
          observed = await this.#ledger.lookup(checked);
        const d =
          observed && typeof observed === 'object'
            ? Object.getOwnPropertyDescriptor(observed, 'status')
            : undefined;
        const accepted = d && 'value' in d && d.value === 'accepted';
        const o = fields(observed, accepted ? ['status', 'receipt'] : ['status']);
        if (!accepted && o.status !== 'absent') throw new StarterError('Unavailable');
        reply = {
          schemaVersion: 1,
          status: 'known',
          observation: accepted
            ? { status: 'accepted', receipt: receipt(o.receipt, checked) }
            : { status: 'absent' },
        };
      } else if (req.url === '/v1/sms/send' && a.role === 'ordinary') {
        const checked = checkedSend(value, a.binding);
        reply = {
          schemaVersion: 1,
          status: 'known',
          result: carrier(
            await this.#ledger.ordinarySend(checked),
            checked.attemptId,
            digest(JSON.stringify(checked)),
          ),
        };
      } else if (req.url === '/v1/idempotent-sms/send' && a.role === 'idempotent') {
        const p = fields(value, ['schemaVersion', 'operation', 'operationDigest', 'attempt']);
        const op = checkedOperation(p.operation, a.binding),
          operationDigest = digest(JSON.stringify(op));
        const attempt = fields(p.attempt, [
          'attemptId',
          'requestDigest',
          'associationVersion',
          'routeVersion',
        ]);
        if (p.schemaVersion !== 1 || p.operationDigest !== operationDigest)
          throw new StarterError('IdentityConflict');
        const attemptId = uuid(attempt.attemptId),
          request: SendRequest = {
            schemaVersion: 1,
            outboundId: op.outboundId,
            responseId: op.responseId,
            body: op.body,
            scope: op.scope,
            caseId: op.caseId,
            conversationId: op.conversationId,
            attemptId,
            providerOperationKey: op.providerOperationKey,
            providerScope: op.providerScope,
            senderId: op.senderId,
            associationVersion: revision(attempt.associationVersion),
            routeVersion: revision(attempt.routeVersion),
          };
        const requestDigest = digest(JSON.stringify(request));
        if (attempt.requestDigest !== requestDigest) throw new StarterError('IdentityConflict');
        reply = {
          schemaVersion: 1,
          status: 'known',
          providerOperationKey: op.providerOperationKey,
          operationDigest,
          result: carrier(
            await this.#ledger.idempotentSend(op, operationDigest, attemptId, requestDigest),
            attemptId,
            requestDigest,
          ),
        };
      } else if (req.url === '/v1/idempotent-sms/lookup' && a.role === 'idempotent') {
        const p = fields(value, [
          'schemaVersion',
          'providerScope',
          'providerOperationKey',
          'operationDigest',
        ]);
        if (p.schemaVersion !== 1) throw new StarterError('InvalidCommand');
        const sc = provider(p.providerScope, a.binding),
          key = uuid(p.providerOperationKey),
          dg = hash(p.operationDigest);
        reply = {
          schemaVersion: 1,
          status: 'known',
          observation: providerLookup(
            await this.#ledger.idempotentLookup(sc, key, dg),
            sc,
            key,
            dg,
          ),
        };
      } else throw new StarterError('AccessDenied');
      this.#known++;
      await this.#send(
        res,
        200,
        reply,
        ['/v1/sms/send', '/v1/idempotent-sms/send', '/v1/idempotent-sms/lookup'].includes(
          req.url ?? '',
        ),
      );
    } catch (e) {
      this.#rejected++;
      const code = safeStarterCode(e) ?? 'Unavailable';
      await this.#send(
        res,
        status(code),
        { schemaVersion: 1, status: 'unavailable', code },
        ['/v1/sms/send', '/v1/idempotent-sms/send', '/v1/idempotent-sms/lookup'].includes(
          req.url ?? '',
        ),
      );
    }
  }
  async #send(
    res: ServerResponse,
    code: number,
    value: unknown,
    legacyCarrier = false,
  ): Promise<void> {
    const data = Buffer.from(JSON.stringify(value));
    if (res.destroyed) return;
    if (
      data.length >
      (code === 200 ? STARTER_LIMITS.externalResponseBytes : STARTER_LIMITS.externalErrorBytes)
    ) {
      res.destroy();
      return;
    }
    await new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        res.off('finish', finish);
        res.off('close', finish);
        res.off('error', finish);
        resolve();
      };
      const timer = setTimeout(() => {
        res.destroy();
        finish();
      }, STARTER_LIMITS.externalFlushMs);
      res.once('finish', finish);
      res.once('close', finish);
      res.once('error', finish);
      try {
        res.writeHead(code, {
          'content-type': 'application/json',
          'content-length': data.length,
          connection: 'close',
          ...(legacyCarrier ? {} : { 'cache-control': 'no-store' }),
        });
        res.end(data);
      } catch {
        res.destroy();
        finish();
      }
    });
  }
  close(): Promise<void> {
    this.#closing = true;
    return this.#closeObservation.observe(async () => {
      this.#ending ??= Promise.resolve().then(async () => {
        if (this.#starting) await this.#starting.catch(() => undefined);
        const listener = new Promise<void>((resolve, reject) => {
          if (!this.#server.listening) {
            resolve();
            return;
          }
          this.#server.close((e) => (e ? reject(e) : resolve()));
        });
        for (const s of this.#sockets.keys()) s.destroy();
        const handled = await Promise.allSettled([...this.#handlers]);
        await Promise.all([...this.#sockets.values()]);
        await listener;
        if (handled.some((r) => r.status === 'rejected'))
          throw new StarterError('CleanupIncomplete');
      });
      await this.#ending;
      await this.#ledger.close();
    });
  }
}

type ClientCall = {
  done: Promise<void>;
  finish(): void;
  request?: ClientRequest;
  socket?: Socket;
  requestClosed: boolean;
  socketClosed: boolean;
};
export class ExternalOperationClient {
  readonly #config: OperationClientConfig;
  readonly #calls = new Set<ClientCall>();
  #closing = false;
  readonly #closeObservation = new CloseObservation();
  constructor(configInput: OperationClientConfig);
  constructor(configInput: StarterConfig, credentialsInput: RuntimeCredentials);
  constructor(
    configInput: OperationClientConfig | StarterConfig,
    credentialsInput?: RuntimeCredentials,
  ) {
    if (arguments.length === 1) {
      this.#config = operationConfig(configInput);
    } else {
      const config = parseConfig(configInput);
      const c = parseCredentials(credentialsInput, config);
      if (c.role !== 'runtime') throw new StarterError('AccessDenied');
      this.#config = Object.freeze({
        schemaVersion: 1,
        profileId: config.profileId,
        endpoint: Object.freeze({ host: '127.0.0.1', port: config.endpoints.external }),
        bindings: Object.freeze(
          config.bindings.map((binding) =>
            Object.freeze({
              ...binding,
              operationBearer: c.externalBearers.find((bearer) => bearer.alias === binding.alias)!
                .operation,
            }),
          ),
        ),
      });
    }
  }
  readonly capabilities = 'stable_idempotency_and_lookup' as const;
  metrics(): Readonly<{ active: number; closing: boolean }> {
    return Object.freeze({ active: this.#calls.size, closing: this.#closing });
  }
  #binding(rawScope: unknown): OperationClientBinding {
    const input = fields(rawScope, ['tenantId', 'accountId']);
    const b = this.#config.bindings.find(
      (b) =>
        b.accountScope.tenantId === input.tenantId && b.accountScope.accountId === input.accountId,
    );
    if (!b) throw new StarterError('AccessDenied');
    return b;
  }
  preflight(alias: string, signal: AbortSignal): Promise<void> {
    if (!this.#config.bindings.some((b) => b.alias === alias))
      return Promise.reject(new StarterError('AccessDenied'));
    return this.#exchange(
      '/v1/investigations/inspect-profile',
      { schemaVersion: 1, profileId: this.#config.profileId },
      alias,
      signal,
      false,
      (value) => {
        const p = fields(value, ['schemaVersion', 'status', 'profileId', 'ready']);
        if (
          p.schemaVersion !== 1 ||
          p.status !== 'known' ||
          p.profileId !== this.#config.profileId ||
          p.ready !== true
        )
          throw new StarterError('Unavailable');
      },
    );
  }
  lookup(input: OperationLookup, signal: AbortSignal): ReturnType<ExternalLedgerPort['lookup']> {
    const p = fields(input, ['operationKey', 'scope', 'payloadDigest']);
    const b = this.#binding(p.scope),
      checked = checkedLookup(p, b);
    return this.#exchange('/v1/investigations/lookup', checked, b.alias, signal, false, (value) => {
      const p = fields(value, ['schemaVersion', 'status', 'observation']);
      if (p.schemaVersion !== 1 || p.status !== 'known') throw new StarterError('Unavailable');
      const o = fields(p.observation, [
        'status',
        ...(Object.hasOwn(p.observation as object, 'receipt') ? ['receipt'] : []),
      ]);
      if (o.status === 'absent') return Object.freeze({ status: 'absent' as const });
      if (o.status !== 'accepted') throw new StarterError('Unavailable');
      return Object.freeze({
        status: 'accepted' as const,
        receipt: this.#receipt(o.receipt, checked),
      });
    });
  }
  accept(input: PreparedDispatch, signal: AbortSignal): Promise<OperationReceipt> {
    const p = fields(input, ['submission', 'canonicalPayload', 'payloadDigest']);
    const submission = fields(p.submission, [
      'schemaVersion',
      'kind',
      'operationKey',
      'scope',
      'caseId',
      'caseRevision',
      'conversationId',
      'message',
    ]);
    const b = this.#binding(submission.scope);
    const checked = checkedPrepared(p, b);
    return this.#exchange(
      '/v1/investigations/accept',
      {
        schemaVersion: 1,
        canonicalPayload: checked.canonicalPayload,
        payloadDigest: checked.payloadDigest,
      },
      b.alias,
      signal,
      true,
      (value) => {
        const p = fields(value, ['schemaVersion', 'status', 'receipt']);
        if (p.schemaVersion !== 1 || p.status !== 'known') throw new StarterError('OutcomeUnknown');
        return this.#receipt(p.receipt, {
          operationKey: checked.submission.operationKey,
          scope: checked.submission.scope,
          payloadDigest: checked.payloadDigest,
        });
      },
    );
  }
  #receipt(value: unknown, input: OperationLookup): OperationReceipt {
    const p = fields(value, ['operationKey', 'scope', 'payloadDigest', 'receiptId']);
    const s = fields(p.scope, ['tenantId', 'accountId']);
    if (
      p.operationKey !== input.operationKey ||
      p.payloadDigest !== input.payloadDigest ||
      s.tenantId !== input.scope.tenantId ||
      s.accountId !== input.scope.accountId
    )
      throw new StarterError('IdentityConflict');
    return Object.freeze({ ...input, receiptId: uuid(p.receiptId) });
  }
  #exchange<T>(
    path: string,
    value: unknown,
    alias: string,
    signal: AbortSignal,
    write: boolean,
    decode: (v: unknown) => T,
  ): Promise<T> {
    if (this.#closing) return Promise.reject(new StarterError('Closed'));
    if (this.#calls.size >= 2) return Promise.reject(new StarterError('Overloaded'));
    if (signal.aborted) return Promise.reject(new StarterError('Unavailable'));
    const payload = Buffer.from(JSON.stringify(value));
    if (payload.length > STARTER_LIMITS.externalRequestBytes)
      return Promise.reject(new StarterError('InvalidCommand'));
    let done!: () => void;
    const call: ClientCall = {
      done: new Promise<void>((r) => {
        done = r;
      }),
      finish: () => done(),
      requestClosed: false,
      socketClosed: true,
    };
    this.#calls.add(call);
    const bearer = this.#config.bindings.find((b) => b.alias === alias)!.operationBearer;
    const failure = () => new StarterError(write ? 'OutcomeUnknown' : 'Unavailable');
    let timer: ReturnType<typeof setTimeout> | undefined, abort: (() => void) | undefined;
    const release = () => {
      if (call.requestClosed && call.socketClosed && this.#calls.delete(call)) call.finish();
    };
    return new Promise<T>((resolve, reject) => {
      let delivered = false;
      const fail = () => {
        if (!delivered) {
          delivered = true;
          reject(failure());
        }
        call.request?.destroy();
        call.socket?.destroy();
      };
      timer = setTimeout(fail, this.#config.callTimeoutMs ?? STARTER_LIMITS.externalCallMs);
      try {
        const req = httpRequest(
          {
            hostname: '127.0.0.1',
            port: this.#config.endpoint.port,
            path,
            method: 'POST',
            agent: false,
            headers: {
              host: '127.0.0.1:' + this.#config.endpoint.port,
              authorization: 'Bearer ' + bearer,
              'content-type': 'application/json',
              'content-length': payload.length,
              connection: 'close',
            },
          },
          (res) => {
            const length = res.headers['content-length'];
            if (
              res.statusCode !== 200 ||
              res.headers['content-type'] !== 'application/json' ||
              res.headers.connection !== 'close' ||
              res.headers['cache-control'] !== 'no-store' ||
              res.headers['transfer-encoding'] !== undefined ||
              typeof length !== 'string' ||
              !/^[1-9][0-9]{0,4}$/.test(length) ||
              Number(length) > STARTER_LIMITS.externalResponseBytes
            ) {
              res.resume();
              fail();
              return;
            }
            const chunks: Buffer[] = [];
            let total = 0;
            res.on('data', (b: Buffer) => {
              total += b.length;
              if (total > Number(length)) {
                res.destroy();
                fail();
              } else chunks.push(b);
            });
            res.once('aborted', fail);
            res.once('error', fail);
            res.once('end', () => {
              if (delivered) return;
              try {
                if (total !== Number(length) || signal.aborted) throw failure();
                const result = decode(
                  parseJson(Buffer.concat(chunks), STARTER_LIMITS.externalResponseBytes),
                );
                delivered = true;
                resolve(result);
              } catch {
                fail();
              }
            });
          },
        );
        call.request = req;
        req.once('close', () => {
          call.requestClosed = true;
          release();
        });
        req.once('error', fail);
        req.once('socket', (s) => {
          call.socket = s;
          call.socketClosed = false;
          s.once('close', () => {
            call.socketClosed = true;
            release();
          });
        });
        if (this.#calls.has(call)) {
          abort = fail;
          signal.addEventListener('abort', abort, { once: true });
        }
        if (signal.aborted) fail();
        else req.end(payload);
      } catch {
        fail();
        if (!call.request) {
          call.requestClosed = true;
          release();
        }
      }
    }).finally(() => {
      if (timer) clearTimeout(timer);
      if (abort) signal.removeEventListener('abort', abort);
    });
  }
  close(): Promise<void> {
    this.#closing = true;
    return this.#closeObservation.observe(async () => {
      await Promise.all([...this.#calls].map((c) => c.done));
    });
  }
}
