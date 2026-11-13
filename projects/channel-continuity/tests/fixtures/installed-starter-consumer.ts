/** Copied unchanged into an isolated installed archive consumer. No checkout imports. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import {
  constants,
  openSync,
  closeSync,
  writeSync,
  fsyncSync,
  linkSync,
  unlinkSync,
  lstatSync,
  fstatSync,
  readSync,
} from 'node:fs';
import { join, resolve } from 'node:path';
import { createServer, request, type ServerResponse, type ClientRequest } from 'node:http';
import type { Socket } from 'node:net';
import {
  createStandaloneApplication,
  createStandaloneOwner,
  parseConfig,
  parseCredentials,
  readPrivateJson,
  writePrivateJson,
  StarterError,
  safeStarterCode,
  ExternalOperationClient,
  ExternalHttpServer,
  STARTER_GROUPS,
  type StarterConfig,
  type RuntimeCredentials,
  type StandaloneApplication,
  type StarterCode,
} from '@livekit-ecosystem/channel-continuity/starter';
import { signFakeSms, type SignedFakeSms } from '@livekit-ecosystem/channel-continuity/security';
import { encodeRevisionCommand } from '@livekit-ecosystem/channel-continuity/routing';
import {
  signFakeSmsCallback,
  type CallbackObservation,
} from '@livekit-ecosystem/channel-continuity/callbacks';
import type { StoredMessage } from '@livekit-ecosystem/channel-continuity/postgres';
import type { PreparedDispatch } from '@livekit-ecosystem/channel-continuity/dispatch';
import type {
  SendRequest,
  OutboxObservation,
  RecoveryCommandView,
  SendOutcome,
} from '@livekit-ecosystem/channel-continuity/outbox';
import { FakeSmsSendClient } from '@livekit-ecosystem/channel-continuity/fake-sms-send';
import { IdempotentFakeSmsClient } from '@livekit-ecosystem/channel-continuity/idempotent-fake-sms';
import { P1_CONTRACT_STAGES, runP1Contract } from './starter-p1-consumer.js';

const MODES = [
  'config-negative',
  'setup',
  'baseline-client',
  'gateway-a',
  'ack-client',
  'before-restart',
  'later-input',
  'delivery-begin',
  'delivery-recovery',
  'fresh-verify',
  'restore-verify',
  'p1-contract',
] as const;
type Mode = (typeof MODES)[number];
type Label = 'R' | 'T' | 'K' | 'U' | 'V';
const LABELS: readonly Label[] = ['R', 'T', 'K', 'U', 'V'];
const MAX_PROOF = 2097152;
const sha = (s: string | Uint8Array) => createHash('sha256').update(s).digest('hex');
function required(name: string): string {
  const s = process.env[name];
  assert.ok(s);
  return s;
}
const mode = required('P2_STARTER_MODE') as Mode;
assert.ok(MODES.includes(mode));
assert.deepEqual(
  Object.keys(process.env)
    .filter((k) => k.startsWith('P2_STARTER_'))
    .sort(),
  [
    'P2_STARTER_MODE',
    'P2_STARTER_WORK',
    'P2_STARTER_OWNER',
    'P2_STARTER_CONFIG',
    'P2_STARTER_CREDENTIALS',
    'P2_STARTER_IDS',
    'P2_STARTER_OUTPUT',
    ...(mode === 'restore-verify' ? ['P2_STARTER_EXTERNAL_CREDENTIALS'] : []),
  ].sort(),
);
const owner = required('P2_STARTER_OWNER');
assert.match(owner, /^[a-f0-9]{32}$/);
const work = resolve(required('P2_STARTER_WORK'));
assert.equal(lstatSync(work).mode & 0o777, 0o700);
assert.equal(lstatSync(work).uid, process.getuid?.());
assert.equal(lstatSync(work).isSymbolicLink(), false);
function uuid(label: string) {
  const h = sha('p2-starter:41:' + owner + ':' + label);
  return (
    h.slice(0, 8) +
    '-' +
    h.slice(8, 12) +
    '-4' +
    h.slice(13, 16) +
    '-' +
    ((parseInt(h[16]!, 16) & 3) | 8).toString(16) +
    h.slice(17, 20) +
    '-' +
    h.slice(20, 32)
  );
}
function ids() {
  return {
    schemaVersion: 1,
    owner,
    events: Object.fromEntries(
      LABELS.map((l) => [
        l,
        { eventId: 'starter_' + owner + '_' + l, messageId: 'message_' + owner + '_' + l },
      ]),
    ),
    outbound: { ordinary: uuid('outbound:ordinary'), idempotent: uuid('outbound:idempotent') },
    responses: {
      ordinary: 'reply_' + owner + '_ordinary',
      idempotent: 'reply_' + owner + '_idempotent',
    },
    recovery: {
      ordinary: uuid('recovery:ordinary'),
      ordinaryRetry: uuid('recovery:ordinaryRetry'),
      idempotent: uuid('recovery:idempotent'),
    },
    callbacks: {
      delivered: 'callback_' + owner + '_delivered',
      sent: 'callback_' + owner + '_sent',
    },
    probes: {
      ordinaryPhysical: {
        outboundId: uuid('physical:outbound'),
        attemptId: uuid('physical:attempt'),
        providerOperationKey: uuid('physical:operation'),
        responseId: 'physical_' + owner,
      },
      investigations: Array.from({ length: 11 }, (_, i) => uuid('investigation:' + i)),
      idempotent: Array.from({ length: 15 }, (_, i) => uuid('idempotent:' + i)),
      ordinary: Array.from({ length: 13 }, (_, i) => uuid('ordinary:' + i)),
    },
  };
}
const fixed = ids();
function json<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}
function same(a: unknown, b: unknown) {
  assert.deepEqual(json(a), json(b));
}
same(readPrivateJson(required('P2_STARTER_IDS')), fixed);
const eventIds = fixed.events as Record<Label, { eventId: string; messageId: string }>;
function proof(name: string, value: unknown) {
  assert.match(name, /^starter-[a-z0-9-]+\.json$/);
  writePrivateJson(join(work, name), value, MAX_PROOF);
}
function load<T>(name: string): T {
  return readPrivateJson(join(work, name), MAX_PROOF) as T;
}
function publish(stem: string) {
  assert.match(stem, /^[a-z][a-z0-9_]{0,63}$/);
  const target = join(work, stem + '.reached'),
    pending = target + '.' + process.pid + '.pending';
  let fd: number | undefined,
    owned = false;
  try {
    fd = openSync(
      pending,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
      0o600,
    );
    owned = true;
    const bytes = Buffer.from(process.pid + '\n');
    let n = 0;
    while (n < bytes.length) n += writeSync(fd, bytes, n, bytes.length - n);
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    linkSync(pending, target);
  } finally {
    if (fd !== undefined) closeSync(fd);
    if (owned) unlinkSync(pending);
  }
}
function released(stem: string) {
  const path = join(work, stem + '.released');
  let stat;
  try {
    stat = lstatSync(path);
  } catch (e) {
    if (Object.getOwnPropertyDescriptor(e as object, 'code')?.value === 'ENOENT') return false;
    throw e;
  }
  assert.ok(
    stat.isFile() &&
      !stat.isSymbolicLink() &&
      stat.uid === process.getuid?.() &&
      (stat.mode & 0o777) === 0o600 &&
      [1, 2].includes(stat.nlink),
  );
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const opened = fstatSync(fd);
    assert.equal(opened.dev, stat.dev);
    assert.equal(opened.ino, stat.ino);
    assert.ok(opened.size <= 33);
    const bytes = Buffer.alloc(34),
      length = readSync(fd, bytes, 0, bytes.length, null),
      after = fstatSync(fd);
    assert.equal(after.dev, opened.dev);
    assert.equal(after.ino, opened.ino);
    assert.equal(after.size, opened.size);
    assert.ok([1, 2].includes(after.nlink));
    if (after.nlink === 2) {
      try {
        const pending = lstatSync(path + '.' + process.pid + '.pending');
        assert.ok(
          pending.isFile() &&
            !pending.isSymbolicLink() &&
            pending.dev === after.dev &&
            pending.ino === after.ino &&
            pending.uid === after.uid &&
            (pending.mode & 0o777) === 0o600,
        );
      } catch (e) {
        if (
          Object.getOwnPropertyDescriptor(e as object, 'code')?.value !== 'ENOENT' ||
          fstatSync(fd).nlink !== 1
        )
          throw e;
      }
    }
    assert.equal(bytes.subarray(0, length).toString('ascii'), process.pid + '\n');
    return true;
  } finally {
    closeSync(fd);
  }
}

const delay = (ms = 10) => new Promise<void>((r) => setTimeout(r, ms));
async function until(predicate: () => boolean | Promise<boolean>, ms = 10000) {
  const deadline = performance.now() + ms;
  while (!(await predicate())) {
    assert.ok(performance.now() < deadline);
    await delay();
  }
}
function observe<T>(p: Promise<T>) {
  return p.then(
    (value) => ({ ok: true as const, value }),
    (error) => ({ ok: false as const, code: code(error) }),
  );
}
function code(error: unknown): StarterCode {
  const own = safeStarterCode(error);
  if (own) return own;
  try {
    const d = Object.getOwnPropertyDescriptor(error as object, 'code');
    if (
      d &&
      'value' in d &&
      ['IdentityConflict', 'Overloaded', 'OutcomeUnknown', 'AccessDenied', 'NotFound'].includes(
        d.value,
      )
    )
      return d.value as StarterCode;
  } catch {}
  return 'Unavailable';
}
async function expectCode(p: Promise<unknown>, expected: StarterCode) {
  const result = await observe(p);
  assert.ok(!result.ok && result.code === expected);
}
async function entry<T>(entered: Promise<void>, caller: Promise<T>, ms = 5000) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const outcome = observe(caller);
  try {
    const result = await Promise.race([
      entered.then(() => 'entered' as const),
      outcome.then(() => 'settled' as const),
      new Promise<'timeout'>((r) => {
        timer = setTimeout(() => r('timeout'), ms);
      }),
    ]);
    assert.equal(result, 'entered');
  } finally {
    if (timer) clearTimeout(timer);
  }
}
function deferred() {
  let release!: () => void;
  const promise = new Promise<void>((r) => {
    release = r;
  });
  return { promise, release };
}

type HttpResult = { status: number; body: Record<string, unknown>; wire: string; bytes: number };
async function post(
  port: number,
  path: string,
  wire: Buffer,
  headers: Record<string, string> = {},
): Promise<HttpResult> {
  return new Promise((resolve, reject) => {
    let result: HttpResult | undefined;
    const req = request(
      {
        host: '127.0.0.1',
        port,
        path,
        method: 'POST',
        agent: false,
        headers: {
          host: '127.0.0.1:' + port,
          connection: 'close',
          'content-type': 'application/json',
          'content-length': String(wire.length),
          ...headers,
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        let size = 0;
        res.on('data', (b: Buffer) => {
          size += b.length;
          if (size > 65536) req.destroy(new StarterError('Unavailable'));
          else chunks.push(b);
        });
        res.on('error', reject);
        res.on('end', () => {
          try {
            const text = Buffer.concat(chunks).toString('utf8');
            result = {
              status: res.statusCode!,
              body: JSON.parse(text) as Record<string, unknown>,
              wire: text,
              bytes: size,
            };
          } catch (e) {
            reject(e);
          }
        });
      },
    );
    const timer = setTimeout(() => req.destroy(new StarterError('Unavailable')), 5000);
    req.once('error', reject);
    req.once('close', () => {
      clearTimeout(timer);
      if (result) resolve(result);
      else reject(new StarterError('Unavailable'));
    });
    req.end(wire);
  });
}
function input(
  config: StarterConfig,
  creds: RuntimeCredentials,
  label: Label,
  body?: string,
  sender?: string,
): SignedFakeSms {
  const b = config.bindings[0]!;
  const content =
    body ??
    (label === 'R'
      ? encodeRevisionCommand({
          schemaVersion: 1,
          kind: 'case.revise_investigation',
          expectedRevision: '0',
          request: { ...b.initialCase.request, newCheckIn: '2030-12-04' },
        })
      : label === 'T' || label === 'U'
        ? 'Please investigate the booking change.'
        : 'Continue this investigation ' + label + '.');
  return signFakeSms(
    {
      schemaVersion: 1,
      ...eventIds[label],
      senderId: sender ?? b.senderId,
      body: content,
      occurredAt: '2030-12-01T10:00:00.000Z',
    },
    Buffer.from(creds.providerHmac, 'base64url'),
    Math.floor(Date.now() / 1000),
    b.providerScope,
  );
}
async function acceptHttp(
  config: StarterConfig,
  creds: RuntimeCredentials,
  label: Label,
  body?: string,
  sender?: string,
) {
  const signed = input(config, creds, label, body, sender);
  return post(config.endpoints.gateway, '/webhooks/fake-sms', Buffer.from(signed.raw), {
    'x-p2-timestamp': signed.headers.timestamp,
    'x-p2-signature': signed.headers.signature,
  });
}
function prepared(message: StoredMessage, body?: string, operationKey?: string): PreparedDispatch {
  assert.equal(message.event.type, 'text.received');
  if (message.event.type !== 'text.received') throw new StarterError('Unavailable');
  const submission = {
    schemaVersion: 1 as const,
    kind: 'investigation' as const,
    operationKey: operationKey ?? message.operationKey,
    scope: {
      tenantId: message.event.accountScope!.tenantId,
      accountId: message.event.accountScope!.accountId,
    },
    caseId: message.event.caseId!,
    caseRevision: '1',
    conversationId: message.event.conversationId,
    message: {
      receiptId: message.receipt.receiptId,
      eventId: message.event.eventId,
      messageId: message.event.messageId,
      senderId: message.event.senderId,
      body: body ?? message.event.body,
    },
  };
  const canonicalPayload = JSON.stringify(submission);
  return { submission, canonicalPayload, payloadDigest: sha(canonicalPayload) };
}
async function externalReceipt(client: ExternalOperationClient, message: StoredMessage) {
  const p = prepared(message);
  const r = await client.lookup(
    {
      operationKey: p.submission.operationKey,
      scope: p.submission.scope,
      payloadDigest: p.payloadDigest,
    },
    new AbortController().signal,
  );
  assert.equal(r.status, 'accepted');
  return r;
}
function appClosed(app: StandaloneApplication) {
  same(app.metrics(), {
    commandsActive: 0,
    retainedGraphs: 0,
    gatewayActive: false,
    closing: true,
  });
}
async function usingApp<T>(
  config: StarterConfig,
  creds: RuntimeCredentials,
  fn: (app: StandaloneApplication) => Promise<T>,
): Promise<T> {
  const app = createStandaloneApplication(config, creds);
  let primary: unknown, value: T | undefined;
  try {
    value = await fn(app);
  } catch (e) {
    primary = e;
  } finally {
    try {
      await app.close();
      appClosed(app);
    } catch (e) {
      primary ??= e;
    }
  }
  if (primary) throw primary;
  return value as T;
}
async function pages(app: StandaloneApplication) {
  const result: Awaited<ReturnType<StandaloneApplication['history']>>[] = [];
  let after = '0';
  for (let n = 0; n < 4; n++) {
    const page = await app.history('primary', { after, limit: 2 });
    result.push(page);
    if (!page.nextCursor) return result;
    assert.ok(BigInt(page.nextCursor) > BigInt(after));
    after = page.nextCursor;
  }
  throw new StarterError('Unavailable');
}
async function allMessages(app: StandaloneApplication) {
  return (await pages(app)).flatMap((p) => p.messages);
}
async function waitDispatched(app: StandaloneApplication, receipt: string) {
  let value = await app.processing('primary', receipt);
  await until(async () => {
    value = await app.processing('primary', receipt);
    return value.state === 'dispatched';
  });
  return value;
}

type Held = {
  path: string;
  request: string;
  requestDigest: string;
  requestBytes: number;
  response: string;
  responseDigest: string;
  responseBytes: number;
  httpStatus: number;
};
/** Gate-owned bounded relay. No workflow state; upstream is fixed configured loopback. */
class Relay {
  readonly records: Held[] = [];
  readonly calls: {
    path: string;
    requestDigest: string | null;
    responseDigest: string | null;
    httpStatus: number | null;
  }[] = [];
  readonly #sockets = new Set<Socket>();
  readonly #requests = new Set<ClientRequest>();
  readonly #tasks = new Set<Promise<void>>();
  readonly #holds = new Map<string, ReturnType<typeof deferred>>();
  readonly #entries = new Map<string, ReturnType<typeof deferred>>();
  #closing = false;
  #port = 0;
  readonly #server = createServer({ maxHeaderSize: 4096 }, (req, res) => {
    if (this.#closing || this.#tasks.size >= 4) {
      req.destroy();
      return;
    }
    const actual = this.#handle(req, res);
    this.#tasks.add(actual);
    void actual.then(
      () => this.#tasks.delete(actual),
      () => {
        this.#tasks.delete(actual);
        res.destroy();
      },
    );
  });
  constructor(
    readonly upstream: number,
    hold = true,
  ) {
    if (hold)
      for (const p of ['/v1/investigations/accept', '/v1/sms/send', '/v1/idempotent-sms/send']) {
        this.#holds.set(p, deferred());
        this.#entries.set(p, deferred());
      }
    this.#server.maxConnections = 8;
    this.#server.setTimeout(3000, (s) => s.destroy());
    this.#server.on('connection', (s) => {
      this.#sockets.add(s);
      s.once('close', () => this.#sockets.delete(s));
    });
    this.#server.on('clientError', (_e, s) => s.destroy());
  }
  async start() {
    await new Promise<void>((r, bad) => {
      this.#server.once('error', bad);
      this.#server.listen(0, '127.0.0.1', () => {
        this.#server.off('error', bad);
        r();
      });
    });
    const a = this.#server.address();
    assert.ok(a && typeof a !== 'string');
    this.#port = a.port;
    return a.port;
  }
  entered(path: string) {
    return this.#entries.get(path)!.promise;
  }
  release(path: string) {
    this.#holds.get(path)?.release();
  }
  async #handle(req: import('node:http').IncomingMessage, res: ServerResponse) {
    assert.ok(this.calls.length < 8);
    const observed = {
      path: req.url ?? '',
      requestDigest: null as string | null,
      responseDigest: null as string | null,
      httpStatus: null as number | null,
    };
    this.calls.push(observed); // Count actual ingress before any body/upstream await.
    assert.equal(req.method, 'POST');
    assert.equal(req.headers.host, '127.0.0.1:' + this.#port);
    assert.ok(
      [
        '/v1/investigations/accept',
        '/v1/investigations/lookup',
        '/v1/investigations/inspect-profile',
        '/v1/sms/send',
        '/v1/idempotent-sms/send',
        '/v1/idempotent-sms/lookup',
      ].includes(req.url!),
    );
    const chunks: Buffer[] = [];
    let bytes = 0;
    for await (const part of req) {
      const b = Buffer.from(part as Uint8Array);
      bytes += b.length;
      assert.ok(bytes <= 32768);
      chunks.push(b);
    }
    const raw = Buffer.concat(chunks);
    const upstream = await post(this.upstream, req.url!, raw, {
      authorization: String(req.headers.authorization),
    });
    observed.requestDigest = sha(raw);
    observed.responseDigest = sha(upstream.wire);
    observed.httpStatus = upstream.status;
    const held = this.#holds.get(req.url!);
    if (held && upstream.status === 200) {
      this.records.push({
        path: req.url!,
        request: raw.toString('utf8'),
        requestDigest: sha(raw),
        requestBytes: raw.length,
        response: upstream.wire,
        responseDigest: sha(upstream.wire),
        responseBytes: upstream.bytes,
        httpStatus: upstream.status,
      });
      this.#entries.get(req.url!)!.release();
      await held.promise;
    }
    if (!res.destroyed) {
      res.writeHead(upstream.status, {
        'content-type': 'application/json',
        'content-length': upstream.bytes,
        connection: 'close',
        ...(!req.url!.includes('sms/') ? { 'cache-control': 'no-store' } : {}),
      });
      res.end(upstream.wire);
    }
  }
  async close() {
    this.#closing = true;
    for (const h of this.#holds.values()) h.release();
    const closed = new Promise<void>((r, bad) => this.#server.close((e) => (e ? bad(e) : r())));
    for (const r of this.#requests) r.destroy();
    for (const s of this.#sockets) s.destroy();
    await Promise.allSettled([...this.#tasks]);
    await closed;
    assert.equal(this.#tasks.size, 0);
    assert.equal(this.#sockets.size, 0);
  }
}

type Setup = {
  schemaVersion: 1;
  owner: string;
  initialCase: unknown;
  association: { challengeId: string; associationVersion: string };
  messages: StoredMessage[];
  route: unknown;
  afterCase: unknown;
};
type Ack = {
  schemaVersion: 1;
  owner: string;
  httpStatus: number;
  receipt: StoredMessage['receipt'];
  message: StoredMessage;
};
type Begin = {
  schemaVersion: 1;
  owner: string;
  message: StoredMessage;
  operationOutcome: Readonly<{ ok: false; code: 'DispatchUnavailable' }>;
  dispatch: unknown;
  ordinary: OutboxObservation;
  idempotent: OutboxObservation;
  relay: Held[];
  outcomes: unknown[];
};
const configPath = required('P2_STARTER_CONFIG'),
  credentialsPath = required('P2_STARTER_CREDENTIALS');
let stage = 'configuration';
async function main() {
  if (mode === 'p1-contract')
    return runP1Contract(configPath, credentialsPath, (value) => {
      stage = value;
    });
  const config = parseConfig(readPrivateJson(configPath)),
    creds = parseCredentials(readPrivateJson(credentialsPath), config);
  assert.equal(creds.role, 'runtime');
  if (creds.role !== 'runtime') throw new StarterError('AccessDenied');
  assert.equal(config.profileId.replaceAll('-', ''), owner);
  assert.equal(config.bindings.length, 1);
  assert.equal(config.bindings[0]!.alias, 'primary');
  const binding = config.bindings[0]!;
  if (mode === 'config-negative') {
    stage = 'invalid-config';
    assert.throws(() => parseConfig({ ...config, unknown: true }));
    assert.throws(() =>
      parseConfig({ ...config, postgres: { ...config.postgres, host: 'example.com' } }),
    );
    assert.throws(() => parseCredentials({ ...creds, profileId: uuid('foreign') }, config));
    assert.throws(() => createStandaloneOwner(config, creds));
    let invoked = 0;
    const evil = { ...config };
    Object.defineProperty(evil, 'profileId', {
      enumerable: true,
      get() {
        invoked++;
        return config.profileId;
      },
    });
    assert.throws(() => parseConfig(evil));
    assert.equal(invoked, 0);
    return {
      schemaVersion: 1,
      owner,
      mode,
      rejections: 5,
      setupStarted: false,
      providersInvoked: false,
    };
  }
  if (mode === 'setup')
    return usingApp(config, creds, async (app) => {
      stage = 'association';
      const initialCase = await app.currentCase('primary');
      assert.equal(initialCase.revision, '0');
      const challenge = await app.challenge('primary');
      const link = signFakeSms(
        {
          schemaVersion: 1,
          eventId: 'link_' + owner,
          messageId: 'link_message_' + owner,
          senderId: binding.senderId,
          body: `LINK ${challenge.challengeId} ${challenge.secret}`,
          occurredAt: '2030-12-01T09:00:00.000Z',
        },
        Buffer.from(creds.providerHmac, 'base64url'),
        Math.floor(Date.now() / 1000),
        binding.providerScope,
      );
      const association = await app.associate(link.raw, link.headers);
      assert.equal(association.associationVersion, '1');
      const signedR = input(config, creds, 'R'),
        signedT = input(config, creds, 'T');
      const r = await app.accept(signedR.raw, signedR.headers),
        t = await app.accept(signedT.raw, signedT.headers);
      const messages = [
        await app.inspect('primary', r.receipt.receiptId),
        await app.inspect('primary', t.receipt.receiptId),
      ];
      stage = 'route';
      const route = await app.route('primary', r.receipt.receiptId);
      assert.equal(route.status, 'revised');
      const stale = await app.route('primary', r.receipt.receiptId);
      assert.equal(stale.status, 'revision_conflict');
      const plain = await app.route('primary', t.receipt.receiptId);
      assert.equal(plain.status, 'clarification_required');
      assert.throws(
        () => app.inspect('foreign', r.receipt.receiptId),
        (e) => safeStarterCode(e) === 'AccessDenied',
      );
      const unlinked = input(config, creds, 'K', undefined, 'unlinked_' + owner);
      await expectCode(app.accept(unlinked.raw, unlinked.headers), 'AssociationRequired');
      const afterCase = await app.currentCase('primary');
      assert.equal(afterCase.revision, '1');
      assert.equal(afterCase.cancelled, false);
      assert.equal(afterCase.committed, false);
      const value: Setup = {
        schemaVersion: 1,
        owner,
        initialCase,
        association: {
          challengeId: challenge.challengeId,
          associationVersion: association.associationVersion,
        },
        messages,
        route,
        afterCase,
      };
      proof('starter-setup.json', value);
      return {
        schemaVersion: 1,
        owner,
        mode,
        stale,
        plain,
        foreignDenied: true,
        unlinkedDenied: true,
      };
    });
  if (mode === 'gateway-a') {
    stage = 'gateway';
    const hold = deferred();
    const app = createStandaloneApplication(config, creds, {
      harnessAfterAcknowledgement: async () => {
        publish('starter_ack_flushed');
        await hold.promise;
      },
    });
    let primary: unknown;
    const stopped = deferred();
    const stop = () => {
      hold.release();
      stopped.release();
    };
    process.once('SIGTERM', stop);
    process.once('SIGINT', stop);
    try {
      const endpoint = await app.startGateway();
      writePrivateJson(join(work, 'starter-gateway-a-ready.json'), {
        schemaVersion: 1,
        owner,
        pid: process.pid,
        kind: 'gateway',
        profileId: config.profileId,
        ...endpoint,
      });
      publish('starter_gateway_a_ready');
      await stopped.promise;
    } catch (e) {
      primary = e;
    } finally {
      stop();
      process.off('SIGTERM', stop);
      process.off('SIGINT', stop);
      try {
        await app.close();
        appClosed(app);
      } catch (e) {
        primary ??= e;
      }
    }
    if (primary) throw primary;
    return {
      schemaVersion: 1,
      owner,
      mode,
      metrics: app.metrics(),
      gatewayMetrics: app.gatewayMetrics(),
    };
  }
  if (mode === 'baseline-client')
    return usingApp(config, creds, async (app) => {
      stage = 'baseline';
      const setup = load<Setup>('starter-setup.json'),
        dispatches = [];
      for (const m of setup.messages)
        dispatches.push(await waitDispatched(app, m.receipt.receiptId));
      const replay = await acceptHttp(config, creds, 'T');
      assert.equal(replay.status, 200);
      assert.equal(replay.body.replayed, true);
      same(replay.body.receipt, setup.messages[1]!.receipt);
      const conflict = await acceptHttp(config, creds, 'T', 'changed retained text');
      assert.equal(conflict.status, 409);
      const unknown = await acceptHttp(config, creds, 'K', undefined, 'unlinked_' + owner);
      assert.equal(unknown.status, 401);
      // Cross-process serve mutex blocks route/second serve, even with valid credentials.
      await expectCode(
        app.route('primary', setup.messages[0]!.receipt.receiptId),
        'ApplicationBusy',
      );
      const second = createStandaloneApplication(config, creds);
      try {
        await expectCode(second.startGateway(), 'ApplicationBusy');
      } finally {
        await second.close();
        appClosed(second);
      }
      const messages = await allMessages(app),
        client = new ExternalOperationClient(config, creds);
      try {
        const externalReceipts = [];
        for (const m of messages) externalReceipts.push(await externalReceipt(client, m));
        const historyPages = await pages(app);
        proof('starter-baseline.json', {
          schemaVersion: 1,
          owner,
          messages,
          dispatches,
          externalReceipts,
          historyPages,
          replay: replay.body,
          conflictStatus: conflict.status,
          foreignStatus: unknown.status,
        });
      } finally {
        await client.close();
      }
      return {
        schemaVersion: 1,
        owner,
        mode,
        messages: messages.length,
        dispatched: dispatches.length,
      };
    });
  if (mode === 'ack-client')
    return usingApp(config, creds, async (app) => {
      stage = 'ack';
      const response = await acceptHttp(config, creds, 'K');
      assert.equal(response.status, 200);
      assert.equal(response.body.replayed, false);
      const receipt = response.body.receipt as StoredMessage['receipt'];
      const message = await app.inspect('primary', receipt.receiptId);
      assert.equal(message.processingState, 'pending');
      const value: Ack = { schemaVersion: 1, owner, httpStatus: response.status, receipt, message };
      proof('starter-ack.json', value);
      return { schemaVersion: 1, owner, mode, receiptId: receipt.receiptId };
    });
  if (mode === 'before-restart')
    return usingApp(config, creds, async (app) => {
      stage = 'before-restart';
      const ack = load<Ack>('starter-ack.json'),
        message = await app.inspect('primary', ack.receipt.receiptId),
        dispatch = await app.processing('primary', ack.receipt.receiptId);
      same(message, ack.message);
      assert.equal(dispatch.state, 'pending');
      assert.equal(dispatch.possibleExternal, false);
      const p = prepared(message),
        client = new ExternalOperationClient(config, creds);
      try {
        const lookup = await client.lookup(
          {
            operationKey: message.operationKey,
            scope: binding.accountScope,
            payloadDigest: p.payloadDigest,
          },
          new AbortController().signal,
        );
        assert.equal(lookup.status, 'absent');
        proof('starter-before-restart.json', {
          schemaVersion: 1,
          owner,
          message,
          dispatch,
          lookup,
        });
      } finally {
        await client.close();
      }
      return { schemaVersion: 1, owner, mode, originalPending: true };
    });
  if (mode === 'later-input')
    return usingApp(config, creds, async (app) => {
      stage = 'recovered';
      const ack = load<Ack>('starter-ack.json'),
        dispatch = await waitDispatched(app, ack.receipt.receiptId);
      const replay = await acceptHttp(config, creds, 'K');
      assert.equal(replay.status, 200);
      same(replay.body.receipt, ack.receipt);
      const response = await acceptHttp(config, creds, 'U');
      assert.equal(response.status, 200);
      assert.equal(response.body.replayed, false);
      const receipt = response.body.receipt as StoredMessage['receipt'],
        laterDispatch = await waitDispatched(app, receipt.receiptId),
        originalMessage = await app.inspect('primary', ack.receipt.receiptId),
        laterMessage = await app.inspect('primary', receipt.receiptId);
      const prior = load<Setup>('starter-setup.json').messages[1]!;
      assert.equal(laterMessage.event.type, 'text.received');
      assert.equal(prior.event.type, 'text.received');
      if (laterMessage.event.type === 'text.received' && prior.event.type === 'text.received')
        assert.equal(laterMessage.event.body, prior.event.body);
      assert.notEqual(laterMessage.operationKey, prior.operationKey);
      const client = new ExternalOperationClient(config, creds);
      try {
        const external = await externalReceipt(client, originalMessage),
          laterExternal = await externalReceipt(client, laterMessage);
        proof('starter-recovered.json', {
          schemaVersion: 1,
          owner,
          originalMessage,
          replayedReceipt: replay.body.receipt,
          dispatch,
          externalReceipt: external,
          laterMessage,
          laterDispatch,
          laterExternal,
        });
      } finally {
        await client.close();
      }
      return { schemaVersion: 1, owner, mode, knownOriginal: true, usefulNewInput: true };
    });
  if (mode === 'delivery-begin') {
    stage = 'delivery-operation';
    const relay = new Relay(config.endpoints.external);
    let app: StandaloneApplication | undefined, primary: unknown, result: unknown;
    let operationOutcome: Readonly<{ ok: false; code: 'DispatchUnavailable' }> | undefined;
    try {
      const relayPort = await relay.start(),
        through = parseConfig({
          ...config,
          endpoints: { ...config.endpoints, external: relayPort },
        });
      app = createStandaloneApplication(through, creds);
      const v = input(config, creds, 'V'),
        accepted = await app.accept(v.raw, v.headers),
        message = await app.inspect('primary', accepted.receipt.receiptId);
      const dispatchCaller = app.dispatch('primary', message.receipt.receiptId),
        dispatchOutcome = observe(dispatchCaller);
      try {
        await entry(relay.entered('/v1/investigations/accept'), dispatchCaller);
        proof('starter-external-held.json', {
          schemaVersion: 1,
          owner,
          message,
          record: relay.records[0],
        });
        publish('starter_external_committed');
        await until(() => released('starter_external_committed'));
        const outcome = await dispatchOutcome;
        assert.ok(!outcome.ok && outcome.code === 'DispatchUnavailable');
        operationOutcome = { ok: outcome.ok, code: outcome.code };
      } finally {
        relay.release('/v1/investigations/accept');
        await dispatchOutcome;
      }
      const dispatch = await app.processing('primary', message.receipt.receiptId);
      assert.equal(dispatch.state, 'uncertain');
      assert.equal(dispatch.possibleExternal, true);
      assert.equal(dispatch.externalReceiptId, null);
      stage = 'delivery-carriers';
      const route = await app.selectRoute('primary', {
        senderId: binding.senderId,
        associationVersion: '1',
        expectedRouteVersion: '0',
      });
      assert.equal(route.version, '1');
      const outcomes: unknown[] = [];
      for (const kind of ['ordinary', 'idempotent'] as const) {
        await app.reply('primary', {
          schemaVersion: 1,
          outboundId: fixed.outbound[kind],
          responseId: fixed.responses[kind],
          body: 'Scripted investigation reply ' + kind + '.',
        });
        const controller = new AbortController(),
          path = kind === 'ordinary' ? '/v1/sms/send' : '/v1/idempotent-sms/send';
        const caller: Promise<SendOutcome> = app.send(
          'primary',
          fixed.outbound[kind],
          kind === 'ordinary' ? 'ordinary_fake_sms_v1' : 'idempotent_fake_sms_v1',
          controller.signal,
        );
        const outcome = observe<SendOutcome>(caller);
        try {
          await entry(relay.entered(path), caller);
          controller.abort();
          const value = await outcome;
          assert.ok(
            (!value.ok && value.code === 'OutcomeUnknown') ||
              (value.ok && value.value.status === 'unknown'),
          );
          outcomes.push(value);
        } finally {
          controller.abort();
          relay.release(path);
          await outcome;
        }
      }
      const ordinary = await app.inspectReply('primary', fixed.outbound.ordinary),
        idempotent = await app.inspectReply(
          'primary',
          fixed.outbound.idempotent,
          'idempotent_fake_sms_v1',
        );
      assert.equal(ordinary.state, 'unknown');
      assert.equal(idempotent.state, 'unknown');
      result = {
        schemaVersion: 1,
        owner,
        message,
        operationOutcome,
        dispatch,
        ordinary,
        idempotent,
        relay: relay.records,
        outcomes,
      };
      proof('starter-unknown.json', result);
      publish('starter_external_unknown');
      await until(() => released('starter_external_unknown'));
    } catch (e) {
      primary = e;
    } finally {
      for (const p of ['/v1/investigations/accept', '/v1/sms/send', '/v1/idempotent-sms/send'])
        relay.release(p);
      let appClosedOk = !app;
      try {
        await app?.close();
        if (app) appClosed(app);
        appClosedOk = true;
      } catch (e) {
        primary ??= e;
      }
      if (appClosedOk)
        try {
          await relay.close();
        } catch (e) {
          primary ??= e;
        }
    }
    if (primary) throw primary;
    return {
      schemaVersion: 1,
      owner,
      mode,
      operationUnknown: true,
      carrierUnknown: 2,
      physicalCalls: relay.records.length,
    };
  }
  if (mode === 'delivery-recovery')
    return usingApp(config, creds, async (app) => {
      stage = 'recovery';
      const begin = load<Begin>('starter-unknown.json'),
        step = await app.dispatch('primary', begin.message.receipt.receiptId, true);
      assert.equal(step.status, 'dispatched');
      if (step.status === 'dispatched') assert.equal(step.reconciled, true);
      const ordinaryAttempt = begin.ordinary.attempts[0]!,
        idempotentAttempt = begin.idempotent.attempts[0]!;
      const recoveries: RecoveryCommandView[] = [];
      recoveries.push(
        await app.reconcile('primary', 'ordinary_fake_sms_v1', {
          commandId: fixed.recovery.ordinary,
          outboundId: fixed.outbound.ordinary,
          attemptId: ordinaryAttempt.request.attemptId,
        }),
      );
      recoveries.push(
        await app.retry('primary', 'ordinary_fake_sms_v1', {
          commandId: fixed.recovery.ordinaryRetry,
          outboundId: fixed.outbound.ordinary,
          expectedAttemptId: ordinaryAttempt.request.attemptId,
        }),
      );
      recoveries.push(
        await app.reconcile('primary', 'idempotent_fake_sms_v1', {
          commandId: fixed.recovery.idempotent,
          outboundId: fixed.outbound.idempotent,
          attemptId: idempotentAttempt.request.attemptId,
        }),
      );
      assert.equal(recoveries[0]!.receipt.code, 'ordinary_no_resend');
      assert.equal(recoveries[1]!.receipt.code, 'ordinary_no_resend');
      assert.equal(recoveries[2]!.observation?.state, 'accepted_by_provider');
      const idempotent = await app.inspectReply(
          'primary',
          fixed.outbound.idempotent,
          'idempotent_fake_sms_v1',
        ),
        ordinary = await app.inspectReply('primary', fixed.outbound.ordinary);
      assert.equal(ordinary.attempts.length, 1);
      assert.equal(idempotent.attempts.length, 1);
      const upstream = begin.relay.find((r) => r.path === '/v1/sms/send')!,
        response = JSON.parse(upstream.response) as { result: { providerMessageId: string } };
      const callback = (which: 'delivered' | 'sent'): CallbackObservation => ({
        schemaVersion: 1,
        eventId: fixed.callbacks[which],
        attemptId: ordinaryAttempt.request.attemptId,
        providerOperationKey: ordinaryAttempt.request.providerOperationKey,
        requestDigest: ordinaryAttempt.requestDigest,
        providerMessageId: response.result.providerMessageId,
        state: which === 'sent' ? 'accepted_by_provider' : 'delivered',
        occurredAt: which === 'sent' ? '2030-12-01T10:00:01.000Z' : '2030-12-01T10:00:02.000Z',
      });
      const callbacks = [];
      for (const which of ['delivered', 'sent', 'delivered'] as const) {
        const signed = signFakeSmsCallback(
          callback(which),
          Buffer.from(creds.callbackHmac, 'base64url'),
          Math.floor(Date.now() / 1000),
          binding.providerScope,
        );
        callbacks.push(await app.callback(signed.raw, signed.headers));
      }
      same(callbacks[0], callbacks[2]);
      const callbackFacts = await app.inspectCallbacks(
        'primary',
        ordinary.receipt.outboundId,
        ordinaryAttempt.request.attemptId,
      );
      assert.equal(callbackFacts.observations.length, 2);
      assert.equal(callbackFacts.evidence.strongestReported, 'delivered');
      const replayProof = await replayRecoveries(
        config,
        creds,
        ordinaryAttempt.request.attemptId,
        idempotentAttempt.request.attemptId,
      );
      const replayedRecoveries = replayProof.commands;
      same(replayedRecoveries, recoveries);
      proof('starter-delivery.json', {
        schemaVersion: 1,
        owner,
        operation: step,
        ordinary,
        idempotent,
        callbacks,
        callbackFacts,
        recoveries,
        replayedRecoveries,
        providerCalls: replayProof.providerCalls,
      });
      stage = 'capacity';
      await capacity(config, creds, begin.message);
      stage = 'original';
      const facts = await collect(app, config, creds);
      proof('starter-original.json', { schemaVersion: 1, owner, ...facts });
      return {
        schemaVersion: 1,
        owner,
        mode,
        dispatchReconciled: true,
        recoveryCommands: recoveries.length,
        callbacks: callbacks.length,
      };
    });
  if (mode === 'fresh-verify')
    return usingApp(config, creds, async (app) => {
      stage = 'fresh';
      const original = load<Record<string, unknown>>('starter-original.json');
      const facts = await collect(app, config, creds);
      same({ schemaVersion: 1, owner, ...facts }, original);
      proof('starter-fresh.json', { schemaVersion: 1, owner, facts, metrics: app.metrics() });
      return { schemaVersion: 1, owner, mode, originalFacts: true, groups: STARTER_GROUPS };
    });
  if (mode === 'restore-verify') {
    // Explicit test-only dual role: this actor receives the separately validated
    // external credential file; runtime credentials are never promoted.
    const external = parseCredentials(
      readPrivateJson(required('P2_STARTER_EXTERNAL_CREDENTIALS')),
      config,
    );
    assert.equal(external.role, 'external');
    if (external.role !== 'external') throw new StarterError('AccessDenied');
    const server = new ExternalHttpServer(config, external),
      app = createStandaloneApplication(config, creds);
    let primary: unknown,
      facts: Awaited<ReturnType<typeof collect>> | undefined,
      dependentClosed = false;
    try {
      stage = 'fresh';
      await server.start();
      facts = await collect(app, config, creds);
      same(
        { schemaVersion: 1, owner, ...facts },
        load<Record<string, unknown>>('starter-original.json'),
      );
    } catch (e) {
      primary = e;
    } finally {
      try {
        await app.close();
        appClosed(app);
        dependentClosed = true;
      } catch (e) {
        primary ??= e;
      }
      if (dependentClosed)
        try {
          await server.close();
        } catch (e) {
          primary ??= e;
        }
    }
    if (primary) throw primary;
    const externalMetrics = server.metrics();
    same(externalMetrics, {
      started: 5,
      known: 5,
      rejected: 0,
      active: 0,
      sockets: 0,
      closing: true,
      profileReads: 0,
    });
    const metrics = { application: app.metrics(), external: externalMetrics };
    proof('starter-restored.json', { schemaVersion: 1, owner, facts, metrics });
    return { schemaVersion: 1, owner, mode, originalFacts: true, groups: STARTER_GROUPS, metrics };
  }
  throw new StarterError('InvalidCommand');
}
async function collect(
  app: StandaloneApplication,
  config: StarterConfig,
  creds: RuntimeCredentials,
) {
  const historyPages = await pages(app),
    messages = historyPages.flatMap((p) => p.messages);
  assert.equal(messages.length, 5);
  const cases = [await app.currentCase('primary')],
    dispatches = [];
  for (const m of messages) dispatches.push(await app.processing('primary', m.receipt.receiptId));
  assert.ok(dispatches.every((d) => d.state === 'dispatched'));
  const replies = [
    await app.inspectReply('primary', fixed.outbound.ordinary),
    await app.inspectReply('primary', fixed.outbound.idempotent, 'idempotent_fake_sms_v1'),
  ];
  const callbacks = [
    await app.inspectCallbacks(
      'primary',
      fixed.outbound.ordinary,
      replies[0]!.attempts[0]!.request.attemptId,
    ),
  ];
  const recoveries = load<{ recoveries: RecoveryCommandView[] }>(
    'starter-delivery.json',
  ).recoveries; // Then actually replay/inspect every public command identity below.
  const replayProof = await replayRecoveries(
    config,
    creds,
    replies[0]!.attempts[0]!.request.attemptId,
    replies[1]!.attempts[0]!.request.attemptId,
  );
  const commands = replayProof.commands;
  same(commands, recoveries);
  const client = new ExternalOperationClient(config, creds);
  try {
    const externalReceipts = [];
    for (const m of messages) externalReceipts.push(await externalReceipt(client, m));
    return {
      cases,
      messages,
      dispatches,
      replies,
      callbacks,
      recoveries: commands,
      externalReceipts,
      historyPages,
      recoveryReplay: replayProof.providerCalls,
    };
  } finally {
    await client.close();
  }
}

async function replayRecoveries(
  config: StarterConfig,
  creds: RuntimeCredentials,
  ordinaryAttempt: string,
  idempotentAttempt: string,
) {
  const relay = new Relay(config.endpoints.external, false);
  let app: StandaloneApplication | undefined,
    primary: unknown,
    result:
      | {
          commands: RecoveryCommandView[];
          providerCalls: { before: number; after: number; requests: unknown[] };
        }
      | undefined;
  try {
    const port = await relay.start();
    app = createStandaloneApplication(
      parseConfig({ ...config, endpoints: { ...config.endpoints, external: port } }),
      creds,
    );
    const before = relay.calls.length;
    const commands = [
      await app.reconcile('primary', 'ordinary_fake_sms_v1', {
        commandId: fixed.recovery.ordinary,
        outboundId: fixed.outbound.ordinary,
        attemptId: ordinaryAttempt,
      }),
      await app.retry('primary', 'ordinary_fake_sms_v1', {
        commandId: fixed.recovery.ordinaryRetry,
        outboundId: fixed.outbound.ordinary,
        expectedAttemptId: ordinaryAttempt,
      }),
      await app.reconcile('primary', 'idempotent_fake_sms_v1', {
        commandId: fixed.recovery.idempotent,
        outboundId: fixed.outbound.idempotent,
        attemptId: idempotentAttempt,
      }),
    ];
    assert.equal(relay.calls.length, before);
    result = {
      commands,
      providerCalls: { before, after: relay.calls.length, requests: [...relay.calls] },
    };
  } catch (e) {
    primary = e;
  } finally {
    let dependentClosed = !app;
    try {
      await app?.close();
      if (app) appClosed(app);
      dependentClosed = true;
    } catch (e) {
      primary ??= e;
    }
    if (dependentClosed)
      try {
        await relay.close();
      } catch (e) {
        primary ??= e;
      }
  }
  if (primary) throw primary;
  return result!;
}

async function capacity(config: StarterConfig, creds: RuntimeCredentials, base: StoredMessage) {
  const b = config.bindings[0]!,
    auth = creds.externalBearers[0]!,
    client = new ExternalOperationClient(config, creds);
  const investigations: unknown[] = [],
    ordinary: unknown[] = [],
    idempotent: unknown[] = [];
  try {
    for (const [i, key] of fixed.probes.investigations.entries()) {
      const p = prepared(
        {
          ...base,
          operationKey: key,
          receipt: { ...base.receipt, receiptId: uuid('probe-receipt:' + i) },
        },
        i === 0 ? '\u0000'.repeat(4096) : i === 1 ? '' : 'capacity investigation ' + i,
        key,
      );
      const receipt = await client.accept(p, new AbortController().signal);
      investigations.push({ prepared: p, receipt });
    }
    const p = (investigations[0] as { prepared: PreparedDispatch }).prepared;
    const wire = (p: PreparedDispatch) =>
      Buffer.from(
        JSON.stringify({
          schemaVersion: 1,
          canonicalPayload: p.canonicalPayload,
          payloadDigest: p.payloadDigest,
        }),
      );
    const headers = { authorization: 'Bearer ' + auth.operation };
    const replay = await post(
      config.endpoints.external,
      '/v1/investigations/accept',
      wire(p),
      headers,
    );
    assert.equal(replay.status, 200);
    same(replay.body.receipt, (investigations[0] as { receipt: unknown }).receipt);
    const changed = prepared(base, 'changed capacity body', p.submission.operationKey);
    const conflict = await post(
      config.endpoints.external,
      '/v1/investigations/accept',
      wire(changed),
      headers,
    );
    assert.equal(conflict.status, 409);
    const extra = prepared(base, 'new overcapacity', uuid('over-investigation'));
    const overloaded = await post(
      config.endpoints.external,
      '/v1/investigations/accept',
      wire(extra),
      headers,
    );
    assert.equal(overloaded.status, 429);
    const makeSend = (key: string, body: string, kind: 'ordinary' | 'idempotent'): SendRequest => ({
      schemaVersion: 1,
      outboundId: key,
      responseId: 'probe_' + key,
      body,
      scope: b.accountScope,
      caseId: b.caseId,
      conversationId: b.conversationId,
      attemptId: uuid(kind + ':attempt:' + key),
      providerOperationKey: uuid(kind + ':operation:' + key),
      providerScope: b.providerScope,
      senderId: b.senderId,
      associationVersion: '1',
      routeVersion: '1',
    });
    const physical = {
      ...makeSend(fixed.probes.ordinaryPhysical.outboundId, 'ordinary physical repeat', 'ordinary'),
      ...fixed.probes.ordinaryPhysical,
    };
    const ordinaryClient = new FakeSmsSendClient(
        { host: '127.0.0.1', port: config.endpoints.external },
        'Bearer ' + auth.ordinary,
        b.providerScope,
      ),
      idempotentClient = new IdempotentFakeSmsClient(
        { host: '127.0.0.1', port: config.endpoints.external },
        'Bearer ' + auth.idempotent,
        b.providerScope,
      );
    try {
      const repeated = [
        await ordinaryClient.send(physical, new AbortController().signal),
        await ordinaryClient.send(physical, new AbortController().signal),
      ];
      assert.ok(
        repeated[0]!.status === 'accepted_by_provider' &&
          repeated[1]!.status === 'accepted_by_provider',
      );
      if (
        repeated[0]!.status === 'accepted_by_provider' &&
        repeated[1]!.status === 'accepted_by_provider'
      )
        assert.notEqual(repeated[0]!.providerMessageId, repeated[1]!.providerMessageId);
      for (const key of fixed.probes.ordinary) {
        const request = makeSend(key, 'ordinary capacity ' + key, 'ordinary');
        ordinary.push({
          request,
          result: await ordinaryClient.send(request, new AbortController().signal),
        });
      }
      for (const key of fixed.probes.idempotent) {
        const request = makeSend(key, 'idempotent capacity ' + key, 'idempotent');
        idempotent.push({
          request,
          result: await idempotentClient.send(request, new AbortController().signal),
        });
      }
      const first = (idempotent[0] as { request: SendRequest }).request;
      const iReplay = await idempotentClient.send(first, new AbortController().signal);
      same(iReplay, (idempotent[0] as { result: unknown }).result);
      const operation = {
        schemaVersion: 1,
        capability: 'idempotent_fake_sms_v1',
        providerScope: first.providerScope,
        scope: first.scope,
        caseId: first.caseId,
        conversationId: first.conversationId,
        outboundId: first.outboundId,
        responseId: first.responseId,
        providerOperationKey: first.providerOperationKey,
        senderId: first.senderId,
        body: first.body,
      };
      const changedOperation = { ...operation, body: operation.body + ' changed' },
        digest = sha(JSON.stringify(changedOperation));
      const changedRequest = { ...first, body: changedOperation.body };
      const iConflict = await post(
        config.endpoints.external,
        '/v1/idempotent-sms/send',
        Buffer.from(
          JSON.stringify({
            schemaVersion: 1,
            operation: changedOperation,
            operationDigest: digest,
            attempt: {
              attemptId: first.attemptId,
              requestDigest: sha(JSON.stringify(changedRequest)),
              associationVersion: '1',
              routeVersion: '1',
            },
          }),
        ),
        { authorization: 'Bearer ' + auth.idempotent },
      );
      assert.equal(iConflict.status, 409);
      const iExtra = makeSend(uuid('idempotent-over'), 'new idempotent overcapacity', 'idempotent');
      const extraOp = {
        ...operation,
        outboundId: iExtra.outboundId,
        responseId: iExtra.responseId,
        providerOperationKey: iExtra.providerOperationKey,
        body: iExtra.body,
      };
      const iOver = await post(
        config.endpoints.external,
        '/v1/idempotent-sms/send',
        Buffer.from(
          JSON.stringify({
            schemaVersion: 1,
            operation: extraOp,
            operationDigest: sha(JSON.stringify(extraOp)),
            attempt: {
              attemptId: iExtra.attemptId,
              requestDigest: sha(JSON.stringify(iExtra)),
              associationVersion: '1',
              routeVersion: '1',
            },
          }),
        ),
        { authorization: 'Bearer ' + auth.idempotent },
      );
      assert.equal(iOver.status, 429);
      const oOver = await post(
        config.endpoints.external,
        '/v1/sms/send',
        Buffer.from(
          JSON.stringify(makeSend(uuid('ordinary-over'), 'new ordinary overcapacity', 'ordinary')),
        ),
        { authorization: 'Bearer ' + auth.ordinary },
      );
      assert.equal(oOver.status, 429);
      proof('starter-capacity.json', {
        schemaVersion: 1,
        owner,
        investigation: {
          rows: investigations,
          replay: replay.body,
          conflict: conflict.body,
          overloaded: overloaded.body,
        },
        idempotent: {
          rows: idempotent,
          replay: iReplay,
          conflict: iConflict.body,
          overloaded: iOver.body,
        },
        ordinary: { rows: ordinary, overloaded: oOver.body },
        ordinaryPhysicalProbe: { request: physical, results: repeated },
      });
    } finally {
      const closed = await Promise.allSettled([ordinaryClient.close(), idempotentClient.close()]);
      assert.ok(closed.every((r) => r.status === 'fulfilled'));
    }
  } finally {
    await client.close();
  }
}
void main().then(
  (value) => {
    writePrivateJson(required('P2_STARTER_OUTPUT'), value, MAX_PROOF);
    process.stdout.write(
      JSON.stringify({ schemaVersion: 1, status: 'passed', mode, cleanupComplete: true }) + '\n',
    );
  },
  (error) => {
    const failure = {
      schemaVersion: 1,
      status: 'failed',
      mode,
      stage:
        [
          'configuration',
          'invalid-config',
          'association',
          'route',
          'gateway',
          'baseline',
          'ack',
          'before-restart',
          'recovered',
          'delivery-operation',
          'delivery-carriers',
          'recovery',
          'capacity',
          'original',
          'fresh',
        ].includes(stage) ||
        (mode === 'p1-contract' && P1_CONTRACT_STAGES.some((value) => value === stage))
          ? stage
          : 'configuration',
      errorType:
        error instanceof StarterError
          ? 'StarterError'
          : error instanceof assert.AssertionError
            ? 'AssertionError'
            : 'UnexpectedError',
      code: code(error),
      cleanupComplete: false,
    };
    try {
      writePrivateJson(required('P2_STARTER_OUTPUT'), failure, 2048);
    } catch {}
    process.stdout.write(JSON.stringify(failure) + '\n');
    process.exitCode = 1;
  },
);
