/** Explicit actual-P2 origin fixture. Imports perform no setup, environment read or listen. */
import assert from 'node:assert/strict';
import { createHash, randomUUID, timingSafeEqual } from 'node:crypto';
import {
  constants,
  closeSync,
  fstatSync,
  fsyncSync,
  linkSync,
  unlinkSync,
  lstatSync,
  openSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from 'node:fs';
import {
  createServer,
  request as httpRequest,
  type IncomingMessage,
  type ServerResponse,
} from 'node:http';
import type { Socket } from 'node:net';
import { isAbsolute, resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import pg from 'pg';
import {
  ChannelInbox,
  SeededAccounts,
  type DatabaseSettings,
} from '@livekit-ecosystem/channel-continuity/postgres';
import {
  createFakeSmsIntegration,
  signFakeSms,
} from '@livekit-ecosystem/channel-continuity/security';
import {
  NativeChannelInbox,
  createNativeIntegration,
} from '@livekit-ecosystem/channel-continuity/native';
import {
  ChannelDispatcher,
  type DispatchPorts,
  type OperationReceipt,
  type PreparedDispatch,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  CurrentCaseHttpClient,
  currentCase,
  type CurrentCaseReference,
} from '@livekit-ecosystem/channel-continuity/rehydration';
import {
  ExternalOperationClient,
  type OperationClientConfig,
} from '@livekit-ecosystem/channel-continuity/starter';
import { ChannelOutbox } from '@livekit-ecosystem/channel-continuity/outbox';
import {
  ChannelResultReceiver,
  ChannelResultReader,
  parseResultIntent,
  encodeResultIntent,
  type P1ResultIntent,
  resultReceipt,
  matchResultReceipt,
  type ResultNativeView,
} from '@livekit-ecosystem/channel-continuity/result-receiver';
import {
  installChannelSchema,
  upgradeChannelSchemaV2,
  upgradeChannelSchemaV3,
  upgradeChannelSchemaV4,
  upgradeChannelSchemaV5,
  upgradeChannelSchemaV6,
  upgradeChannelSchemaV7,
  upgradeChannelSchemaV8,
} from '@livekit-ecosystem/channel-continuity/migrations';

export const ORIGIN_MODES = [
  'setup',
  'race',
  'ack-caller',
  'reconcile',
  'negative',
  'result-host',
  'native-read',
  'cleanup',
] as const;
export type OriginMode = (typeof ORIGIN_MODES)[number];
const CODES = [
  'invalid_mode',
  'invalid_environment',
  'invalid_fixture',
  'unsafe_path',
  'invalid_proof',
  'deadline_exceeded',
  'component_failed',
  'cleanup_incomplete',
  'unexpected_outcome',
] as const;
type FixtureCode = (typeof CODES)[number];
export class OriginFixtureError extends Error {
  readonly code: FixtureCode;
  constructor(code: FixtureCode = 'component_failed') {
    const safe = CODES.includes(code) ? code : 'component_failed';
    super(safe);
    this.code = safe;
    this.name = 'OriginFixtureError';
  }
}
function fail(code: FixtureCode = 'invalid_fixture'): never {
  throw new OriginFixtureError(code);
}
function fields(value: unknown, names: readonly string[]): Record<string, unknown> {
  try {
    if (
      !value ||
      typeof value !== 'object' ||
      Array.isArray(value) ||
      ![Object.prototype, null].includes(Object.getPrototypeOf(value))
    )
      fail();
    const keys = Reflect.ownKeys(value);
    if (
      keys.length !== names.length ||
      keys.some((k) => typeof k !== 'string' || !names.includes(k))
    )
      fail();
    const out: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
    for (const k of names) {
      const d = Object.getOwnPropertyDescriptor(value, k);
      if (!d || !('value' in d) || !d.enumerable) fail();
      out[k] = d.value;
    }
    return out;
  } catch {
    return fail();
  }
}
const digest = (value: string | Buffer) => createHash('sha256').update(value).digest('hex');
const uuid = (value: unknown): string => {
  if (
    typeof value !== 'string' ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/.test(value)
  )
    fail();
  return value;
};
const id = (value: unknown): string => {
  if (typeof value !== 'string' || !/^[a-z][a-z0-9_-]{0,63}(?![\s\S])/.test(value)) fail();
  return value;
};
const p2id = (value: unknown): string => {
  if (typeof value !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}(?![\s\S])/.test(value))
    fail();
  return value;
};
const integer = (value: unknown, lo: number, hi: number): number => {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < lo || value > hi) fail();
  return value;
};
const token = (value: unknown): string => {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{43}(?![\s\S])/.test(value)) fail();
  return value;
};
const scope = (value: unknown) => {
  const x = fields(value, ['tenantId', 'accountId']);
  return Object.freeze({ tenantId: id(x.tenantId), accountId: id(x.accountId) });
};
const P = 'P2_ORIGIN_';
const TOKENS = [
  'ACCOUNT_TOKEN',
  'NATIVE_PUBLISHER_TOKEN',
  'PUBLISHER_TOKEN',
  'NATIVE_A_BEARER',
  'NATIVE_B_BEARER',
  'OPERATION_TOKEN',
] as const;
const BASE = ['PATH', 'LANG', 'CI', 'NO_COLOR', '__CF_USER_TEXT_ENCODING'] as const;
export type OriginEnvironment = Readonly<{
  mode: OriginMode;
  directory: string;
  schema: string;
  pgPort: number;
  ownerPassword?: string;
  runtimePassword?: string;
  tokens: Readonly<Record<(typeof TOKENS)[number], string>>;
  caseAuthorization: string;
}>;
export function parseEnvironment(mode: unknown, input: unknown): OriginEnvironment {
  try {
    if (typeof mode !== 'string' || !ORIGIN_MODES.includes(mode as OriginMode))
      throw new OriginFixtureError('invalid_mode');
    const m = mode as OriginMode,
      keys = [
        'DIRECTORY',
        'SCHEMA',
        'PG_PORT',
        ...TOKENS,
        'CASE_AUTHORIZATION',
        ...(m === 'setup' || m === 'cleanup' ? ['OWNER_PASSWORD'] : []),
        ...(m !== 'cleanup' ? ['RUNTIME_PASSWORD'] : []),
      ].map((k) => P + k);
    if (!input || typeof input !== 'object') fail();
    const own = Reflect.ownKeys(input);
    if (own.some((k) => typeof k !== 'string' || ![...BASE, ...keys].includes(k))) fail();
    // Node's process.env has a host-specific prototype. Validate its closed
    // own-key inventory before inspecting any value, then copy data descriptors
    // only. JSON fixture objects retain the stricter fields() boundary.
    const raw: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
    for (const k of own as string[]) {
      const descriptor = Object.getOwnPropertyDescriptor(input, k);
      if (!descriptor || !('value' in descriptor) || !descriptor.enumerable) fail();
      raw[k] = descriptor.value;
    }
    for (const k of keys) if (!Object.hasOwn(raw, k)) fail();
    for (const k of BASE)
      if (raw[k] !== undefined && (typeof raw[k] !== 'string' || (raw[k] as string).length > 4096))
        fail();
    if (
      raw.CI !== '1' ||
      raw.NO_COLOR !== '1' ||
      typeof raw.PATH !== 'string' ||
      !raw.PATH ||
      typeof raw.LANG !== 'string' ||
      !raw.LANG
    )
      fail();
    const directory = raw[P + 'DIRECTORY'];
    if (
      typeof directory !== 'string' ||
      !isAbsolute(directory) ||
      resolve(directory) !== directory ||
      directory.length > 4096 ||
      /[\u0000-\u001f\u007f]/.test(directory)
    )
      fail();
    const schema = raw[P + 'SCHEMA'];
    if (typeof schema !== 'string' || !/^p2_origin_[0-9a-f]{32}(?![\s\S])/.test(schema)) fail();
    const port = raw[P + 'PG_PORT'];
    if (typeof port !== 'string' || !/^[1-9][0-9]{0,4}(?![\s\S])/.test(port)) fail();
    const tokens = Object.fromEntries(TOKENS.map((k) => [k, token(raw[P + k])])) as Record<
      (typeof TOKENS)[number],
      string
    >;
    const authorization = raw[P + 'CASE_AUTHORIZATION'];
    if (
      typeof authorization !== 'string' ||
      !/^Bearer [A-Za-z0-9_-]{43}(?![\s\S])/.test(authorization)
    )
      fail();
    const password = (key: string) => {
      const s = raw[P + key];
      if (
        typeof s !== 'string' ||
        s.length < 16 ||
        s.length > 256 ||
        /[\u0000-\u001f\u007f]/.test(s)
      )
        fail();
      return s;
    };
    return Object.freeze({
      mode: m,
      directory,
      schema,
      pgPort: integer(Number(port), 1, 65535),
      ...(m === 'setup' || m === 'cleanup' ? { ownerPassword: password('OWNER_PASSWORD') } : {}),
      ...(m !== 'cleanup' ? { runtimePassword: password('RUNTIME_PASSWORD') } : {}),
      tokens: Object.freeze(tokens),
      caseAuthorization: authorization,
    });
  } catch (e) {
    throw new OriginFixtureError(
      safeCode(e) === 'invalid_mode' ? 'invalid_mode' : 'invalid_environment',
    );
  }
}
export type OriginFixture = Readonly<{
  schema_version: 1;
  scope: Readonly<{ tenantId: string; accountId: string }>;
  case_id: string;
  conversation_id: string;
  recipient_id: string;
  p2_schema: string;
  case_endpoint: Readonly<{ host: '127.0.0.1'; port: number }>;
  native_binding_ids: Readonly<{ a: string; b: string }>;
  parent_expires_at_ms: number;
}>;
export function parseFixture(
  value: unknown,
  env: OriginEnvironment,
  nowMs = Date.now(),
): OriginFixture {
  const x = fields(value, [
    'schema_version',
    'scope',
    'case_id',
    'conversation_id',
    'recipient_id',
    'p2_schema',
    'case_endpoint',
    'native_binding_ids',
    'parent_expires_at_ms',
  ]);
  const endpoint = fields(x.case_endpoint, ['host', 'port']),
    bindings = fields(x.native_binding_ids, ['a', 'b']);
  if (
    x.schema_version !== 1 ||
    x.p2_schema !== env.schema ||
    endpoint.host !== '127.0.0.1' ||
    bindings.a === bindings.b
  )
    fail();
  return Object.freeze({
    schema_version: 1,
    scope: scope(x.scope),
    case_id: id(x.case_id),
    conversation_id: id(x.conversation_id),
    recipient_id: id(x.recipient_id),
    p2_schema: env.schema,
    case_endpoint: Object.freeze({ host: '127.0.0.1', port: integer(endpoint.port, 1, 65535) }),
    native_binding_ids: Object.freeze({ a: uuid(bindings.a), b: uuid(bindings.b) }),
    parent_expires_at_ms: integer(x.parent_expires_at_ms, nowMs + 1, nowMs + 180000),
  });
}
export function parseReady(value: unknown) {
  const x = fields(value, ['schema_version', 'pid', 'host', 'port']);
  if (x.schema_version !== 1 || x.host !== '127.0.0.1') fail('invalid_proof');
  return Object.freeze({
    schema_version: 1 as const,
    pid: integer(x.pid, 2, 2147483647),
    host: '127.0.0.1' as const,
    port: integer(x.port, 1, 65535),
  });
}
type InputIdentity = Readonly<{ receiptId: string; operationKey: string }>;
type Setup = Readonly<{
  schema_version: 1;
  receiver_id: string;
  inputs: Readonly<{ original: InputIdentity; ack: InputIdentity }>;
}>;
export function parseSetup(value: unknown): Setup {
  const x = fields(value, ['schema_version', 'receiver_id', 'inputs']),
    inputs = fields(x.inputs, ['original', 'ack']);
  if (x.schema_version !== 1) fail('invalid_proof');
  const input = (v: unknown) => {
    const y = fields(v, ['receiptId', 'operationKey']);
    return Object.freeze({ receiptId: uuid(y.receiptId), operationKey: uuid(y.operationKey) });
  };
  const original = input(inputs.original),
    ack = input(inputs.ack);
  if (original.receiptId === ack.receiptId || original.operationKey === ack.operationKey)
    fail('invalid_proof');
  return Object.freeze({
    schema_version: 1,
    receiver_id: uuid(x.receiver_id),
    inputs: Object.freeze({ original, ack }),
  });
}
export function parsePrepared(value: unknown): PreparedDispatch {
  const x = fields(value, ['submission', 'canonicalPayload', 'payloadDigest']),
    s = fields(x.submission, [
      'schemaVersion',
      'kind',
      'operationKey',
      'scope',
      'caseId',
      'caseRevision',
      'conversationId',
      'message',
    ]),
    message = fields(s.message, ['receiptId', 'eventId', 'messageId', 'senderId', 'body']);
  if (
    s.schemaVersion !== 1 ||
    s.kind !== 'investigation' ||
    typeof s.caseRevision !== 'string' ||
    !/^[1-9][0-9]{0,18}(?![\s\S])/.test(s.caseRevision) ||
    BigInt(s.caseRevision) > 9223372036854775807n ||
    typeof message.body !== 'string' ||
    Buffer.byteLength(message.body) > 4096 ||
    Buffer.from(message.body).toString() !== message.body
  )
    fail('invalid_proof');
  const submission = Object.freeze({
    schemaVersion: 1 as const,
    kind: 'investigation' as const,
    operationKey: uuid(s.operationKey),
    scope: scope(s.scope),
    caseId: id(s.caseId),
    caseRevision: s.caseRevision,
    conversationId: id(s.conversationId),
    message: Object.freeze({
      receiptId: uuid(message.receiptId),
      eventId: p2id(message.eventId),
      messageId: p2id(message.messageId),
      senderId: p2id(message.senderId),
      body: message.body,
    }),
  });
  const canonicalPayload = JSON.stringify(submission);
  if (
    canonicalPayload !== x.canonicalPayload ||
    digest(canonicalPayload) !== x.payloadDigest ||
    Buffer.byteLength(canonicalPayload) > 32768 ||
    Buffer.byteLength(
      JSON.stringify({ schemaVersion: 1, canonicalPayload, payloadDigest: x.payloadDigest }),
    ) > 32768
  )
    fail('invalid_proof');
  return Object.freeze({ submission, canonicalPayload, payloadDigest: digest(canonicalPayload) });
}
const SAFE_CODES = new Set<string>([
  ...CODES,
  'InvalidCommand',
  'InvalidConfiguration',
  'AccessDenied',
  'IdentityConflict',
  'Overloaded',
  'Unavailable',
  'OutcomeUnknown',
  'AcknowledgementUnknown',
  'CleanupIncomplete',
  'Closed',
  'DispatchUnavailable',
  'StorageUnavailable',
  'OperationConflict',
  'NotFound',
  'invalid_input',
  'forbidden',
  'dependency_unavailable',
]);
export function safeCode(error: unknown): string {
  try {
    if (!error || typeof error !== 'object') return 'component_failed';
    const d = Object.getOwnPropertyDescriptor(error, 'code');
    return d && 'value' in d && typeof d.value === 'string' && SAFE_CODES.has(d.value)
      ? d.value
      : 'component_failed';
  } catch {
    return 'component_failed';
  }
}
export function isEntrypoint(url: string, argv: readonly string[]): boolean {
  return typeof argv[1] === 'string' && pathToFileURL(resolve(argv[1])).href === url;
}
function privateDirectory(directory: string): void {
  try {
    const s = lstatSync(directory);
    if (
      !s.isDirectory() ||
      s.isSymbolicLink() ||
      (s.mode & 0o777) !== 0o700 ||
      s.uid !== process.getuid?.() ||
      realpathSync(directory) !== directory
    )
      fail('unsafe_path');
  } catch {
    fail('unsafe_path');
  }
}
function proofPath(directory: string, name: string): string {
  if (typeof name !== 'string' || !/^[a-z][a-z0-9-]{0,90}\.json(?![\s\S])/.test(name))
    fail('unsafe_path');
  privateDirectory(directory);
  return join(directory, name);
}
export function proofPublished(directory: string, name: string): boolean {
  const path = proofPath(directory, name);
  let info: ReturnType<typeof lstatSync>;
  try {
    info = lstatSync(path);
  } catch (error) {
    const d =
      error && typeof error === 'object'
        ? Object.getOwnPropertyDescriptor(error, 'code')
        : undefined;
    if (d && 'value' in d && d.value === 'ENOENT') return false;
    fail('unsafe_path');
  }
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    info.uid !== process.getuid?.() ||
    (info.mode & 0o777) !== 0o600
  )
    fail('unsafe_path');
  if (info.nlink === 2) return false;
  if (info.nlink !== 1) fail('invalid_proof');
  return true;
}
export function readProof(directory: string, name: string, maximum = 65536): unknown {
  integer(maximum, 1, 65536);
  const path = proofPath(directory, name);
  let fd: number | undefined;
  try {
    fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
    const s = fstatSync(fd);
    if (
      !s.isFile() ||
      s.nlink !== 1 ||
      (s.mode & 0o777) !== 0o600 ||
      s.uid !== process.getuid?.() ||
      s.size < 1 ||
      s.size > maximum
    )
      fail('unsafe_path');
    return JSON.parse(readFileSync(fd, 'utf8')) as unknown;
  } catch {
    return fail('invalid_proof');
  } finally {
    if (fd !== undefined) closeSync(fd);
  }
}
export function writeProof(directory: string, name: string, value: unknown, maximum = 65536): void {
  integer(maximum, 1, 65536);
  const final = proofPath(directory, name),
    pending = join(directory, '.origin-proof-' + randomUUID() + '.pending');
  let fd: number | undefined;
  let identity: { ino: number; dev: number } | undefined;
  let failed = false;
  try {
    const encoded = JSON.stringify(value);
    if (encoded === undefined) fail('invalid_proof');
    const raw = encoded + '\n';
    if (Buffer.byteLength(raw) > maximum) fail('invalid_proof');
    fd = openSync(
      pending,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
      0o600,
    );
    const info = fstatSync(fd);
    identity = { ino: info.ino, dev: info.dev };
    if (
      !info.isFile() ||
      info.nlink !== 1 ||
      (info.mode & 0o777) !== 0o600 ||
      info.uid !== process.getuid?.()
    )
      fail('unsafe_path');
    writeFileSync(fd, raw);
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    linkSync(pending, final);
  } catch {
    failed = true;
  } finally {
    if (fd !== undefined) {
      try {
        closeSync(fd);
      } catch {
        failed = true;
      }
    }
    if (identity !== undefined) {
      try {
        const info = lstatSync(pending);
        if (
          !info.isFile() ||
          info.isSymbolicLink() ||
          info.ino !== identity.ino ||
          info.dev !== identity.dev ||
          info.uid !== process.getuid?.()
        )
          fail('unsafe_path');
        unlinkSync(pending);
      } catch {
        failed = true;
      }
    }
  }
  if (failed) fail('invalid_proof');
}

/** One fixed parent final deadline; twenty seconds are reserved for cleanup. */
export class OriginBudget {
  readonly businessDeadline: number;
  readonly finalDeadline: number;
  constructor(
    parentExpiresAtMs: number,
    wallNowMs = Date.now(),
    monotonicNowMs = performance.now(),
  ) {
    integer(parentExpiresAtMs, 0, 4102444800000);
    integer(wallNowMs, 0, 4102444800000);
    if (
      typeof monotonicNowMs !== 'number' ||
      !Number.isFinite(monotonicNowMs) ||
      monotonicNowMs < 0
    )
      fail('invalid_fixture');
    this.finalDeadline = monotonicNowMs + parentExpiresAtMs - wallNowMs;
    this.businessDeadline = this.finalDeadline - 20000;
    Object.freeze(this);
  }
  checkBusiness(nowMs = performance.now()): void {
    if (!Number.isFinite(nowMs) || nowMs >= this.businessDeadline) fail('deadline_exceeded');
  }
  checkCleanup(nowMs = performance.now()): void {
    if (!Number.isFinite(nowMs) || nowMs >= this.finalDeadline) fail('cleanup_incomplete');
  }
}
type Closeable = { close(): Promise<void> };
export class Context {
  readonly budget: OriginBudget;
  readonly owned = new Map<Closeable, number>();
  cleanupIncomplete = false;
  own<T extends Closeable>(value: T, tier: number): T {
    this.owned.set(value, tier);
    return value;
  }
  constructor(
    readonly env: OriginEnvironment,
    readonly fixture: OriginFixture,
  ) {
    this.budget = new OriginBudget(fixture.parent_expires_at_ms);
  }
  check() {
    this.budget.checkBusiness();
  }
  observe() {
    this.budget.checkCleanup();
  }
  async readBusiness<T>(read: () => Promise<T>): Promise<T> {
    this.check();
    const value = await read();
    this.check();
    return value;
  }
  cleanupComplete(): boolean {
    return !this.cleanupIncomplete && this.owned.size === 0;
  }
  save(name: string, value: unknown) {
    this.observe();
    const raw = JSON.stringify(value);
    const secrets = [
      ...Object.values(this.env.tokens),
      this.env.ownerPassword,
      this.env.runtimePassword,
      this.env.caseAuthorization,
    ];
    if (secrets.some((s) => s && raw.includes(s))) fail('invalid_proof');
    writeProof(this.env.directory, name, value);
  }
  read(name: string, phase: 'business' | 'cleanup' = 'business') {
    if (phase === 'cleanup') this.observe();
    else this.check();
    return readProof(this.env.directory, name);
  }
  async wait(name: string, phase: 'business' | 'cleanup' = 'business'): Promise<unknown> {
    while (!proofPublished(this.env.directory, name)) {
      if (phase === 'cleanup') this.observe();
      else this.check();
      await delay(5);
    }
    return this.read(name, phase);
  }
  db(owner = false): DatabaseSettings {
    if (this.env.mode === 'cleanup') this.observe();
    else this.check();
    const password = owner ? this.env.ownerPassword : this.env.runtimePassword;
    if (!password) fail('invalid_environment');
    return {
      host: '127.0.0.1',
      port: this.env.pgPort,
      database: 'livekit_lab',
      user: owner ? 'continuity_migrator' : 'livekit_lab',
      password,
      schema: this.env.schema,
    };
  }
  reference() {
    return {
      scope: this.fixture.scope,
      caseId: this.fixture.case_id,
      conversationId: this.fixture.conversation_id,
    };
  }
  accounts() {
    return new SeededAccounts([
      {
        ...this.fixture.scope,
        token: this.env.tokens.ACCOUNT_TOKEN,
        caseId: this.fixture.case_id,
        conversationId: this.fixture.conversation_id,
      },
    ]);
  }
  nativeIntegration() {
    return createNativeIntegration(
      {
        tenantId: this.fixture.scope.tenantId,
        provider: 'livekit',
        providerAccountId: 'origin_fixture_rtc',
      },
      [{ token: this.env.tokens.NATIVE_PUBLISHER_TOKEN, ...this.reference() }],
    );
  }
  smsIntegration() {
    return createFakeSmsIntegration(this.provider(), Buffer.alloc(32, 0x4f));
  }
  provider() {
    return {
      tenantId: this.fixture.scope.tenantId,
      provider: 'fake_sms',
      providerAccountId: 'origin_fixture_sms',
    };
  }
  native() {
    return this.own(
      new NativeChannelInbox(this.db(), this.nativeIntegration(), this.accounts(), {}, () => {}),
      2,
    );
  }
  sms() {
    return this.own(
      new ChannelInbox(this.db(), this.smsIntegration(), this.accounts(), {}, () => {}),
      2,
    );
  }
  cases() {
    this.check();
    return this.own(
      new CurrentCaseHttpClient(
        this.fixture.case_endpoint,
        this.env.caseAuthorization,
        [this.reference()],
        { timeoutMs: 1000, cleanupMs: 1000, maxActive: 2 },
      ),
      2,
    );
  }
  setup() {
    return parseSetup(
      this.read('p2-origin-setup.json', this.env.mode === 'cleanup' ? 'cleanup' : 'business'),
    );
  }
  async endpoint(role: string) {
    return parseReady(await this.wait('origin-' + role + '-ready.json'));
  }
  async client(
    role: string,
    sender: string,
    profile = this.setup().receiver_id,
    bearer = this.env.tokens.OPERATION_TOKEN,
  ) {
    const ready = await this.endpoint(role);
    const config: OperationClientConfig = {
      schemaVersion: 1,
      profileId: profile,
      endpoint: { host: '127.0.0.1', port: ready.port },
      bindings: [
        {
          alias: 'origin',
          accountScope: this.fixture.scope,
          caseId: this.fixture.case_id,
          conversationId: this.fixture.conversation_id,
          senderId: sender,
          operationBearer: bearer,
        },
      ],
    };
    return this.own(new ExternalOperationClient(config), 1);
  }
  async close(resources: readonly Closeable[], name: string): Promise<boolean> {
    try {
      this.observe();
    } catch {
      this.cleanupIncomplete = true;
      return false;
    }
    const outcomes = await Promise.allSettled(
      resources.map((x) => Promise.resolve().then(() => x.close())),
    );
    let ok = outcomes.every((x) => x.status === 'fulfilled');
    try {
      this.observe();
    } catch {
      ok = false;
    }
    outcomes.forEach((x, n) => {
      if (x.status === 'fulfilled') this.owned.delete(resources[n]!);
    });
    try {
      writeProof(this.env.directory, name, {
        schema_version: 1,
        cleanup_complete: ok,
        resources: outcomes.map((x) => x.status),
      });
    } catch {
      this.cleanupIncomplete = true;
    }
    if (!ok) this.cleanupIncomplete = true;
    return ok;
  }
  async finish() {
    for (const tier of [...new Set(this.owned.values())].sort((a, b) => a - b)) {
      const values = [...this.owned].filter(([, t]) => t === tier).map(([r]) => r);
      if (!(await this.close(values, 'origin-' + this.env.mode + '-final-tier-' + tier + '.json')))
        break;
    }
  }
}
async function sql<T>(c: Context, action: (db: pg.Client) => Promise<T>): Promise<T> {
  const client = new pg.Client({
    ...c.db(true),
    ssl: false,
    connectionTimeoutMillis: 1500,
    query_timeout: 3000,
    application_name: 'p2-origin-fixture-' + c.env.mode,
    options: '-c search_path=pg_catalog -c statement_timeout=2500 -c lock_timeout=1500',
  });
  try {
    await client.connect();
    return await action(client);
  } finally {
    await client.end();
  }
}
async function nativeInput(c: Context, inbox: NativeChannelInbox, label: 'a' | 'b') {
  c.check();
  return inbox.accept(c.env.tokens[label === 'a' ? 'NATIVE_A_BEARER' : 'NATIVE_B_BEARER'], {
    schemaVersion: 1,
    inputId: randomUUID(),
    channel: 'web_chat',
    body:
      label === 'a' ? 'Review the original booking policy.' : 'Review the revised booking policy.',
    roomId: 'origin_room_' + label,
    participantId: 'origin_participant_' + label,
  });
}
async function setup(c: Context) {
  await installChannelSchema(c.db(true));
  await upgradeChannelSchemaV2(c.db(true));
  await upgradeChannelSchemaV3(c.db(true), { maxReplies: 8, maxRoutes: 8, maxAttempts: 3 });
  await upgradeChannelSchemaV4(c.db(true));
  await upgradeChannelSchemaV5(c.db(true));
  await upgradeChannelSchemaV6(c.db(true));
  await upgradeChannelSchemaV7(c.db(true));
  const receiver = uuid(await upgradeChannelSchemaV8(c.db(true)));
  const inbox = c.native(),
    sms = c.sms();
  try {
    for (const label of ['a', 'b'] as const) {
      c.check();
      await inbox.bind(c.env.tokens.NATIVE_PUBLISHER_TOKEN, {
        bindingId: c.fixture.native_binding_ids[label],
        bearer: c.env.tokens[label === 'a' ? 'NATIVE_A_BEARER' : 'NATIVE_B_BEARER'],
        roomId: 'origin_room_' + label,
        participantId: 'origin_participant_' + label,
        expiresAt: new Date(c.fixture.parent_expires_at_ms).toISOString(),
      });
    }
    const original = await nativeInput(c, inbox, 'a');
    const signed = (body: string, event: string) =>
      signFakeSms(
        {
          schemaVersion: 1,
          eventId: event,
          messageId: event,
          senderId: 'origin_sms_sender',
          body,
          occurredAt: new Date().toISOString(),
        },
        Buffer.alloc(32, 0x4f),
        Math.floor(Date.now() / 1000),
        c.provider(),
      );
    c.check();
    const challenge = await sms.createChallenge(c.env.tokens.ACCOUNT_TOKEN, 'origin_sms_sender'),
      link = signed('LINK ' + challenge.challengeId + ' ' + challenge.secret, 'origin_link');
    c.check();
    await sms.completeAssociation(link.raw, link.headers);
    const input = signed('Review policy after asynchronous SMS.', 'origin_sms_input');
    c.save('origin-sms-source.json', {
      schema_version: 1,
      raw_utf8: Buffer.from(input.raw).toString('utf8'),
      headers: input.headers,
    });
    c.check();
    const accepted = await sms.acceptSms(input.raw, input.headers),
      ack = await c.readBusiness(() =>
        sms.inspect(c.env.tokens.ACCOUNT_TOKEN, accepted.receipt.receiptId),
      );
    c.save('p2-origin-setup.json', {
      schema_version: 1,
      receiver_id: receiver,
      inputs: {
        original: { receiptId: original.receiptId, operationKey: original.operationKey },
        ack: { receiptId: ack.receipt.receiptId, operationKey: ack.operationKey },
      },
    });
  } finally {
    await c.close([inbox, sms], 'origin-setup-ownership.json');
  }
}
function dispatcher(
  c: Context,
  native: boolean,
  cases: CurrentCaseHttpClient,
  operations: DispatchPorts['operations'],
): ChannelDispatcher {
  const ports: DispatchPorts = {
    cases: {
      async inspect(ref, signal) {
        c.check();
        const current = await cases.inspect(
          { ...ref, conversationId: c.fixture.conversation_id },
          signal,
        );
        c.check();
        if (
          current.source !== 'p1_public_v4' ||
          !/^[1-9][0-9]*(?![\s\S])/.test(current.revision) ||
          BigInt(current.revision) > 1000000n
        )
          fail('invalid_proof');
        return {
          scope: current.scope,
          caseId: current.caseId,
          revision: current.revision,
          source: 'synthetic_read_only',
        };
      },
    },
    agent: {
      async prepare(input) {
        c.check();
        return {
          kind: 'investigation',
          source: 'scripted',
          caseRevision: input.currentCase.revision,
        };
      },
    },
    operations: {
      capabilities: 'stable_idempotency_and_lookup',
      lookup(query, signal) {
        c.check();
        return operations.lookup(query, signal);
      },
      accept(input, signal) {
        c.check();
        return operations.accept(input, signal);
      },
    },
  };
  return c.own(
    new ChannelDispatcher(
      c.db(),
      native ? c.nativeIntegration() : c.smsIntegration(),
      c.accounts(),
      ports,
      { timeoutMs: 5000, cleanupTimeoutMs: 2000, observer: () => {} },
    ),
    1,
  );
}
function receipt(prepared: PreparedDispatch, externalReceiptId: string): OperationReceipt {
  return {
    operationKey: prepared.submission.operationKey,
    scope: prepared.submission.scope,
    payloadDigest: prepared.payloadDigest,
    receiptId: uuid(externalReceiptId),
  };
}
async function race(c: Context) {
  const clients = [
      await c.client('race-a', c.fixture.native_binding_ids.a),
      await c.client('race-b', c.fixture.native_binding_ids.a),
    ],
    cases = c.cases();
  let saved: PreparedDispatch | undefined,
    calls = 0;
  const dispatch = dispatcher(c, true, cases, {
    capabilities: 'stable_idempotency_and_lookup',
    lookup: (q, s) => clients[0]!.lookup(q, s),
    async accept(input, signal) {
      calls++;
      saved = parsePrepared(input);
      c.save('origin-original-prepared.json', saved);
      const observed = await Promise.all(clients.map((client) => client.accept(input, signal)));
      assert.deepEqual(observed[0], observed[1]);
      c.save('origin-race-callers.json', {
        schema_version: 1,
        receipts: observed,
        clients: clients.map((x) => x.metrics()),
      });
      return observed[0]!;
    },
  });
  try {
    const input = c.setup().inputs.original,
      result = (c.check(), await dispatch.step(c.env.tokens.ACCOUNT_TOKEN, input.receiptId));
    assert.equal(result.status, 'dispatched');
    if (result.status !== 'dispatched' || !saved) fail('unexpected_outcome');
    assert.equal(calls, 1);
    const observed = await c.readBusiness(() =>
      dispatch.inspect(c.env.tokens.ACCOUNT_TOKEN, input.receiptId),
    );
    c.save('origin-race.json', {
      schema_version: 1,
      receipt: receipt(saved, result.externalReceiptId),
      input_receipt_id: input.receiptId,
      dispatch: observed,
      operation_accept_calls: calls,
    });
  } finally {
    if (await c.close([dispatch, ...clients], 'origin-race-dependent-ownership.json'))
      await c.close([cases], 'origin-race-case-ownership.json');
  }
}
async function ackCaller(c: Context) {
  const client = await c.client('ack', 'origin_sms_sender'),
    cases = c.cases();
  let code = 'not_called',
    accepts = 0;
  const dispatch = dispatcher(c, false, cases, {
    capabilities: 'stable_idempotency_and_lookup',
    lookup: (q, s) => client.lookup(q, s),
    async accept(input, signal) {
      accepts++;
      c.save('origin-ack-prepared.json', parsePrepared(input));
      try {
        return await client.accept(input, signal);
      } catch (e) {
        code = safeCode(e);
        throw e;
      }
    },
  });
  try {
    const input = c.setup().inputs.ack;
    let stepCode = 'not_rejected';
    try {
      c.check();
      await dispatch.step(c.env.tokens.ACCOUNT_TOKEN, input.receiptId);
    } catch (e) {
      stepCode = safeCode(e);
    }
    assert.equal(code, 'OutcomeUnknown');
    assert.equal(stepCode, 'DispatchUnavailable');
    const observed = await c.readBusiness(() =>
      dispatch.inspect(c.env.tokens.ACCOUNT_TOKEN, input.receiptId),
    );
    assert.equal(observed.possibleExternal, true);
    assert.equal(observed.state, 'uncertain');
    assert.equal(accepts, 1);
    c.save('origin-ack-caller.json', {
      schema_version: 1,
      external_code: code,
      dispatch_code: stepCode,
      dispatch: observed,
      accept_calls: accepts,
    });
  } finally {
    if (await c.close([dispatch, client], 'origin-ack-dependent-ownership.json'))
      await c.close([cases], 'origin-ack-case-ownership.json');
  }
}
async function reconcile(c: Context) {
  const client = await c.client('recovered', 'origin_sms_sender'),
    cases = c.cases();
  let accepts = 0;
  const dispatch = dispatcher(c, false, cases, {
    capabilities: 'stable_idempotency_and_lookup',
    lookup: (q, s) => client.lookup(q, s),
    async accept() {
      accepts++;
      fail('unexpected_outcome');
    },
  });
  try {
    const input = c.setup().inputs.ack,
      result = (c.check(), await dispatch.reconcile(c.env.tokens.ACCOUNT_TOKEN, input.receiptId));
    if (result.status !== 'dispatched' || !result.reconciled) fail('unexpected_outcome');
    assert.equal(accepts, 0);
    const prepared = parsePrepared(c.read('origin-ack-prepared.json', 'cleanup'));
    c.save('origin-reconcile.json', {
      schema_version: 1,
      receipt: receipt(prepared, result.externalReceiptId),
      input_receipt_id: input.receiptId,
      accept_calls: accepts,
      dispatch: await c.readBusiness(() =>
        dispatch.inspect(c.env.tokens.ACCOUNT_TOKEN, input.receiptId),
      ),
    });
  } finally {
    if (await c.close([dispatch, client], 'origin-reconcile-dependent-ownership.json'))
      await c.close([cases], 'origin-reconcile-case-ownership.json');
  }
}
async function rejected(
  c: Context,
  action: () => Promise<unknown>,
  expected: string,
): Promise<string> {
  c.check();
  let code = 'not_rejected';
  try {
    await action();
  } catch (e) {
    code = safeCode(e);
  }
  if (code !== expected) fail('unexpected_outcome');
  return code;
}
async function negative(c: Context) {
  const input = parsePrepared(c.read('origin-original-prepared.json')),
    client = await c.client('recovered', c.fixture.native_binding_ids.a),
    wrongProfile = await c.client('recovered', c.fixture.native_binding_ids.a, randomUUID()),
    wrongBearer = await c.client(
      'recovered',
      c.fixture.native_binding_ids.a,
      c.setup().receiver_id,
      (c.env.tokens.OPERATION_TOKEN[0] === 'z' ? 'y' : 'z') + c.env.tokens.OPERATION_TOKEN.slice(1),
    );
  try {
    const submission = {
        ...input.submission,
        message: { ...input.submission.message, body: 'Changed original source body.' },
      },
      canonicalPayload = JSON.stringify(submission),
      changed = { submission, canonicalPayload, payloadDigest: digest(canonicalPayload) };
    const codes = {
      changed_origin: await rejected(
        c,
        () => client.accept(changed, new AbortController().signal),
        'OutcomeUnknown',
      ),
      changed_lookup: await rejected(
        c,
        () =>
          client.lookup(
            {
              operationKey: input.submission.operationKey,
              scope: input.submission.scope,
              payloadDigest: '0'.repeat(64),
            },
            new AbortController().signal,
          ),
        'Unavailable',
      ),
      wrong_profile: await rejected(
        c,
        () => wrongProfile.preflight('origin', new AbortController().signal),
        'Unavailable',
      ),
      wrong_bearer: await rejected(
        c,
        () => wrongBearer.preflight('origin', new AbortController().signal),
        'Unavailable',
      ),
    };
    c.save('origin-negative-controls.json', { schema_version: 1, codes });
  } finally {
    await c.close([client, wrongProfile, wrongBearer], 'origin-negative-control-ownership.json');
  }
  if (c.cleanupIncomplete) fail('cleanup_incomplete');
  const ready = fields(await c.wait('origin-hold-ready.json'), ['schema_version', 'hold']);
  if (ready.schema_version !== 1 || ready.hold !== true) fail('invalid_proof');
  const clients = [
      await c.client('recovered', c.fixture.native_binding_ids.a),
      await c.client('recovered', c.fixture.native_binding_ids.a),
    ],
    aborts = Array.from({ length: 4 }, () => new AbortController());
  c.check();
  const query = {
      operationKey: input.submission.operationKey,
      scope: input.submission.scope,
      payloadDigest: input.payloadDigest,
    },
    outcomes = clients.flatMap((x, n) =>
      [0, 1].map((k) =>
        x.lookup(query, aborts[n * 2 + k]!.signal).then(
          () => 'known',
          (e) => safeCode(e),
        ),
      ),
    );
  try {
    const overload = await Promise.all(
      clients.map((x) =>
        rejected(c, () => x.lookup(query, new AbortController().signal), 'Overloaded'),
      ),
    );
    c.save('origin-hold-callers-started.json', { schema_version: 1, callerCount: 4 });
    const abort = fields(await c.wait('origin-abort-lookups.json', 'cleanup'), [
      'schema_version',
      'abort',
    ]);
    if (abort.schema_version !== 1 || abort.abort !== true) fail('invalid_proof');
    const before = clients.map((x) => x.metrics());
    aborts.forEach((x) => x.abort());
    const codes = await Promise.all(outcomes);
    assert.deepEqual(codes, Array(4).fill('Unavailable'));
    await Promise.all(clients.map((x) => x.close()));
    c.save('origin-held-lookups.json', {
      schema_version: 1,
      before,
      after: clients.map((x) => x.metrics()),
      outcomes: codes,
      overload,
      caller_sockets_settled: true,
      p1_drain_claimed: false,
    });
  } finally {
    aborts.forEach((x) => x.abort());
    await Promise.all(outcomes);
    await c.close(clients, 'origin-held-client-ownership.json');
  }
}
function equalBearer(actual: string | undefined, expected: string): boolean {
  const a = Buffer.from(actual ?? ''),
    b = Buffer.from('Bearer ' + expected);
  return a.length === b.length && timingSafeEqual(a, b);
}
async function httpBody(req: IncomingMessage, maximum: number): Promise<string> {
  if (
    req.headers['content-type'] !== 'application/json' ||
    req.headers['content-encoding'] !== undefined ||
    req.headers['transfer-encoding'] !== undefined ||
    typeof req.headers['content-length'] !== 'string' ||
    !/^[1-9][0-9]{0,4}(?![\s\S])/.test(req.headers['content-length']) ||
    Number(req.headers['content-length']) > maximum
  )
    fail('invalid_proof');
  let bytes = 0;
  const parts: Buffer[] = [];
  for await (const raw of req) {
    const part = Buffer.from(raw as Uint8Array);
    bytes += part.length;
    if (bytes > maximum) fail('invalid_proof');
    parts.push(part);
  }
  if (bytes !== Number(req.headers['content-length'])) fail('invalid_proof');
  return new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(parts));
}
function response(res: ServerResponse, status: number, value: unknown, maximum = 2048) {
  const raw = Buffer.from(JSON.stringify(value));
  if (raw.length > maximum) fail('invalid_proof');
  if (res.destroyed) return;
  res.writeHead(status, {
    'content-type': 'application/json',
    'content-length': raw.length,
    'cache-control': 'no-store',
    connection: 'close',
  });
  res.end(raw);
}
async function resultHost(c: Context) {
  const inbox = c.native(),
    cases = c.cases();
  let carrierCalls = 0;
  const outbox = c.own(
    new ChannelOutbox(
      c.db(),
      c.smsIntegration(),
      c.accounts(),
      [{ token: c.env.tokens.PUBLISHER_TOKEN, ...c.reference() }],
      {
        capabilities: 'ordinary_fake_sms_v1',
        async send() {
          carrierCalls++;
          fail('unexpected_outcome');
        },
      },
      { observer: () => {} },
    ),
    2,
  );
  const binding = { ...c.reference(), recipientId: c.fixture.recipient_id },
    receiver = c.own(
      new ChannelResultReceiver(
        outbox,
        {
          receiverId: c.setup().receiver_id,
          bindings: [{ ...binding, publisherToken: c.env.tokens.PUBLISHER_TOKEN }],
        },
        { observer: () => {} },
      ),
      1,
    ),
    reader = c.own(
      new ChannelResultReader(
        outbox,
        inbox,
        cases,
        { receiverId: c.setup().receiver_id, bindings: [binding] },
        { timeoutMs: 3000, cleanupMs: 1000, observer: () => {} },
      ),
      1,
    );
  const tasks = new Set<Promise<void>>(),
    sockets = new Set<Socket>();
  let closing = false,
    handlers = 0;
  const handle = async (req: IncomingMessage, res: ServerResponse) => {
    if (closing || handlers >= 4) {
      response(res, 429, { schemaVersion: 1, status: 'error', error: 'Overloaded' });
      return;
    }
    handlers++;
    try {
      c.check();
      if (
        req.method !== 'POST' ||
        req.headers.host !==
          '127.0.0.1:' + ((server.address() as { port: number } | null)?.port ?? 0) ||
        (req.headers.connection !== undefined && req.headers.connection !== 'close') ||
        (req.headers.accept !== undefined && req.headers.accept !== 'application/json') ||
        req.rawHeaders.length > 64 ||
        new Set(req.rawHeaders.filter((_, i) => i % 2 === 0).map((x) => x.toLowerCase())).size !==
          req.rawHeaders.length / 2 ||
        Object.keys(req.headers).some(
          (k) =>
            ![
              'host',
              'authorization',
              'content-type',
              'content-length',
              'connection',
              'accept',
              'accept-encoding',
              'user-agent',
            ].includes(k),
        )
      )
        fail('invalid_proof');
      if (req.url === '/v1/p2-result-receiver/native-read') {
        if (!equalBearer(req.headers.authorization, c.env.tokens.NATIVE_B_BEARER)) {
          response(res, 403, { schemaVersion: 1, status: 'error', error: 'AccessDenied' });
          return;
        }
        const q = fields(JSON.parse(await httpBody(req, 256)) as unknown, [
          'schemaVersion',
          'deliveryId',
        ]);
        if (q.schemaVersion !== 1) fail('invalid_proof');
        c.check();
        const view = await reader.native(c.env.tokens.NATIVE_B_BEARER, uuid(q.deliveryId));
        response(res, 200, { schemaVersion: 1, status: view ? 'known' : 'missing', view }, 32768);
        return;
      }
      if (!equalBearer(req.headers.authorization, c.env.tokens.PUBLISHER_TOKEN)) {
        response(res, 403, { schemaVersion: 1, status: 'error', error: 'AccessDenied' });
        return;
      }
      if (!['/v1/p2-result-receiver/accept', '/v1/p2-result-receiver/find'].includes(req.url ?? ''))
        fail('invalid_proof');
      const intent = parseResultIntent(await httpBody(req, 16384));
      c.check();
      const observed = req.url?.endsWith('/accept')
        ? await receiver.accept(c.env.tokens.PUBLISHER_TOKEN, intent)
        : await receiver.find(c.env.tokens.PUBLISHER_TOKEN, intent);
      response(res, 200, {
        schemaVersion: 1,
        status: observed ? 'accepted' : 'missing',
        receipt: observed,
      });
    } catch (e) {
      const code = safeCode(e),
        safe = [
          'AccessDenied',
          'IdentityConflict',
          'Overloaded',
          'UpgradeRequired',
          'AcknowledgementUnknown',
          'Unavailable',
          'Closed',
        ].includes(code)
          ? code
          : 'InvalidCommand';
      response(
        res,
        safe === 'AccessDenied'
          ? 403
          : safe === 'IdentityConflict'
            ? 409
            : safe === 'Overloaded'
              ? 429
              : safe === 'InvalidCommand'
                ? 400
                : 503,
        { schemaVersion: 1, status: 'error', error: safe },
      );
    } finally {
      handlers--;
    }
  };
  const server = createServer(
    { maxHeaderSize: 4096, requestTimeout: 2000, headersTimeout: 1000 },
    (req, res) => {
      if (closing || handlers >= 4) {
        req.socket.destroy();
        return;
      }
      try {
        c.check();
      } catch {
        req.socket.destroy();
        return;
      }
      const task = handle(req, res);
      tasks.add(task);
      void task.then(
        () => tasks.delete(task),
        () => tasks.delete(task),
      );
    },
  );
  server.maxHeadersCount = 32;
  server.maxConnections = 8;
  server.keepAliveTimeout = 1;
  server.setTimeout(2000, (s) => s.destroy());
  server.on('connection', (s) => {
    sockets.add(s);
    s.once('close', () => sockets.delete(s));
  });
  server.on('clientError', (_e, s) => s.destroy());
  let stop!: () => void;
  const stopped = new Promise<void>((r) => {
    stop = r;
  });
  const sig = () => stop();
  process.once('SIGTERM', sig);
  process.once('SIGINT', sig);
  try {
    await new Promise<void>((ok, bad) => {
      server.once('error', bad);
      server.listen(0, '127.0.0.1', ok);
    });
    const addr = server.address();
    if (!addr || typeof addr === 'string') fail('component_failed');
    c.save('origin-result-ready.json', {
      schema_version: 1,
      pid: process.pid,
      host: '127.0.0.1',
      port: addr.port,
      receiver_id: c.setup().receiver_id,
    });
    const observeStop = async () => {
      while (!closing) {
        c.observe();
        if (proofPublished(c.env.directory, 'origin-result-stop.json')) {
          const v = fields(c.read('origin-result-stop.json', 'cleanup'), [
            'schema_version',
            'stop',
          ]);
          if (v.schema_version !== 1 || v.stop !== true) fail('invalid_proof');
          return;
        }
        await delay(10);
      }
    };
    await Promise.race([stopped, observeStop()]);
  } finally {
    closing = true;
    process.removeListener('SIGTERM', sig);
    process.removeListener('SIGINT', sig);
    await new Promise<void>((ok, bad) => {
      server.close((e) => (e ? bad(new OriginFixtureError('cleanup_incomplete')) : ok()));
      server.closeIdleConnections();
    });
    await Promise.allSettled([...tasks]);
    const dependentsClosed = await c.close(
      [receiver, reader],
      'origin-result-dependent-ownership.json',
    );
    const storageClosed =
      dependentsClosed &&
      (await c.close([outbox, inbox, cases], 'origin-result-storage-ownership.json'));
    const cleanupComplete =
      dependentsClosed &&
      storageClosed &&
      c.cleanupComplete() &&
      handlers === 0 &&
      tasks.size === 0 &&
      sockets.size === 0;
    assert.equal(carrierCalls, 0);
    c.save('origin-result-final.json', {
      schema_version: 1,
      handlers,
      pending_tasks: tasks.size,
      sockets: sockets.size,
      receiver: receiver.metrics(),
      reader: reader.metrics(),
      outbox: outbox.metrics(),
      inbox: inbox.metrics(),
      cases: cases.metrics(),
      carrier_calls: carrierCalls,
      cleanup_complete: cleanupComplete,
    });
  }
}

export function parseNativeView(value: unknown, reference: CurrentCaseReference): ResultNativeView {
  try {
    const v = fields(value, ['schemaVersion', 'intent', 'receipt', 'case', 'observed']),
      seen = fields(v.observed, [
        'p2ObservedAt',
        'caseObservedAt',
        'disclosureAdmittedAt',
        'atomic',
      ]);
    if (v.schemaVersion !== 1 || seen.atomic !== false) fail('invalid_proof');
    const stamp = (x: unknown) => {
      if (
        typeof x !== 'string' ||
        !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z(?![\s\S])/.test(x) ||
        !Number.isFinite(Date.parse(x)) ||
        new Date(x).toISOString() !== x
      )
        fail('invalid_proof');
      return x;
    };
    const intent = parseResultIntent(encodeResultIntent(v.intent as P1ResultIntent)),
      receipt = resultReceipt(v.receipt);
    matchResultReceipt(intent, receipt);
    if (
      intent.scope.tenant_id !== reference.scope.tenantId ||
      intent.scope.account_id !== reference.scope.accountId
    )
      fail('invalid_proof');
    return Object.freeze({
      schemaVersion: 1,
      intent,
      receipt,
      case: currentCase(v.case, reference),
      observed: Object.freeze({
        p2ObservedAt: stamp(seen.p2ObservedAt),
        caseObservedAt: stamp(seen.caseObservedAt),
        disclosureAdmittedAt: stamp(seen.disclosureAdmittedAt),
        atomic: false,
      }),
    });
  } catch {
    fail('invalid_proof');
  }
}

async function nativeHttpRead(
  endpoint: ReturnType<typeof parseReady>,
  bearer: string,
  deliveryId: string,
  reference: CurrentCaseReference,
): Promise<ResultNativeView> {
  const raw = Buffer.from(JSON.stringify({ schemaVersion: 1, deliveryId }));
  let requestClosed = false,
    socketClosed = true;
  let settled!: () => void;
  const actual = new Promise<void>((r) => {
    settled = r;
  });
  const retire = () => {
    if (requestClosed && socketClosed) settled();
  };
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await new Promise<ResultNativeView>((ok, bad) => {
      let done = false;
      let req: ReturnType<typeof httpRequest> | undefined;
      const reject = () => {
        if (!done) {
          done = true;
          bad(new OriginFixtureError('component_failed'));
        }
        req?.destroy();
      };
      try {
        req = httpRequest(
          {
            hostname: '127.0.0.1',
            port: endpoint.port,
            path: '/v1/p2-result-receiver/native-read',
            method: 'POST',
            agent: false,
            headers: {
              host: '127.0.0.1:' + endpoint.port,
              authorization: 'Bearer ' + bearer,
              'content-type': 'application/json',
              'content-length': raw.length,
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
              !/^[1-9][0-9]{0,4}(?![\s\S])/.test(length) ||
              Number(length) > 32768
            ) {
              res.resume();
              reject();
              return;
            }
            let size = 0;
            const parts: Buffer[] = [];
            res.on('data', (part: Buffer) => {
              size += part.length;
              if (size > Number(length)) {
                res.destroy();
                reject();
              } else parts.push(part);
            });
            res.once('aborted', reject);
            res.once('error', reject);
            res.once('end', () => {
              if (done) return;
              try {
                if (size !== Number(length)) fail('invalid_proof');
                const data = fields(
                  JSON.parse(
                    new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(parts)),
                  ) as unknown,
                  ['schemaVersion', 'status', 'view'],
                );
                if (data.schemaVersion !== 1 || data.status !== 'known') fail('invalid_proof');
                const view = parseNativeView(data.view, reference);
                done = true;
                ok(view);
              } catch {
                reject();
              }
            });
          },
        );
        req.once('close', () => {
          requestClosed = true;
          retire();
        });
        req.once('socket', (socket) => {
          socketClosed = false;
          socket.once('close', () => {
            socketClosed = true;
            retire();
          });
        });
        req.once('error', reject);
        timer = setTimeout(reject, 5000);
        req.end(raw);
      } catch {
        reject();
        if (!req) {
          requestClosed = true;
          retire();
        }
      }
    });
  } finally {
    if (timer) clearTimeout(timer);
    await actual;
  }
}

async function nativeRead(c: Context) {
  const advanced = fields(await c.wait('origin-case-advanced.json'), [
    'schema_version',
    'revision',
  ]);
  if (advanced.schema_version !== 1 || advanced.revision !== 2) fail('invalid_proof');
  const inbox = c.native(),
    cases = c.cases(),
    client = await c.client('current', c.fixture.native_binding_ids.b);
  let prepared: PreparedDispatch | undefined;
  const dispatch = dispatcher(c, true, cases, {
    capabilities: 'stable_idempotency_and_lookup',
    lookup: (q, s) => client.lookup(q, s),
    async accept(input, signal) {
      prepared = parsePrepared(input);
      c.save('origin-current-prepared.json', prepared);
      return client.accept(input, signal);
    },
  });
  try {
    const accepted = await nativeInput(c, inbox, 'b');
    c.check();
    const step = await dispatch.step(c.env.tokens.ACCOUNT_TOKEN, accepted.receiptId);
    if (step.status !== 'dispatched' || !prepared) fail('unexpected_outcome');
    assert.equal(prepared.submission.caseRevision, '2');
    c.save('origin-current-accepted.json', {
      schema_version: 1,
      receipt: receipt(prepared, step.externalReceiptId),
      input_receipt_id: accepted.receiptId,
    });
    const delivered = fields(await c.wait('origin-current-delivered.json', 'cleanup'), [
      'schema_version',
      'work_id',
      'delivery_id',
      'receipt',
    ]);
    if (delivered.schema_version !== 1 || delivered.work_id !== step.externalReceiptId)
      fail('invalid_proof');
    const resultEndpoint = fields(await c.wait('origin-result-ready.json'), [
      'schema_version',
      'pid',
      'host',
      'port',
      'receiver_id',
    ]);
    const endpoint = parseReady({
      schema_version: resultEndpoint.schema_version,
      pid: resultEndpoint.pid,
      host: resultEndpoint.host,
      port: resultEndpoint.port,
    });
    if (resultEndpoint.receiver_id !== c.setup().receiver_id) fail('invalid_proof');
    c.check();
    const view = await nativeHttpRead(
      endpoint,
      c.env.tokens.NATIVE_B_BEARER,
      uuid(delivered.delivery_id),
      c.reference(),
    );
    if (!view) fail('invalid_proof');
    assert.equal(view.intent.work_id, step.externalReceiptId);
    assert.equal(view.intent.delivery_id, delivered.delivery_id);
    assert.deepEqual(view.receipt, resultReceipt(delivered.receipt));
    assert.equal(view.intent.receiver_id, c.setup().receiver_id);
    assert.equal(view.intent.recipient_id, c.fixture.recipient_id);
    assert.equal(view.case.revision, '2');
    assert.equal(view.case.source, 'p1_public_v4');
    assert.deepEqual(view.case.scope, c.fixture.scope);
    assert.equal(view.case.caseId, c.fixture.case_id);
    assert.equal(view.case.conversationId, c.fixture.conversation_id);
    assert.equal(view.observed.atomic, false);
    c.save('origin-native-read.json', {
      schema_version: 1,
      view,
      input: accepted,
      dispatch: await c.readBusiness(() =>
        dispatch.inspect(c.env.tokens.ACCOUNT_TOKEN, accepted.receiptId),
      ),
      rtc_rooms: 0,
      provider_calls: false,
    });
  } finally {
    if (await c.close([dispatch, client], 'origin-native-read-dependent-ownership.json'))
      await c.close([inbox, cases], 'origin-native-read-storage-ownership.json');
  }
}
async function cleanup(c: Context) {
  const receiver = c.setup().receiver_id;
  const guard = await sql(c, async (db) => {
    const rows = await db.query(
      "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=$1",
      [c.env.schema],
    );
    if (
      rows.rowCount !== 1 ||
      rows.rows[0]?.owner !== 'continuity_migrator' ||
      rows.rows[0]?.marker !== 'p2-channel-schema-v8'
    )
      fail('invalid_proof');
    return rows.rows[0] as { owner: string; marker: string };
  });
  assert.equal(await upgradeChannelSchemaV8(c.db(true)), receiver);
  await sql(c, async (db) => {
    await db.query('DROP SCHEMA "' + c.env.schema + '" CASCADE');
    assert.equal(
      (await db.query('SELECT 1 FROM pg_namespace WHERE nspname=$1', [c.env.schema])).rowCount,
      0,
    );
  });
  c.save('origin-cleanup.json', {
    schema_version: 1,
    guard,
    receiver_id: receiver,
    namespace_absent: true,
  });
}
export async function run(mode: unknown, environment: unknown): Promise<void> {
  const env = parseEnvironment(mode, environment),
    fixture = parseFixture(readProof(env.directory, 'fixture.json'), env),
    c = new Context(env, fixture);
  let primary: unknown;
  let failed = false;
  try {
    if (env.mode === 'setup') await setup(c);
    else if (env.mode === 'race') await race(c);
    else if (env.mode === 'ack-caller') await ackCaller(c);
    else if (env.mode === 'reconcile') await reconcile(c);
    else if (env.mode === 'negative') await negative(c);
    else if (env.mode === 'result-host') await resultHost(c);
    else if (env.mode === 'native-read') await nativeRead(c);
    else await cleanup(c);
  } catch (error) {
    primary = error;
    failed = true;
  } finally {
    await c.finish();
  }
  if (failed) throw primary;
  if (c.cleanupIncomplete || c.owned.size) fail('cleanup_incomplete');
}
if (isEntrypoint(import.meta.url, process.argv)) {
  const mode = process.argv[2];
  try {
    await run(mode, process.env);
    process.stdout.write(
      JSON.stringify({
        schema_version: 1,
        mode,
        status: 'passed',
        carrier_calls: 0,
        provider_calls: false,
        rtc_rooms: 0,
      }) + '\n',
    );
  } catch (error) {
    process.stdout.write(
      JSON.stringify({
        schema_version: 1,
        mode: ORIGIN_MODES.includes(mode as OriginMode) ? mode : 'invalid',
        status: 'failed',
        code: safeCode(error),
      }) + '\n',
    );
    process.exitCode = 1;
  }
}
